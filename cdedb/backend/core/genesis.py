#!/usr/bin/env python3

"""
The `CoreGenesisBackend` subclasses the `CoreBaseBackend` and provides functionality
for "genesis", that is for account creation via anonymous account requests.
"""

from collections.abc import Collection
from typing import Protocol

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.core as models
from cdedb.backend.common import (
    Silencer,
    access,
    affirm_validation as affirm,
    internal,
    singularize,
)
from cdedb.backend.core.base import CoreBaseBackend
from cdedb.common import (
    CdEDBObject,
    CdEDBObjectMap,
    DefaultReturnCode,
    DeletionBlockers,
    GenesisDecision,
    RequestState,
    is_tor_exit_node,
    merge_dicts,
    now,
    unwrap,
)
from cdedb.common.exceptions import PrivilegeError
from cdedb.common.n_ import n_
from cdedb.common.roles import PERSONA_DEFAULTS, Realms, Roles
from cdedb.common.validation.validate import (
    PERSONA_CDE_CREATION as CDE_TRANSITION_FIELDS,
)
from cdedb.database.connection import Atomizer
from cdedb.models.common import CdEDataclassMap


class CoreGenesisBackend(CoreBaseBackend):
    @access(Roles.anonymous)
    def genesis_request(
        self, rs: RequestState, data: CdEDBObject
    ) -> DefaultReturnCode | None:
        """Log a request for a new account.

        This is the initial entry point for such a request.

        :returns: id of the new request or None if the username is already
          taken
        """
        realm = affirm(Realms, data["realm"], supports_genesis=True)
        case_model = models.GenesisCase.get_model_by_realm(realm)
        data = affirm(case_model, data, creation=True)

        data['status'] = const.GenesisStati.unconfirmed
        if self.is_locked_down(rs) and not self.is_admin(rs):
            return None
        if attachment_hash := data.get("attachment_hash"):
            if not self.get_genesis_attachment_store(rs).is_available(attachment_hash):
                raise RuntimeError(n_("File has been lost."))

        with Atomizer(rs):
            if self.verify_existence(rs, data['username']):
                return None
            ret = self.sql_insert(rs, "core.genesis_cases", data)
            self.logger.info(
                f"Genesis request ({data['realm']}) for"
                f" {data['given_names']} {data['family_name']} <{data['username']}>"
                f" from IP {rs.request.remote_addr if rs.request else None}"
            )
            if (
                rs.request
                and rs.request.remote_addr
                and is_tor_exit_node(rs.request.remote_addr)
            ):
                self.logger.warning(
                    f"Blocked genesis request from TOR exit node:"
                    f" {data['given_names']} {data['family_name']} <{data['username']}>"
                    f" from IP {rs.request.remote_addr}"
                )
                raise RuntimeError(n_("Blocked genesis request from TOR exit node."))
            self.core_log(
                rs,
                const.CoreLogCodes.genesis_request,
                persona_id=None,
                change_note=data['username'],
            )
        return ret

    @access(Roles.event)
    def genesis_request_upgrade(
        self,
        rs: RequestState,
        data: CdEDBObject,
    ) -> DefaultReturnCode:
        """Record the desire of an existing event user to aquire cde realm."""
        assert rs.user.persona_id is not None
        if "cde" in rs.user.roles or self.genesis_has_upgrade_request(
            rs, rs.user.persona_id
        ):
            raise ValueError(n_("Invalid account for upgrade request."))
        data = affirm(models.GenesisUpgrade, data, creation=True)

        data["realm"] = Realms.cde
        data["status"] = const.GenesisStati.to_review
        data['persona_id'] = rs.user.persona_id
        data['is_upgrade'] = True

        if attachment_hash := data.get("attachment_hash"):
            if not self.get_genesis_attachment_store(rs).is_available(attachment_hash):
                raise RuntimeError(n_("File has been lost."))

        with Atomizer(rs):
            ret = self.sql_insert(rs, "core.genesis_cases", data)
            self.core_log(
                rs,
                const.CoreLogCodes.genesis_upgrade_requested,
                persona_id=rs.user.persona_id,
            )
        return ret

    @access(Roles.event)
    def genesis_has_upgrade_request(self, rs: RequestState, persona_id: int) -> bool:
        """Does the persona has a pending account upgrade request?"""
        persona_id = affirm(vtypes.PersonaID, persona_id)
        query = """
            SELECT id
            FROM core.genesis_cases
            WHERE persona_id = %(persona_id)s AND status = %(status)s
        """
        params: CdEDBObject = {
            "persona_id": persona_id,
            "status": const.GenesisStati.to_review,
        }
        data = self.query_one(rs, query, params)
        return bool(data)

    @access(*Roles.all_genesis_realm_roles())
    def delete_genesis_case_blockers(
        self, rs: RequestState, case_id: int
    ) -> DeletionBlockers:
        """Determine what keeps a genesis case from being deleted.

        Possible blockers:

        * unconfirmed: A genesis case with status unconfirmed may only be
                       deleted after the timeout period has passed.
        * status: A genesis case may not be deleted if it has one of the
                  following stati: to_review, approved.

        :return: List of blockers, separated by type. The values of the dict
            are the ids of the blockers.
        """

        case_id = affirm(vtypes.ID, case_id)
        blockers: DeletionBlockers = {}

        case = self.genesis_get_case(rs, case_id)
        if (
            case.status == const.GenesisStati.unconfirmed
            and now() < case.ctime + self.conf["PARAMETER_TIMEOUT"]
        ):
            blockers["unconfirmed"] = [case_id]
        if case.status in {const.GenesisStati.to_review, const.GenesisStati.approved}:
            blockers["status"] = [case.status]

        return blockers

    @access(*Roles.all_genesis_realm_roles())
    def delete_genesis_case(
        self, rs: RequestState, case_id: int, cascade: Collection[str] | None = None
    ) -> DefaultReturnCode:
        """Remove a genesis case."""

        case_id = affirm(vtypes.ID, case_id)
        blockers = self.delete_genesis_case_blockers(rs, case_id)
        if "unconfirmed" in blockers.keys():
            raise ValueError(
                n_(
                    "Unable to remove unconfirmed genesis case "
                    "before confirmation timeout."
                )
            )
        if "status" in blockers.keys():
            raise ValueError(
                n_("Unable to remove genesis case with status '%(status)s'."),
                {"status": blockers["status"]},
            )
        if not cascade:
            cascade = set()
        cascade = affirm(set[str], cascade) & blockers.keys()
        if blockers.keys() - cascade:
            raise ValueError(
                n_("Deletion of %(type)s blocked by %(block)s."),
                {
                    "type": "genesis case",
                    "block": blockers.keys() - cascade,
                },
            )

        ret = 1
        with Atomizer(rs):
            case = self.genesis_get_case(rs, case_id)
            if cascade:
                if "unconfirmed" in cascade:
                    raise ValueError(
                        n_("Unable to cascade %(blocker)s."), {"blocker": "unconfirmed"}
                    )
                if "status" in cascade:
                    raise ValueError(
                        n_("Unable to cascade %(blocker)s."), {"blocker": "status"}
                    )

            if not blockers:
                ret *= self.sql_delete_one(rs, "core.genesis_cases", case_id)
                self.core_log(
                    rs,
                    const.CoreLogCodes.genesis_deleted,
                    persona_id=None,
                    change_note=case.persona.username,
                )
            else:
                raise ValueError(
                    n_("Deletion of %(type)s blocked by %(block)s."),
                    {"type": "assembly", "block": blockers.keys()},
                )

        return ret

    @access(Roles.core_admin, Roles.cde_admin)
    def get_genesis_attachment_usage(
        self, rs: RequestState, attachment_hash: str
    ) -> bool:
        """Check whether an attachment is still referenced."""
        attachment_hash = affirm(vtypes.Identifier, attachment_hash)
        query = "SELECT COUNT(*) FROM core.genesis_cases WHERE attachment_hash = %s"
        return bool(unwrap(self.query_one(rs, query, (attachment_hash,))))

    @access(Roles.anonymous)
    def genesis_case_by_email(self, rs: RequestState, email: str) -> int | None:
        """Get the id of an unconfirmed or unreviewed genesis case for a given email.

        :returns: The case id if the case is unconfirmed, the negative id if the case
            is pending review, None if no such case exists.
        """
        email = affirm(str, email)
        query = """
            SELECT id
            FROM core.genesis_cases
            WHERE username = %(username)s AND status = %(status)s
        """
        params: CdEDBObject = {
            "username": email,
            "status": const.GenesisStati.unconfirmed,
        }
        data = self.query_one(rs, query, params)
        if data:
            return unwrap(data)
        params["status"] = const.GenesisStati.to_review
        data = self.query_one(rs, query, params)
        # Pylint does not understand, that unwrap(data) cannot be None here.
        return -unwrap(data) if data else None

    @access(Roles.anonymous)
    def genesis_verify(
        self, rs: RequestState, case_id: int
    ) -> tuple[DefaultReturnCode, Realms | None]:
        """Confirm the new email address and proceed to the next stage.

        Returning the realm is a conflation caused by lazyness, but before
        we create another function bloating the code this will do.

        :returns: (default return code, realm of the case if successful)
            A negative return code means, that the case was already verified.
            A zero return code means the case was not found or another error
            occured.
        """
        case_id = affirm(vtypes.ID, case_id)
        with Atomizer(rs):
            data = self.sql_select_one(
                rs, "core.genesis_cases", ("realm", "username", "status"), case_id
            )
            # These should be displayed as useful errors in the frontend.
            if not data:
                return 0, None
            realm = Realms(data["realm"])  # type: ignore[call-arg]
            if not data["status"] == const.GenesisStati.unconfirmed:
                return -1, realm
            query = """
                UPDATE core.genesis_cases
                SET status = %(new_status)s
                WHERE id = %(id)s AND status = %(old_status)s
            """
            params = {
                "new_status": const.GenesisStati.to_review,
                "id": case_id,
                "old_status": const.GenesisStati.unconfirmed,
            }
            ret = self.query_exec(rs, query, params)
            if ret:
                self.core_log(
                    rs,
                    const.CoreLogCodes.genesis_verified,
                    persona_id=None,
                    change_note=data["username"],
                )
        return ret, realm

    @access(*Roles.all_genesis_realm_roles())
    def genesis_list_cases(
        self,
        rs: RequestState,
        stati: Collection[const.GenesisStati] | None = None,
        realms: Collection[Realms] | Realms | None = None,
    ) -> CdEDBObjectMap:
        """List persona creation cases.

        Restrict to certain stati and certain target realms.
        """
        if isinstance(realms, Realms):
            realms = [realms]
        realms = affirm(set[Realms], realms or set(Realms))
        stati = affirm(set[const.GenesisStati], stati or set())
        if not rs.user.new_roles.get_genesis_realms().has_all(*realms):
            raise PrivilegeError(n_("Not privileged."))
        query = """
            SELECT id, ctime, username, given_names, family_name, status
            FROM core.genesis_cases
        """
        conditions = []
        params: CdEDBObject = {}
        if realms != set(Realms):
            conditions.append("realm = ANY(%(realms)s)")
            params["realms"] = list(realms)
        if stati:
            conditions.append("status = ANY(%(stati)s)")
            params["stati"] = stati

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        data = self.query_all(rs, query, params)
        return {e['id']: e for e in data}

    @access(*Roles.all_genesis_realm_roles())
    def genesis_get_cases(
        self, rs: RequestState, genesis_case_ids: Collection[int]
    ) -> CdEDataclassMap[models.GenesisCase]:
        """Retrieve datasets for persona creation cases."""
        genesis_case_ids = affirm(set[vtypes.ID], genesis_case_ids)
        cases = models.GenesisCase.many_from_database(
            self.query_all(
                rs, *models.GenesisCase.get_select_query(genesis_case_ids, "id")
            )
        )
        if not rs.user.new_roles.get_genesis_realms().has_all(
            *(case.realm for case in cases.values())
        ):
            raise PrivilegeError(n_("Not privileged."))
        return cases

    class _GenesisGetCaseProtocol(Protocol):
        def __call__(
            self, rs: RequestState, genesis_case_id: int
        ) -> models.GenesisCase: ...

    genesis_get_case: _GenesisGetCaseProtocol = singularize(
        genesis_get_cases, "genesis_case_ids", "genesis_case_id"
    )

    @access(*Roles.all_genesis_realm_roles())
    def genesis_modify_case(
        self, rs: RequestState, data: CdEDBObject
    ) -> DefaultReturnCode:
        """Modify a persona creation case."""
        with Atomizer(rs):
            # Get case already checks privilege and existence for the current data set.
            current = self.genesis_get_case(rs, data['id'])
            if current.status.is_finalized():
                raise ValueError(n_("Genesis case already finalized."))
            case_model = models.GenesisCase.get_model_by_realm(current.realm)
            data = affirm(case_model, data)
            ret = self.sql_update(rs, "core.genesis_cases", data)
            self.core_log(
                rs,
                const.CoreLogCodes.genesis_change,
                change_note=current.persona.username,
            )
        return ret

    @access(*Roles.all_genesis_realm_roles())
    def genesis_modify_case_realm(
        self, rs: RequestState, case_id: int, realm: Realms
    ) -> DefaultReturnCode:
        """Modify a the realm of a persona creation case."""
        realm = affirm(Realms, realm, supports_genesis=True)
        update = {"id": case_id, "realm": realm}
        with Atomizer(rs):
            # Get case already checks privilege and existence for the current data set.
            current = self.genesis_get_case(rs, case_id)
            if not (Realms.cde | Realms.event).has_all(realm, current.realm):
                raise RuntimeError("Realm modification forbidden.")
            if current.realm not in rs.user.new_roles.get_genesis_realms():
                raise PrivilegeError(n_("Not privileged."))
            if current.status.is_finalized():
                raise ValueError(n_("Genesis case already finalized."))
            ret = self.sql_update(rs, "core.genesis_cases", update)
            self.core_log(
                rs,
                const.CoreLogCodes.genesis_change,
                change_note=current.persona.username,
            )
        return ret

    @access(*Roles.all_genesis_realm_roles())
    @internal
    def genesis_modify_case_meta(
        self,
        rs: RequestState,
        case_id: int,
        *,
        status: const.GenesisStati | None = None,
        reviewer_id: int | None = None,
        persona_id: int | None = None,
    ) -> DefaultReturnCode:
        """Modify some meta data of a persona creation case."""
        update = {"id": case_id}
        if status:
            update["status"] = status
        if reviewer_id:
            update["reviewer"] = reviewer_id
        if persona_id:
            update["persona_id"] = persona_id
        with Atomizer(rs):
            # Get case already checks privilege and existence for the current data set.
            current = self.genesis_get_case(rs, case_id)
            if current.status.is_finalized():
                raise ValueError(n_("Genesis case already finalized."))
            ret = self.sql_update(rs, "core.genesis_cases", update)

            log_code = const.CoreLogCodes.genesis_change
            if status and status != current.status:
                if status == const.GenesisStati.approved:
                    # This is only ever used intermittenly with a Silencer.
                    if not rs.is_quiet:
                        raise RuntimeError("Intermediate status should not be logged.")
                elif status == const.GenesisStati.successful:
                    log_code = const.CoreLogCodes.genesis_approved
                elif status == const.GenesisStati.rejected:
                    log_code = const.CoreLogCodes.genesis_rejected
                elif status == const.GenesisStati.existing_updated:
                    log_code = const.CoreLogCodes.genesis_merged
            self.core_log(
                rs,
                log_code,
                persona_id=persona_id,
                change_note=current.persona.username,
            )
        return ret

    @access(*Roles.all_genesis_realm_roles())
    def genesis_decide(
        self,
        rs: RequestState,
        case_id: int,
        decision: GenesisDecision,
        persona_id: vtypes.PersonaID | None = None,
    ) -> vtypes.PersonaID | None:
        """Final step in the genesis process. Create or modify an account or do nothing.

        :returns: The id of the newly created or modified user if any, -1 if rejected.
        """
        case_id = affirm(vtypes.ID, case_id)
        decision = affirm(GenesisDecision, decision)
        persona_id = affirm(vtypes.PersonaID | None, persona_id)

        with Atomizer(rs):
            # Privilege check is done in genesis_get_case, since it requires the case.
            case = self.genesis_get_case(rs, case_id)
            if case.status != const.GenesisStati.to_review:
                raise ValueError(n_("Case not to review."))

            # Set the case as finalized without generating a log message.
            # This is necessary to soothe username checks for f.e. dearchival.
            with Silencer(rs):
                self.genesis_modify_case_meta(
                    rs,
                    case_id,
                    status=const.GenesisStati.approved,
                )

            if decision.is_approved():
                if case.is_upgrade:
                    assert case.persona_id is not None
                    status = const.GenesisStati.existing_updated
                    persona_id = case.persona_id

                    persona = self.get_event_user(rs, case.persona_id).as_dict()
                    merge_dicts(persona, models.CdEPersona.get_field_defaults())
                    for key in tuple(persona.keys()):
                        if key not in CDE_TRANSITION_FIELDS and key != 'id':
                            del persona[key]
                    persona["is_cde_realm"] = True
                    for realm in case.realm.implied_realms:
                        persona[realm.realm_marker] = True
                    change_note = "CdE Bereich hinzugefügt nach Upgradeanfrage."
                    code = self.core.change_persona_realms(rs, persona, change_note)
                    if not code:  # pragma: no cover
                        raise RuntimeError(n_("Granting CdE realm failed."))

                elif not persona_id:
                    if self.verify_existence(rs, case.persona.username):
                        raise ValueError(n_("Email address already taken."))
                    status = const.GenesisStati.successful

                    data = case.get_persona_creation().as_dict()
                    data.pop("id")
                    # TODO remove those after adjusting the validation of personas for dataclasses
                    merge_dicts(data, PERSONA_DEFAULTS)
                    for admin_role in Roles.all_admin_roles():
                        data.pop(admin_role.marker, None)
                    del data["is_archived"]
                    del data["is_purged"]
                    if "balance" in data:
                        del data["balance"]
                    data["notes"] = case.notes
                    data = affirm(vtypes.Persona, data, creation=True)
                    persona_id = self.create_persona(
                        rs, data, submitted_by=rs.user.persona_id
                    )

                else:
                    status = const.GenesisStati.existing_updated
                    case.persona_id = persona_id

                    persona = self.get_persona(rs, persona_id)
                    persona_status = self.get_persona_status(rs, persona_id)
                    if not self._is_relative_admin(rs, persona_status):
                        raise PrivilegeError(n_("Not privileged."))
                    username = case.persona.username
                    if persona.is_archived:
                        code = self.dearchive_persona(rs, persona_id, username)
                        if not code:  # pragma: no cover
                            raise RuntimeError(n_("Dearchival failed."))
                    elif username != persona.username:
                        code, _ = self.change_username(rs, persona_id, username, None)
                        if not code:  # pragma: no cover
                            raise RuntimeError(n_("Username change failed."))
                    # Set force_review, so that all changes can be reviewed and adjusted
                    # manually and we don't just overwrite existing data blindly.
                    self.change_persona(
                        rs,
                        case.get_persona_upgrade(),
                        force_review=True,
                        change_note="Daten aus Accountanfrage übernommen.",
                    )

            else:
                status = const.GenesisStati.rejected
                persona_id = None

            # finalize the genesis case, now with the correct log message
            code = self.genesis_modify_case_meta(
                rs,
                case_id,
                status=status,
                reviewer_id=rs.user.persona_id,
                persona_id=persona_id,
            )
            if not code:
                raise RuntimeError(n_("Genesis modification failed."))

            if decision.grants_trial_membership() and case.realm == Realms.cde:
                assert persona_id is not None
                persona_status = self.get_persona_status(rs, persona_id)
                if not persona_status.is_member:
                    self.change_membership_easy_mode(
                        rs, persona_id, is_member=True, trial_member=True
                    )

            # Special return value for rejected cases.
            return persona_id
