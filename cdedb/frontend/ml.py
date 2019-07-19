#!/usr/bin/env python3

"""Services for the ml realm."""

import copy
import collections
import werkzeug

from cdedb.frontend.common import (
    REQUESTdata, REQUESTdatadict, access, csv_output, periodic,
    check_validation as check, mailinglist_guard, query_result_to_json)
from cdedb.frontend.uncommon import AbstractUserFrontend
from cdedb.query import QUERY_SPECS, mangle_query_input
from cdedb.common import  n_, name_key, merge_dicts, ProxyShim
import cdedb.database.constants as const
from cdedb.database.constants import (
    SubscriptionStates as SS, SubscriptionPolicy as SP)
from cdedb.backend.event import EventBackend
from cdedb.backend.assembly import AssemblyBackend
from cdedb.backend.ml import MlBackend
from cdedb.config import SecretsConfig


class MlFrontend(AbstractUserFrontend):
    """Manage mailing lists which will be run by an external software."""
    realm = "ml"
    user_management = {
        "persona_getter": lambda obj: obj.coreproxy.get_ml_user,
    }

    def __init__(self, configpath):
        super().__init__(configpath)
        self.eventproxy = ProxyShim(EventBackend(configpath))
        self.mlproxy = ProxyShim(MlBackend(configpath))
        self.assemblyproxy = ProxyShim(AssemblyBackend(configpath))
        secrets = SecretsConfig(configpath)
        self.validate_scriptkey = lambda k: k == secrets.ML_SCRIPT_KEY

    def finalize_session(self, rs, connpool, auxilliary=False):
        super().finalize_session(rs, connpool, auxilliary=auxilliary)
        if self.validate_scriptkey(rs.scriptkey):
            # Special case the access of the mailing list software since
            # it's not tied to an actual persona. Note that this is not
            # affected by the LOCKDOWN configuration.
            rs.user.roles.add("ml_script")
            # Upgrade db connection
            rs._conn = connpool["cdb_persona"]
        if "ml" in rs.user.roles:
            rs.user.moderator = self.mlproxy.moderator_info(rs,
                                                            rs.user.persona_id)

    @classmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

    @access("ml")
    def index(self, rs):
        """Render start page."""
        policies = const.AudiencePolicy.applicable(rs.user.roles)
        mailinglists = self.mlproxy.list_mailinglists(
            rs, audience_policies=policies)
        mailinglist_infos = self.mlproxy.get_mailinglists(rs, mailinglists)
        subscriptions = self.mlproxy.get_subscriptions(
            rs, rs.user.persona_id, states=SS.subscribing_states())
        return self.render(rs, "index", {
            'mailinglists': mailinglists, 'subscriptions': subscriptions,
            'mailinglist_infos': mailinglist_infos})

    @access("ml_admin")
    def create_user_form(self, rs):
        defaults = {
            'is_member': False,
            'bub_search': False,
        }
        merge_dicts(rs.values, defaults)
        return super().create_user_form(rs)

    @access("ml_admin", modi={"POST"})
    @REQUESTdatadict(
        "given_names", "family_name", "display_name", "notes", "username")
    def create_user(self, rs, data):
        defaults = {
            'is_cde_realm': False,
            'is_event_realm': False,
            'is_ml_realm': True,
            'is_assembly_realm': False,
            'is_active': True,
        }
        data.update(defaults)
        return super().create_user(rs, data)

    @access("ml_admin")
    @REQUESTdata(("download", "str_or_None"), ("is_search", "bool"))
    def user_search(self, rs, download, is_search):
        """Perform search."""
        spec = copy.deepcopy(QUERY_SPECS['qview_persona'])
        # mangle the input, so we can prefill the form
        query_input = mangle_query_input(rs, spec)
        if is_search:
            query = check(rs, "query_input", query_input, "query",
                          spec=spec, allow_empty=False)
        else:
            query = None
        default_queries = self.conf.DEFAULT_QUERIES['qview_ml_user']
        params = {
            'spec': spec, 'default_queries': default_queries, 'choices': {},
            'choices_lists': {}, 'query': query}
        # Tricky logic: In case of no validation errors we perform a query
        if not rs.errors and is_search:
            query.scope = "qview_persona"
            result = self.mlproxy.submit_general_query(rs, query)
            params['result'] = result
            if download:
                fields = []
                for csvfield in query.fields_of_interest:
                    fields.extend(csvfield.split(','))
                if download == "csv":
                    csv_data = csv_output(result, fields)
                    return self.send_csv_file(
                        rs, data=csv_data, inline=False,
                        filename="user_search_result.csv")
                elif download == "json":
                    json_data = query_result_to_json(result, fields)
                    return self.send_file(
                        rs, data=json_data, inline=False,
                        filename="user_search_result.json")
        else:
            rs.values['is_search'] = is_search = False
        return self.render(rs, "user_search", params)

    @access("ml_admin")
    def list_mailinglists(self, rs):
        """Show all mailinglists."""
        mailinglists = self.mlproxy.list_mailinglists(rs, active_only=False)
        mailinglist_infos = self.mlproxy.get_mailinglists(rs, mailinglists)
        subscriptions = self.mlproxy.get_subscriptions(
            rs, rs.user.persona_id, states=SS.subscribing_states())
        events = self.eventproxy.list_db_events(rs)
        assemblies = self.assemblyproxy.list_assemblies(rs)
        for mailinglist_id in mailinglists:
            subs = self.mlproxy.get_subscription_states(
                rs, mailinglist_id, states=SS.subscribing_states())
            mailinglist_infos[mailinglist_id]['num_subscribers'] = len(subs)
        return self.render(rs, "list_mailinglists", {
            'mailinglists': mailinglists, 'subscriptions': subscriptions,
            'mailinglist_infos': mailinglist_infos, 'events': events,
            'assemblies': assemblies})

    @access("ml_admin")
    def create_mailinglist_form(self, rs):
        """Render form."""
        mailinglists = self.mlproxy.list_mailinglists(rs)
        sorted_mailinglists = sorted([(k, v) for k, v in mailinglists.items()],
                                     key=lambda x: x[1])
        events = self.eventproxy.list_db_events(rs)
        sorted_events = sorted([(k, v) for k, v in events.items()],
                               key=lambda x: x[1])
        assemblies = self.assemblyproxy.list_assemblies(rs)
        sorted_assemblies = sorted([(k, v["title"]) for k, v in assemblies.items()],
                                   key=lambda x: x[1])
        return self.render(rs, "create_mailinglist", {
            'sorted_mailinglists': sorted_mailinglists,
            'sorted_events': sorted_events,
            'sorted_assemblies': sorted_assemblies})

    @access("ml_admin", modi={"POST"})
    @REQUESTdatadict(
        "title", "address", "description", "sub_policy", "mod_policy",
        "attachment_policy", "audience_policy", "subject_prefix", "maxsize",
        "is_active", "notes", "event_id", "registration_stati",
        "assembly_id")
    def create_mailinglist(self, rs, data):
        """Make a new list."""
        data = check(rs, "mailinglist", data, creation=True)
        if rs.errors:
            return self.create_mailinglist_form(rs)

        new_id = self.mlproxy.create_mailinglist(rs, data)
        self.notify_return_code(rs, new_id)
        return self.redirect(rs, "ml/show_mailinglist", {
            'mailinglist_id': new_id})

    @access("ml_admin")
    @REQUESTdata(("codes", "[int]"), ("mailinglist_id", "id_or_None"),
                 ("persona_id", "cdedbid_or_None"),
                 ("submitted_by", "cdedbid_or_None"),
                 ("additional_info", "str_or_None"),
                 ("start", "non_negative_int_or_None"),
                 ("stop", "non_negative_int_or_None"),
                 ("time_start", "datetime_or_None"),
                 ("time_stop", "datetime_or_None"))
    def view_log(self, rs, codes, mailinglist_id, start, stop, persona_id,
                 submitted_by, additional_info, time_start, time_stop):
        """View activities."""
        start = start or 0
        stop = stop or 50
        # no validation since the input stays valid, even if some options
        # are lost
        log = self.mlproxy.retrieve_log(
            rs, codes, mailinglist_id, start, stop, persona_id=persona_id,
            submitted_by=submitted_by, additional_info=additional_info,
            time_start=time_start, time_stop=time_stop)
        persona_ids = (
                {entry['submitted_by'] for entry in log if
                 entry['submitted_by']}
                | {entry['persona_id'] for entry in log if entry['persona_id']})
        personas = self.coreproxy.get_personas(rs, persona_ids)
        mailinglist_ids = {entry['mailinglist_id']
                           for entry in log if entry['mailinglist_id']}
        mailinglists = self.mlproxy.get_mailinglists(rs, mailinglist_ids)
        all_mailinglists = self.mlproxy.list_mailinglists(rs, active_only=False)
        return self.render(rs, "view_log", {
            'log': log, 'personas': personas,
            'mailinglists': mailinglists, 'all_mailinglists': all_mailinglists})

    @access("ml")
    def show_mailinglist(self, rs, mailinglist_id):
        """Details of a list."""
        ml = rs.ambience['mailinglist']
        state = self.mlproxy.get_subscription(
            rs, rs.user.persona_id, mailinglist_id=mailinglist_id)

        if not self.mlproxy.may_view(rs, ml, state):
            return werkzeug.exceptions.Forbidden()

        sub_address = None
        if state and state.is_subscribed:
            sub_address = self.mlproxy.get_subscription_address(
                rs, mailinglist_id, rs.user.persona_id, explicits_only=True)

        event = {}
        if ml['event_id']:
            event = self.eventproxy.get_event(rs, ml['event_id'])
            is_registered = bool(self.eventproxy.list_registrations(
                rs, event['id'], rs.user.persona_id))
            event['is_visible'] = (
                    "event_admin" in rs.user.roles
                    or rs.user.persona_id in event['orgas']
                    or (event['is_open'] and event['is_visible'])
                    or is_registered)

        assembly = {}
        if ml['assembly_id']:
            assembly = self.assemblyproxy.get_assembly(rs, ml['assembly_id'])
            is_attending = bool(self.assemblyproxy.does_attend(
                rs, assembly_id=assembly['id']))
            assembly['is_visible'] = (
                    "assembly_admin" in rs.user.roles
                    or "member" in rs.user.roles
                    or is_attending)

        may_subscribe = self.mlproxy.may_subscribe(rs, rs.user.persona_id,
                                                   mailinglist=ml)
        personas = self.coreproxy.get_personas(rs, ml['moderators'])
        moderators = collections.OrderedDict(
            (anid, personas[anid]) for anid in sorted(
                personas, key=lambda anid: name_key(personas[anid])))

        return self.render(rs, "show_mailinglist", {
            'sub_address': sub_address, 'state': state,
            'may_subscribe': may_subscribe, 'event': event,
            'assembly': assembly, 'moderators': moderators})

    @access("ml")
    @mailinglist_guard()
    def change_mailinglist_form(self, rs, mailinglist_id):
        """Render form."""
        mailinglists = self.mlproxy.list_mailinglists(rs)
        sorted_mailinglists = sorted([(k, v) for k, v in mailinglists.items()],
                                     key=lambda x: x[1])
        events = self.eventproxy.list_db_events(rs)
        sorted_events = sorted([(k, v) for k, v in events.items()],
                               key=lambda x: x[1])
        assemblies = self.assemblyproxy.list_assemblies(rs)
        sorted_assemblies = sorted(
            [(k, v["title"]) for k, v in assemblies.items()],
            key=lambda x: x[1])
        merge_dicts(rs.values, rs.ambience['mailinglist'])
        if not self.is_admin(rs):
            rs.notify("info",
                      n_("Only Admins may change mailinglist configuration."))
        return self.render(rs, "change_mailinglist", {
            'sorted_mailinglists': sorted_mailinglists,
            'sorted_events': sorted_events,
            'sorted_assemblies': sorted_assemblies})

    @access("ml_admin", modi={"POST"})
    @REQUESTdata(("audience_policy", "enum_audiencepolicy"),
                 ("registration_stati", "[enum_registrationpartstati]"))
    @REQUESTdatadict(
        "title", "address", "description", "sub_policy", "mod_policy",
        "notes", "attachment_policy", "subject_prefix", "maxsize",
        "is_active", "event_id", "assembly_id")
    def change_mailinglist(self, rs, mailinglist_id, audience_policy,
                           registration_stati, data):
        """Modify simple attributes of mailinglists."""
        data['id'] = mailinglist_id
        data['audience_policy'] = audience_policy
        data['registration_stati'] = registration_stati
        data = check(rs, "mailinglist", data)
        if rs.errors:
            return self.change_mailinglist_form(rs, mailinglist_id)
        code = self.mlproxy.set_mailinglist(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "ml/show_mailinglist")

    @access("ml_admin", modi={"POST"})
    @REQUESTdata(("ack_delete", "bool"))
    def delete_mailinglist(self, rs, mailinglist_id, ack_delete):
        """Remove a mailinglist."""
        if not ack_delete:
            rs.errors.append(("ack_delete", ValueError(n_("Must be checked."))))
        if rs.errors:
            return self.management(rs, mailinglist_id)

        code = self.mlproxy.delete_mailinglist(
            rs, mailinglist_id, cascade={"subscriptions", "log", "addresses",
                                         "whitelist", "moderators"})

        self.notify_return_code(rs, code)
        return self.redirect(rs, "ml/list_mailinglists")

    @access("ml")
    @REQUESTdata(("codes", "[int]"), ("start", "non_negative_int_or_None"),
                 ("persona_id", "cdedbid_or_None"),
                 ("submitted_by", "cdedbid_or_None"),
                 ("additional_info", "str_or_None"),
                 ("stop", "non_negative_int_or_None"),
                 ("time_start", "datetime_or_None"),
                 ("time_stop", "datetime_or_None"))
    @mailinglist_guard()
    def view_ml_log(self, rs, mailinglist_id, codes, start, stop, persona_id,
                    submitted_by, additional_info, time_start, time_stop):
        """View activities pertaining to one list."""
        start = start or 0
        stop = stop or 50
        # no validation since the input stays valid, even if some options
        # are lost
        log = self.mlproxy.retrieve_log(
            rs, codes, mailinglist_id, start, stop, persona_id=persona_id,
            submitted_by=submitted_by, additional_info=additional_info,
            time_start=time_start, time_stop=time_stop)
        persona_ids = (
                {entry['submitted_by'] for entry in log if
                 entry['submitted_by']}
                | {entry['persona_id'] for entry in log if entry['persona_id']})
        personas = self.coreproxy.get_personas(rs, persona_ids)
        return self.render(rs, "view_ml_log", {
            'log': log, 'personas': personas,
        })

    @access("ml")
    @mailinglist_guard()
    def management(self, rs, mailinglist_id):
        """Render form."""
        subscribers = self.mlproxy.get_subscription_states(
            rs, mailinglist_id, states=SS.subscribing_states())
        requests = self.mlproxy.get_subscription_states(
            rs, mailinglist_id, states=(SS.pending,))
        persona_ids = (set(rs.ambience['mailinglist']['moderators'])
                       | set(subscribers.keys()) | set(requests))
        personas = self.coreproxy.get_personas(rs, persona_ids)
        subscribers = collections.OrderedDict(
            (anid, personas[anid]) for anid in sorted(
                subscribers, key=lambda anid: name_key(personas[anid])))
        moderators = collections.OrderedDict(
            (anid, personas[anid]) for anid in sorted(
                rs.ambience['mailinglist']['moderators'],
                key=lambda anid: name_key(personas[anid])))
        requests = collections.OrderedDict(
            (anid, personas[anid]) for anid in sorted(
             requests, key=lambda anid: name_key(personas[anid])))
        return self.render(rs, "management", {
            'subscribers': subscribers, 'requests': requests,
            'moderators': moderators})

    @access("ml")
    @mailinglist_guard()
    def show_subscription_details(self, rs, mailinglist_id):
        """Render form."""
        mod_subscribed = self.mlproxy.get_subscription_states(
            rs, mailinglist_id, states=(SS.mod_subscribed,))
        mod_unsubscribed = self.mlproxy.get_subscription_states(
            rs, mailinglist_id, states=(SS.mod_unsubscribed,))
        persona_ids = (set(rs.ambience['mailinglist']['moderators'])
                       | set(mod_subscribed.keys()) | set(mod_unsubscribed))
        personas = self.coreproxy.get_personas(rs, persona_ids)
        mod_subscribed = collections.OrderedDict(
            (anid, personas[anid]) for anid in sorted(
                mod_subscribed, key=lambda anid: name_key(personas[anid])))
        mod_unsubscribed = collections.OrderedDict(
            (anid, personas[anid]) for anid in sorted(
                mod_unsubscribed, key=lambda anid: name_key(personas[anid])))
        return self.render(rs, "show_subscription_details", {
            'mod_subscribed': mod_subscribed,
            'mod_unsubscribed': mod_unsubscribed})

    @access("ml", modi={"POST"})
    @REQUESTdata(("moderator_id", "cdedbid"))
    @mailinglist_guard()
    def add_moderator(self, rs, mailinglist_id, moderator_id):
        """Promote persona to moderator."""
        if rs.errors:
            return self.management(rs, mailinglist_id)
        data = {
            'id': mailinglist_id,
            'moderators': (set(rs.ambience['mailinglist']['moderators'])
                           | {moderator_id}),
        }
        code = self.mlproxy.set_mailinglist(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "ml/management")

    @access("ml", modi={"POST"})
    @REQUESTdata(("moderator_id", "id"))
    @mailinglist_guard()
    def remove_moderator(self, rs, mailinglist_id, moderator_id):
        """Demote persona from moderator status."""
        if rs.errors:
            return self.management(rs, mailinglist_id)
        if moderator_id == rs.user.persona_id and not self.is_admin(rs):
            rs.notify("error",
                      n_("Not allowed to remove yourself as moderator."))
            return self.management(rs, mailinglist_id)
        data = {
            'id': mailinglist_id,
            'moderators': (set(rs.ambience['mailinglist']['moderators'])
                           - {moderator_id}),
        }
        code = self.mlproxy.set_mailinglist(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "ml/management")

    @access("ml", modi={"POST"})
    @REQUESTdata(("email", "email"))
    @mailinglist_guard()
    def add_whitelist(self, rs, mailinglist_id, email):
        """Allow address to write to the list."""
        if rs.errors:
            return self.show_subscription_details(rs, mailinglist_id)
        data = {
            'id': mailinglist_id,
            'whitelist': set(rs.ambience['mailinglist']['whitelist']) | {email},
        }
        code = self.mlproxy.set_mailinglist(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "ml/show_subscription_details")

    @access("ml", modi={"POST"})
    @REQUESTdata(("email", "email"))
    @mailinglist_guard()
    def remove_whitelist(self, rs, mailinglist_id, email):
        """Withdraw privilege of writing to list."""
        if rs.errors:
            return self.show_subscription_details(rs, mailinglist_id)
        data = {
            'id': mailinglist_id,
            'whitelist': set(rs.ambience['mailinglist']['whitelist']) - {email},
        }
        code = self.mlproxy.set_mailinglist(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "ml/show_subscription_details")

    @access("ml", modi={"POST"})
    @REQUESTdata(("persona_id", "id"),
                 ("resolution", "enum_subscriptionrequestresolutions"))
    @mailinglist_guard()
    def decide_request(self, rs, mailinglist_id, persona_id, resolution):
        """Evaluate whether to admit subscribers."""
        if rs.errors:
            return self.management(rs, mailinglist_id)
        datum = {
            'mailinglist_id': mailinglist_id,
            'persona_id': persona_id,
            'resolution': resolution,
        }
        code = self.mlproxy.decide_subscription_request(rs, datum)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "ml/management")

    @access("ml", modi={"POST"})
    @REQUESTdata(("subscriber_id", "cdedbid"))
    @mailinglist_guard()
    def add_subscriber(self, rs, mailinglist_id, subscriber_id):
        """Administratively subscribe somebody."""
        if rs.errors:
            return self.management(rs, mailinglist_id)
        code, msg = self.mlproxy.add_subscriber(
            rs, mailinglist_id, subscriber_id)
        self.notify_return_code(rs, code, error=msg, pending=msg)
        return self.redirect(rs, "ml/management")

    @access("ml", modi={"POST"})
    @REQUESTdata(("subscriber_id", "id"))
    @mailinglist_guard()
    def remove_subscriber(self, rs, mailinglist_id, subscriber_id):
        """Administratively unsubscribe somebody."""
        if rs.errors:
            return self.management(rs, mailinglist_id)
        code, msg = self.mlproxy.remove_subscriber(
            rs, mailinglist_id, subscriber_id)
        self.notify_return_code(rs, code, error=msg, pending=msg)
        return self.redirect(rs, "ml/management")

    @access("ml", modi={"POST"})
    @REQUESTdata(("subscriber_id", "cdedbid"))
    @mailinglist_guard()
    def add_mod_subscriber(self, rs, mailinglist_id, subscriber_id):
        """Administratively subscribe somebody with moderator override."""
        if rs.errors:
            return self.show_subscription_details(rs, mailinglist_id)
        code, error = self.mlproxy.add_mod_subscriber(
            rs, mailinglist_id, subscriber_id)
        self.notify_return_code(rs, code, error=error)
        return self.redirect(rs, "ml/show_subscription_details")

    @access("ml", modi={"POST"})
    @REQUESTdata(("subscriber_id", "id"))
    @mailinglist_guard()
    def remove_mod_subscriber(self, rs, mailinglist_id, subscriber_id):
        """Administratively remove subscribe somebody with moderator override."""
        if rs.errors:
            return self.show_subscription_details(rs, mailinglist_id)
        code, error = self.mlproxy.remove_mod_subscriber(
            rs, mailinglist_id, subscriber_id)
        self.notify_return_code(rs, code, error=error)
        return self.redirect(rs, "ml/show_subscription_details")

    @access("ml", modi={"POST"})
    @REQUESTdata(("subscriber_id", "cdedbid"))
    @mailinglist_guard()
    def add_mod_unsubscriber(self, rs, mailinglist_id, subscriber_id):
        """Administratively block somebody."""
        if rs.errors:
            return self.show_subscription_details(rs, mailinglist_id)
        code, error = self.mlproxy.add_mod_unsubscriber(
            rs, mailinglist_id, subscriber_id)
        self.notify_return_code(rs, code, error=error)
        return self.redirect(rs, "ml/show_subscription_details")

    @access("ml", modi={"POST"})
    @REQUESTdata(("subscriber_id", "id"))
    @mailinglist_guard()
    def remove_mod_unsubscriber(self, rs, mailinglist_id, subscriber_id):
        """Administratively remove block."""
        if rs.errors:
            return self.show_subscription_details(rs, mailinglist_id)
        code, error = self.mlproxy.remove_mod_unsubscriber(
            rs, mailinglist_id, subscriber_id)
        self.notify_return_code(rs, code, error=error)
        return self.redirect(rs, "ml/show_subscription_details")


    @access("ml", modi={"POST"})
    def subscribe(self, rs, mailinglist_id):
        """Change own subscription state to subscribed or pending."""
        if rs.errors:
            return self.show_mailinglist(rs, mailinglist_id)
        code = self.mlproxy.subscribe(rs, mailinglist_id)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "ml/show_mailinglist")

    @access("ml", modi={"POST"})
    def request_subscription(self, rs, mailinglist_id):
        """Change own subscription state to subscribed or pending."""
        if rs.errors:
            return self.show_mailinglist(rs, mailinglist_id)
        code = self.mlproxy.request_subscription(rs, mailinglist_id)
        self.notify_return_code(rs, code,
            success="Subscription request awaits moderation.")
        return self.redirect(rs, "ml/show_mailinglist")

    @access("ml", modi={"POST"})
    def unsubscribe(self, rs, mailinglist_id):
        """Change own subscription state to unsubscribed."""
        if rs.errors:
            return self.show_mailinglist(rs, mailinglist_id)
        code = self.mlproxy.unsubscribe(rs, mailinglist_id)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "ml/show_mailinglist")

    @access("ml", modi={"POST"})
    def cancel_subscription(self, rs, mailinglist_id):
        """Cancel subscription request."""
        if rs.errors:
            return self.show_mailinglist(rs, mailinglist_id)
        code = self.mlproxy.cancel_subscription(rs, mailinglist_id)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "ml/show_mailinglist")

    @access("ml", modi={"POST"})
    @REQUESTdata(("email", "email_or_None"))
    def change_address(self, rs, mailinglist_id, email):
        """Modify address to which emails are delivered for this list.

        If this address has not been used before, we verify it.
        """
        if rs.errors:
            return self.show_mailinglist(rs, mailinglist_id)
        is_subscribed = self.mlproxy.is_subscribed(
            rs, rs.user.persona_id, mailinglist_id)
        if not is_subscribed:
            rs.notify("error", n_("Not subscribed."))
            return self.redirect(rs, "ml/show_mailinglist")
        policy = const.SubscriptionPolicy(
            rs.ambience['mailinglist']['sub_policy'])
        if email and policy == SP.mandatory:
            rs.notify("warning", n_("Disallowed to change address."))
            return self.redirect(rs, "ml/show_mailinglist")

        subscriptions = self.mlproxy.get_persona_addresses(rs)
        datum = {
            'mailinglist_id': mailinglist_id,
            'persona_id': rs.user.persona_id,
        }

        if not email:
            code = self.mlproxy.remove_subscription_address(rs, datum)
            self.notify_return_code(rs, code)
        elif email in subscriptions.values():
            datum['address'] = email
            code = self.mlproxy.set_subscription_address(rs, datum)
            self.notify_return_code(rs, code)
        else:
            self.do_mail(
                rs, "confirm_address",
                {'To': (email,),
                 'Subject': "E-Mail-Adresse für Mailingliste bestätigen"},
                {'email': self.encode_parameter(
                    "ml/do_address_change", "email", email)})
            rs.notify("info", n_("Confirmation email sent."))
        return self.redirect(rs, "ml/show_mailinglist")

    @access("ml")
    @REQUESTdata(("email", "#email"))
    def do_address_change(self, rs, mailinglist_id, email):
        """Successful verification for new address in :py:meth:`change_address`.

        This is not a POST since the link is shared via email.
        """
        if rs.errors:
            return self.show_mailinglist(rs, mailinglist_id)
        is_subscribed = self.mlproxy.is_subscribed(rs, rs.user.persona_id,
                                                   mailinglist_id)
        if not is_subscribed:
            rs.notify("error", n_("Not subscribed."))
            return self.redirect(rs, "ml/show_mailinglist")
        policy = const.SubscriptionPolicy(
            rs.ambience['mailinglist']['sub_policy'])
        if policy == SP.mandatory:
            rs.notify("warning", n_("Disallowed to change address."))
            return self.redirect(rs, "ml/show_mailinglist")

        datum = {
            'mailinglist_id': mailinglist_id,
            'persona_id': rs.user.persona_id,
            'address': email,
        }
        code = self.mlproxy.set_subscription_address(rs, datum)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "ml/show_mailinglist")

    @periodic("write_subscription_states")
    def write_subscription_states(self, rs, store):
        """Write the current state of implicit subscribers to the database."""
        mailinglist_ids = self.mlproxy.list_mailinglists(rs)

        for ml_id in mailinglist_ids:
            self.mlproxy.write_subscription_states(rs, ml_id)

        return store

    @access("ml_script")
    def export_overview(self, rs):
        """Provide listing for mailinglist software"""
        if rs.errors:
            return self.send_json(rs, {'error': tuple(map(str, rs.errors))})
        return self.send_json(rs, self.mlproxy.export_overview(rs))

    @access("ml_script")
    @REQUESTdata(("address", "email"))
    def export_one(self, rs, address):
        """Provide specific infos for mailinglist software"""
        if rs.errors:
            return self.send_json(rs, {'error': tuple(map(str, rs.errors))})
        return self.send_json(rs, self.mlproxy.export_one(rs, address))

    @access("ml_script")
    def oldstyle_mailinglist_config_export(self, rs):
        """Provide listing for comptability mailinglist software"""
        if rs.errors:
            return self.send_json(rs, {'error': tuple(map(str, rs.errors))})
        return self.send_json(
            rs, self.mlproxy.oldstyle_mailinglist_config_export(rs))

    @access("ml_script")
    @REQUESTdata(("address", "email"))
    def oldstyle_mailinglist_export(self, rs, address):
        """Provide specific infos for comptability mailinglist software"""
        if rs.errors:
            return self.send_json(rs, {'error': tuple(map(str, rs.errors))})
        return self.send_json(rs, self.mlproxy.oldstyle_mailinglist_export(
            rs, address))

    @access("ml_script")
    @REQUESTdata(("address", "email"))
    def oldstyle_modlist_export(self, rs, address):
        """Provide specific infos for comptability mailinglist software"""
        if rs.errors:
            return self.send_json(rs, {'error': tuple(map(str, rs.errors))})
        return self.send_json(rs, self.mlproxy.oldstyle_modlist_export(
            rs, address))

    @access("ml_script", modi={"POST"}, check_anti_csrf=False)
    @REQUESTdata(("address", "email"), ("error", "int"))
    def oldstyle_bounce(self, rs, address, error):
        """Provide specific infos for comptability mailinglist software"""
        if rs.errors:
            return self.send_json(rs, {'error': tuple(map(str, rs.errors))})
        return self.send_json(rs, self.mlproxy.oldstyle_bounce(rs, address,
                                                               error))