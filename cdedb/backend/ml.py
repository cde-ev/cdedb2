#!/usr/bin/env python3

"""The ml backend provides mailing lists. This provides services to the
event and assembly realm in the form of specific mailing lists.

This has an additional user role ml_script which is intended to be
filled by a mailing list software and not a usual persona. This acts as
if it has moderator privileges for all lists.
"""

from cdedb.backend.common import (
    access, affirm_validation as affirm, AbstractBackend,
    affirm_set_validation as affirm_set, singularize,
    affirm_array_validation as affirm_array, internal_access)
from cdedb.backend.event import EventBackend
from cdedb.backend.assembly import AssemblyBackend
from cdedb.common import (
    n_, glue, PrivilegeError, unwrap, MAILINGLIST_FIELDS,
    extract_roles, implying_realms, now, ProxyShim,
    SubscriptionError, SubscriptionInfo,
    SubscriptionActions)
from cdedb.query import QueryOperators, Query
from cdedb.database.connection import Atomizer
import cdedb.database.constants as const
import cdedb.ml_type_aux as ml_type


class MlBackend(AbstractBackend):
    """Take note of the fact that some personas are moderators and thus have
    additional actions available."""
    realm = "ml"

    def __init__(self, configpath):
        super().__init__(configpath)
        self.event = ProxyShim(EventBackend(configpath), internal=True)
        self.assembly = ProxyShim(AssemblyBackend(configpath), internal=True)
        self.backends = ml_type.BackendContainer(
            core=self.core, event=self.event, assembly=self.assembly)

    @classmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

    @access("ml")
    def get_ml_type(self, rs, mailinglist_id):
        mailinglist_id = affirm("id", mailinglist_id)
        data = self.sql_select_one(
            rs, "ml.mailinglists", ("ml_type",), mailinglist_id)
        if not data:
            raise ValueError(n_("Unknown mailinglist_id."))
        if not data["ml_type"]:
            return None
        return ml_type.TYPE_MAP[const.MailinglistTypes(data["ml_type"])]

    @access("ml")
    def is_relevant_admin(self, rs, *, mailinglist=None, mailinglist_id=None):
        """Check if the user is a relevant admin for a mailinglist.

        Exactly one of the inputs should be provided.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type mailinglist: {str: object}
        :type mailinglist_id: int
        :rtype: bool
        """
        # TODO: for now this is just ml_admin, with the new MailinglistTypes,
        # this could be other admins as well.
        return self.is_admin(rs)

    @staticmethod
    @access("ml")
    def is_moderator(rs, ml_id):
        """Check for moderator privileges as specified in the ml.moderators
        table.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ml_id: int
        :rtype: bool
        """
        ml_id = affirm("id_or_None", ml_id)

        return ml_id is not None and (ml_id in rs.user.moderator
                                      or "ml_script" in rs.user.roles)

    @access("ml")
    def may_manage(self, rs, mailinglist_id):
        """Check whether a user is allowed to manage a given mailinglist.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type mailinglist_id: int
        :rtype: bool
        """
        mailinglist_id = affirm("id_or_None", mailinglist_id)

        return (self.is_moderator(rs, mailinglist_id)
                or self.is_relevant_admin(rs, mailinglist_id=mailinglist_id))

    @access("ml")
    def get_interaction_policy(self, rs, persona_id, *, mailinglist=None,
                               mailinglist_id=None):
        """What may the user do with a mailinglist. Be aware, that this does
        not take unsubscribe overrides into account.

        If the mailinglist is available to the caller, they should pass it,
        otherwise it will be retrieved from the database.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type persona_id: int
        :type mailinglist: {str: object}
        :type mailinglist_id: int
        :rtype: const.MailinglistInteractionPolicy or None
        """
        # TODO put these checks in an atomizer?
        if mailinglist is None and mailinglist_id is None:
            raise ValueError("No input specified")
        elif mailinglist is not None and mailinglist_id is not None:
            raise ValueError("Too many inputs specified")
        elif mailinglist_id:
            mailinglist_id = affirm("id", mailinglist_id)
            mailinglist = self.get_mailinglist(rs, mailinglist_id)

        persona_id = affirm("id", persona_id)
        ml = affirm("mailinglist", mailinglist, _allow_readonly=True)

        if not (rs.user.persona_id == persona_id
                or self.may_manage(rs, ml['id'])):
            raise PrivilegeError(n_("Not privileged."))

        return self.get_ml_type(rs, ml["id"]).get_interaction_policy(
            rs, self.backends, ml, persona_id)

    @access("ml")
    def filter_personas_by_policy(self, rs, ml, data, allowed_pols):
        """Restrict persona sample to eligibles.

        This additional endpoint checking for interaction policies is
        supposed to only be used for
        `cdedb.frontend.core.select_persona()`, to reduce the amount
        of necessary database queries.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ml: {str: object}
        :type data: [{str: object}]
        :param data: Return of the persona select query
        :type allowed_pols: {const.MailinglistInteractionPolicy}
        :return: Tuple of personas whose interaction policies are in
            allowed_pols
        """
        affirm("mailinglist", ml, _allow_readonly=True)
        affirm_set("enum_mailinglistinteractionpolicy", allowed_pols)

        # persona_ids are validated inside get_personas
        persona_ids = tuple(e['id'] for e in data)
        persona_policies = self.get_ml_type(rs, ml['id']).\
            get_interaction_policies(rs, self.backends, ml, persona_ids)
        return tuple(e for e in data
                     if persona_policies[e['id']] in allowed_pols)

    @access("ml")
    def may_view(self, rs, ml):
        """Helper to determine whether a persona may view a mailinglist.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ml: {str: object}
        :type: bool
        """
        is_subscribed = bool(self.get_subscription(
            rs, rs.user.persona_id, mailinglist_id=ml["id"],
            states=const.SubscriptionStates.subscribing_states()))
        return (is_subscribed or self.get_ml_type(rs, ml["id"]).may_view(rs)
                or ml["id"] in rs.user.moderator)

    @access("persona")
    @singularize("moderator_info")
    def moderator_infos(self, rs, ids):
        """List mailing lists moderated by specific personas.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: {int: {int}}
        """
        ids = affirm_set("id", ids)
        data = self.sql_select(
            rs, "ml.moderators", ("persona_id", "mailinglist_id"), ids,
            entity_key="persona_id")
        ret = {}
        for anid in ids:
            ret[anid] = {x['mailinglist_id']
                         for x in data if x['persona_id'] == anid}
        return ret

    def ml_log(self, rs, code, mailinglist_id, persona_id=None,
               additional_info=None):
        """Make an entry in the log.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type code: int
        :param code: One of :py:class:`cdedb.database.constants.MlLogCodes`.
        :type mailinglist_id: int or None
        :type persona_id: int or None
        :param persona_id: ID of affected user (like who was subscribed).
        :type additional_info: str or None
        :param additional_info: Infos not conveyed by other columns.
        :rtype: int
        :returns: default return code
        """
        if rs.is_quiet:
            return 0
        new_log = {
            "code": code,
            "mailinglist_id": mailinglist_id,
            "submitted_by": rs.user.persona_id,
            "persona_id": persona_id,
            "additional_info": additional_info,

        }
        return self.sql_insert(rs, "ml.log", new_log)

    @access("ml")
    def retrieve_log(self, rs, codes=None, mailinglist_ids=None, offset=None,
                     length=None, persona_id=None, submitted_by=None,
                     additional_info=None, time_start=None,
                     time_stop=None):
        """Get recorded activity.

        To support relative admins, this is the only retrieve_log function
        which allows to query a list for entity_ids.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type codes: [int] or None
        :type mailinglist_ids: [int] or None
        :type offset: int or None
        :type length: int or None
        :type persona_id: int or None
        :type submitted_by: int or None
        :type additional_info: str or None
        :type time_start: datetime or None
        :type time_stop: datetime or None
        :rtype: [{str: object}]
        """
        mailinglist_ids = affirm_set("id", mailinglist_ids, allow_None=True)
        if not (self.is_admin(rs)
                or all(self.may_manage(rs, ml_id) for ml_id in mailinglist_ids)):
            raise PrivilegeError(n_("Not privileged."))
        return self.generic_retrieve_log(
            rs, "enum_mllogcodes", "mailinglist", "ml.log", codes=codes,
            entity_ids=mailinglist_ids, offset=offset, length=length,
            persona_id=persona_id, submitted_by=submitted_by,
            additional_info=additional_info, time_start=time_start,
            time_stop=time_stop)

    @access("ml_admin")
    def submit_general_query(self, rs, query):
        """Realm specific wrapper around
        :py:meth:`cdedb.backend.common.AbstractBackend.general_query`.`

        :type rs: :py:class:`cdedb.common.RequestState`
        :type query: :py:class:`cdedb.query.Query`
        :rtype: [{str: object}]
        """
        query = affirm("query", query)
        if query.scope == "qview_persona":
            # Include only un-archived ml-users
            query.constraints.append(("is_ml_realm", QueryOperators.equal,
                                      True))
            query.constraints.append(("is_archived", QueryOperators.equal,
                                      False))
            query.spec["is_ml_realm"] = "bool"
            query.spec["is_archived"] = "bool"
            # Exclude users of any higher realm (implying event)
            for realm in implying_realms('ml'):
                query.constraints.append(
                    ("is_{}_realm".format(realm), QueryOperators.equal, False))
                query.spec["is_{}_realm".format(realm)] = "bool"
        else:
            raise RuntimeError(n_("Bad scope."))
        return self.general_query(rs, query)

    @access("ml")
    def list_mailinglists(self, rs, active_only=True):
        """List all mailinglists you may view

        :type rs: :py:class:`cdedb.common.RequestState`
        :type active_only: bool
        :param active_only: Toggle wether inactive lists should be included.
        :rtype: {int: str}
        :returns: Mapping of mailinglist ids to titles.
        """
        active_only = affirm("bool", active_only)
        query = "SELECT id, title FROM ml.mailinglists"
        constraints = []
        params = []
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

        if self.is_admin(rs):
            return ret
        return {k: v for k, v in ret.items()
                if self.may_view(rs, mailinglists[k])}

    @access("ml")
    @singularize("get_mailinglist")
    def get_mailinglists(self, rs, ids):
        """Retrieve data for some mailinglists.

        This provides the following additional attributes:

        * moderators,
        * whitelist.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_set("id", ids)
        with Atomizer(rs):
            data = self.sql_select(rs, "ml.mailinglists", MAILINGLIST_FIELDS,
                                   ids)
            ret = {e['id']: e for e in data}
            # Maybe more elegant than using get_ml_type?
            # for k in ret:
            #    ret[k]['type'] = ml_type.TYPE_MAP[ret[k]['ml_type']]
            data = self.sql_select(
                rs, "ml.moderators", ("persona_id", "mailinglist_id"), ids,
                entity_key="mailinglist_id")
            for anid in ids:
                moderators = {d['persona_id']
                              for d in data if d['mailinglist_id'] == anid}
                assert ('moderators' not in ret[anid])
                ret[anid]['moderators'] = moderators
            data = self.sql_select(
                rs, "ml.whitelist", ("address", "mailinglist_id"), ids,
                entity_key="mailinglist_id")
            for anid in ids:
                whitelist = {d['address']
                             for d in data if d['mailinglist_id'] == anid}
                assert ('whitelist' not in ret[anid])
                ret[anid]['whitelist'] = whitelist
            for anid in ids:
                ret[anid]['domain_str'] = str(const.MailinglistDomain(ret[anid]['domain']))
                ret[anid]['ml_type_class'] = ml_type.TYPE_MAP[ret[anid]['ml_type']]
        return ret

    @access("ml")
    def set_moderators(self, rs, mailinglist_id, moderator_ids):
        """Set moderators of a mailinglist.

        A complete set must be passed, which will superseed the current set.

        Contrary to `set_mailinglist` this may be used by moderators.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type mailinglist_id: int
        :type moderator_ids: {int}
        :rtype: int
        :returns: default return code
        """
        mailinglist_id = affirm("id", mailinglist_id)
        moderator_ids = affirm_set("id", moderator_ids)

        if not self.may_manage(rs, mailinglist_id):
            raise PrivilegeError("Not privileged.")

        ret = 1
        with Atomizer(rs):
            current = unwrap(self.get_mailinglists(rs, (mailinglist_id,)))

            existing = current['moderators']
            new = moderator_ids - existing
            deleted = existing - moderator_ids
            if new:
                for anid in new:
                    new_mod = {
                        'persona_id': anid,
                        'mailinglist_id': mailinglist_id,
                    }
                    ret *= self.sql_insert(rs, "ml.moderators", new_mod)
                    self.ml_log(rs, const.MlLogCodes.moderator_added,
                                mailinglist_id, persona_id=anid)
            if deleted:
                query = glue(
                    "DELETE FROM ml.moderators",
                    "WHERE persona_id = ANY(%s) AND mailinglist_id = %s")
                ret *= self.query_exec(rs, query, (deleted, mailinglist_id))
                for anid in deleted:
                    self.ml_log(rs, const.MlLogCodes.moderator_removed,
                                mailinglist_id, persona_id=anid)
        return ret

    @access("ml")
    def set_whitelist(self, rs, mailinglist_id, whitelist):
        """Set whitelist of a mailinglist.

        A complete set must be passed, which will superseed the current set.

        Contrary to `set_mailinglist` this may be used by moderators.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type mailinglist_id: int
        :type whitelist: {str}
        :rtype: int
        :returns: default return code
        """
        mailinglist_id = affirm("id", mailinglist_id)
        whitelist = affirm_set("str", whitelist)

        if not self.may_manage(rs, mailinglist_id):
            raise PrivilegeError(n_("Not privileged."))

        ret = 1
        with Atomizer(rs):
            current = unwrap(self.get_mailinglists(rs, (mailinglist_id,)))

            existing = current['whitelist']
            new = whitelist - existing
            deleted = existing - whitelist
            if new:
                for address in new:
                    new_white = {
                        'address': address,
                        'mailinglist_id': mailinglist_id,
                    }
                    ret *= self.sql_insert(rs, "ml.whitelist", new_white)
                    self.ml_log(rs, const.MlLogCodes.whitelist_added,
                                mailinglist_id, additional_info=address)
            if deleted:
                query = glue(
                    "DELETE FROM ml.whitelist",
                    "WHERE address = ANY(%s) AND mailinglist_id = %s")
                ret *= self.query_exec(rs, query, (deleted, mailinglist_id))
                for address in deleted:
                    self.ml_log(rs, const.MlLogCodes.whitelist_removed,
                                mailinglist_id, additional_info=address)
        return ret

    @access("ml")
    def set_mailinglist(self, rs, data):
        """Update some keys of a mailinglist.

        If the keys 'moderators' or 'whitelist' are present you have to pass
        the complete set of moderator IDs or whitelisted addresses, which
        will superseed the current list.

        If the new mailinglist type does not allow unsubscription,
        all unsubscriptions are dropped without exception.

        This requires different levels of access depending on what change is
        made. Setting whitelist or moderators is allowed for moderators, setting
        the mailinglist itself is not.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :rtype: int
        :returns: default return code
        """
        data = affirm("mailinglist", data)

        ret = 1
        with Atomizer(rs):
            current = unwrap(self.get_mailinglists(rs, (data['id'],)))
            # TODO return enum members from get_mailinglist.
            # This validation is required to get the enum members for data.
            current = affirm("mailinglist", current, _allow_readonly=True)
            # Only allow modification of the mailinglist for admins.
            if not self.is_relevant_admin(rs, mailinglist=current):
                raise PrivilegeError(n_("Not privileged."))

            mdata = {k: v for k, v in data.items() if k in MAILINGLIST_FIELDS}
            if len(mdata) > 1:
                mdata['address'] = ml_type.full_address(dict(current, **mdata))
                ret *= self.sql_update(rs, "ml.mailinglists", mdata)
                self.ml_log(rs, const.MlLogCodes.list_changed, data['id'])
                # Check if privileges allow new state of the mailinglist.
                if not self.is_relevant_admin(rs, mailinglist_id=data['id']):
                    raise PrivilegeError("Not privileged to make this change.")
            if data.get('moderators'):
                ret *= self.set_moderators(rs, data['id'], data['moderators'])
            if data.get('whitelist'):
                ret *= self.set_whitelist(rs, data['id'], data['whitelist'])
            if data.get('ml_type'):
                if not ml_type.TYPE_MAP[data['ml_type']].allow_unsub:
                    # Delete all unsubscriptions for mandatory list.
                    query = ("DELETE FROM ml.subscription_states "
                             "WHERE mailinglist_id = %s "
                             "AND subscription_state = ANY(%s)")
                    params = (data['id'], set(const.SubscriptionStates) -
                              const.SubscriptionStates.subscribing_states())
                    ret *= self.query_exec(rs, query, params)

            # Update subscription states.
            ret *= self.write_subscription_states(rs, data['id'])
        return ret

    @access("ml")
    def create_mailinglist(self, rs, data):
        """Make a new mailinglist.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :rtype: int
        :returns: the id of the new mailinglist
        """
        data = affirm("mailinglist", data, creation=True)
        data['address'] = ml_type.full_address(data)
        if not self.is_relevant_admin(rs, mailinglist=data):
            raise PrivilegeError("Not privileged to create mailinglist of this "
                                 "type.")
        with Atomizer(rs):
            mdata = {k: v for k, v in data.items() if k in MAILINGLIST_FIELDS}
            new_id = self.sql_insert(rs, "ml.mailinglists", mdata)
            self.ml_log(rs, const.MlLogCodes.list_created, new_id)
            if data.get("moderators"):
                self.set_moderators(rs, new_id, data["moderators"])
            if data.get("whitelist"):
                self.set_whitelist(rs, new_id, data["whitelist"])
            self.write_subscription_states(rs, new_id)
        return new_id

    @access("ml_admin")
    def delete_mailinglist_blockers(self, rs, mailinglist_id):
        """Determine what blocks a mailinglist from being deleted.

        Possible blockers:
        * subscriptions: A subscription to the mailinglist.
        * addresses: A non-default subscribtion address for the mailinglist.
        * whitelist: An entry on the whitelist of the mailinglist.
        * moderator: A moderator of the mailinglist.
        * log: A log entry for the mailinglist.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type mailinglist_id: int
        :rtype: {str: [int]}
        :return: List of blockers, separated by type. The values of the dict
            are the ids of the blockers.
        """
        mailinglist_id = affirm("id", mailinglist_id)
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

    @access("ml_admin")
    def delete_mailinglist(self, rs, mailinglist_id, cascade=None):
        """Remove a mailinglist.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type mailinglist_id: int
        :type cascade: {str} or None
        :param cascade: Specify which deletion blockers to cascadingly
            remove or ignore. If None or empty, cascade none.
        :rtype: int
        :returns: default return code
        """
        mailinglist_id = affirm("id", mailinglist_id)
        blockers = self.delete_mailinglist_blockers(rs, mailinglist_id)
        if not cascade:
            cascade = set()
        cascade = affirm_set("str", cascade)
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
                            mailinglist_id=None, additional_info="{} ({})".
                            format(ml_data['title'], ml_data['address']))
            else:
                raise ValueError(
                    n_("Deletion of %(type)s blocked by %(block)s."),
                    {"type": "mailinglist", "block": blockers.keys()})

        return ret

    @internal_access("ml")
    def _set_subscriptions(self, rs, data):
        """Change or add ml.subscription_states rows.

        This does not check whether the subscription change makes sense
        regarding the mailinglists polcies, so this should only be used
        internally.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: [{str: int}]
        :rtype: int
        :returns: Number of affected rows.
        """
        data = affirm_array("subscription_state", data)

        if not all(datum['persona_id'] == rs.user.persona_id
                   or self.may_manage(rs, datum['mailinglist_id'])
                   for datum in data):
            raise PrivilegeError("Not privileged.")

        num = 0
        with Atomizer(rs):
            query = ("INSERT INTO ml.subscription_states "
                     "({keys}) VALUES {placeholders} "
                     "ON CONFLICT (mailinglist_id, persona_id) DO UPDATE "
                     "SET subscription_state = EXCLUDED.subscription_state")
            keys = ("subscription_state", "mailinglist_id", "persona_id")
            placeholders = ", ".join(("(%s, %s, %s)",) * len(data))
            query = query.format(keys=", ".join(keys), placeholders=placeholders)

            params = []
            for datum in data:
                params.extend(datum[key] for key in keys)

            num += self.query_exec(rs, query, params)

        return num

    @internal_access("ml")
    def _set_subscription(self, rs, datum):
        """Maunual singularization of `_set_subscriptions.

        This is required to make the `@internal_access` decorator work.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type datum: {str: int}
        :rtype: int
        :returns: Number of affected rows.
        """

        return self._set_subscriptions(rs, [datum])

    @internal_access("ml")
    def _remove_subscriptions(self, rs, data):
        """Remove rows from the ml.subscription_states table.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: [{str: int}]
        :rtype: int
        :returns: Number of affected rows.
        """
        data = affirm_array("subscription_identifier", data)

        if not all(datum['persona_id'] == rs.user.persona_id
                   or self.may_manage(rs, datum['mailinglist_id'])
                   for datum in data):
            raise PrivilegeError("Not privileged.")

        with Atomizer(rs):
            query = "DELETE FROM ml.subscription_states"
            phrase = "mailinglist_id = %s AND persona_id = %s"
            query = query + " WHERE " + " OR ".join([phrase] * len(data))
            params = []
            for datum in data:
                params.extend((datum['mailinglist_id'], datum['persona_id']))

            ret = self.query_exec(rs, query, params)

        return ret

    @internal_access("ml")
    def _remove_subscription(self, rs, datum):
        """Maunual singularization of `_remove_subscriptions.

        This is required to make the `@internal_access` decorator work.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type datum: {str: int}
        :rtype: int
        :returns: Number of affected rows.
        """

        return self._remove_subscriptions(rs, [datum])

    @access("ml")
    def do_subscription_action(self, rs, action, mailinglist_id,
                               persona_id=None):
        """Provide a single entry point for all subscription actions.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type action: `SubscriptionActions`
        :type mailinglist_id: int
        :type persona_id: int
        :rtype: int
        :returns: number of affected rows.
        """
        action = affirm("enum_subscriptionactions", action)
        sa = SubscriptionActions

        # 1: Check if everything is alright – current state comes later
        mailinglist_id = affirm("id", mailinglist_id)
        # Managing actions can only be done by moderators. Other options always
        # change your own subscription state.
        if action.is_managing():
            if not self.may_manage(rs, mailinglist_id):
                raise PrivilegeError("Not privileged.")
            persona_id = affirm("id", persona_id)
        else:
            persona_id = rs.user.persona_id

        with Atomizer(rs):
            self._check_transition_requirements(rs, action, mailinglist_id,
                                                persona_id)

            # 2: Check if current state allows transition
            old_state = self.get_subscription(
                rs, persona_id, mailinglist_id=mailinglist_id)
            error_matrix = sa.error_matrix()
            if error_matrix[action][old_state]:
                raise error_matrix[action][old_state]

            # 3: Do the transition
            new_state = action.get_target_state()
            code = action.get_log_code()
            datum = {
                'mailinglist_id': mailinglist_id,
                'persona_id': persona_id,
                'subscription_state': new_state,
            }

            if new_state is not None:
                ret = self._set_subscription(rs, datum)
            else:
                del datum['subscription_state']
                ret = self._remove_subscription(rs, datum)
            if ret and code:
                self.ml_log(
                    rs, code, datum['mailinglist_id'], datum['persona_id'])

            return ret

    def _check_transition_requirements(self, rs, action, mailinglist_id,
                                       persona_id):
        """Un-inlined code from `do_subscription_action`.

        This has to be called with an atomized context.
        :type rs: :py:class:`cdedb.common.RequestState`
        :type action: `SubscriptionActions`
        :type mailinglist_id: int
        :type persona_id: int
        """
        sa = SubscriptionActions

        # This checks if a user may subscribe via the action triggered
        # This does not check for the override states, as they are always
        # allowed
        policy = self.get_interaction_policy(rs, persona_id,
                                             mailinglist_id=mailinglist_id)
        if action == sa.add_subscriber and (
                not policy or policy.is_implicit()):
            raise SubscriptionError(n_(
                "User has no means to access this list."))
        elif action == sa.subscribe and policy not in (
                const.MailinglistInteractionPolicy.opt_out,
                const.MailinglistInteractionPolicy.opt_in):
            raise SubscriptionError(n_("Can not subscribe."))
        elif (action.is_unsubscribing()
                and not self.get_ml_type(rs, mailinglist_id).allow_unsub):
            raise SubscriptionError(n_("Can not unsubscribe."))
        elif (action == sa.request_subscription and
              policy != const.MailinglistInteractionPolicy.moderated_opt_in):
            raise SubscriptionError(n_("Can not request subscription."))

    @access("ml")
    def set_subscription_address(self, rs, mailinglist_id, persona_id, email):
        """Change or add a subscription address.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type mailinglist_id: int
        :type persona_id: int
        :type email: str
        :rtype: int
        :return: Default return code.
        """
        mailinglist_id = affirm("id", mailinglist_id)
        persona_id = affirm("id", persona_id)
        email = affirm("email", email)

        if not self.is_admin(rs) and persona_id != rs.user.persona_id:
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
                    mailinglist_id, persona_id, additional_info=email)

        return ret

    @access("ml")
    def remove_subscription_address(self, rs, mailinglist_id, persona_id):
        """Remove a subscription address.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type mailinglist_id: int
        :type persona_id: int
        :rtype: int
        :return: Default return code.
        """
        mailinglist_id = affirm("id", mailinglist_id)
        persona_id = affirm("id", persona_id)

        if not self.is_admin(rs) and persona_id != rs.user.persona_id:
            raise PrivilegeError(n_("Not privileged."))

        with Atomizer(rs):
            query = ("DELETE FROM ml.subscription_addresses "
                     "WHERE mailinglist_id = %s AND persona_id = %s")
            params = (mailinglist_id, persona_id)

            ret = self.query_exec(rs, query, params)

            self.ml_log(rs, const.MlLogCodes.subscription_changed,
                        mailinglist_id, persona_id)

        return ret

    @access("ml", "ml_script")
    @singularize("get_subscription_states", "mailinglist_ids", "mailinglist_id")
    def get_many_subscription_states(self, rs, mailinglist_ids, states=None):
        """Get all users related to a given mailinglist and their sub state.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type mailinglist_ids: [int]
        :type states: [int] or None
        :rtype: {int: const.SubscriptionStates}
        :return: Dict mapping persona_ids to their subscription state for the
            given mailinglist. If states were given, limit this to personas with
            those states.
        """
        mailinglist_ids = affirm_set("id", mailinglist_ids)
        states = states or set()
        states = affirm_array("enum_subscriptionstates", states)

        if not all(self.may_manage(rs, ml_id) for ml_id in mailinglist_ids):
            raise PrivilegeError(n_("Not privileged."))

        query = ("SELECT mailinglist_id, persona_id, subscription_state FROM "
                 "ml.subscription_states")

        constraints = ["mailinglist_id = ANY(%s)"]
        params = [mailinglist_ids]

        if states:
            constraints.append("subscription_state = ANY(%s)")
            params.append(states)

        if constraints:
            query = query + " WHERE " + " AND ".join(constraints)

        data = self.query_all(rs, query, params)

        ret = {ml_id: {} for ml_id in mailinglist_ids}
        for e in data:
            ret[e["mailinglist_id"]][e["persona_id"]] = \
                const.SubscriptionStates(e["subscription_state"])

        return ret

    @access("ml")
    def get_user_subscriptions(self, rs, persona_id, states=None,
                               mailinglist_ids=None):
        """Returns a list of mailinglists the persona is related to.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type persona_id: int
        :type states: [const.SubscriptionStates] or None
        :param states: If given only relations with these states are returned.
        :type mailinglist_ids: [int] or None
        :param mailinglist_ids: If given only relations to these mailinglists
            are returned.
        :rtype: {int: const.SubscriptionStates}
        :return: A mapping of mailinglist ids to the persona's subscription
            state wrt. this mailinglist.
        """
        persona_id = affirm("id", persona_id)
        states = states or set()
        states = affirm_set("enum_subscriptionstates", states)
        mailinglist_ids = affirm_set("id", mailinglist_ids or set())
        if (not self.is_admin(rs) and rs.user.persona_id != persona_id
                and (not mailinglist_ids
                     or any(not self.may_manage(rs, ml_id)
                            for ml_id in mailinglist_ids))):
            raise PrivilegeError(n_("Not privileged."))

        query = ("SELECT mailinglist_id, subscription_state "
                 "FROM ml.subscription_states")

        constraints = ["persona_id = %s"]
        params = [persona_id]

        if states:
            constraints.append("subscription_state = ANY(%s)")
            params.append(states)
        if mailinglist_ids:
            constraints.append("mailinglist_id = ANY(%s)")
            params.append(mailinglist_ids)

        if constraints:
            query = query + " WHERE " + " AND ".join(constraints)

        data = self.query_all(rs, query, params)

        SS = const.SubscriptionStates
        ret = {ml_id: None for ml_id in mailinglist_ids}
        ret.update({e["mailinglist_id"]: SS(e["subscription_state"])
                    for e in data})

        return ret

    @access("ml")
    def get_subscription(self, rs, persona_id, states=None,
                         mailinglist_id=None):
        """Return the relation between a persona and a mailinglist.

        Returns None if there exists no such persona, mailinglist or relation.

        Manual implementation of singularization of `get_user_subscriptions`,
        to make sure the parameters work.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type persona_id: int
        :type states: [const.SubscriptionStates] or None
        :type mailinglist_id: int or None
        :rtype: const.SubscriptionStates or None
        """
        # Validation is done inside.
        return unwrap(self.get_user_subscriptions(
            rs, persona_id, states=states, mailinglist_ids=(mailinglist_id,)))

    @access("ml", "ml_script")
    def get_subscription_addresses(self, rs, mailinglist_id, persona_ids=None,
                                   explicits_only=False):
        """Retrieve email addresses of the given personas for the mailinglist.

        With `explicits_only = False`, this returns a dict mapping all
        subscribers (or a subset given via `persona_ids`) to email addresses.
        If they have expicitly specified a subscription address that one is
        returned, otherwise the username is returned.
        If a subscriber has neither a username nor a explicit subscription
        address then for that subscriber None is returned.

        With `explicits_only = True` every subscriber is mapped to their
        explicit subscription address or None, if none is given.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type mailinglist_id: int
        :type persona_ids: [int] or None
        :param persona_ids: Limit the result to a subset of subscribers. Get all
            subscribers if this is None.
        :type explicits_only: bool
        :param explicits_only: If this is False, also fetch usernames for
            subscribers without explicit subscription addresses.
        :rtype: {int: str or None}
        :returns: Returns persona ids mapped to email addresses or None if
            `explicits_only` is True.
        """
        mailinglist_id = affirm("id", mailinglist_id)

        ret = {}
        with Atomizer(rs):
            if not self.may_manage(rs, mailinglist_id):
                    raise PrivilegeError(n_("Not privileged."))

            subscribers = self.get_subscription_states(
                rs, mailinglist_id,
                states=const.SubscriptionStates.subscribing_states())
            if persona_ids is None:
                # Default to all subscribers.
                persona_ids = set(subscribers)
            else:
                persona_ids = affirm_set("id", persona_ids)
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
                data = self.core.get_personas(rs, defaults)
                data = {
                    e["id"]: e["username"] for e in data.values()}
                ret.update(data)
            else:
                ret.update({p_id: None for p_id in defaults})

        return ret

    @access("ml", "ml_script")
    def get_subscription_address(self, rs, mailinglist_id, persona_id,
                                 explicits_only=False):
        """Return the subscription address for one persona and one mailinglist.

        This slightly differs for requesting another users subscription address
        and one's own, due to differing privilege requirements.

        Manual implementation of singularization of
        `get_subscription_addresses`, to make sure the parameters work.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type mailinglist_id: int
        :type persona_id: int
        :type explicits_only: bool
        :rtype: str or None
        """

        if persona_id == rs.user.persona_id:
            mailinglist_id = affirm("id", mailinglist_id)
            persona_id = affirm("id", persona_id)

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
    def get_persona_addresses(self, rs):
        """Get all confirmed email addresses for a user.

        This includes all subscription addresses as well as the username.

        :type rs: :py:class:`cdedb.common.RequestState`
        :rtype: {str}
        """
        query = ("SELECT DISTINCT address FROM ml.subscription_addresses "
                 "WHERE persona_id = %s")
        params = (rs.user.persona_id,)
        data = self.query_all(rs, query, params)
        ret = {e["address"] for e in data}
        ret.add(rs.user.username)
        return ret

    @access("ml")
    def is_subscribed(self, rs, persona_id, mailinglist_id):
        """Sugar coating around :py:meth:`get_user_subscriptions`.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type persona_id: int
        :type mailinglist_id: int
        :rtype: bool
        """
        # validation is done inside
        sub_states = const.SubscriptionStates.subscribing_states()
        data = self.get_subscription(
            rs, persona_id, states=sub_states, mailinglist_id=mailinglist_id)
        return bool(data)

    @access("ml_admin")
    def write_subscription_states(self, rs, mailinglist_id):
        """This takes care of writing implicit subscriptions to the db.

        This also checks the integrity of existing subscriptions.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type mailinglist_id: int
        :rtype: int
        :return: default return code.
        """
        mailinglist_id = affirm("id", mailinglist_id)

        # States of current subscriptions we may touch.
        old_subscriber_states = {const.SubscriptionStates.implicit,
                                 const.SubscriptionStates.subscribed}
        # States of current subscriptions we may not touch.
        protected_states = {const.SubscriptionStates.unsubscribed,
                            const.SubscriptionStates.unsubscription_override,
                            const.SubscriptionStates.subscription_override}

        ret = 1
        with Atomizer(rs):
            ml = self.get_mailinglist(rs, mailinglist_id)
            atype = self.get_ml_type(rs, mailinglist_id)

            if not atype.periodic_cleanup(rs, ml):
                return ret

            old_subscribers = self.get_subscription_states(
                rs, mailinglist_id, states=old_subscriber_states)
            # This is dependant on mailinglist type

            new_implicits = atype.get_implicit_subscribers(
                rs, self.backends, ml)

            # Check whether current subscribers may stay subscribed.
            # This is the case if they are still implicit subscribers of
            # the list or if `get_interaction_policy` says so.
            delete = []
            personas = self.core.get_personas(
                rs, set(old_subscribers) - new_implicits)
            for persona_id, persona in personas.items():
                may_subscribe = atype.get_interaction_policy(
                    rs, self.backends, mailinglist=ml, persona_id=persona_id)
                state = old_subscribers[persona_id]
                if (state == const.SubscriptionStates.implicit
                        or not may_subscribe
                        or may_subscribe.is_implicit()):
                    datum = {
                        'mailinglist_id': mailinglist_id,
                        'persona_id': persona_id,
                    }
                    # Log this to prevent confusion especially for team lists
                    self.ml_log(rs, const.MlLogCodes.cron_removed,
                                mailinglist_id, persona_id=persona_id)
                    delete.append(datum)

            # Remove those who may not stay subscribed.
            if delete:
                num = self._remove_subscriptions(rs, delete)
                ret *= num
                msg = "Removed {} subscribers from mailinglist {}."
                self.logger.info(msg.format(num, mailinglist_id))

            # Check whether any implicit subscribers need to be written.
            # This is the case if they are not already old subscribers and
            # they don't have a protected subscription.
            protected = self.get_subscription_states(
                rs, mailinglist_id, states=protected_states)
            write = set(new_implicits) - set(old_subscribers) - set(protected)

            # Set implicit subscriptions.
            data = [
                {
                    'mailinglist_id': mailinglist_id,
                    'persona_id': persona_id,
                    'subscription_state': const.SubscriptionStates.implicit,
                }
                for persona_id in write
            ]
            if data:
                self._set_subscriptions(rs, data)
                ret *= len(data)
                msg = "Added {} subscribers to mailinglist {}."
                self.logger.debug(msg.format(len(write), mailinglist_id))

        return ret

    @access("persona")
    def verify_existence(self, rs, address):
        """
        Check whether a mailinglist with the given address is known.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type address: str
        :rtype: bool
        """
        address = affirm("email", address)

        query = "SELECT COUNT(*) AS num FROM ml.mailinglists WHERE address = %s"
        data = self.query_one(rs, query, (address,))
        return bool(data['num'])

    # Everythin beyond this point is for communication with the mailinglist
    # software, and should normally not be used otherwise.
    @access("ml_script")
    def export_overview(self, rs):
        """Get a summary of all existing mailing lists.

        This is used to setup the mailinglist software.

        :type rs: :py:class:`cdedb.common.RequestState`
        :rtype: [{str: object}]
        """
        query = "SELECT address, is_active FROM ml.mailinglists"
        data = self.query_all(rs, query, tuple())
        return data

    @access("ml_script")
    def export_one(self, rs, address):
        """Retrieve data about a specific mailinglist.

        This is invoked by the mailinglist software to query for the
        configuration of a specific mailinglist.

        Care has to be taken, to filter away any empty email addresses which
        may happen because they were unset in the backend.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type address: str
        :rtype: {str: object}
        """
        address = affirm("email", address)
        with Atomizer(rs):
            query = "SELECT id FROM ml.mailinglists WHERE address = %s"
            mailinglist_id = self.query_one(rs, query, (address,))
            if not mailinglist_id:
                return None
            mailinglist_id = unwrap(mailinglist_id)
            mailinglist = unwrap(self.get_mailinglists(rs, (mailinglist_id,)))
            local_part, domain = mailinglist['address'].split('@')
            # We do not use self.core.get_personas since this triggers an
            # access violation. It would be quite tedious to fix this so
            # it's better to allow a small hack.
            query = "SELECT username FROM core.personas WHERE id = ANY(%s)"
            tmp = self.query_all(rs, query, (mailinglist['moderators'],))
            moderators = tuple(filter(None, (e['username'] for e in tmp)))
            # TODO fix this.
            subscribers = self.get_subscription_addresses(
                rs, mailinglist_id, explicits_only=True)
            defaults = {anid for anid in subscribers if not subscribers[anid]}
            tmp = self.query_all(rs, query, (defaults,))
            subscribers.update({e['username']: e['username'] for e in tmp})
            subscribers = tuple(filter(None, subscribers.values()))
            return {
                "listname": mailinglist['title'],
                "address": mailinglist['address'],
                "admin_address": "{}-owner@{}".format(local_part, domain),
                "sender": mailinglist['address'],
                # "footer" will be set in the frontend
                # FIXME "prefix" currently not supported
                "size_max": mailinglist['maxsize'],
                "moderators": moderators,
                "subscribers": subscribers,
                "whitelist": mailinglist['whitelist'],
            }

    @access("ml_script")
    def oldstyle_mailinglist_config_export(self, rs):
        """
        mailinglist_config_export() - get config information about all lists

        Get configuration information for all lists which are needed
        for autoconfiguration. See the description of table mailinglist
        for the meaning of the entries in the dict returned.

        :rtype: [{'address' : unicode, 'inactive' : bool,
                  'maxsize' : int or None, 'mime' : bool or None}]
        """
        query = glue("SELECT address, NOT is_active AS inactive, maxsize,",
                     "attachment_policy AS mime FROM ml.mailinglists")
        data = self.query_all(rs, query, tuple())
        COMPAT_MAP = {
            const.AttachmentPolicy.allow: False,
            const.AttachmentPolicy.pdf_only: None,
            const.AttachmentPolicy.forbid: True,
        }
        for entry in data:
            entry['mime'] = COMPAT_MAP[entry['mime']]
        return data

    @access("ml_script")
    def oldstyle_mailinglist_export(self, rs, address):
        """
        mailinglist_export() - get export information about a list

        This function returns a dict containing all necessary fields
        for the mailinglist software to run the list with the list
        address @address.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type address: unicode
        :rtype: {'listname' : unicode, 'address' : unicode,
                 'sender' : unicode, 'list-unsubscribe' : unicode,
                 'list-subscribe' : unicode, 'list-owner' : unicode,
                 'moderators' : [unicode, ...],
                 'subscribers' : [unicode, ...],
                 'whitelist' : [unicode, ...]}
        """
        address = affirm("email", address)
        with Atomizer(rs):
            query = "SELECT id FROM ml.mailinglists WHERE address = %s"
            mailinglist_id = self.query_one(rs, query, (address,))
            if not mailinglist_id:
                return None
            mailinglist_id = unwrap(mailinglist_id)
            mailinglist = unwrap(self.get_mailinglists(rs, (mailinglist_id,)))
            local_part, domain = mailinglist['address'].split('@')
            envelope = local_part + u"-bounces@" + domain
            # We do not use self.core.get_personas since this triggers an
            # access violation. It would be quite tedious to fix this so
            # it's better to allow a small hack.
            query = "SELECT username FROM core.personas WHERE id = ANY(%s)"
            tmp = self.query_all(rs, query, (mailinglist['moderators'],))
            moderators = tuple(filter(None, (e['username'] for e in tmp)))
            # TODO fix this.
            subscribers = self.get_subscription_addresses(
                rs, mailinglist_id, explicits_only=True)
            defaults = {anid for anid in subscribers if not subscribers[anid]}
            tmp = self.query_all(rs, query, (defaults,))
            subscribers.update({e['username']: e['username'] for e in tmp})
            subscribers = tuple(filter(None, subscribers.values()))
            mod_policy = const.ModerationPolicy
            if mailinglist['mod_policy'] == mod_policy.unmoderated:
                whitelist = ['*']
            else:
                whitelist = list(mailinglist['whitelist'])
                if mailinglist['mod_policy'] == mod_policy.non_subscribers:
                    whitelist.append('.')
            return {
                'listname': mailinglist['subject_prefix'],
                'address': mailinglist['address'],
                'moderators': moderators,
                'subscribers': subscribers,
                'whitelist': whitelist,
                'sender': envelope,
                'list-unsubscribe': u"https://db.cde-ev.de/",
                'list-subscribe': u"https://db.cde-ev.de/",
                'list-owner': u"https://db.cde-ev.de/",
            }

    @access("ml_script")
    def oldstyle_modlist_export(self, rs, address):
        """
        mod_export() - get export information for moderators' list

        This function returns a dict containing all necessary fields
        for the mailinglist software to run a list for the moderators
        of the list with address @address.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type address: unicode
        :rtype: {'listname' : unicode, 'address' : unicode,
                 'sender' : unicode, 'list-unsubscribe' : unicode,
                 'list-subscribe' : unicode, 'list-owner' : unicode,
                 'moderators' : [unicode, ...],
                 'subscribers' : [unicode, ...],
                 'whitelist' : [unicode, ...]}
        """
        address = affirm("email", address)
        with Atomizer(rs):
            query = "SELECT id FROM ml.mailinglists WHERE address = %s"
            mailinglist_id = self.query_one(rs, query, (address,))
            if not mailinglist_id:
                return None
            mailinglist_id = unwrap(mailinglist_id)
            mailinglist = unwrap(self.get_mailinglists(rs, (mailinglist_id,)))
            local_part, domain = mailinglist['address'].split('@')
            # We do not use self.core.get_personas since this triggers an
            # access violation. It would be quite tedious to fix this so
            # it's better to allow a small hack.
            query = "SELECT username FROM core.personas WHERE id = ANY(%s)"
            tmp = self.query_all(rs, query, (mailinglist['moderators'],))
            moderators = tuple(filter(None, (e['username'] for e in tmp)))
            return {
                'listname': mailinglist['subject_prefix'],
                'address': mailinglist['address'],
                'moderators': moderators,
                'subscribers': moderators,
                'whitelist': ['*'],
                'sender': "cdedb-doublebounces@cde-ev.de",
                'list-unsubscribe': u"https://db.cde-ev.de/",
                'list-subscribe': u"https://db.cde-ev.de/",
                'list-owner': u"https://db.cde-ev.de/",
            }

    @access("ml_script")
    def oldstyle_bounce(self, rs, address, error):
        address = affirm("email", address)
        error = affirm("int", error)
        with Atomizer(rs):
            # We do not use self.core.get_personas since this triggers an
            # access violation. It would be quite tedious to fix this so
            # it's better to allow a small hack.
            query = glue("SELECT id, username FROM core.personas",
                         "WHERE username = lower(%s)")
            data = self.query_all(rs, query, (address,))
            if not data:
                return None
            reasons = {1: "Ungültige E-Mail",
                       2: "Postfach voll.",
                       3: "Anderes Problem."}
            line = "E-Mail-Adresse '{}' macht Probleme - {} - {}".format(
                address, reasons.get(error, "Unbekanntes Problem."),
                now().date().isoformat())
            self.ml_log(rs, const.MlLogCodes.email_trouble, None,
                        persona_id=unwrap(data)['id'], additional_info=line)
            return True
