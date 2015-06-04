#!/usr/bin/env python3

"""The ml backend provides mailing lists. This provides services to the
event and assembly realm in the form of specific mailing lists.

This has an additional user role ml_script which is intended to be
filled by a mailing list software and not a usual persona. This acts as
if it has moderator privileges for all lists.
"""

from cdedb.backend.uncommon import AbstractUserBackend
from cdedb.backend.common import (
    access, internal_access, make_RPCDaemon, run_RPCDaemon,
    affirm_validation as affirm, affirm_array_validation as affirm_array,
    singularize, BackendUser, BackendRequestState)
from cdedb.common import glue, PrivilegeError, unwrap, MAILINGLIST_FIELDS
from cdedb.config import Config, SecretsConfig
from cdedb.query import QueryOperators
from cdedb.database.connection import Atomizer
import cdedb.database.constants as const
import argparse

class MlBackend(AbstractUserBackend):
    """Take note of the fact that some personas are moderators and thus have
    additional actions available."""
    realm = "ml"
    user_management = {
        "data_table": None,
        "data_fields": None,
        "validator": "persona_data",
        "user_status": const.PersonaStati.ml_user,
    }

    def __init__(self, configpath):
        super().__init__(configpath)
        secrets = SecretsConfig(configpath)
        self.validate_scriptkey = lambda k: k == secrets.ML_SCRIPT_KEY

    def establish(self, sessionkey, method, allow_internal=False):
        if method == "export" and self.validate_scriptkey(sessionkey):
            ## Special case the access of the mailing list software since
            ## it's not tied to an actual persona.
            user = BackendUser(
                persona_id=None, roles={"anonymous", "ml_script"}, realm="ml")
            return BackendRequestState(
                sessionkey, user, self.connpool[self.db_role("cdb_persona")])
        else:
            ret = super().establish(sessionkey, method,
                                    allow_internal=allow_internal)
            if ret and ret.user.is_persona:
                ret.user.moderator = unwrap(self.moderator_infos(
                    ret, (ret.user.persona_id,)))
            return ret

    @classmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

    @staticmethod
    def is_moderator(rs, ml_id=None):
        """Check for moderator privileges as specified in the ml.moderators
        table.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ml_id: int
        :rtype: bool
        """
        return ml_id in rs.user.moderator or "ml_script" in rs.user.roles

    @access("persona")
    @singularize("moderator_info")
    def moderator_infos(self, rs, ids):
        """List mailing lists moderated by specific personas.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int: {int}}
        """
        ids = affirm_array("int", ids)
        data = self.sql_select(
            rs, "ml.moderators", ("persona_id", "mailinglist_id"), ids,
            entity_key="persona_id")
        ret = {}
        for anid in ids:
            ret[anid] = {x['mailinglist_id']
                         for x in data if x['persona_id'] == anid}
        return ret

    @access("ml_user")
    def change_user(self, rs, data):
        return super().change_user(rs, data)

    @access("ml_user")
    @singularize("get_data_one")
    def get_data(self, rs, ids):
        return super().get_data(rs, ids)

    @access("ml_admin")
    def create_user(self, rs, data):
        return super().create_user(rs, data)

    @access("anonymous")
    def genesis_check(self, rs, case_id, secret):
        return super().genesis_check(rs, case_id, secret)

    @access("anonymous")
    def genesis(self, rs, case_id, secret, data):
        return super().genesis(rs, case_id, secret, data)

    def ml_log(self, rs, code, mailinglist_id, persona_id=None,
               additional_info=None):
        """Make an entry in the log.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
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
        new_log = {
            "code": code,
            "mailinglist_id": mailinglist_id,
            "submitted_by": rs.user.persona_id,
            "persona_id": persona_id,
            "additional_info": additional_info,

        }
        return self.sql_insert(rs, "ml.log", new_log)

    @access("ml_user")
    def retrieve_log(self, rs, codes=None, mailinglist_id=None,
                     start=None, stop=None):
        """Get recorded activity.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type codes: [int] or None
        :type mailinglist_id: int or None
        :type start: int or None
        :type stop: int or None
        :rtype: [{str: object}]
        """
        mailinglist_id = affirm("int_or_None", mailinglist_id)
        if not self.is_moderator(rs, mailinglist_id) and not self.is_admin(rs):
            raise PrivilegeError("Not privileged.")
        return self.generic_retrieve_log(
            rs, "enum_mllogcodes", "mailinglist", "ml.log", codes,
            mailinglist_id, start, stop)

    @access("ml_user")
    @singularize("acquire_data_one")
    def acquire_data(self, rs, ids):
        """Return user data sets.

        Since the ml realm does not define any additional attributes this
        delegates to :py:meth:`cdedb.backend.core.CoreBackend.get_data`.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_array("int", ids)
        return self.core.get_data(rs, ids)

    @access("ml_admin")
    def submit_general_query(self, rs, query):
        """Realm specific wrapper around
        :py:meth:`cdedb.backend.common.AbstractBackend.general_query`.`

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type query: :py:class:`cdedb.query.Query`
        :rtype: [{str: object}]
        """
        query = affirm("serialized_query", query)
        if query.scope == "qview_generic_user":
            query.constraints.append(("status", QueryOperators.equal,
                                      const.PersonaStati.ml_user))
            query.spec['status'] = "int"
        else:
            raise RuntimeError("Bad scope.")
        return self.general_query(rs, query)

    @access("ml_user")
    def list_mailinglists(self, rs, status=None, active_only=True):
        """List all mailinglists

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type status: int or None
        :param status: If given, display only mailinglists with audience
          including this status.
        :type active_only: bool
        :param active_only: Toggle wether inactive lists should be included.
        :rtype: {int: str}
        :returns: Mapping of mailinglist ids to titles.
        """
        active_only = affirm("bool", active_only)
        query = "SELECT id, title FROM ml.mailinglists"
        params = []
        if active_only:
            query = glue(query, "WHERE is_active = True")
        if status is not None:
            connector = "AND" if active_only else "WHERE"
            query = glue(query, "{} %s = ANY(audience)".format(connector))
            params.append(status)
        data = self.query_all(rs, query, params)
        return {e['id']: e['title'] for e in data}

    @access("ml_user")
    @singularize("get_mailinglist")
    def get_mailinglists(self, rs, ids):
        """Retrieve data for some mailinglists.

        This provides the following additional attributes:

        * moderators,
        * whitelist.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_array("int", ids)
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
                assert('moderators' not in ret[anid])
                ret[anid]['moderators'] = moderators
            data = self.sql_select(
                rs, "ml.whitelist", ("address", "mailinglist_id"), ids,
                entity_key="mailinglist_id")
            for anid in ids:
                whitelist = {d['address']
                             for d in data if d['mailinglist_id'] == anid}
                assert('whitelist' not in ret[anid])
                ret[anid]['whitelist'] = whitelist
        return ret

    @access("ml_user")
    def set_mailinglist(self, rs, data):
        """Update some keys of a mailinglist.

        If the keys 'moderators' or 'whitelist' are present you have to pass
        the complete set of moderator IDs or whitelisted addresses, which
        will superseed the current list.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str: object}
        :rtype: int
        :returns: default return code
        """
        data = affirm("mailinglist_data", data)
        if not self.is_moderator(rs, data['id']) and not self.is_admin(rs):
            raise PrivilegeError("Not privileged.")
        ret = 1
        with Atomizer(rs):
            mdata = {k: v for k, v in data.items() if k in MAILINGLIST_FIELDS}
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

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str: object}
        :rtype: int
        :returns: the id of the new mailinglist
        """
        data = affirm("mailinglist_data", data, creation=True)
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

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type mailinglist_id: int
        :type cascade: bool
        :param cascade: If False, there must be no references to the list
          first (i.e. there have to be no subscriptions, moderators,
          ...). If True, this function first removes all refering entities.
        :rtype: int
        :returns: default return code
        """
        mailinglist_id = affirm("int", mailinglist_id)
        cascade = affirm("bool", cascade)
        with Atomizer(rs):
            data = unwrap(self.get_mailinglists(rs, (mailinglist_id,)))
            if cascade:
                tables = ("ml.subscription_states", "ml.subscription_requests",
                          "ml.whitelist", "ml.moderators", "ml.log")
                for table in tables:
                    self.sql_delete_one(rs, table, mailinglist_id,
                                        entity_key="mailinglist_id")
            ret = self.sql_delete_one(rs, "ml.mailinglists", mailinglist_id)
            self.ml_log(rs, const.MlLogCodes.list_deleted, mailinglist_id=None,
                        additional_info="{} ({})".format(
                            data['title'], data['address']))
            return ret

    @access("ml_user")
    def subscribers(self, rs, mailinglist_id):
        """Compile a list of subscribers.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type mailinglist_id: int
        :rtype: {int: str}
        :returns: A dict mapping ids of subscribers to their subscribed
          email addresses.
        """
        mailinglist_id = affirm("int", mailinglist_id)
        if not self.is_moderator(rs, mailinglist_id) and not self.is_admin(rs):
            raise PrivilegeError("Not privileged.")
        event_list_query = glue(
            "SELECT DISTINCT regs.persona_id FROM event.registrations AS regs",
            "JOIN event.registration_parts AS parts",
            "ON regs.id = parts.registration_id",
            "WHERE regs.event_id = %s AND parts.status = ANY(%s)")
        ret = {}
        with Atomizer(rs):
            ml_data = unwrap(self.get_mailinglists(rs, (mailinglist_id,)))
            sub_data = self.sql_select(
                rs, "ml.subscription_states",
                ("persona_id", "address", "is_subscribed"), (mailinglist_id,),
                entity_key="mailinglist_id")
            explicits = {e['persona_id']: e['address']
                         for e in sub_data if e['is_subscribed']}
            excludes = {e['persona_id']
                        for e in sub_data if not e['is_subscribed']}
            if ml_data['event_id']:
                if not ml_data['registration_stati']:
                    odata = self.sql_select(
                        rs, "event.orgas", ("persona_id",),
                        (ml_data['event_id'],), entity_key="event_id")
                    ret = {e['persona_id']: None for e in odata}
                else:
                    rdata = self.query_all(rs, event_list_query, (
                        ml_data['event_id'], ml_data['registration_stati']))
                    ret = {e['persona_id']: None for e in rdata}
            elif ml_data['assembly_id']:
                adata = self.sql_select(
                    rs, "assembly.attendees", ("persona_id",),
                    (ml_data['assembly_id'],), entity_key="assembly_id")
                ret = {e['persona_id']: None for e in adata}
            elif const.SubscriptionPolicy(ml_data['sub_policy']).is_additive():
                ## explicits take care of everything
                pass
            else:
                query = glue("SELECT id FROM core.personas",
                             "WHERE status = ANY(%s) AND is_active = True")
                pdata = self.query_all(rs, query, (ml_data['audience'],))
                ret = {e['id']: None for e in pdata}
            ret = {k: v for k, v in ret.items() if k not in excludes}
            ret.update(explicits)
            defaults = tuple(k for k, v in ret.items() if not v)
            udata = self.sql_select(rs, "core.personas",
                                    ("id", "username"), defaults)
            ret.update({e['id']: e['username'] for e in udata})
            return ret

    @access("ml_user")
    def is_subscribed(self, rs, persona_id, mailinglist_id):
        """Sugar coating around :py:meth:`subscriptions`.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type persona_id: int
        :type mailinglist_id: int
        :rtype: bool
        """
        ## validation is done inside
        return bool(self.subscriptions(rs, persona_id, lists=(mailinglist_id,)))

    @access("ml_user")
    def subscriptions(self, rs, persona_id, lists=None):
        """Which lists is a persona subscribed to.

        .. note:: For lists associated to an event or an assembly this is
          somewhat expensive. This is alleviated by the possibility to
          restrict the lookup to a subset of all lists.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type persona_id: int
        :type lists: [int] or None
        :param lists: If given check only these lists.
        :rtype: {int: str or None}
        :returns: A dict mapping each mailing list to the address the
          persona is subscribed with or None, if no explicit address was
          given, meaning the username is used.
        """
        persona_id = affirm("int", persona_id)
        lists = affirm_array("int", lists, allow_None=True)
        if (persona_id != rs.user.persona_id
                and not self.is_admin(rs)
                and not all(self.is_moderator(rs, anid) for anid in lists)):
            raise PrivilegeError("Not privileged.")
        event_list_query = glue(
            "SELECT DISTINCT regs.persona_id FROM event.registrations AS regs",
            "JOIN event.registration_parts AS parts",
            "ON regs.id = parts.registration_id",
            "WHERE regs.event_id = %s AND parts.status = ANY(%s)",
            "AND regs.persona_id = %s")
        ret = {}
        with Atomizer(rs):
            lists = lists or self.list_mailinglists(rs)
            ml_data = self.get_mailinglists(rs, lists)
            sub_data = {e['mailinglist_id']: e for e in self.sql_select(
                rs, "ml.subscription_states",
                ("persona_id", "mailinglist_id", "address", "is_subscribed"),
                (persona_id,), entity_key="persona_id")}
            for mailinglist_id in ml_data:
                if mailinglist_id in sub_data:
                    this_data = sub_data[mailinglist_id]
                    if this_data['is_subscribed']:
                        ret[mailinglist_id] = this_data['address']
                else:
                    this_ml = ml_data[mailinglist_id]
                    if this_ml['event_id']:
                        if not this_ml['registration_stati']:
                            query = glue(
                                "SELECT persona_id FROM event.orgas",
                                "WHERE event_id = %s AND persona_id = %s")
                            odata = self.query_one(rs, query, (
                                this_ml['event_id'], persona_id))
                            if odata:
                                ret[mailinglist_id] = None
                        else:
                            rdata = self.query_one(rs, event_list_query, (
                                this_ml['event_id'],
                                this_ml['registration_stati'], persona_id))
                            if rdata:
                                ret[mailinglist_id] = None
                    elif this_ml['assembly_id']:
                        query = glue(
                            "SELECT persona_id FROM assembly.attendees",
                            "WHERE assembly_id = %s AND persona_id = %s")
                        adata = self.query_one(rs, query, (
                            this_ml['assembly_id'], persona_id))
                        if adata:
                            ret[mailinglist_id] = None
                    elif not const.SubscriptionPolicy(
                            this_ml['sub_policy']).is_additive():
                        ret[mailinglist_id] = None
            return ret

    def write_subscription_state(self, rs, mailinglist_id, persona_id,
                                 is_subscribed, address):
        """Helper to persist a (un)subscription.

        We want to update existing infos instead of simply deleting all
        existing infos and inserting new ones. Thus this helper.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
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
            data = self.query_one(rs, query, (mailinglist_id, persona_id))
            new_data = {
                'mailinglist_id': mailinglist_id,
                'persona_id': persona_id,
                'is_subscribed': is_subscribed,
                'address': address,
            }
            if data is None:
                return self.sql_insert(rs, "ml.subscription_states", new_data)
            else:
                new_data['id'] = unwrap(data)
                return self.sql_update(rs, "ml.subscription_states", new_data)

    @access("ml_user")
    def change_subscription_state(self, rs, mailinglist_id, persona_id,
                                  subscribe, address=None):
        """Alter any piece of a subscription.

        This also handles unsubscriptions, changing of addresses with which
        a persona is subscribed and subscription requests for lists with
        moderated opt-in.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type mailinglist_id: int
        :type persona_id: int
        :type subscribe: bool
        :param subscribe: The target state, which need not differ from the
          current state.
        :type address: str or None
        :rtype: int
        :returns: default return code
        """
        mailinglist_id = affirm("int", mailinglist_id)
        persona_id = affirm("int", persona_id)
        subscribe = affirm("bool", subscribe)
        address = affirm("email_or_None", address)
        if (persona_id != rs.user.persona_id
                and not self.is_moderator(rs, mailinglist_id)
                and not self.is_admin(rs)):
            raise PrivilegeError("Not privileged.")

        privileged = self.is_moderator(rs, mailinglist_id) or self.is_admin(rs)
        with Atomizer(rs):
            ml_data = unwrap(self.get_mailinglists(rs, (mailinglist_id,)))
            if not privileged and not ml_data['is_active']:
                return 0
            if self.is_subscribed(rs, persona_id, mailinglist_id) == subscribe:
                self.ml_log(rs, const.MlLogCodes.subscription_changed,
                            mailinglist_id, persona_id=persona_id,
                            additional_info=address)
                return self.write_subscription_state(
                    rs, mailinglist_id, persona_id, subscribe, address)
            gateway = False
            if subscribe and ml_data['gateway']:
                gateway = self.is_subscribed(rs, persona_id, ml_data['gateway'])
            policy = const.SubscriptionPolicy
            if (subscribe and not privileged and not gateway
                    and ml_data['sub_policy'] == policy.moderated_opt_in):
                query = glue("SELECT id FROM ml.subscription_requests",
                             "WHERE mailinglist_id = %s AND persona_id = %s")
                rdata = self.query_one(rs, query, (mailinglist_id, persona_id))
                if rdata:
                    return 0
                self.ml_log(rs, const.MlLogCodes.subscription_requested,
                            mailinglist_id, persona_id=persona_id)
                request = {
                    'mailinglist_id': mailinglist_id,
                    'persona_id': persona_id,
                }
                return -self.sql_insert(rs, "ml.subscription_requests", request)
            if (policy(ml_data['sub_policy']).privileged_transition(subscribe)
                    and not privileged and not gateway):
                raise PrivilegeError("Must be moderator.")
            if subscribe:
                code = const.MlLogCodes.subscribed
            else:
                code = const.MlLogCodes.unsubscribed
            self.ml_log(rs, code, mailinglist_id, persona_id=persona_id)
            return self.write_subscription_state(rs, mailinglist_id, persona_id,
                                                 subscribe, address)

    @access("ml_user")
    def list_requests(self, rs, mailinglist_id):
        """Retrieve open subscription requests.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type mailinglist_id: int
        :rtype: [int]
        :returns: personas waiting for subscription
        """
        mailinglist_id = affirm("int", mailinglist_id)
        if not self.is_moderator(rs, mailinglist_id) and not self.is_admin(rs):
            raise PrivilegeError("Not privileged.")

        data = self.sql_select(
            rs, "ml.subscription_requests", ("persona_id",),
            (mailinglist_id,), entity_key="mailinglist_id")
        return tuple(e['persona_id'] for e in data)

    @access("ml_user")
    def decide_request(self, rs, mailinglist_id, persona_id, ack):
        """Moderate subscription to an opt-in list.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type mailinglist_id: int
        :type persona_id: int
        :type ack: bool
        :rtype: int
        :returns: default return code
        """
        mailinglist_id = affirm("int", mailinglist_id)
        persona_id = affirm("int", persona_id)
        ack = affirm("bool", ack)
        if not self.is_moderator(rs, mailinglist_id) and not self.is_admin(rs):
            raise PrivilegeError("Not privileged.")

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

    @access("ml_admin")
    @singularize("check_states_one")
    def check_states(self, rs, mailinglist_ids):
        """Verify that all explicit subscriptions are by the target audience.

        A persona may change state or may be subscribed by a moderated
        even if she is not in the target audience. Since defending
        against the first case is rather complicated, we choose to offer
        the means of verification afterwards.

        This also checks for inactive accounts which are subscribed to a
        list.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type mailinglist_ids: [int]
        :rtype: {int: [int]}
        :returns: A dict mapping list ids to offending personas.
        """
        mailinglist_ids = affirm_array("int", mailinglist_ids)

        query = glue(
            "SELECT subs.mailinglist_id, subs.persona_id",
            "FROM ml.subscription_states AS subs",
            "JOIN core.personas AS p ON subs.persona_id = p.id",
            "JOIN ml.mailinglists AS lists ON subs.mailinglist_id = lists.id",
            "WHERE subs.is_subscribed = True",
            "AND lists.id = ANY(%s)",
            "AND (NOT (p.status = ANY(lists.audience)) OR p.is_active = False)")
        data = self.query_all(rs, query, (mailinglist_ids,))
        return {mailinglist_id: tuple(e['persona_id'] for e in data
                                      if e['mailinglist_id'] == mailinglist_id)
                for mailinglist_id in mailinglist_ids}

    @access("ml_script")
    def export(self, rs, mailinglist_id):
        """TODO"""
        # omit subscriptions with empty email addresses (may happen in
        # reality, because username was deleted because of bouncing mail)
        raise NotImplementedError("TODO")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Run CdEDB Backend for mailinglist services.')
    parser.add_argument('-c', default=None, metavar='/path/to/config',
                        dest="configpath")
    args = parser.parse_args()
    ml_backend = MlBackend(args.configpath)
    conf = Config(args.configpath)
    ml_server = make_RPCDaemon(ml_backend, conf.ML_SOCKET,
                               access_log=conf.ML_ACCESS_LOG)
    run_RPCDaemon(ml_server, conf.ML_STATE_FILE)
