#!/usr/bin/env python3

"""The ml backend provides mailing lists. This provides services to the
event and assembly realm in the form of specific mailing lists.
"""
import itertools
from datetime import datetime
from typing import (
    Any, Collection, Dict, List, Optional, Protocol, Set, Tuple, cast, overload,
)

import cdedb.database.constants as const
import cdedb.ml_type_aux as ml_type
import cdedb.subman as subman
import cdedb.validationtypes as vtypes
from cdedb.backend.assembly import AssemblyBackend
from cdedb.backend.common import (
    AbstractBackend, access, affirm_array_validation as affirm_array,
    affirm_set_validation as affirm_set, affirm_validation as affirm, internal,
    singularize,
)
from cdedb.backend.event import EventBackend
from cdedb.common import (
    ADMIN_KEYS, MAILINGLIST_FIELDS, MOD_ALLOWED_FIELDS, RESTRICTED_MOD_ALLOWED_FIELDS,
    CdEDBLog, CdEDBObject, CdEDBObjectMap, DefaultReturnCode, DeletionBlockers,
    PrivilegeError, RequestState, implying_realms, make_proxy, n_, unwrap, xsorted,
)
from cdedb.database.connection import Atomizer
from cdedb.ml_type_aux import MLType, MLTypeLike
from cdedb.query import Query, QueryOperators, QueryScope, QuerySpecEntry
from cdedb.subman.machine import SubscriptionAction, SubscriptionPolicy

SubStates = Collection[const.SubscriptionState]


class MlBackend(AbstractBackend):
    """Take note of the fact that some personas are moderators and thus have
    additional actions available."""
    realm = "ml"

    def __init__(self):
        super().__init__()
        self.event = make_proxy(EventBackend(), internal=True)
        self.assembly = make_proxy(AssemblyBackend(), internal=True)
        self.backends = ml_type.BackendContainer(
            core=self.core, event=self.event, assembly=self.assembly)
        self.subman = subman.SubscriptionManager(
            unwritten_states=(const.SubscriptionState.none,))

    @classmethod
    def is_admin(cls, rs: RequestState) -> bool:
        return super().is_admin(rs)

    @access("ml")
    def get_ml_type(self, rs: RequestState, mailinglist_id: int) -> MLType:
        mailinglist_id = affirm(vtypes.ID, mailinglist_id)
        data = self.sql_select_one(
            rs, "ml.mailinglists", ("ml_type",), mailinglist_id)
        if not data:
            raise ValueError(n_("Unknown mailinglist_id."))
        return ml_type.get_type(data['ml_type'])

    @overload
    def is_relevant_admin(self, rs: RequestState, *,
                          mailinglist: CdEDBObject) -> bool: ...

    @overload
    def is_relevant_admin(self, rs: RequestState, *,
                          mailinglist_id: int) -> bool: ...

    @access("ml")
    def is_relevant_admin(self, rs: RequestState, *,
                          mailinglist: CdEDBObject = None,
                          mailinglist_id: int = None) -> bool:
        """Check if the user is a relevant admin for a mailinglist.

        Exactly one of the inputs should be provided.
        """
        if mailinglist is None:
            if mailinglist_id is None:
                raise ValueError(n_("No mailinglist specified."))
            atype = self.get_ml_type(rs, mailinglist_id)
        else:
            if mailinglist_id is not None:
                if mailinglist['id'] != mailinglist_id:
                    raise ValueError(n_("Different mailinglists specified."))
            atype = ml_type.get_type(mailinglist['ml_type'])
        return atype.is_relevant_admin(rs.user)

    @access("ml")
    def is_moderator(self, rs: RequestState, ml_id: int,
                     allow_restricted: bool = True) -> bool:
        """Check for moderator privileges as specified in the ml.moderators
        table.

        :param allow_restricted: Whether or not to allow restricted moderators to
            perform this action. Delegated to `MailinglistType.is_restricted_moderator`.
        """
        ml_id = affirm(vtypes.ID, ml_id)

        is_moderator = ml_id in rs.user.moderator
        if not allow_restricted:
            atype = self.get_ml_type(rs, ml_id)
            ml = self.get_mailinglist(rs, ml_id)
            is_restricted = atype.is_restricted_moderator(rs, self.backends, ml)
            is_moderator = is_moderator and not is_restricted

        return is_moderator

    @access("ml")
    def may_manage(self, rs: RequestState, mailinglist_id: int,
                   allow_restricted: bool = True) -> bool:
        """Check whether a user is allowed to manage a given mailinglist.

        :param allow_restricted: See `MlBackend.is_moderator`.
        """
        mailinglist_id = affirm(vtypes.ID, mailinglist_id)

        return (self.is_moderator(rs, mailinglist_id, allow_restricted=allow_restricted)
                or self.is_relevant_admin(rs, mailinglist_id=mailinglist_id))

    @access("ml")
    def get_available_types(self, rs: RequestState) -> Set[const.MailinglistTypes]:  # pylint: disable=no-self-use
        """Get a list of MailinglistTypes the user is allowed to manage."""
        ret = {enum_member for enum_member, atype in ml_type.TYPE_MAP.items()
               if atype.is_relevant_admin(rs.user)}
        return ret

    @overload
    def get_subscription_policy(self, rs: RequestState, persona_id: int, *,
                                mailinglist: CdEDBObject) -> SubscriptionPolicy:
        pass

    @overload
    def get_subscription_policy(self, rs: RequestState, persona_id: int, *,
                                mailinglist_id: int) -> SubscriptionPolicy:
        pass

    @access("ml")
    def get_subscription_policy(self, rs: RequestState, persona_id: int, *,
                                mailinglist: CdEDBObject = None,
                                mailinglist_id: int = None) -> SubscriptionPolicy:
        """What may the user do with a mailinglist. Be aware, that this does
        not take unsubscribe overrides into account.

        If the mailinglist is available to the caller, they should pass it,
        otherwise it will be retrieved from the database.
        """
        # TODO put these checks in an atomizer?
        if mailinglist is None and mailinglist_id is None:
            raise ValueError("No input specified")
        elif mailinglist is not None and mailinglist_id is not None:
            raise ValueError("Too many inputs specified")
        elif mailinglist_id:
            mailinglist_id = affirm(vtypes.ID, mailinglist_id)
            mailinglist = self.get_mailinglist(rs, mailinglist_id)

        persona_id = affirm(vtypes.ID, persona_id)
        ml = cast(CdEDBObject,
                  affirm(vtypes.Mailinglist, mailinglist, _allow_readonly=True))

        if not (rs.user.persona_id == persona_id
                or self.may_manage(rs, ml['id'], allow_restricted=False)):
            raise PrivilegeError(n_("Not privileged."))

        return self.get_ml_type(rs, ml["id"]).get_subscription_policy(
            rs, self.backends, ml, persona_id)

    @access("ml")
    def filter_personas_by_policy(self, rs: RequestState, ml: CdEDBObject,
                                  data: Collection[CdEDBObject],
                                  allowed_pols: Collection[SubscriptionPolicy],
                                  ) -> Tuple[CdEDBObject, ...]:
        """Restrict persona sample to eligibles.

        This additional endpoint checking for interaction policies is
        supposed to only be used for
        `cdedb.frontend.core.select_persona()`, to reduce the amount
        of necessary database queries.

        :param data: Return of the persona select query
        :return: Tuple of personas whose interaction policies are in
            allowed_pols
        """
        affirm(vtypes.Mailinglist, ml, _allow_readonly=True)
        affirm_set(SubscriptionPolicy, allowed_pols)

        # persona_ids are validated inside get_personas
        persona_ids = tuple(e['id'] for e in data)
        atype = ml_type.get_type(ml['ml_type'])
        persona_policies = atype.get_subscription_policies(
            rs, self.backends, ml, persona_ids)
        return tuple(e for e in data
                     if persona_policies[e['id']] in allowed_pols)

    @access("ml")
    def may_view(self, rs: RequestState, ml: CdEDBObject) -> bool:
        """Helper to determine whether a persona may view a mailinglist.

        :type: bool
        """
        is_subscribed = self.is_subscribed(rs, rs.user.persona_id, ml["id"])
        return (is_subscribed or self.get_ml_type(rs, ml["id"]).may_view(rs)
                or ml["id"] in rs.user.moderator)

    @access("persona")
    def moderator_infos(self, rs: RequestState, persona_ids: Collection[int]
                        ) -> Dict[int, Set[int]]:
        """List mailing lists moderated by specific personas."""
        persona_ids = affirm_set(vtypes.ID, persona_ids)
        data = self.sql_select(
            rs, "ml.moderators", ("persona_id", "mailinglist_id"), persona_ids,
            entity_key="persona_id")
        ret = {}
        for anid in persona_ids:
            ret[anid] = {x['mailinglist_id'] for x in data if x['persona_id'] == anid}
        return ret

    class _ModeratorInfoProtocol(Protocol):
        def __call__(self, rs: RequestState, persona_id: int) -> Set[int]: ...
    moderator_info: _ModeratorInfoProtocol = singularize(
        moderator_infos, "persona_ids", "persona_id")

    def ml_log(self, rs: RequestState, code: const.MlLogCodes,
               mailinglist_id: Optional[int], persona_id: Optional[int] = None,
               change_note: Optional[str] = None, atomized: bool = True
               ) -> DefaultReturnCode:
        """Make an entry in the log.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.

        :param atomized: Whether this function should enforce an atomized context
            to be present.
        """
        if rs.is_quiet:
            return 0
        # To ensure logging is done if and only if the corresponding action happened,
        # we require atomization by default.
        if atomized:
            self.affirm_atomized_context(rs)
        new_log = {
            "code": code,
            "mailinglist_id": mailinglist_id,
            "submitted_by": rs.user.persona_id,
            "persona_id": persona_id,
            "change_note": change_note,

        }
        return self.sql_insert(rs, "ml.log", new_log)

    @access("ml", "auditor")
    def retrieve_log(self, rs: RequestState,
                     codes: Optional[Collection[const.MlLogCodes]] = None,
                     mailinglist_ids: Optional[Collection[int]] = None,
                     offset: Optional[int] = None, length: Optional[int] = None,
                     persona_id: Optional[int] = None,
                     submitted_by: Optional[int] = None,
                     change_note: Optional[str] = None,
                     time_start: Optional[datetime] = None,
                     time_stop: Optional[datetime] = None) -> CdEDBLog:
        """Get recorded activity.

        To support relative admins, this is the only retrieve_log function
        which allows to query a list for entity_ids.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.
        """
        mailinglist_ids = affirm_set(vtypes.ID, mailinglist_ids or set())
        if not (self.is_admin(rs) or (mailinglist_ids
                and all(self.may_manage(rs, ml_id)
                        for ml_id in mailinglist_ids))
                or "auditor" in rs.user.roles):
            raise PrivilegeError(n_("Not privileged."))
        return self.generic_retrieve_log(
            rs, const.MlLogCodes, "mailinglist", "ml.log", codes=codes,
            entity_ids=mailinglist_ids, offset=offset, length=length,
            persona_id=persona_id, submitted_by=submitted_by,
            change_note=change_note, time_start=time_start,
            time_stop=time_stop)

    @access("core_admin", "ml_admin")
    def submit_general_query(self, rs: RequestState,
                             query: Query) -> Tuple[CdEDBObject, ...]:
        """Realm specific wrapper around
        :py:meth:`cdedb.backend.common.AbstractBackend.general_query`.`
        """
        query = affirm(Query, query)
        if query.scope in {QueryScope.ml_user, QueryScope.archived_persona}:
            # Include only un-archived ml users.
            query.constraints.append(("is_ml_realm", QueryOperators.equal,
                                      True))
            query.constraints.append(("is_archived", QueryOperators.equal,
                                      query.scope == QueryScope.archived_persona))
            query.spec["is_ml_realm"] = QuerySpecEntry("bool", "")
            query.spec["is_archived"] = QuerySpecEntry("bool", "")
            # Exclude users of any higher realm (implying event)
            for realm in implying_realms('ml'):
                query.constraints.append(
                    ("is_{}_realm".format(realm), QueryOperators.equal, False))
                query.spec["is_{}_realm".format(realm)] = QuerySpecEntry("bool", "")
        else:
            raise RuntimeError(n_("Bad scope."))
        return self.general_query(rs, query)

    @access("ml")
    def list_mailinglists(self, rs: RequestState, active_only: bool = True,
                          managed: str = None) -> Dict[int, str]:
        """List all mailinglists you may view

        :param active_only: Toggle wether inactive lists should be included.
        :param managed: Valid values:

            * None:         no additional filter
            * admin:        list only lists administrated
            * managed:      list only lists moderated or administrated
        :returns: Mapping of mailinglist ids to titles.
        """
        active_only = affirm(bool, active_only)
        query = "SELECT id, title FROM ml.mailinglists"
        constraints = []
        params: List[Any] = []
        if active_only:
            constraints.append("is_active = True")

        if constraints:
            query += " WHERE " + " AND ".join(constraints)

        with Atomizer(rs):
            data = self.query_all(rs, query, params)
            # Get additional information to find out if we can view these lists
            ml_ids = [e['id'] for e in data]
            mailinglists = self.get_mailinglists(rs, ml_ids)
        ret = {e['id']: e['title'] for e in data}

        # Filter the  list returned depending on value of managed
        # Admins can administrate and view anything
        if self.is_admin(rs):
            return ret
        if managed == 'admin':
            return {k: v for k, v in ret.items()
                    if self.is_relevant_admin(rs, mailinglist_id=k)}
        if managed == 'managed':
            return {k: v for k, v in ret.items()
                    if self.may_manage(rs, mailinglist_id=k)}
        else:
            return {k: v for k, v in ret.items()
                    if self.may_view(rs, mailinglists[k])}

    def list_mailinglist_addresses(self, rs: RequestState) -> Dict[int, str]:
        """List all mailinglist adresses

        This is for the purpose of preventing duplicate mail adresses,
        so it lists mail adresses even if you can not see the corresponding
        mailinglists.

        :returns: Mapping of mailinglist ids to titles.
        """
        query = "SELECT id, address FROM ml.mailinglists"
        data = self.query_all(rs, query, [])
        return {e['id']: e['address'] for e in data}

    @access("ml", "droid")
    def get_mailinglists(self, rs: RequestState, mailinglist_ids: Collection[int]
                         ) -> CdEDBObjectMap:
        """Retrieve data for some mailinglists.

        This provides the following additional attributes:

        * moderators,
        * whitelist.
        """
        mailinglist_ids = affirm_set(vtypes.ID, mailinglist_ids)
        with Atomizer(rs):
            data = self.sql_select(rs, "ml.mailinglists", MAILINGLIST_FIELDS,
                                   mailinglist_ids)
            ret = {}
            for e in data:
                e['ml_type'] = const.MailinglistTypes(e['ml_type'])
                e['ml_type_class'] = ml_type.TYPE_MAP[e['ml_type']]
                e['domain'] = const.MailinglistDomain(e['domain'])
                e['domain_str'] = e['domain'].get_domain()
                e['mod_policy'] = const.ModerationPolicy(e['mod_policy'])
                e['attachment_policy'] = const.AttachmentPolicy(e['attachment_policy'])
                e['registration_stati'] = [
                    const.RegistrationPartStati(v) for v in e['registration_stati']]
                ret[e['id']] = e
            data = self.sql_select(
                rs, "ml.moderators", ("persona_id", "mailinglist_id"), mailinglist_ids,
                entity_key="mailinglist_id")
            for anid in mailinglist_ids:
                moderators = {d['persona_id']
                              for d in data if d['mailinglist_id'] == anid}
                if 'moderators' in ret[anid]:
                    raise RuntimeError()
                ret[anid]['moderators'] = moderators
            data = self.sql_select(
                rs, "ml.whitelist", ("address", "mailinglist_id"), mailinglist_ids,
                entity_key="mailinglist_id")
        for ml in ret.values():
            ml['whitelist'] = set()
        for e in data:
            ret[e['mailinglist_id']]['whitelist'].add(e['address'])
        return ret

    class _GetMailinglistProtocol(Protocol):
        def __call__(self, rs: RequestState, mailinglist_id: int) -> CdEDBObject: ...
    get_mailinglist: _GetMailinglistProtocol = singularize(get_mailinglists)

    @access("ml")
    def add_moderators(self, rs: RequestState, mailinglist_id: int,
                       persona_ids: Collection[int], change_note: Optional[str] = None
                       ) -> DefaultReturnCode:
        """Add moderators to a mailinglist."""
        mailinglist_id = affirm(vtypes.ID, mailinglist_id)
        persona_ids = affirm_set(vtypes.ID, persona_ids)

        if not self.may_manage(rs, mailinglist_id):
            raise PrivilegeError("Not privileged.")

        ret = 1
        with Atomizer(rs):
            if not self.core.verify_ids(rs, persona_ids, is_archived=False):
                raise ValueError(n_(
                    "Some of these users do not exist or are archived."))
            if not self.core.verify_personas(rs, persona_ids, {"ml"}):
                raise ValueError(n_("Some of these users are not ml users."))

            for anid in xsorted(persona_ids):
                new_mod = {
                    'persona_id': anid,
                    'mailinglist_id': mailinglist_id,
                }
                # on conflict do nothing
                r = self.sql_insert(rs, "ml.moderators", new_mod,
                                    drop_on_conflict=True)
                if r:
                    self.ml_log(rs, const.MlLogCodes.moderator_added, mailinglist_id,
                                persona_id=anid, change_note=change_note)
                ret *= r

        return ret

    @access("ml")
    def remove_moderator(self, rs: RequestState, mailinglist_id: int,
                         persona_id: int, change_note: Optional[str] = None
                         ) -> DefaultReturnCode:
        """Remove moderators from a mailinglist."""
        mailinglist_id = affirm(vtypes.ID, mailinglist_id)
        persona_id = affirm(vtypes.ID, persona_id)

        if not self.may_manage(rs, mailinglist_id):
            raise PrivilegeError("Not privileged.")

        query = ("DELETE FROM ml.moderators"
                 " WHERE persona_id = %s AND mailinglist_id = %s")
        with Atomizer(rs):
            # First make sure there is at least one moderator left.
            current_moderators = self.sql_select_one(
                rs, "ml.moderators", ["mailinglist_id", "persona_id"],
                mailinglist_id, "mailinglist_id")
            assert current_moderators is not None
            if len(current_moderators) == 1:
                raise ValueError(n_("Cannot remove all moderators."))

            ret = self.query_exec(rs, query, (persona_id, mailinglist_id))
            if ret:
                self.ml_log(rs, const.MlLogCodes.moderator_removed, mailinglist_id,
                            persona_id=persona_id, change_note=change_note)
        return ret

    @access("ml")
    def add_whitelist_entry(self, rs: RequestState, mailinglist_id: int,
                            address: str) -> DefaultReturnCode:
        """Add whitelist entry for a mailinglist."""
        mailinglist_id = affirm(vtypes.ID, mailinglist_id)
        address = affirm(str, address)

        if not self.may_manage(rs, mailinglist_id):
            raise PrivilegeError(n_("Not privileged."))

        new_white = {
            'address': address,
            'mailinglist_id': mailinglist_id,
        }
        with Atomizer(rs):
            ret = self.sql_insert(rs, "ml.whitelist", new_white,
                                  drop_on_conflict=True)
            if ret:
                self.ml_log(rs, const.MlLogCodes.whitelist_added,
                            mailinglist_id, change_note=address)
        return ret

    @access("ml")
    def remove_whitelist_entry(self, rs: RequestState, mailinglist_id: int,
                               address: str) -> DefaultReturnCode:
        """Remove whitelist entry from a mailinglist."""
        mailinglist_id = affirm(vtypes.ID, mailinglist_id)
        address = affirm(str, address)

        if not self.may_manage(rs, mailinglist_id):
            raise PrivilegeError(n_("Not privileged."))

        query = ("DELETE FROM ml.whitelist"
                 " WHERE address = %s AND mailinglist_id = %s")
        with Atomizer(rs):
            ret = self.query_exec(rs, query, (address, mailinglist_id))
            if ret:
                self.ml_log(rs, const.MlLogCodes.whitelist_removed,
                            mailinglist_id, change_note=address)
        return ret

    def _ml_type_transition(self, rs: RequestState, mailinglist_id: int,
                            old_type: MLTypeLike,
                            new_type: MLTypeLike) -> DefaultReturnCode:
        old_type = ml_type.get_type(old_type)
        new_type = ml_type.get_type(new_type)
        # implicitly atomized context.
        self.affirm_atomized_context(rs)
        obsolete_fields = (
            old_type.get_additional_fields().keys()
            - new_type.get_additional_fields().keys()
        )
        if obsolete_fields:
            setter = ", ".join(f"{f} = DEFAULT" for f in obsolete_fields)
            query = f"UPDATE ml.mailinglists SET {setter} WHERE id = %s"
            params = (mailinglist_id,)
            return self.query_exec(rs, query, params)
        else:
            return 1

    @access("ml")
    def set_mailinglist(self, rs: RequestState,
                        data: CdEDBObject) -> DefaultReturnCode:
        """Update some keys of a mailinglist.

        If the keys 'moderators' or 'whitelist' are present you have to pass
        the complete set of moderator IDs or whitelisted addresses, which
        will superseed the current list.

        If the new mailinglist type does not allow unsubscription,
        all unsubscriptions are dropped without exception.

        This requires different levels of access depending on what change is
        made. Most attributes of the mailinglist may set by moderators, but for
        some you need admin privileges.
        """
        data = affirm(vtypes.Mailinglist, data)

        ret = 1
        with Atomizer(rs):
            current = self.get_mailinglist(rs, data['id'])
            changed = {k for k, v in data.items()
                       if k not in current or v != current[k]}
            is_admin = self.is_relevant_admin(rs, mailinglist=current)
            is_moderator = self.is_moderator(rs, current['id'])
            is_restricted = not self.is_moderator(rs, current['id'],
                                                  allow_restricted=False)
            # determinate if changes are permitted
            if not is_admin:
                if not is_moderator:
                    raise PrivilegeError(n_(
                        "Need to be moderator or admin to change mailinglist."))
                if not changed <= MOD_ALLOWED_FIELDS:
                    raise PrivilegeError(n_("Need to be admin to change this."))
                if not changed <= RESTRICTED_MOD_ALLOWED_FIELDS and is_restricted:
                    raise PrivilegeError(n_(
                        "Restricted moderators are not allowed to change this."))

            mdata = {k: v for k, v in data.items() if k in MAILINGLIST_FIELDS}
            if len(mdata) > 1:
                mdata['address'] = self.validate_address(
                    rs, dict(current, **mdata))
                ret *= self.sql_update(rs, "ml.mailinglists", mdata)
                self.ml_log(rs, const.MlLogCodes.list_changed, data['id'])
            if 'ml_type' in changed:
                # Check if privileges allow new state of the mailinglist.
                if not self.is_relevant_admin(rs, mailinglist_id=data['id']):
                    raise PrivilegeError("Not privileged to make this change.")
                if not ml_type.TYPE_MAP[data['ml_type']].allow_unsub:
                    # Delete all unsubscriptions for mandatory list.
                    query = ("DELETE FROM ml.subscription_states "
                             "WHERE mailinglist_id = %s "
                             "AND subscription_state = ANY(%s)")
                    # noinspection PyTypeChecker
                    params = (data['id'], self.subman.written_states -
                              const.SubscriptionState.subscribing_states())
                    self.query_exec(rs, query, params)
                ret *= self._ml_type_transition(
                    rs, data['id'], old_type=current['ml_type'],
                    new_type=data['ml_type'])

            # only full moderators and admins can make subscription state
            # related changes.
            if is_admin or not is_restricted:
                ret *= self.write_subscription_states(rs, (data['id'],))
        return ret

    @access("ml")
    def create_mailinglist(self, rs: RequestState,
                           data: CdEDBObject) -> DefaultReturnCode:
        """Make a new mailinglist.

        :returns: the id of the new mailinglist
        """
        data = affirm(vtypes.Mailinglist, data, creation=True)
        data['address'] = self.validate_address(rs, data)
        if not self.is_relevant_admin(rs, mailinglist=data):
            raise PrivilegeError("Not privileged to create mailinglist of this type.")
        with Atomizer(rs):
            mdata = {k: v for k, v in data.items() if k in MAILINGLIST_FIELDS}
            new_id = self.sql_insert(rs, "ml.mailinglists", mdata)
            self.ml_log(rs, const.MlLogCodes.list_created, new_id)
            if data.get("moderators"):
                self.add_moderators(rs, new_id, data["moderators"])
            self.write_subscription_states(rs, (new_id,))
        return new_id

    @access("ml")
    def validate_address(self, rs: RequestState, data: CdEDBObject) -> str:
        """Construct the complete address and check for duplicates.

        :returns: the id of the new mailinglist
        """
        address = ml_type.get_full_address(data)
        addresses = self.list_mailinglist_addresses(rs)
        # address can either be free or taken by the current mailinglist
        if (address in addresses.values()
                and address != addresses.get(data.get('id', 0))):
            raise ValueError(n_("Non-unique mailinglist name"))
        return address

    @access("ml")
    def delete_mailinglist_blockers(self, rs: RequestState,
                                    mailinglist_id: int) -> DeletionBlockers:
        """Determine what blocks a mailinglist from being deleted.

        Possible blockers:

        * subscriptions: A subscription to the mailinglist.
        * addresses: A non-default subscribtion address for the mailinglist.
        * whitelist: An entry on the whitelist of the mailinglist.
        * moderator: A moderator of the mailinglist.
        * log: A log entry for the mailinglist.

        :return: List of blockers, separated by type. The values of the dict
            are the ids of the blockers.
        """
        mailinglist_id = affirm(vtypes.ID, mailinglist_id)
        if not self.is_relevant_admin(rs, mailinglist_id=mailinglist_id):
            raise PrivilegeError(n_("Not privileged."))
        blockers = {}

        subscriptions = self.sql_select(
            rs, "ml.subscription_states", ("id",), (mailinglist_id,),
            entity_key="mailinglist_id")
        if subscriptions:
            blockers["subscriptions"] = [e["id"] for e in subscriptions]

        addresses = self.sql_select(
            rs, "ml.subscription_addresses", ("id",), (mailinglist_id,),
            entity_key="mailinglist_id")
        if addresses:
            blockers["addresses"] = [e["id"] for e in addresses]

        whitelist = self.sql_select(
            rs, "ml.whitelist", ("id",), (mailinglist_id,),
            entity_key="mailinglist_id")
        if whitelist:
            blockers["whitelist"] = [e["id"] for e in whitelist]

        moderators = self.sql_select(
            rs, "ml.moderators", ("id",), (mailinglist_id,),
            entity_key="mailinglist_id")
        if moderators:
            blockers["moderators"] = [e["id"] for e in moderators]

        log = self.sql_select(
            rs, "ml.log", ("id",), (mailinglist_id,),
            entity_key="mailinglist_id")
        if log:
            blockers["log"] = [e["id"] for e in log]

        return blockers

    @access("ml")
    def delete_mailinglist(self, rs: RequestState, mailinglist_id: int,
                           cascade: Collection[str] = None,
                           ) -> DefaultReturnCode:
        """Remove a mailinglist.

        :param cascade: Specify which deletion blockers to cascadingly
            remove or ignore. If None or empty, cascade none.
        """
        mailinglist_id = affirm(vtypes.ID, mailinglist_id)
        if not self.is_relevant_admin(rs, mailinglist_id=mailinglist_id):
            raise PrivilegeError(n_("Not privileged."))
        blockers = self.delete_mailinglist_blockers(rs, mailinglist_id)
        if not cascade:
            cascade = set()
        cascade = affirm_set(str, cascade)
        cascade = cascade & blockers.keys()
        if blockers.keys() - cascade:
            raise ValueError(n_("Deletion of %(type)s blocked by %(block)s."),
                             {
                                 "type": "mailinglist",
                                 "block": blockers.keys() - cascade,
                             })

        ret = 1
        with Atomizer(rs):
            if cascade:
                if "subscriptions" in cascade:
                    ret *= self.sql_delete(rs, "ml.subscription_states",
                                           blockers["subscriptions"])
                if "addresses" in cascade:
                    ret *= self.sql_delete(rs, "ml.subscription_addresses",
                                           blockers["addresses"])
                if "whitelist" in cascade:
                    ret *= self.sql_delete(rs, "ml.whitelist",
                                           blockers["whitelist"])
                if "moderators" in cascade:
                    ret *= self.sql_delete(rs, "ml.moderators",
                                           blockers["moderators"])
                if "log" in cascade:
                    ret *= self.sql_delete(rs, "ml.log", blockers["log"])

                # check if mailinglist is deletable after cascading
                blockers = self.delete_mailinglist_blockers(rs, mailinglist_id)

            if not blockers:
                ml_data = self.get_mailinglist(rs, mailinglist_id)
                ret *= self.sql_delete_one(
                    rs, "ml.mailinglists", mailinglist_id)
                self.ml_log(rs, const.MlLogCodes.list_deleted,
                            mailinglist_id=None, change_note="{} ({})".
                            format(ml_data['title'], ml_data['address']))
            else:
                raise ValueError(
                    n_("Deletion of %(type)s blocked by %(block)s."),
                    {"type": "mailinglist", "block": blockers.keys()})

        return ret

    @internal
    @access("ml")
    def _set_subscriptions(self, rs: RequestState,
                           data: Collection[CdEDBObject]) -> DefaultReturnCode:
        """Change or add ml.subscription_states rows.

        This does not check whether the subscription change makes sense
        regarding the mailinglists polcies, so this should only be used
        internally.

        :returns: Number of affected rows.
        """
        set_data = []
        remove_data = []
        for datum in data:
            datum = affirm(vtypes.SubscriptionDataset, datum)
            if datum['subscription_state'] == const.SubscriptionState.none:
                del datum['subscription_state']
                remove_data.append(datum)
            else:
                set_data.append(datum)

        num = 0
        with Atomizer(rs):
            if remove_data:
                # Privileges for removal are checked separately inside.
                num += self._remove_subscriptions(rs, remove_data)

            if set_data:
                if not all(datum['persona_id'] == rs.user.persona_id
                           or self.may_manage(rs, datum['mailinglist_id'],
                                              allow_restricted=False)
                           for datum in set_data):
                    raise PrivilegeError("Not privileged.")

                keys = ("subscription_state", "mailinglist_id", "persona_id")
                placeholders = ", ".join(("(%s, %s, %s)",) * len(set_data))
                query = f"""INSERT INTO ml.subscription_states ({", ".join(keys)})
                    VALUES {placeholders}
                    ON CONFLICT (mailinglist_id, persona_id) DO UPDATE SET
                    subscription_state = EXCLUDED.subscription_state"""

                params = tuple(itertools.chain.from_iterable(
                    (datum[key] for key in keys) for datum in set_data))
                num += self.query_exec(rs, query, params)

        return num

    class _SetSubscriptionProtocol(Protocol):
        def __call__(self, rs: RequestState, datum: CdEDBObject
                     ) -> DefaultReturnCode: ...
    _set_subscription: _SetSubscriptionProtocol = singularize(
        _set_subscriptions, "data", "datum", passthrough=True)

    @internal
    @access("ml")
    def _remove_subscriptions(self, rs: RequestState,
                              data: Collection[CdEDBObject],
                              ) -> DefaultReturnCode:
        """Remove rows from the ml.subscription_states table.

        :returns: Number of affected rows.
        """
        data = affirm_array(vtypes.SubscriptionIdentifier, data)

        with Atomizer(rs):
            if not all(datum['persona_id'] == rs.user.persona_id
                       or self.may_manage(rs, datum['mailinglist_id'])
                       for datum in data):
                raise PrivilegeError("Not privileged.")

            # noinspection SqlWithoutWhere
            query = "DELETE FROM ml.subscription_states"
            phrase = "mailinglist_id = %s AND persona_id = %s"
            query = query + " WHERE " + " OR ".join((phrase,) * len(data))
            params: List[Any] = []
            for datum in data:
                params.extend((datum['mailinglist_id'], datum['persona_id']))

            ret = self.query_exec(rs, query, params)

        return ret

    class _RemoveSubscriptionProtocol(Protocol):
        def __call__(self, rs: RequestState, datum: CdEDBObject
                     ) -> DefaultReturnCode: ...
    _remove_subscription: _RemoveSubscriptionProtocol = singularize(
        _remove_subscriptions, "data", "datum", passthrough=True)

    @access("ml")
    def do_subscription_action(self, rs: RequestState,
                               action: SubscriptionAction, mailinglist_id: int,
                               persona_id: Optional[int] = None,
                               ) -> DefaultReturnCode:
        """Provide a single entry point for all subscription actions.

        :returns: number of affected rows.
        """
        action = affirm(SubscriptionAction, action)

        # 1: Check if everything is alright – current state comes later
        mailinglist_id = affirm(vtypes.ID, mailinglist_id)
        # Managing actions can only be done by moderators. Other options always
        # change your own subscription state.
        if action.is_managing():
            if not self.may_manage(rs, mailinglist_id, allow_restricted=False):
                raise PrivilegeError(n_("Not privileged."))
            persona_id = affirm(vtypes.ID, persona_id)
        else:
            persona_id = rs.user.persona_id

        with Atomizer(rs):
            assert persona_id is not None
            atype = self.get_ml_type(rs, mailinglist_id)
            ml = self.get_mailinglist(rs, mailinglist_id)
            old_state = self.get_subscription(rs, persona_id,
                                              mailinglist_id=mailinglist_id)

            new_state = self.subman.apply_action(
                action=action,
                policy=self.get_subscription_policy(rs, persona_id, mailinglist=ml),
                allow_unsub=atype.allow_unsub,
                old_state=old_state)
            code = const.MlLogCodes.from_subman(action)

            # Write the transition to the database
            datum = {
                'mailinglist_id': mailinglist_id,
                'persona_id': persona_id,
                'subscription_state': new_state,
            }

            ret = self._set_subscription(rs, datum)
            if ret and code:
                self.ml_log(rs, code, datum['mailinglist_id'], datum['persona_id'])

        return ret

    @access("ml")
    def set_subscription_address(self, rs: RequestState, mailinglist_id: int,
                                 persona_id: int, email: str,
                                 ) -> DefaultReturnCode:
        """Change or add a subscription address.
        """
        mailinglist_id = affirm(vtypes.ID, mailinglist_id)
        persona_id = affirm(vtypes.ID, persona_id)
        email = affirm(vtypes.Email, email)

        if (not self.is_relevant_admin(rs, mailinglist_id=mailinglist_id)
                and persona_id != rs.user.persona_id):
            raise PrivilegeError(n_("Not privileged."))

        with Atomizer(rs):
            query = ("INSERT INTO ml.subscription_addresses "
                     "(mailinglist_id, persona_id, address) "
                     "VALUES (%s, %s, %s) "
                     "ON CONFLICT (mailinglist_id, persona_id) DO UPDATE "
                     "SET address=EXCLUDED.address")
            params = (mailinglist_id, persona_id, email)
            ret = self.query_exec(rs, query, params)
            if ret:
                self.ml_log(
                    rs, const.MlLogCodes.subscription_changed,
                    mailinglist_id, persona_id, change_note=email)

        return ret

    @access("ml")
    def remove_subscription_address(self, rs: RequestState, mailinglist_id: int,
                                    persona_id: int) -> DefaultReturnCode:
        """Remove a subscription address."""
        mailinglist_id = affirm(vtypes.ID, mailinglist_id)
        persona_id = affirm(vtypes.ID, persona_id)

        if (not self.is_relevant_admin(rs, mailinglist_id=mailinglist_id)
                and persona_id != rs.user.persona_id):
            raise PrivilegeError(n_("Not privileged."))

        with Atomizer(rs):
            query = ("DELETE FROM ml.subscription_addresses "
                     "WHERE mailinglist_id = %s AND persona_id = %s")
            params = (mailinglist_id, persona_id)

            ret = self.query_exec(rs, query, params)

            self.ml_log(rs, const.MlLogCodes.subscription_changed,
                        mailinglist_id, persona_id)

        return ret

    @access("ml")
    def get_many_subscription_states(
            self, rs: RequestState, mailinglist_ids: Collection[int],
            states: SubStates = None,
    ) -> Dict[int, Dict[int, const.SubscriptionState]]:
        """Get all users related to a given mailinglist and their sub state.

        :param states: Defaults to DatabseStates
        :return: Dict mapping mailinglist ids to a dict mapping persona_ids to
            their subscription state for the respective mailinglist for the
            given mailinglists.
            If states were given, limit this to personas with those states.
        """
        mailinglist_ids = affirm_set(vtypes.ID, mailinglist_ids)
        states = states or set()
        # We are more restrictive here than in the signature
        states = affirm_array(vtypes.DatabaseSubscriptionState, states)

        if not all(self.may_manage(rs, ml_id) for ml_id in mailinglist_ids):
            raise PrivilegeError(n_("Not privileged."))

        query = ("SELECT mailinglist_id, persona_id, subscription_state FROM "
                 "ml.subscription_states")

        constraints = ["mailinglist_id = ANY(%s)"]
        params: List[Any] = [mailinglist_ids]

        if states:
            constraints.append("subscription_state = ANY(%s)")
            params.append(states)
        if constraints:
            query = query + " WHERE " + " AND ".join(constraints)
        data = self.query_all(rs, query, params)

        ret: Dict[int, Dict[int, const.SubscriptionState]]
        ret = {ml_id: {} for ml_id in mailinglist_ids}
        for e in data:
            state = const.SubscriptionState(e["subscription_state"])
            ret[e["mailinglist_id"]][e["persona_id"]] = state

        return ret

    class _GetSubScriptionStatesProtocol(Protocol):
        def __call__(self, rs: RequestState, mailinglist_id: int,
                     states: SubStates = None
                     ) -> Dict[int, const.SubscriptionState]: ...
    get_subscription_states: _GetSubScriptionStatesProtocol = singularize(
        get_many_subscription_states, "mailinglist_ids", "mailinglist_id")

    @access("ml")
    def get_redundant_unsubscriptions(self, rs: RequestState, mailinglist_id: int
                                      ) -> Set[int]:
        """Retrieve all unsubscribed users who's unsubscriptions have no effect.

        This is the case if and only if the user is no implicit subscriber of the
        mailing list.
        """
        mailinglist_id = affirm(vtypes.ID, mailinglist_id)

        # shortcut if the user is not privileged to change subscription states of the ml
        if not self.may_manage(rs, mailinglist_id, allow_restricted=False):
            return set()

        atype = self.get_ml_type(rs, mailinglist_id)
        ml = self.get_mailinglist(rs, mailinglist_id)

        possible_implicits = atype.get_implicit_subscribers(rs, self.backends, ml)
        data = self.get_subscription_states(
            rs, mailinglist_id, states={const.SubscriptionState.unsubscribed})

        return data.keys() - possible_implicits

    @access("ml")
    def get_user_subscriptions(
            self, rs: RequestState, persona_id: int, states: SubStates = None,
    ) -> Dict[int, const.SubscriptionState]:
        """Returns a list of mailinglists the persona is related to.

        :param states: If given only relations with these states are returned.
            Defaults to all states written into the database (`subman.written_states`).
        :return: A mapping of mailinglist ids to the persona's subscription
            state wrt. this mailinglist.
        """
        persona_id = affirm(vtypes.ID, persona_id)
        states = states or set()
        # We are more restrictive here than in the signature
        states = affirm_set(vtypes.DatabaseSubscriptionState, states)
        if not (self.is_admin(rs) or self.core.is_relative_admin(rs, persona_id)
                or rs.user.persona_id == persona_id):
            raise PrivilegeError(n_("Not privileged."))

        query = ("SELECT mailinglist_id, subscription_state "
                 "FROM ml.subscription_states")

        constraints = ["persona_id = %s"]
        params: List[Any] = [persona_id]

        if states:
            constraints.append("subscription_state = ANY(%s)")
            params.append(states)
        if constraints:
            query = query + " WHERE " + " AND ".join(constraints)
        data = self.query_all(rs, query, params)

        return {
            e["mailinglist_id"]: const.SubscriptionState(e["subscription_state"])
            for e in data}

    @access("ml")
    def get_subscription(self, rs: RequestState, persona_id: int, mailinglist_id: int
                         ) -> const.SubscriptionState:
        """Returns state of a persona with regard to a mailinglist."""
        persona_id = affirm(vtypes.ID, persona_id)

        if not self.may_manage(rs, mailinglist_id) and rs.user.persona_id != persona_id:
            raise PrivilegeError(n_("Not privileged."))

        query = ("SELECT subscription_state FROM ml.subscription_states"
                 " WHERE persona_id = %s AND mailinglist_id = %s")

        state = unwrap(self.query_one(rs, query, (persona_id, mailinglist_id)))
        if state:
            return const.SubscriptionState(state)
        else:
            return const.SubscriptionState.none

    @access("ml")
    def get_subscription_addresses(self, rs: RequestState, mailinglist_id: int,
                                   persona_ids: Collection[int] = None,
                                   explicits_only: bool = False,
                                   ) -> Dict[int, Optional[str]]:
        """Retrieve email addresses of the given personas for the mailinglist.

        With `explicits_only = False`, this returns a dict mapping all
        subscribers (or a subset given via `persona_ids`) to email addresses.
        If they have expicitly specified a subscription address that one is
        returned, otherwise the username is returned.

        With `explicits_only = True` every subscriber is mapped to their
        explicit subscription address or None, if none is given.

        :param persona_ids: Limit the result to a subset of subscribers. Get all
            subscribers if this is None.
        :param explicits_only: If this is False, also fetch usernames for
            subscribers without explicit subscription addresses.
        :returns: Returns persona ids mapped to email addresses or None if
            `explicits_only` is True.
        """
        mailinglist_id = affirm(vtypes.ID, mailinglist_id)

        ret: Dict[int, Optional[str]] = {}
        with Atomizer(rs):
            if not self.may_manage(rs, mailinglist_id):
                raise PrivilegeError(n_("Not privileged."))

            subscribers = self.get_subscription_states(
                rs, mailinglist_id,
                states=const.SubscriptionState.subscribing_states())
            if persona_ids is None:
                # Default to all subscribers.
                persona_ids = set(subscribers)
            else:
                persona_ids = affirm_set(vtypes.ID, persona_ids)
                # Limit to actual subscribers.
                persona_ids = {p_id for p_id in persona_ids
                               if p_id in subscribers}

            query = ("SELECT persona_id, address "
                     "FROM ml.subscription_addresses "
                     "WHERE mailinglist_id = %s AND persona_id = ANY(%s)")
            params = (mailinglist_id, persona_ids)

            data = self.query_all(rs, query, params)

            ret = {e["persona_id"]: e["address"] for e in data if e["address"]}
            defaults = persona_ids - set(ret)

            # Get usernames for subscribers without explicit address.
            if not explicits_only:
                persona_data = self.core.get_personas(rs, defaults)
                personas = {
                    e["id"]: e["username"] for e in persona_data.values()}
                ret.update(personas)
            else:
                ret.update({p_id: None for p_id in defaults})

        return ret

    @access("ml")
    def get_subscription_address(self, rs: RequestState,
                                 mailinglist_id: int, persona_id: int,
                                 explicits_only: bool = False) -> Optional[str]:
        """Return the subscription address for one persona and one mailinglist.

        This slightly differs for requesting another users subscription address
        and one's own, due to differing privilege requirements.

        Manual implementation of singularization of
        `get_subscription_addresses`, to make sure the parameters work.
        """

        if persona_id == rs.user.persona_id:
            mailinglist_id = affirm(vtypes.ID, mailinglist_id)
            persona_id = affirm(vtypes.ID, persona_id)

            query = ("SELECT address FROM ml.subscription_addresses "
                     "WHERE mailinglist_id = %s AND persona_id = %s")
            params = (mailinglist_id, persona_id)

            data = self.query_one(rs, query, params)

            if data:
                ret = data["address"]
            elif not explicits_only:
                ret = rs.user.username
            else:
                ret = None
            return ret
        else:
            # Validation is done inside.
            return unwrap(self.get_subscription_addresses(
                rs, mailinglist_id, persona_ids=(persona_id,),
                explicits_only=explicits_only))

    @access("ml")
    def get_user_subscription_addresses(self, rs: RequestState, persona_id: int
                                        ) -> Dict[int, str]:
        """Retrieve explicit email addresses of the given persona for all mailinglists.

        :returns: Returns dict mapping mailinglist_id with explicit addresses to the
            respective addresses
        """
        if not (self.is_admin(rs) or self.core.is_relative_admin(rs, persona_id)
                or rs.user.persona_id == persona_id):
            raise PrivilegeError(n_("Not privileged."))
        persona_id = affirm(vtypes.ID, persona_id)
        query = ("SELECT mailinglist_id, address"
                 " FROM ml.subscription_addresses"
                 " WHERE persona_id = %s")
        data = self.query_all(rs, query, [persona_id])
        return {e["mailinglist_id"]: e["address"] for e in data}

    @access("ml")
    def get_persona_addresses(self, rs: RequestState) -> Set[str]:
        """Get all confirmed email addresses for a user.

        This includes all subscription addresses as well as the username.
        """
        assert rs.user.persona_id is not None
        data = self.get_user_subscription_addresses(rs, rs.user.persona_id)
        ret = set(data.values())
        ret.add(rs.user.username)
        return ret

    @access("ml")
    def get_implicit_whitelist(self, rs: RequestState, mailinglist_id: int
                               ) -> Set[str]:
        """Get all usernames of users which have a custom subscription address
        configured for the mailinglist.

        This allows those users to also pass moderation with mails sent from
        their username address instead of just their subscription address,
        if the ml has non_subscribers moderation policy.
        Take care to use this function only in this case!

        :returns: Set of mailadresses to whitelist
        """
        persona_ids = self.get_subscription_states(
            rs, mailinglist_id, states=const.SubscriptionState.subscribing_states())
        persona_ids = {
            persona_id for persona_id, address
            in self.get_subscription_addresses(
                rs, mailinglist_id, persona_ids, explicits_only=True).items()
            if address
        }
        return {persona['username'] for persona
                in self.core.get_ml_users(rs, persona_ids).values()}

    @access("ml")
    def is_subscribed(self, rs: RequestState, persona_id: Optional[int],
                      mailinglist_id: int) -> bool:
        """Sugar coating around :py:meth:`get_user_subscriptions`.
        """
        if not persona_id:
            # Only accounts can be subscribers
            return False
        # validation is done inside
        state = self.get_subscription(rs, persona_id, mailinglist_id)
        return state.is_subscribed()

    @access("ml")
    def write_subscription_states(self, rs: RequestState,
                                  mailinglist_ids: Collection[int] = None,
                                  ) -> DefaultReturnCode:
        """This takes care of writing implicit subscriptions to the db.

        This also checks the integrity of existing subscriptions.
        """
        if mailinglist_ids is None:
            if not self.is_admin(rs):
                raise PrivilegeError("Must be admin.")
            mailinglist_ids = self.list_mailinglists(rs)
        mailinglist_ids = affirm_set(vtypes.ID, mailinglist_ids)

        # States we may not touch.
        protected_states = (self.subman.written_states
                            & self.subman.cleanup_protected_states)
        # States we may touch: non-special subscriptions.
        old_subscriber_states = (self.subman.written_states
                                 - self.subman.cleanup_protected_states)

        ret = 1
        with Atomizer(rs):
            ml_data = self.get_mailinglists(rs, mailinglist_ids)
            if not all(self.may_manage(rs, ml_id, allow_restricted=False)
                       for ml_id in mailinglist_ids):
                raise PrivilegeError(n_("Moderator access has been restricted."))

            # Only run write_subscription_states if the mailinglist is active and has
            # periodic cleanup enabled.
            mailinglist_ids = {
                ml_id for ml_id, ml in ml_data.items()
                if ml_data[ml_id]["ml_type_class"].periodic_cleanup(rs, ml)
                   and ml['is_active']}

            # Gather old subscription data.
            old_subscribers = self.get_many_subscription_states(
                rs, mailinglist_ids, states=old_subscriber_states)
            protected = self.get_many_subscription_states(
                rs, mailinglist_ids, states=protected_states)

            for mailinglist_id in mailinglist_ids:
                ml = ml_data[mailinglist_id]
                atype: ml_type.MLType = ml["ml_type_class"]

                # This is dependant on mailinglist type
                new_implicits = atype.get_implicit_subscribers(rs, self.backends, ml)

                # Check whether current subscribers may stay subscribed.
                # This is the case if they are still implicit subscribers of
                # the list or if `get_subscription_policy` says so.
                delete = []
                policies = atype.get_subscription_policies(
                    rs, self.backends, mailinglist=ml,
                    persona_ids=old_subscribers[mailinglist_id])
                for persona_id in old_subscribers[mailinglist_id]:
                    old_state = old_subscribers[mailinglist_id][persona_id]
                    if self.subman.is_obsolete(policy=policies[persona_id],
                                               old_state=old_state,
                                               is_implied=persona_id in new_implicits):
                        datum = {
                            'mailinglist_id': mailinglist_id,
                            'persona_id': persona_id,
                        }
                        delete.append(datum)
                        # Log this to prevent confusion especially for team lists
                        self.ml_log(rs, const.MlLogCodes.automatically_removed,
                                    mailinglist_id, persona_id=persona_id)

                # Remove those who may not stay subscribed.
                if delete:
                    num = self._remove_subscriptions(rs, delete)
                    ret *= num
                    self.logger.info(f"Removed {num} subscribers from mailinglist"
                                     f" {mailinglist_id}.")

                # Check whether any implicit subscribers need to be written.
                # This is the case if they are not already old subscribers and
                # they don't have a protected subscription.
                write = (set(new_implicits) - set(old_subscribers[mailinglist_id])
                         - set(protected[mailinglist_id]))

                # Set implicit subscriptions.
                data = [
                    {
                        'mailinglist_id': mailinglist_id,
                        'persona_id': persona_id,
                        'subscription_state': const.SubscriptionState.implicit,
                    }
                    for persona_id in write
                ]
                if data:
                    self._set_subscriptions(rs, data)
                    ret *= len(data)
                    self.logger.info(f"Added {len(write)} subscribers to mailinglist"
                                     f" {mailinglist_id}.")

        return ret

    @access("persona")
    def verify_existence(self, rs: RequestState, address: str) -> bool:
        """Check whether a mailinglist with the given address is known."""
        address = affirm(vtypes.Email, address)

        query = "SELECT COUNT(*) AS num FROM ml.mailinglists WHERE address = %s"
        data = self.query_one(rs, query, (address,))
        return bool(unwrap(data))

    @access("ml_admin")
    def merge_accounts(self, rs: RequestState,
                       source_persona_id: vtypes.ID,
                       target_persona_id: vtypes.ID,
                       clone_addresses: bool = True) -> DefaultReturnCode:
        """Merge an ml_only account into another persona.

        This takes the source_persona, mirrors all subscription states and moderator
        privileges to the target_persona, and archives the source_persona at last.

        Make sure that the two users are not related to the same mailinglist. Otherwise,
        this function will abort.

        :param source_persona_id: user from which will be merged
        :param target_persona_id: user into which will be merged
        :param clone_addresses: if true, use the address (explicit set or username) of
            the source when subscribing the target to a mailinglist
        """
        source_persona_id = affirm(vtypes.ID, source_persona_id)
        target_persona_id = affirm(vtypes.ID, target_persona_id)

        SS = const.SubscriptionState
        SA = SubscriptionAction
        log = const.MlLogCodes

        non_implicit_states = {state for state in SS
                               if state not in {SS.implicit, SS.none}}

        state_to_log: Dict[const.SubscriptionState, const.MlLogCodes] = {
            SS.subscribed: log.from_subman(SA.add_subscriber),
            SS.unsubscribed: log.from_subman(SA.remove_subscriber),
            SS.subscription_override: log.from_subman(SA.add_subscription_override),
            SS.unsubscription_override: log.from_subman(SA.add_unsubscription_override),
            SS.pending: log.from_subman(SA.request_subscription),
            # we ignore implicit subscriptions
            # SS.implicit: None,
        }

        with Atomizer(rs):
            # check the source user is ml_only, no admin and not archived
            source = self.core.get_ml_user(rs, source_persona_id)
            if any(source[admin_bit] for admin_bit in ADMIN_KEYS):
                raise ValueError(n_("Source User is admin and can not be merged."))
            if not self.core.verify_persona(rs, source_persona_id,
                                            allowed_roles={'ml'}):
                raise ValueError(n_("Source persona must be a ml-only user."))
            if source['is_archived']:
                raise ValueError(n_("Source User is not accessible."))

            # check the target user is a valid persona and not archived
            target = self.core.get_ml_user(rs, target_persona_id)
            if not self.core.verify_persona(rs, target_persona_id,
                                            required_roles={'ml'}):
                raise ValueError(n_("Target User is no valid ml user."))
            if target['is_archived']:
                raise ValueError(n_("Target User is not accessible."))
            if source_persona_id == target_persona_id:
                raise ValueError(n_("Can not merge user into himself."))

            # retrieve all mailinglists they are subscribed to
            # TODO restrict to active mailinglists?
            source_subscriptions = self.get_user_subscriptions(
                rs, source_persona_id, states=non_implicit_states)
            target_subscriptions = self.get_user_subscriptions(rs, target_persona_id)

            # retrieve all mailinglists moderated by the source
            source_moderates = self.moderator_info(rs, source_persona_id)

            ml_overlap = set(source_subscriptions) & set(target_subscriptions)
            if ml_overlap:
                ml_titles = [e['title']
                             for e in self.get_mailinglists(rs, ml_overlap).values()]
                msg = n_("Both users are related to the same mailinglists: %(mls)s")
                rs.notify("error", msg, {'mls': ", ".join(ml_titles)})
                return 0

            code = 1
            msg = f"Nutzer {source_persona_id} ist in diesem Account aufgegangen."

            for ml_id, state in source_subscriptions.items():
                # state=None is only possible, if we handle a set of mailinglists
                # to get_subscription_states
                assert state is not None

                if clone_addresses:
                    address = self.get_subscription_address(
                        rs, ml_id, explicits_only=False, persona_id=source_persona_id)
                    # get_subscription_address returns only None if explicits_only=True
                    assert address is not None

                # set the target to the subscription state of the source
                datum = {
                    'mailinglist_id': ml_id,
                    'persona_id': target_persona_id,
                    'subscription_state': state,
                }
                code *= self._set_subscription(rs, datum)
                self.ml_log(
                    rs, state_to_log[state], datum['mailinglist_id'],
                    datum['persona_id'], change_note=msg)

                # set the subscribing address of the target to the address of the source
                if clone_addresses:
                    assert address is not None
                    code *= self.set_subscription_address(
                        rs, ml_id, persona_id=target_persona_id, email=address)

            for ml_id in source_moderates:
                # we do not mind if both users are currently moderator of a mailinglist
                self.add_moderators(rs, ml_id, {target_persona_id}, change_note=msg)

            # at last, archive the source user
            # this will delete all subscriptions and remove all moderator rights
            msg = f"Dieser Account ist in Nutzer {target_persona_id} aufgegangen."
            code *= self.core.archive_persona(rs, persona_id=source_persona_id,
                                              note=msg)

        return code

    @access("ml")
    def log_moderation(self, rs: RequestState, code: const.MlLogCodes,
                       mailinglist_id: int, change_note: str) -> DefaultReturnCode:
        """Log a moderation action (delegated to Mailman).

        Since they should usually be called inside an atomized context, logs demand an
        Atomizer by default. However, since we are not acting on our database here,
        this is not applicable.
        """
        code = affirm(const.MlLogCodes, code)
        mailinglist_id = affirm(int, mailinglist_id)
        change_note = affirm(str, change_note)
        return self.ml_log(rs, code, mailinglist_id, change_note=change_note,
                           atomized=False)
