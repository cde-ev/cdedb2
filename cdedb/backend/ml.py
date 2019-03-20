#!/usr/bin/env python3

"""The ml backend provides mailing lists. This provides services to the
event and assembly realm in the form of specific mailing lists.

This has an additional user role ml_script which is intended to be
filled by a mailing list software and not a usual persona. This acts as
if it has moderator privileges for all lists.
"""

from cdedb.backend.common import (
    access, affirm_validation as affirm, Silencer, AbstractBackend,
    affirm_set_validation as affirm_set, singularize)
from cdedb.common import (
    n_, glue, PrivilegeError, unwrap, MAILINGLIST_FIELDS, SubscriptionStates,
    extract_roles, implying_realms, now)
from cdedb.query import QueryOperators
from cdedb.database.connection import Atomizer
import cdedb.database.constants as const


class MlBackend(AbstractBackend):
    """Take note of the fact that some personas are moderators and thus have
    additional actions available."""
    realm = "ml"

    @classmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

    @staticmethod
    def is_moderator(rs, ml_id):
        """Check for moderator privileges as specified in the ml.moderators
        table.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ml_id: int
        :rtype: bool
        """
        return ml_id in rs.user.moderator or "ml_script" in rs.user.roles

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
    def retrieve_log(self, rs, codes=None, mailinglist_id=None,
                     start=None, stop=None, additional_info=None):
        """Get recorded activity.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type codes: [int] or None
        :type mailinglist_id: int or None
        :type start: int or None
        :type stop: int or None
        :type additional_info: str or None
        :rtype: [{str: object}]
        """
        mailinglist_id = affirm("id_or_None", mailinglist_id)
        if not self.is_moderator(rs, mailinglist_id) and not self.is_admin(rs):
            raise PrivilegeError(n_("Not privileged."))
        return self.generic_retrieve_log(
            rs, "enum_mllogcodes", "mailinglist", "ml.log", codes,
            mailinglist_id, start, stop, additional_info=additional_info)

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
    def list_mailinglists(self, rs, audience_policies=None, active_only=True):
        """List all mailinglists

        :type rs: :py:class:`cdedb.common.RequestState`
        :type audience_policies: [AudiencePolicy] or None
        :param audience_policies: If given, display only mailinglists with these
          audience policies.
        :type active_only: bool
        :param active_only: Toggle wether inactive lists should be included.
        :rtype: {int: str}
        :returns: Mapping of mailinglist ids to titles.
        """
        active_only = affirm("bool", active_only)
        audience_policies = affirm_set(
            "enum_audiencepolicy", audience_policies, allow_None=True)
        query = "SELECT id, title FROM ml.mailinglists"
        params = []
        if active_only:
            query = glue(query, "WHERE is_active = True")
        if audience_policies is not None:
            connector = "AND" if active_only else "WHERE"
            query = glue(query,
                         "{} audience_policy = ANY(%s)".format(connector))
            params.append(audience_policies)
        data = self.query_all(rs, query, params)
        return {e['id']: e['title'] for e in data}

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
        return ret

    @access("ml")
    def set_mailinglist(self, rs, data):
        """Update some keys of a mailinglist.

        If the keys 'moderators' or 'whitelist' are present you have to pass
        the complete set of moderator IDs or whitelisted addresses, which
        will superseed the current list.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :rtype: int
        :returns: default return code
        """
        data = affirm("mailinglist", data)
        if not self.is_moderator(rs, data['id']) and not self.is_admin(rs):
            raise PrivilegeError(n_("Not privileged."))
        ret = 1
        with Atomizer(rs):
            mdata = {k: v for k, v in data.items() if k in MAILINGLIST_FIELDS}
            policy = const.SubscriptionPolicy
            if ('sub_policy' in mdata and not self.is_admin(rs)
                    and not policy(mdata['sub_policy'].is_additive())):
                current = unwrap(self.get_mailinglists(rs, (data['id'],)))
                if current['sub_policy'] != mdata['sub_policy']:
                    raise PrivilegeError(
                        n_("Only admin may set opt out policies."))
            if len(mdata) > 1:
                ret *= self.sql_update(rs, "ml.mailinglists", mdata)
                self.ml_log(rs, const.MlLogCodes.list_changed, data['id'])
            if 'moderators' in data:
                existing = {e['persona_id'] for e in self.sql_select(
                    rs, "ml.moderators", ("persona_id",), (data['id'],),
                    entity_key="mailinglist_id")}
                new = set(data['moderators']) - existing
                deleted = existing - set(data['moderators'])
                if new:
                    for anid in new:
                        new_mod = {
                            'persona_id': anid,
                            'mailinglist_id': data['id']
                        }
                        ret *= self.sql_insert(rs, "ml.moderators", new_mod)
                        self.ml_log(rs, const.MlLogCodes.moderator_added,
                                    data['id'], persona_id=anid)
                if deleted:
                    query = glue(
                        "DELETE FROM ml.moderators",
                        "WHERE persona_id = ANY(%s) AND mailinglist_id = %s")
                    ret *= self.query_exec(rs, query, (deleted, data['id']))
                    for anid in deleted:
                        self.ml_log(rs, const.MlLogCodes.moderator_removed,
                                    data['id'], persona_id=anid)
            if 'whitelist' in data:
                existing = {e['address'] for e in self.sql_select(
                    rs, "ml.whitelist", ("address",), (data['id'],),
                    entity_key="mailinglist_id")}
                new = set(data['whitelist']) - existing
                deleted = existing - set(data['whitelist'])
                if new:
                    for address in new:
                        new_white = {
                            'address': address,
                            'mailinglist_id': data['id'],
                        }
                        ret *= self.sql_insert(rs, "ml.whitelist", new_white)
                        self.ml_log(rs, const.MlLogCodes.whitelist_added,
                                    data['id'], additional_info=address)
                if deleted:
                    query = glue(
                        "DELETE FROM ml.whitelist",
                        "WHERE address = ANY(%s) AND mailinglist_id = %s")
                    ret *= self.query_exec(rs, query, (deleted, data['id']))
                    for address in deleted:
                        self.ml_log(rs, const.MlLogCodes.whitelist_removed,
                                    data['id'], additional_info=address)
        return ret

    @access("ml_admin")
    def create_mailinglist(self, rs, data):
        """Make a new mailinglist.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :rtype: int
        :returns: the id of the new mailinglist
        """
        data = affirm("mailinglist", data, creation=True)
        with Atomizer(rs):
            mdata = {k: v for k, v in data.items() if k in MAILINGLIST_FIELDS}
            new_id = self.sql_insert(rs, "ml.mailinglists", mdata)
            for aspect in ('moderators', 'whitelist'):
                if aspect in data:
                    adata = {
                        'id': new_id,
                        aspect: data[aspect],
                    }
                    self.set_mailinglist(rs, adata)
            self.ml_log(rs, const.MlLogCodes.list_created, new_id)
        return new_id

    @access("ml_admin")
    def delete_mailinglist(self, rs, mailinglist_id, cascade=False):
        """Remove a mailinglist.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type mailinglist_id: int
        :type cascade: bool
        :param cascade: If False, there must be no references to the list
          first (i.e. there have to be no subscriptions, moderators,
          ...). If True, this function first removes all refering entities.
        :rtype: int
        :returns: default return code
        """
        mailinglist_id = affirm("id", mailinglist_id)
        cascade = affirm("bool", cascade)
        ret = 1
        with Atomizer(rs):
            data = unwrap(self.get_mailinglists(rs, (mailinglist_id,)))
            if cascade:
                with Silencer(rs):
                    deletor = {
                        'id': mailinglist_id,
                        'moderators': tuple(),
                        'whitelist': tuple(),
                    }
                    ret *= self.set_mailinglist(rs, deletor)
                    requests = self.list_requests(rs, mailinglist_id)
                    for persona_id in requests:
                        ret *= self.decide_request(rs, mailinglist_id,
                                                   persona_id, ack=False)
                # Manually delete entries which are not otherwise accessible
                for table in ("ml.subscription_states", "ml.log"):
                    self.sql_delete_one(rs, table, mailinglist_id,
                                        entity_key="mailinglist_id")
            ret *= self.sql_delete_one(rs, "ml.mailinglists", mailinglist_id)
            self.ml_log(rs, const.MlLogCodes.list_deleted, mailinglist_id=None,
                        additional_info="{} ({})".format(
                            data['title'], data['address']))
            return ret

    @access("ml")
    def subscribers(self, rs, mailinglist_id):
        """Compile a list of subscribers.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type mailinglist_id: int
        :rtype: {int: str}
        :returns: A dict mapping ids of subscribers to their subscribed
          email addresses.
        """
        mailinglist_id = affirm("id", mailinglist_id)
        if not self.is_moderator(rs, mailinglist_id) and not self.is_admin(rs):
            raise PrivilegeError(n_("Not privileged."))
        event_list_query = glue(
            "SELECT DISTINCT regs.persona_id FROM event.registrations AS regs",
            "JOIN event.registration_parts AS parts",
            "ON regs.id = parts.registration_id",
            "WHERE regs.event_id = %s AND parts.status = ANY(%s)")
        ret = {}
        with Atomizer(rs):
            ml = unwrap(self.get_mailinglists(rs, (mailinglist_id,)))
            subs = self.sql_select(
                rs, "ml.subscription_states",
                ("persona_id", "address", "is_subscribed"), (mailinglist_id,),
                entity_key="mailinglist_id")
            explicits = {e['persona_id']: e['address']
                         for e in subs if e['is_subscribed']}
            excludes = {e['persona_id']
                        for e in subs if not e['is_subscribed']}
            if ml['event_id']:
                if not ml['registration_stati']:
                    orgas = self.sql_select(
                        rs, "event.orgas", ("persona_id",),
                        (ml['event_id'],), entity_key="event_id")
                    ret = {e['persona_id']: None for e in orgas}
                else:
                    regs = self.query_all(rs, event_list_query, (
                        ml['event_id'], ml['registration_stati']))
                    ret = {e['persona_id']: None for e in regs}
            elif ml['assembly_id']:
                attendees = self.sql_select(
                    rs, "assembly.attendees", ("persona_id",),
                    (ml['assembly_id'],), entity_key="assembly_id")
                ret = {e['persona_id']: None for e in attendees}
            elif const.SubscriptionPolicy(ml['sub_policy']).is_additive():
                # explicits take care of everything
                pass
            else:
                # opt-out lists
                query = glue(
                    "SELECT id FROM core.personas",
                    "WHERE {} AND is_active = True".format(
                        const.AudiencePolicy(
                            ml['audience_policy']).sql_test()))
                personas = self.query_all(rs, query, tuple())
                ret = {e['id']: None for e in personas}
            ret = {k: v for k, v in ret.items() if k not in excludes}
            ret.update(explicits)
            defaults = tuple(k for k, v in ret.items() if not v)
            emails = self.sql_select(rs, "core.personas",
                                     ("id", "username"), defaults)
            ret.update({e['id']: e['username'] for e in emails})
            return ret

    @access("ml")
    def is_subscribed(self, rs, persona_id, mailinglist_id):
        """Sugar coating around :py:meth:`subscriptions`.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type persona_id: int
        :type mailinglist_id: int
        :rtype: bool
        """
        # validation is done inside
        return bool(self.subscriptions(rs, persona_id, lists=(mailinglist_id,)))

    @access("ml")
    def subscriptions(self, rs, persona_id, lists=None):
        """Which lists is a persona subscribed to.

        .. note:: For lists associated to an event or an assembly this is
          somewhat expensive. This is alleviated by the possibility to
          restrict the lookup to a subset of all lists.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type persona_id: int
        :type lists: [int] or None
        :param lists: If given check only these lists.
        :rtype: {int: str or None}
        :returns: A dict mapping each mailing list to the address the
          persona is subscribed with or None, if no explicit address was
          given, meaning the username is used.
        """
        persona_id = affirm("id", persona_id)
        lists = affirm_set("id", lists, allow_None=True)
        if (persona_id != rs.user.persona_id
                and not self.is_admin(rs)
                and not all(self.is_moderator(rs, anid) for anid in lists)):
            raise PrivilegeError(n_("Not privileged."))
        event_list_query = glue(
            "SELECT DISTINCT regs.persona_id FROM event.registrations AS regs",
            "JOIN event.registration_parts AS parts",
            "ON regs.id = parts.registration_id",
            "WHERE regs.event_id = %s AND parts.status = ANY(%s)",
            "AND regs.persona_id = %s")
        ret = {}
        with Atomizer(rs):
            lists = lists or self.list_mailinglists(rs)
            ml = self.get_mailinglists(rs, lists)
            subs = {e['mailinglist_id']: e for e in self.sql_select(
                rs, "ml.subscription_states",
                ("persona_id", "mailinglist_id", "address", "is_subscribed"),
                (persona_id,), entity_key="persona_id")}
            for mailinglist_id in ml:
                if mailinglist_id in subs:
                    this_sub = subs[mailinglist_id]
                    if this_sub['is_subscribed']:
                        ret[mailinglist_id] = this_sub['address']
                else:
                    this_ml = ml[mailinglist_id]
                    if this_ml['event_id']:
                        if not this_ml['registration_stati']:
                            query = glue(
                                "SELECT persona_id FROM event.orgas",
                                "WHERE event_id = %s AND persona_id = %s")
                            orga = self.query_one(rs, query, (
                                this_ml['event_id'], persona_id))
                            if orga:
                                ret[mailinglist_id] = None
                        else:
                            reg = self.query_one(rs, event_list_query, (
                                this_ml['event_id'],
                                this_ml['registration_stati'], persona_id))
                            if reg:
                                ret[mailinglist_id] = None
                    elif this_ml['assembly_id']:
                        query = glue(
                            "SELECT persona_id FROM assembly.attendees",
                            "WHERE assembly_id = %s AND persona_id = %s")
                        attendee = self.query_one(rs, query, (
                            this_ml['assembly_id'], persona_id))
                        if attendee:
                            ret[mailinglist_id] = None
                    elif not const.SubscriptionPolicy(
                            this_ml['sub_policy']).is_additive():
                        ret[mailinglist_id] = None
            return ret

    @access("ml")
    def lookup_subscription_states(self, rs, persona_ids, mailinglist_ids):
        """Check relation between some personas and some mailinglists.

        This especially takes subscription requests into account.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type mailinglist_ids: [int]
        :type persona_ids: [int]
        :rtype: {(int, int): SubscriptionStates}
        :returns: The keys are tuples (persona_id, mailinglist_id).
        """
        persona_ids = affirm_set("id", persona_ids)
        mailinglist_ids = affirm_set("id", mailinglist_ids)
        if (persona_ids != {rs.user.persona_id}
                and (len(mailinglist_ids) > 1
                     or not self.is_moderator(rs, unwrap(mailinglist_ids)))
                and not self.is_admin(rs)):
            raise PrivilegeError(n_("Not privileged."))
        ret = {}
        for persona_id in persona_ids:
            query = glue("SELECT mailinglist_id FROM ml.subscription_requests",
                         "WHERE mailinglist_id = ANY(%s) AND persona_id = %s")
            requests = self.query_all(rs, query, (mailinglist_ids, persona_id))
            requests = tuple(e['mailinglist_id'] for e in requests)
            subscriptions = self.subscriptions(rs, persona_id,
                                               lists=mailinglist_ids)
            for mailinglist_id in mailinglist_ids:
                ss = SubscriptionStates
                if mailinglist_id in subscriptions:
                    ret[(persona_id, mailinglist_id)] = ss.subscribed
                elif mailinglist_id in requests:
                    ret[(persona_id, mailinglist_id)] = ss.requested
                else:
                    ret[(persona_id, mailinglist_id)] = ss.unsubscribed
        return ret

    def write_subscription_state(self, rs, mailinglist_id, persona_id,
                                 is_subscribed, address):
        """Helper to persist a (un)subscription.

        We want to update existing infos instead of simply deleting all
        existing infos and inserting new ones. Thus this helper.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type mailinglist_id: int
        :type persona_id: int
        :type is_subscribed: bool
        :type address: str or None
        :rtype: int
        :returns: default return code
        """
        with Atomizer(rs):
            query = glue("SELECT id FROM ml.subscription_states",
                         "WHERE mailinglist_id = %s AND persona_id = %s")
            current = self.query_one(rs, query, (mailinglist_id, persona_id))
            new = {
                'mailinglist_id': mailinglist_id,
                'persona_id': persona_id,
                'is_subscribed': is_subscribed,
                'address': address,
            }
            if current is None:
                return self.sql_insert(rs, "ml.subscription_states", new)
            else:
                new['id'] = unwrap(current)
                return self.sql_update(rs, "ml.subscription_states", new)

    @access("ml")
    def change_subscription_state(self, rs, mailinglist_id, persona_id,
                                  subscribe, address=None):
        """Alter any piece of a subscription.

        This also handles unsubscriptions, changing of addresses with which
        a persona is subscribed and subscription requests for lists with
        moderated opt-in.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type mailinglist_id: int
        :type persona_id: int
        :type subscribe: bool
        :param subscribe: The target state, which need not differ from the
          current state.
        :type address: str or None
        :rtype: int
        :returns: default return code
        """
        mailinglist_id = affirm("id", mailinglist_id)
        persona_id = affirm("id", persona_id)
        subscribe = affirm("bool", subscribe)
        address = affirm("email_or_None", address)
        if (persona_id != rs.user.persona_id
                and not self.is_moderator(rs, mailinglist_id)
                and not self.is_admin(rs)):
            raise PrivilegeError(n_("Not privileged."))

        privileged = self.is_moderator(rs, mailinglist_id) or self.is_admin(rs)
        with Atomizer(rs):
            # (1) Initial checks for easy situations
            ml = unwrap(self.get_mailinglists(rs, (mailinglist_id,)))
            if not privileged and not ml['is_active']:
                return 0
            query = glue("SELECT id FROM ml.subscription_requests",
                         "WHERE mailinglist_id = %s AND persona_id = %s")
            requested = self.query_one(rs, query, (mailinglist_id, persona_id))
            if requested:
                if subscribe:
                    return 0
                else:
                    self.ml_log(rs, const.MlLogCodes.request_cancelled,
                                mailinglist_id, persona_id=persona_id)
                    query = glue(
                        "DELETE FROM ml.subscription_requests",
                        "WHERE mailinglist_id = %s AND persona_id = %s")
                    return self.query_exec(rs, query,
                                           (mailinglist_id, persona_id))
            if self.is_subscribed(rs, persona_id, mailinglist_id) == subscribe:
                self.ml_log(rs, const.MlLogCodes.subscription_changed,
                            mailinglist_id, persona_id=persona_id,
                            additional_info=address)
                return self.write_subscription_state(
                    rs, mailinglist_id, persona_id, subscribe, address)
            # (2) Handle actual transitions
            policy = const.AudiencePolicy(ml['audience_policy'])
            roles = extract_roles(self.core.get_persona(rs, persona_id))
            if not policy.check(roles) and not self.is_admin(rs):
                # Only admins may add non-matching users
                return 0
            gateway = False
            if subscribe and ml['gateway']:
                gateway = self.is_subscribed(rs, persona_id, ml['gateway'])
            policy = const.SubscriptionPolicy
            if (subscribe and not privileged and not gateway
                    and ml['sub_policy'] == policy.moderated_opt_in):
                self.ml_log(rs, const.MlLogCodes.subscription_requested,
                            mailinglist_id, persona_id=persona_id)
                request = {
                    'mailinglist_id': mailinglist_id,
                    'persona_id': persona_id,
                }
                return -self.sql_insert(rs, "ml.subscription_requests", request)
            if (policy(ml['sub_policy']).privileged_transition(subscribe)
                    and not privileged and not gateway):
                raise PrivilegeError(n_("Must be moderator."))
            if subscribe:
                code = const.MlLogCodes.subscribed
            else:
                code = const.MlLogCodes.unsubscribed
            self.ml_log(rs, code, mailinglist_id, persona_id=persona_id)
            return self.write_subscription_state(rs, mailinglist_id, persona_id,
                                                 subscribe, address)

    @access("ml")
    def list_requests(self, rs, mailinglist_id):
        """Retrieve open subscription requests.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type mailinglist_id: int
        :rtype: [int]
        :returns: personas waiting for subscription
        """
        mailinglist_id = affirm("id", mailinglist_id)
        if not self.is_moderator(rs, mailinglist_id) and not self.is_admin(rs):
            raise PrivilegeError(n_("Not privileged."))

        data = self.sql_select(
            rs, "ml.subscription_requests", ("persona_id",),
            (mailinglist_id,), entity_key="mailinglist_id")
        return tuple(e['persona_id'] for e in data)

    @access("ml")
    def decide_request(self, rs, mailinglist_id, persona_id, ack):
        """Moderate subscription to an opt-in list.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type mailinglist_id: int
        :type persona_id: int
        :type ack: bool
        :rtype: int
        :returns: default return code
        """
        mailinglist_id = affirm("id", mailinglist_id)
        persona_id = affirm("id", persona_id)
        ack = affirm("bool", ack)
        if not self.is_moderator(rs, mailinglist_id) and not self.is_admin(rs):
            raise PrivilegeError(n_("Not privileged."))

        with Atomizer(rs):
            query = glue("DELETE FROM ml.subscription_requests",
                         "WHERE mailinglist_id = %s AND persona_id = %s")
            num = self.query_exec(rs, query, (mailinglist_id, persona_id))
            if ack:
                code = const.MlLogCodes.request_approved
            else:
                code = const.MlLogCodes.request_denied
            self.ml_log(rs, code, mailinglist_id, persona_id=persona_id)
            if not ack or not num:
                return num
            return self.write_subscription_state(
                rs, mailinglist_id, persona_id, is_subscribed=True,
                address=None)

    @access("ml")
    @singularize("check_states_single")
    def check_states(self, rs, mailinglist_ids):
        """Verify that all explicit subscriptions are by the target audience.

        A persona may change state or may be subscribed by a moderator
        even if she is not in the target audience. Since defending
        against the first case is rather complicated, we choose to offer
        the means of verification afterwards.

        This also checks for inactive accounts which are subscribed to a
        list.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type mailinglist_ids: [int]
        :rtype: {int: [{str: object}]}
        :returns: A dict mapping list ids to lists of dicts of offenders.
        """
        mailinglist_ids = affirm_set("id", mailinglist_ids)

        mailinglists = self.get_mailinglists(rs, mailinglist_ids)
        sql_tests = {
            e['id']: const.AudiencePolicy(e['audience_policy']).sql_test()
            for e in mailinglists.values()}
        query = glue(
            "SELECT subs.mailinglist_id, subs.persona_id, subs.is_override",
            "FROM ml.subscription_states AS subs",
            "JOIN core.personas AS p ON subs.persona_id = p.id",
            "JOIN ml.mailinglists AS lists ON subs.mailinglist_id = lists.id",
            "WHERE subs.is_subscribed = True AND lists.id = %s",
            "AND (NOT ({test}) OR p.is_active = False)")
        ret = {}
        for mailinglist_id in mailinglist_ids:
            data = self.query_all(
                rs, query.format(test=sql_tests[mailinglist_id]),
                (mailinglist_id,))
            ret[mailinglist_id] = tuple(data)
        return ret

    @access("ml")
    def mark_override(self, rs, mailinglist_id, persona_id):
        """Allow non-matching (w.r.t. audience) subscriptions.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type mailinglist_id: int
        :type persona_id: int
        :returns: default return code
        """
        mailinglist_id = affirm("id", mailinglist_id)
        persona_id = affirm("id", persona_id)

        with Atomizer(rs):
            ml = unwrap(self.get_mailinglists(rs, (mailinglist_id,)))
            query = glue("SELECT id FROM ml.subscription_states",
                         "WHERE mailinglist_id = %s AND persona_id = %s")
            current = self.query_one(rs, query, (mailinglist_id, persona_id))
            if not ml['is_active'] or not current:
                return 0
            self.ml_log(rs, const.MlLogCodes.marked_override,
                        mailinglist_id, persona_id=persona_id)
            update = {
                'id': unwrap(current),
                'mailinglist_id': mailinglist_id,
                'persona_id': persona_id,
                'is_override': True
            }
            return self.sql_update(rs, "ml.subscription_states", update)

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
            subscribers = tuple(filter(
                None, self.subscribers(rs, mailinglist_id).values()))
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
            subscribers = tuple(filter(
                None, self.subscribers(rs, mailinglist_id).values()))
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
