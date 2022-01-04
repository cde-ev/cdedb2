#!/usr/bin/env python3

"""The core backend provides services which are common for all
users/personas independent of their realm. Thus we have no user role
since the basic division is between known accounts and anonymous
accesses.
"""
from typing import Any, Collection, List, Optional, Protocol, Tuple

import cdedb.database.constants as const
import cdedb.validationtypes as vtypes
from cdedb.backend.common import (
    access, affirm_set_validation as affirm_set, affirm_validation as affirm,
    affirm_validation_optional as affirm_optional, internal, singularize,
)
from cdedb.backend.core.base import CoreBaseBackend
from cdedb.common import (
    GENESIS_CASE_FIELDS, GENESIS_REALM_OVERRIDE, PERSONA_ALL_FIELDS,
    PERSONA_CORE_FIELDS, PERSONA_DEFAULTS, PERSONA_FIELDS_BY_REALM, REALM_ADMINS,
    REALM_SPECIFIC_GENESIS_FIELDS, CdEDBObject, CdEDBObjectMap, DefaultReturnCode,
    DeletionBlockers, GenesisDecision, PrivilegeError, RequestState, extract_realms,
    extract_roles, get_hash, glue, implied_realms, merge_dicts, n_, now, unwrap,
)
from cdedb.database.connection import Atomizer


class CoreGenesisBackend(CoreBaseBackend):
    @access("anonymous")
    def genesis_set_attachment(self, rs: RequestState, attachment: bytes
                               ) -> str:
        """Store a file for genesis usage. Returns the file hash."""
        attachment = affirm(vtypes.PDFFile, attachment, file_storage=False)
        myhash = get_hash(attachment)
        path = self.genesis_attachment_dir / myhash
        if not path.exists():
            with open(path, 'wb') as f:
                f.write(attachment)
        return myhash

    @access("anonymous")
    def genesis_check_attachment(self, rs: RequestState, attachment_hash: str
                                 ) -> bool:
        """Check whether a genesis attachment with the given hash is available.

        Contrary to `genesis_get_attachment` this does not retrieve it's
        content.
        """
        attachment_hash = affirm(str, attachment_hash)
        path = self.genesis_attachment_dir / attachment_hash
        return path.is_file()

    @access(*REALM_ADMINS)
    def genesis_get_attachment(self, rs: RequestState, attachment_hash: str
                               ) -> Optional[bytes]:
        """Retrieve a stored genesis attachment."""
        attachment_hash = affirm(str, attachment_hash)
        path = self.genesis_attachment_dir / attachment_hash
        if path.is_file():
            with open(path, 'rb') as f:
                return f.read()
        return None

    @internal
    @access("core_admin")
    def genesis_attachment_usage(self, rs: RequestState,
                                 attachment_hash: str) -> bool:
        """Check whether a genesis attachment is still referenced in a case."""
        attachment_hash = affirm(vtypes.RestrictiveIdentifier, attachment_hash)
        query = "SELECT COUNT(*) FROM core.genesis_cases WHERE attachment_hash = %s"
        return bool(unwrap(self.query_one(rs, query, (attachment_hash,))))

    @access("core_admin")
    def genesis_forget_attachments(self, rs: RequestState) -> int:
        """Delete genesis attachments that are no longer in use."""
        ret = 0
        for f in self.genesis_attachment_dir.iterdir():
            if f.is_file() and not self.genesis_attachment_usage(rs, f.name):
                f.unlink()
                ret += 1
        return ret

    @access("anonymous")
    def genesis_request(self, rs: RequestState, data: CdEDBObject
                        ) -> Optional[DefaultReturnCode]:
        """Log a request for a new account.

        This is the initial entry point for such a request.

        :returns: id of the new request or None if the username is already
          taken
        """
        data = affirm(vtypes.GenesisCase, data, creation=True)

        if self.verify_existence(rs, data['username']):
            return None
        if self.conf["LOCKDOWN"] and not self.is_admin(rs):
            return None
        data['case_status'] = const.GenesisStati.unconfirmed
        with Atomizer(rs):
            ret = self.sql_insert(rs, "core.genesis_cases", data)
            self.core_log(rs, const.CoreLogCodes.genesis_request, persona_id=None,
                          change_note=data['username'])
        return ret

    @access(*REALM_ADMINS)
    def delete_genesis_case_blockers(self, rs: RequestState,
                                     case_id: int) -> DeletionBlockers:
        """Determine what keeps a genesis case from being deleted.

        Possible blockers:

        * unconfirmed: A genesis case with status unconfirmed may only be
                       deleted after the timeout period has passed.
        * case_status: A genesis case may not be deleted if it has one of the
                       following stati: to_review, approved.

        :return: List of blockers, separated by type. The values of the dict
            are the ids of the blockers.
        """

        case_id = affirm(vtypes.ID, case_id)
        blockers: DeletionBlockers = {}

        case = self.genesis_get_case(rs, case_id)
        if (case["case_status"] == const.GenesisStati.unconfirmed and
                now() < case["ctime"] + self.conf["PARAMETER_TIMEOUT"]):
            blockers["unconfirmed"] = [case_id]
        if case["case_status"] in {const.GenesisStati.to_review,
                                   const.GenesisStati.approved}:
            blockers["case_status"] = [case["case_status"]]

        return blockers

    @access(*REALM_ADMINS)
    def delete_genesis_case(self, rs: RequestState, case_id: int,
                            cascade: Collection[str] = None
                            ) -> DefaultReturnCode:
        """Remove a genesis case."""

        case_id = affirm(vtypes.ID, case_id)
        blockers = self.delete_genesis_case_blockers(rs, case_id)
        if "unconfirmed" in blockers.keys():
            raise ValueError(n_("Unable to remove unconfirmed genesis case "
                                "before confirmation timeout."))
        if "case_status" in blockers.keys():
            raise ValueError(n_("Unable to remove genesis case with status {}.")
                             .format(blockers["case_status"]))
        if not cascade:
            cascade = set()
        cascade = affirm_set(str, cascade) & blockers.keys()
        if blockers.keys() - cascade:
            raise ValueError(n_("Deletion of %(type)s blocked by %(block)s."),
                             {
                                 "type": "genesis case",
                                 "block": blockers.keys() - cascade,
                             })

        ret = 1
        with Atomizer(rs):
            case = self.genesis_get_case(rs, case_id)
            if cascade:
                if "unconfirmed" in cascade:
                    raise ValueError(n_("Unable to cascade %(blocker)s."),
                                     {"blocker": "unconfirmed"})
                if "case_status" in cascade:
                    raise ValueError(n_("Unable to cascade %(blocker)s."),
                                     {"blocker": "case_status"})

            if not blockers:
                ret *= self.sql_delete_one(rs, "core.genesis_cases", case_id)
                self.core_log(rs, const.CoreLogCodes.genesis_deleted,
                              persona_id=None, change_note=case["username"])
            else:
                raise ValueError(
                    n_("Deletion of %(type)s blocked by %(block)s."),
                    {"type": "assembly", "block": blockers.keys()})

        return ret

    @access("anonymous")
    def genesis_case_by_email(self, rs: RequestState,
                              email: str) -> Optional[int]:
        """Get the id of an unconfirmed or unreviewed genesis case for a given email.

        :returns: The case id if the case is unconfirmed, the negative id if the case
            is pending review, None if no such case exists.
        """
        email = affirm(str, email)
        query = ("SELECT id FROM core.genesis_cases"
                 " WHERE username = %s AND case_status = %s")
        params = (email, const.GenesisStati.unconfirmed)
        data = self.query_one(rs, query, params)
        if data:
            return unwrap(data)
        params = (email, const.GenesisStati.to_review)
        data = self.query_one(rs, query, params)
        # Pylint does not understand, that unwrap(data) cannot be None here.
        return -unwrap(data) if data else None  # pylint: disable=invalid-unary-operand-type

    @access("anonymous")
    def genesis_verify(self, rs: RequestState, case_id: int
                       ) -> Tuple[DefaultReturnCode, str]:
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
                rs, "core.genesis_cases", ("realm", "username", "case_status"),
                case_id)
            # These should be displayed as useful errors in the frontend.
            if not data:
                return 0, "core"
            elif not data["case_status"] == const.GenesisStati.unconfirmed:
                return -1, data["realm"]
            query = glue("UPDATE core.genesis_cases SET case_status = %s",
                         "WHERE id = %s AND case_status = %s")
            params = (const.GenesisStati.to_review, case_id,
                      const.GenesisStati.unconfirmed)
            ret = self.query_exec(rs, query, params)
            if ret:
                self.core_log(
                    rs, const.CoreLogCodes.genesis_verified, persona_id=None,
                    change_note=data["username"])
        return ret, data["realm"]

    @access(*REALM_ADMINS)
    def genesis_list_cases(self, rs: RequestState,
                           stati: Collection[const.GenesisStati] = None,
                           realms: Collection[str] = None) -> CdEDBObjectMap:
        """List persona creation cases.

        Restrict to certain stati and certain target realms.
        """
        realms = realms or []
        realms = affirm_set(str, realms)
        stati = stati or set()
        stati = affirm_set(const.GenesisStati, stati)
        if not realms and "core_admin" not in rs.user.roles:
            raise PrivilegeError(n_("Not privileged."))
        elif not all({"{}_admin".format(realm), "core_admin"} & rs.user.roles
                     for realm in realms):
            raise PrivilegeError(n_("Not privileged."))
        query = ("SELECT id, ctime, username, given_names, family_name,"
                 " case_status FROM core.genesis_cases")
        conditions = []
        params: List[Any] = []
        if realms:
            conditions.append("realm = ANY(%s)")
            params.append(realms)
        if stati:
            conditions.append("case_status = ANY(%s)")
            params.append(stati)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        data = self.query_all(rs, query, params)
        return {e['id']: e for e in data}

    @access(*REALM_ADMINS)
    def genesis_get_cases(self, rs: RequestState, genesis_case_ids: Collection[int]
                          ) -> CdEDBObjectMap:
        """Retrieve datasets for persona creation cases."""
        genesis_case_ids = affirm_set(vtypes.ID, genesis_case_ids)
        data = self.sql_select(rs, "core.genesis_cases", GENESIS_CASE_FIELDS,
                               genesis_case_ids)
        ret = {}
        for e in data:
            if "core_admin" not in rs.user.roles:
                if f"{e['realm']}_admin" not in rs.user.roles:
                    raise PrivilegeError(n_("Not privileged."))
            e['case_status'] = const.GenesisStati(e['case_status'])
            ret[e['id']] = e
        return ret

    class _GenesisGetCaseProtocol(Protocol):
        def __call__(self, rs: RequestState, genesis_case_id: int) -> CdEDBObject: ...

    genesis_get_case: _GenesisGetCaseProtocol = singularize(
        genesis_get_cases, "genesis_case_ids", "genesis_case_id")

    @access(*REALM_ADMINS)
    def genesis_modify_case(self, rs: RequestState, data: CdEDBObject,
                            persona_id: int = None) -> DefaultReturnCode:
        """Modify a persona creation case.

        :param persona_id: The account, this modification related to. Especially
            relevant if a new account was created or an existing account was updated.
        """
        data = affirm(vtypes.GenesisCase, data)
        persona_id = affirm_optional(vtypes.ID, persona_id)

        with Atomizer(rs):
            current = self.genesis_get_case(rs, data['id'])
            # Get case already checks privilege and existance for the current data set.
            if not {"core_admin", f"{data['realm']}_admin"} & rs.user.roles:
                raise PrivilegeError(n_("Not privileged."))
            if current['case_status'].is_finalized():
                raise ValueError(n_("Genesis case already finalized."))
            ret = self.sql_update(rs, "core.genesis_cases", data)
            if 'case_status' in data and data['case_status'] != current['case_status']:
                if data['case_status'] == const.GenesisStati.successful:
                    self.core_log(
                        rs, const.CoreLogCodes.genesis_approved, persona_id=persona_id,
                        change_note=current['username'])
                elif data['case_status'] == const.GenesisStati.rejected:
                    self.core_log(
                        rs, const.CoreLogCodes.genesis_rejected, persona_id=persona_id,
                        change_note=current['username'])
                elif data['case_status'] == const.GenesisStati.existing_updated:
                    self.core_log(
                        rs, const.CoreLogCodes.genesis_merged, persona_id=persona_id)
        return ret

    @access(*REALM_ADMINS)
    def genesis_decide(self, rs: RequestState, case_id: int, decision: GenesisDecision,
                       persona_id: int = None) -> DefaultReturnCode:
        """Final step in the genesis process. Create or modify an account or do nothing.

        :returns: Default return code. The id of the newly created user if any.
        """
        case_id = affirm(vtypes.ID, case_id)
        decision = affirm(GenesisDecision, decision)
        persona_id = affirm_optional(vtypes.ID, persona_id)

        ret = 1
        with Atomizer(rs):
            # Privilege check is done in genesis_get_case, since it requires the case.
            case = self.genesis_get_case(rs, case_id)
            if case['case_status'] != const.GenesisStati.to_review:
                raise ValueError(n_("Case not to review."))
            if decision.is_create():
                case_status = const.GenesisStati.approved
                persona_id = None
            elif decision.is_update():
                case_status = const.GenesisStati.existing_updated
            else:
                case_status = const.GenesisStati.rejected
            update = {
                'id': case_id,
                'case_status': case_status,
                'reviewer': rs.user.persona_id,
                'realm': case['realm'],
            }
            if not self.genesis_modify_case(rs, update, persona_id):
                raise RuntimeError(n_("Genesis modification failed."))
            if decision.is_create():
                return self.genesis(rs, case_id)
            if decision.is_update():
                assert persona_id is not None
                persona = self.get_persona(rs, persona_id)
                if persona['is_archived']:
                    code = self.dearchive_persona(rs, persona_id, case['username'])
                    if not code:  # pragma: no cover
                        raise RuntimeError(n_("Dearchival failed."))
                elif case['username'] != persona['username']:
                    code, _ = self.change_username(
                        rs, persona_id, case['username'], None)
                    if not code:  # pragma: no cover
                        raise RuntimeError(n_("Username change failed."))

                # Determine the keys of the persona that should be updated.
                update_keys = set(GENESIS_CASE_FIELDS) & set(PERSONA_CORE_FIELDS)
                roles = extract_roles(persona)
                for realm, fields in REALM_SPECIFIC_GENESIS_FIELDS.items():
                    # For every realm that the persona has, update the fields implied
                    # by that realm if they are also genesis fields.
                    if realm in roles:
                        update_keys.update(set(fields) & PERSONA_FIELDS_BY_REALM[realm])
                update_keys -= {'username', 'id'}
                update = {
                    k: case[k] for k in update_keys if case[k]
                }
                update['display_name'] = update['given_names']
                update['id'] = persona_id
                # Set force_review, so that all changes can be reviewed and adjusted
                # manually and we don't just overwrite existing data blindly.
                ret *= self.change_persona(
                    rs, update, change_note="Daten aus Accountanfrage übernommen.",
                    force_review=True)
        return ret

    @internal
    @access(*REALM_ADMINS)
    def genesis(self, rs: RequestState, case_id: int) -> DefaultReturnCode:
        """Create a new user account upon request.

        This is the final step in the genesis process and actually creates
        the account.
        """
        case_id = affirm(vtypes.ID, case_id)
        with Atomizer(rs):
            case = unwrap(self.genesis_get_cases(rs, (case_id,)))
            if self.verify_existence(rs, case['username'], include_genesis=False):
                raise ValueError(n_("Email address already taken."))
            data = {k: v for k, v in case.items()
                    if k in PERSONA_ALL_FIELDS and k != "id"}
            data['display_name'] = data['given_names']
            merge_dicts(data, PERSONA_DEFAULTS)
            # Fix realms, so that the persona validator does the correct thing
            data.update(GENESIS_REALM_OVERRIDE[case['realm']])
            data = affirm(vtypes.Persona, data, creation=True)
            if case['case_status'] != const.GenesisStati.approved:
                raise ValueError(n_("Invalid genesis state."))
            roles = extract_roles(data)
            if extract_realms(roles) != \
                    ({case['realm']} | implied_realms(case['realm'])):
                raise PrivilegeError(n_("Wrong target realm."))
            new_id = self.create_persona(rs, data, submitted_by=case['reviewer'])
            update = {
                'id': case_id,
                'case_status': const.GenesisStati.successful,
                'realm': case['realm'],
            }
            self.genesis_modify_case(rs, update, persona_id=new_id)
        return new_id
