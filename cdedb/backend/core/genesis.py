#!/usr/bin/env python3

"""
The `CoreGenesisBackend` subclasses the `CoreBaseBackend` and provides functionality
for "genesis", that is for account creation via anonymous account requests.
"""
from collections.abc import Collection
from typing import Any, Optional, Protocol

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
from cdedb.backend.common import (
    access, affirm_set_validation as affirm_set, affirm_validation as affirm,
    affirm_validation_optional as affirm_optional, internal, singularize,
)
from cdedb.backend.core.base import CoreBaseBackend
from cdedb.common import (
    CdEDBObject, CdEDBObjectMap, DefaultReturnCode, DeletionBlockers, GenesisDecision,
    RequestState, glue, merge_dicts, now, unwrap,
)
from cdedb.common.exceptions import PrivilegeError
from cdedb.common.fields import (
    GENESIS_CASE_FIELDS, PERSONA_CORE_FIELDS, REALM_SPECIFIC_GENESIS_FIELDS,
    REALMS_TO_FIELDS,
)
from cdedb.common.n_ import n_
from cdedb.common.roles import (
    GENESIS_REALM_OVERRIDE, PERSONA_DEFAULTS, REALM_ADMINS, extract_realms,
    extract_roles, implied_realms,
)
from cdedb.common.validation.validate import PERSONA_FULL_CREATION, filter_none
from cdedb.database.connection import Atomizer


class CoreGenesisBackend(CoreBaseBackend):
    @access("anonymous")
    def genesis_request(self, rs: RequestState, data: CdEDBObject,
                        ) -> Optional[DefaultReturnCode]:
        """Log a request for a new account.

        This is the initial entry point for such a request.

        :returns: id of the new request or None if the username is already
          taken
        """
        data = affirm(vtypes.GenesisCase, data, creation=True)

        if self.verify_existence(rs, data['username']):
            return None
        if self.is_locked_down(rs) and not self.is_admin(rs):
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
                            cascade: Optional[Collection[str]] = None,
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
    def genesis_verify(self, rs: RequestState, case_id: int,
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
                           stati: Optional[Collection[const.GenesisStati]] = None,
                           realms: Optional[Collection[str]] = None) -> CdEDBObjectMap:
        """List persona creation cases.

        Restrict to certain stati and certain target realms.
        """
        realms = realms or []
        realms = affirm_set(str, realms)
        stati = stati or set()
        stati = affirm_set(const.GenesisStati, stati)
        if not realms and "core_admin" not in rs.user.roles:
            raise PrivilegeError(n_("Not privileged."))
        elif not all({f"{realm}_admin", "core_admin"} & rs.user.roles
                     for realm in realms):
            raise PrivilegeError(n_("Not privileged."))
        query = ("SELECT id, ctime, username, given_names, family_name,"
                 " case_status FROM core.genesis_cases")
        conditions = []
        params: list[Any] = []
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
    def genesis_get_cases(self, rs: RequestState, genesis_case_ids: Collection[int],
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
            if e.get('gender'):
                e['gender'] = const.Genders(e['gender'])
            ret[e['id']] = e
        return ret

    class _GenesisGetCaseProtocol(Protocol):
        def __call__(self, rs: RequestState, genesis_case_id: int) -> CdEDBObject: ...

    genesis_get_case: _GenesisGetCaseProtocol = singularize(
        genesis_get_cases, "genesis_case_ids", "genesis_case_id")

    @access(*REALM_ADMINS)
    def genesis_modify_case(self, rs: RequestState, data: CdEDBObject,
                            ) -> DefaultReturnCode:
        """Modify a persona creation case."""
        data = affirm(vtypes.GenesisCase, data)

        with Atomizer(rs):
            current = self.genesis_get_case(rs, data['id'])
            # Get case already checks privilege and existence for the current data set.
            if not {"core_admin", f"{data['realm']}_admin"} & rs.user.roles:
                raise PrivilegeError(n_("Not privileged."))
            if current['case_status'].is_finalized():
                raise ValueError(n_("Genesis case already finalized."))
            ret = self.sql_update(rs, "core.genesis_cases", data)
            if 'case_status' in data and data['case_status'] != current['case_status']:
                # persona_id of the account this modification is related to. Especially
                # relevant if a new account was created or an existing account was
                # updated. Hence, we sometimes use get and sometimes use [] here.
                if data['case_status'] == const.GenesisStati.successful:
                    self.core_log(
                        rs, const.CoreLogCodes.genesis_approved,
                        persona_id=data['persona_id'], change_note=current['username'])
                elif data['case_status'] == const.GenesisStati.rejected:
                    self.core_log(
                        rs, const.CoreLogCodes.genesis_rejected,
                        persona_id=data.get('persona_id'),
                        change_note=current['username'])
                elif data['case_status'] == const.GenesisStati.existing_updated:
                    self.core_log(
                        rs, const.CoreLogCodes.genesis_merged,
                        persona_id=data['persona_id'])
            else:
                # persona_id should be None in this case.
                self.core_log(rs, const.CoreLogCodes.genesis_change,
                              persona_id=data.get('persona_id'),
                              change_note=current['username'])
        return ret

    @access(*REALM_ADMINS)
    def genesis_decide(self, rs: RequestState, case_id: int, decision: GenesisDecision,
                       persona_id: Optional[int] = None) -> DefaultReturnCode:
        """Final step in the genesis process. Create or modify an account or do nothing.

        :returns: The id of the newly created or modified user if any, -1 if rejected.
        """
        case_id = affirm(vtypes.ID, case_id)
        decision = affirm(GenesisDecision, decision)
        persona_id = affirm_optional(vtypes.ID, persona_id)

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
                'persona_id': persona_id,
            }
            if not self.genesis_modify_case(rs, update):
                raise RuntimeError(n_("Genesis modification failed."))
            if decision.is_create():
                return self.genesis(rs, case_id)
            elif decision.is_update():
                assert persona_id is not None
                persona = self.get_persona(rs, persona_id)
                if not self._is_relative_admin(rs, persona):
                    raise PrivilegeError(n_("Not privileged."))
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
                roles = extract_roles(persona, introspection_only=True)
                for realm, fields in REALM_SPECIFIC_GENESIS_FIELDS.items():
                    # For every realm that the persona has, update the fields implied
                    # by that realm if they are also genesis fields.
                    if realm in roles:
                        update_keys.update(set(fields) & set(REALMS_TO_FIELDS[realm]))
                update_keys -= {'username', 'id'}
                update = {
                    k: case[k] for k in update_keys if case[k]
                }
                update['display_name'] = update['given_names']
                update['id'] = persona_id
                # we grant trial membership by default for cde genesis cases
                if "cde" in roles and not persona["is_member"]:
                    self.change_membership_easy_mode(
                        rs, persona_id, is_member=True, trial_member=True)
                # Set force_review, so that all changes can be reviewed and adjusted
                # manually and we don't just overwrite existing data blindly.
                self.change_persona(
                    rs, update, change_note="Daten aus Accountanfrage übernommen.",
                    force_review=True)
                return persona_id
            # Special return value for rejected cases.
            else:
                return -1

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

            # filter out genesis information not relevant for the respective realm
            allowed_keys = (
                set(filter_none(PERSONA_FULL_CREATION[case['realm']])) & (
                    set(GENESIS_CASE_FIELDS) |
                    set(REALM_SPECIFIC_GENESIS_FIELDS[case['realm']])) - {"id"})

            data = {k: v for k, v in case.items() if k in allowed_keys}
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
                'persona_id': new_id,
            }
            self.genesis_modify_case(rs, update)
        return new_id
