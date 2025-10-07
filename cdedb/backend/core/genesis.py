#!/usr/bin/env python3

"""
The `CoreGenesisBackend` subclasses the `CoreBaseBackend` and provides functionality
for "genesis", that is for account creation via anonymous account requests.
"""

from collections.abc import Collection
from typing import Optional, Protocol

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.core as models
from cdedb.backend.common import (
    access,
    affirm_set_validation as affirm_set,
    affirm_validation as affirm,
    affirm_validation_optional as affirm_optional,
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
    merge_dicts,
    now,
    unwrap,
)
from cdedb.common.exceptions import PrivilegeError
from cdedb.common.n_ import n_
from cdedb.common.roles import (
    ADMIN_KEYS,
    PERSONA_DEFAULTS,
)
from cdedb.database.connection import Atomizer
from cdedb.models.common import CdEDataclassMap


class CoreGenesisBackend(CoreBaseBackend):
    @access("anonymous")
    def genesis_request(
        self, rs: RequestState, data: CdEDBObject
    ) -> Optional[DefaultReturnCode]:
        """Log a request for a new account.

        This is the initial entry point for such a request.

        :returns: id of the new request or None if the username is already
          taken
        """
        realm = affirm(vtypes.Realm, data["realm"], supports_genesis=True)
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
            self.core_log(
                rs,
                const.CoreLogCodes.genesis_request,
                persona_id=None,
                change_note=data['username'],
            )
        return ret

    @access("core_admin", *models.GenesisCase.all_admins)
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

    @access("core_admin", *models.GenesisCase.all_admins)
    def delete_genesis_case(
        self, rs: RequestState, case_id: int, cascade: Optional[Collection[str]] = None
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
        cascade = affirm_set(str, cascade) & blockers.keys()
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

    @access("core_admin", "cde_admin")
    def get_genesis_attachment_usage(
        self, rs: RequestState, attachment_hash: str
    ) -> bool:
        """Check whether an attachment is still referenced."""
        attachment_hash = affirm(vtypes.Identifier, attachment_hash)
        query = "SELECT COUNT(*) FROM core.genesis_cases WHERE attachment_hash = %s"
        return bool(unwrap(self.query_one(rs, query, (attachment_hash,))))

    @access("anonymous")
    def genesis_case_by_email(self, rs: RequestState, email: str) -> Optional[int]:
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

    @access("anonymous")
    def genesis_verify(
        self, rs: RequestState, case_id: int
    ) -> tuple[DefaultReturnCode, str]:
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
                return 0, "core"
            elif not data["status"] == const.GenesisStati.unconfirmed:
                return -1, data["realm"]
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
        return ret, data["realm"]

    @access("core_admin", *models.GenesisCase.all_admins)
    def genesis_list_cases(
        self,
        rs: RequestState,
        stati: Optional[Collection[const.GenesisStati]] = None,
        realms: Optional[Collection[str]] = None,
    ) -> CdEDBObjectMap:
        """List persona creation cases.

        Restrict to certain stati and certain target realms.
        """
        realms = realms or []
        realms = affirm_set(str, realms)
        stati = stati or set()
        stati = affirm_set(const.GenesisStati, stati)
        if not realms and "core_admin" not in rs.user.roles:
            raise PrivilegeError(n_("Not privileged."))
        elif not all(
            {f"{realm}_admin", "core_admin"} & rs.user.roles for realm in realms
        ):
            raise PrivilegeError(n_("Not privileged."))
        query = """
            SELECT id, ctime, username, given_names, family_name, status
            FROM core.genesis_cases
        """
        conditions = []
        params: CdEDBObject = {}
        if realms:
            conditions.append("realm = ANY(%(realms)s)")
            params["realms"] = realms
        if stati:
            conditions.append("status = ANY(%(stati)s)")
            params["stati"] = stati

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        data = self.query_all(rs, query, params)
        return {e['id']: e for e in data}

    @access("core_admin", *models.GenesisCase.all_admins)
    def genesis_get_cases(
        self, rs: RequestState, genesis_case_ids: Collection[int]
    ) -> CdEDataclassMap[models.GenesisCase]:
        """Retrieve datasets for persona creation cases."""
        genesis_case_ids = affirm_set(vtypes.ID, genesis_case_ids)
        cases = models.GenesisCase.many_from_database(
            self.query_all(
                rs, *models.GenesisCase.get_select_query(genesis_case_ids, "id")
            )
        )
        for case in cases.values():
            if {"core_admin", case.relative_admin}.isdisjoint(rs.user.roles):
                raise PrivilegeError(n_("Not privileged."))
        return cases

    class _GenesisGetCaseProtocol(Protocol):
        def __call__(
            self, rs: RequestState, genesis_case_id: int
        ) -> models.GenesisCase: ...

    genesis_get_case: _GenesisGetCaseProtocol = singularize(
        genesis_get_cases, "genesis_case_ids", "genesis_case_id"
    )

    @access("core_admin", *models.GenesisCase.all_admins)
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

    @access("core_admin", *models.GenesisCase.all_admins)
    def genesis_modify_case_realm(
        self, rs: RequestState, case_id: int, realm: str
    ) -> DefaultReturnCode:
        """Modify a the realm of a persona creation case."""
        realm = affirm(vtypes.Realm, realm, supports_genesis=True)
        update = {"id": case_id, "realm": realm}
        with Atomizer(rs):
            # Get case already checks privilege and existence for the current data set.
            current = self.genesis_get_case(rs, case_id)
            if current.realm == "ml" or realm == "ml":
                raise RuntimeError("Realm modification forbidden.")
            relative_admins = {
                models.GenesisCaseCdE.relative_admin,
                models.GenesisCaseEvent.relative_admin,
            }
            if {"core_admin", *relative_admins}.isdisjoint(rs.user.roles):
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

    @access("core_admin", *models.GenesisCase.all_admins)
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
                    # TODO this case was not logged until now, and there is
                    #  no meaningful log code for this.
                    pass
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

    @access("core_admin", *models.GenesisCase.all_admins)
    def genesis_decide(
        self,
        rs: RequestState,
        case_id: int,
        decision: GenesisDecision,
        persona_id: Optional[int] = None,
    ) -> DefaultReturnCode:
        """Final step in the genesis process. Create or modify an account or do nothing.

        :returns: The id of the newly created or modified user if any, -1 if rejected.
        """
        case_id = affirm(vtypes.ID, case_id)
        decision = affirm(GenesisDecision, decision)
        persona_id = affirm_optional(vtypes.ID, persona_id)

        with Atomizer(rs):
            # Privilege check is done in genesis_get_case, since it requires the case.
            case = self.genesis_get_case(rs, case_id)
            if case.status != const.GenesisStati.to_review:
                raise ValueError(n_("Case not to review."))
            if decision.is_create():
                status = const.GenesisStati.approved
            elif decision.is_update():
                case.persona_id = persona_id
                status = const.GenesisStati.existing_updated
            else:
                status = const.GenesisStati.rejected
            ret_code = self.genesis_modify_case_meta(
                rs,
                case_id,
                status=status,
                reviewer_id=rs.user.persona_id,
                persona_id=persona_id,
            )
            if not ret_code:
                raise RuntimeError(n_("Genesis modification failed."))
            if decision.is_create():
                return self.genesis(rs, case_id)
            elif decision.is_update():
                assert case.persona_id is not None
                persona = self.get_persona(rs, case.persona_id)
                if not self._is_relative_admin(rs, persona):
                    raise PrivilegeError(n_("Not privileged."))
                if persona['is_archived']:
                    code = self.dearchive_persona(
                        rs, case.persona_id, case.persona.username
                    )
                    if not code:  # pragma: no cover
                        raise RuntimeError(n_("Dearchival failed."))
                elif case.persona.username != persona['username']:
                    code, _ = self.change_username(
                        rs, case.persona_id, case.persona.username, None
                    )
                    if not code:  # pragma: no cover
                        raise RuntimeError(n_("Username change failed."))

                # we grant trial membership by default for cde genesis cases
                if case.realm == "cde" and not persona["is_member"]:
                    self.change_membership_easy_mode(
                        rs, case.persona_id, is_member=True, trial_member=True
                    )
                # Set force_review, so that all changes can be reviewed and adjusted
                # manually and we don't just overwrite existing data blindly.
                self.change_persona(
                    rs,
                    case.get_persona_upgrade(),
                    force_review=True,
                    change_note="Daten aus Accountanfrage übernommen.",
                )
                return case.persona_id
            # Special return value for rejected cases.
            else:
                return -1

    @internal
    @access("core_admin", *models.GenesisCase.all_admins)
    def genesis(self, rs: RequestState, case_id: int) -> DefaultReturnCode:
        """Create a new user account upon request.

        This is the final step in the genesis process and actually creates
        the account.
        """
        case_id = affirm(vtypes.ID, case_id)
        with Atomizer(rs):
            case = self.genesis_get_case(rs, case_id)
            if self.verify_existence(rs, case.persona.username, include_genesis=False):
                raise ValueError(n_("Email address already taken."))

            data = case.get_persona_creation().as_dict()
            data.pop("id")
            # TODO remove those after adjusting the validation of personas for dataclasses
            merge_dicts(data, PERSONA_DEFAULTS)
            for admin_bit in ADMIN_KEYS:
                del data[admin_bit]
            del data["is_archived"]
            del data["is_purged"]
            if "balance" in data:
                del data["balance"]
            data = affirm(vtypes.Persona, data, creation=True)
            if case.status != const.GenesisStati.approved:
                raise ValueError(n_("Invalid genesis state."))
            new_id = self.create_persona(rs, data, submitted_by=case.reviewer)
            self.genesis_modify_case_meta(
                rs, case_id, status=const.GenesisStati.successful, persona_id=new_id
            )
        return new_id
