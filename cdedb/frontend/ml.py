#!/usr/bin/env python3

"""Services for the ml realm."""

from cdedb.frontend.common import (
    REQUESTdata, REQUESTdatadict, access, ProxyShim, connect_proxy,
    check_validation as check, mailinglist_guard)
from cdedb.frontend.uncommon import AbstractUserFrontend
from cdedb.query import QUERY_SPECS, QueryOperators, mangle_query_input
from cdedb.common import name_key, merge_dicts, unwrap
import cdedb.database.constants as const

import logging
import werkzeug

class MlFrontend(AbstractUserFrontend):
    """Manage mailing lists which will be run by an external software."""
    realm = "ml"
    logger = logging.getLogger(__name__)
    user_management = {
        "persona_getter": lambda obj: obj.coreproxy.get_ml_user,
    }

    def __init__(self, configpath):
        super().__init__(configpath)
        self.cdeproxy = ProxyShim(connect_proxy(
            self.conf.SERVER_NAME_TEMPLATE.format("cde")))
        self.eventproxy = ProxyShim(connect_proxy(
            self.conf.SERVER_NAME_TEMPLATE.format("event")))
        self.assemblyproxy = ProxyShim(connect_proxy(
            self.conf.SERVER_NAME_TEMPLATE.format("assembly")))
        self.mlproxy = ProxyShim(connect_proxy(
            self.conf.SERVER_NAME_TEMPLATE.format("ml")))

    def finalize_session(self, rs, sessiondata):
        ret = super().finalize_session(rs, sessiondata)
        if "persona" in ret.roles:
            ret.moderator = self.mlproxy.moderator_info(rs, ret.persona_id)
        return ret

    @classmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

    @access("persona")
    def index(self, rs):
        """Render start page."""
        return self.render(rs, "index")

    @access("ml")
    @REQUESTdata(("confirm_id", "#int"))
    def show_user(self, rs, persona_id, confirm_id):
        return super().show_user(rs, persona_id, confirm_id)

    @access("ml")
    def change_user_form(self, rs):
        return super().change_user_form(rs)

    @access("ml", modi={"POST"})
    @REQUESTdatadict(
        "display_name", "family_name", "given_names")
    def change_user(self, rs, data):
        return super().change_user(rs, data)

    @access("ml_admin")
    def admin_change_user_form(self, rs, persona_id):
        return super().admin_change_user_form(rs, persona_id)

    @access("ml_admin", modi={"POST"})
    @REQUESTdatadict(
        "given_names", "family_name", "display_name", "notes")
    def admin_change_user(self, rs, persona_id, data):
        return super().admin_change_user(rs, persona_id, data)

    @access("ml_admin")
    def create_user_form(self, rs):
        defaults = {
            'is_member': False,
            'bub_search': False,
            'cloud_account': False,
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

    @access("anonymous")
    @REQUESTdata(("secret", "str"))
    def genesis_form(self, rs, case_id, secret):
        return super().genesis_form(rs, case_id, secret)

    @access("anonymous", modi={"POST"})
    @REQUESTdata(("secret", "str"))
    @REQUESTdatadict("display_name",)
    def genesis(self, rs, case_id, secret, data):
        data.update({
            'is_active': True,
            'cloud_account': False,
            'notes': '',
        })
        return super().genesis(rs, case_id, secret=secret, data=data)

    @access("ml_admin")
    def user_search_form(self, rs):
        """Render form."""
        spec = QUERY_SPECS['qview_generic_user']
        ## mangle the input, so we can prefill the form
        mangle_query_input(rs, spec)
        default_queries = self.conf.DEFAULT_QUERIES['qview_generic_user']
        return self.render(rs, "user_search", {
            'spec': spec, 'queryops': QueryOperators,
            'default_queries': default_queries, 'choices': {}})

    @access("ml_admin")
    @REQUESTdata(("CSV", "bool"))
    def user_search(self, rs, CSV):
        """Perform search."""
        spec = QUERY_SPECS['qview_generic_user']
        query = check(rs, "query_input", mangle_query_input(rs, spec), "query",
                      spec=spec, allow_empty=False)
        if rs.errors:
            return self.user_search_form(rs)
        query.scope = "qview_generic_user"
        result = self.mlproxy.submit_general_query(rs, query)
        params = {'result': result, 'query': query, 'choices': {}}
        if CSV:
            data = self.fill_template(rs, 'web', 'csv_search_result', params)
            return self.send_file(rs, data=data,
                                  filename=self.i18n("result.txt", rs.lang))
        else:
            return self.render(rs, "user_search_result", params)

    def list_some_mailinglists(self, rs, mailinglists, complete):
        """Code deduplication helper displaying lists.

        :type rs: :py:class:`FrontendRequestState`
        :type mailinglists: {int: str}
        :type complete: bool
        :rtype: :py:class:`werkzeug.wrappers.Response` or None
        """
        mailinglist_data = self.mlproxy.get_mailinglists(rs, mailinglists)
        subscriptions = self.mlproxy.subscriptions(
            rs, rs.user.persona_id, lists=mailinglists.keys())
        return self.render(rs, "list_mailinglists", {
            'mailinglists': mailinglists, 'subscriptions': subscriptions,
            'mailinglist_data': mailinglist_data, 'complete': complete})

    @access("ml")
    def list_mailinglists(self, rs):
        """Show all mailinglists of interest for the user."""
        policies = const.AudiencePolicy.applicable(rs.user.roles)
        mailinglists = self.mlproxy.list_mailinglists(
            rs, audience_policies=policies)
        return self.list_some_mailinglists(rs, mailinglists, complete=False)

    @access("ml_admin")
    def list_all_mailinglists(self, rs):
        """Show all mailinglists."""
        mailinglists = self.mlproxy.list_mailinglists(rs, active_only=False)
        return self.list_some_mailinglists(rs, mailinglists, complete=True)

    @access("ml_admin")
    def create_mailinglist_form(self, rs):
        """Render form."""
        mailinglists = self.mlproxy.list_mailinglists(rs)
        events = self.eventproxy.list_events(rs, past=False)
        assemblies = self.assemblyproxy.list_assemblies(rs)
        return self.render(rs, "create_mailinglist", {
            "mailinglists": mailinglists, "events": events,
            "assemblies": assemblies})

    @access("ml_admin", modi={"POST"})
    @REQUESTdatadict(
        "title", "address", "description", "sub_policy", "mod_policy",
        "attachment_policy", "audience_policy", "subject_prefix", "maxsize",
        "is_active", "notes", "gateway", "event_id", "registration_stati",
        "assembly_id")
    def create_mailinglist(self, rs, data):
        """Make a new list."""
        data = check(rs, "mailinglist_data", data, creation=True)
        if rs.errors:
            return self.create_mailinglist_form(rs)

        new_id = self.mlproxy.create_mailinglist(rs, data)
        self.notify_return_code(rs, new_id)
        return self.redirect(rs, "ml/show_mailinglist", {
            'mailinglist_id': new_id})

    @access("ml_admin")
    @REQUESTdata(("codes", "[int]"), ("mailinglist_id", "int_or_None"),
                 ("start", "int_or_None"), ("stop", "int_or_None"))
    def view_log(self, rs, codes, mailinglist_id, start, stop):
        """View activities."""
        start = start or 0
        stop = stop or 50
        ## no validation since the input stays valid, even if some options
        ## are lost
        log = self.mlproxy.retrieve_log(rs, codes, mailinglist_id, start, stop)
        personas = (
            {entry['submitted_by'] for entry in log}
            | {entry['persona_id'] for entry in log if entry['persona_id']})
        persona_data = self.coreproxy.get_personas(rs, personas)
        mailinglists = {entry['mailinglist_id']
                        for entry in log if entry['mailinglist_id']}
        mailinglist_data = self.mlproxy.get_mailinglists(rs, mailinglists)
        mailinglists = self.mlproxy.list_mailinglists(rs, active_only=False)
        return self.render(rs, "view_log", {
            'log': log, 'persona_data': persona_data,
            'mailinglist_data': mailinglist_data, 'mailinglists': mailinglists})

    @access("ml")
    def show_mailinglist(self, rs, mailinglist_id):
        """Details of a list."""
        mailinglist_data = self.mlproxy.get_mailinglist(rs, mailinglist_id)
        is_subscribed = self.mlproxy.is_subscribed(rs, rs.user.persona_id,
                                                   mailinglist_id)
        sub_address = None
        if is_subscribed:
            sub_address = unwrap(self.mlproxy.subscriptions(
                rs, rs.user.persona_id, (mailinglist_id,)))
        audience_check = const.AudiencePolicy(
            mailinglist_data['audience_policy']).check(rs.user.roles)
        if not (audience_check or is_subscribed
                or self.is_moderator(rs, mailinglist_id) or self.is_admin(rs)):
            return werkzeug.exceptions.Forbidden()
        gateway_data = {}
        if mailinglist_data['gateway']:
            gateway_data = self.mlproxy.get_mailinglist(
                rs, mailinglist_data['gateway'])
        event_data = {}
        if mailinglist_data['event_id']:
            event_data = self.eventproxy.get_event_data_one(
                rs, mailinglist_data['event_id'])
        assembly_data = {}
        if mailinglist_data['assembly_id']:
            assembly_data = self.assemblyproxy.get_assembly_data_one(
                rs, mailinglist_data['assembly_id'])
        policy = const.SubscriptionPolicy(mailinglist_data['sub_policy'])
        may_toggle = not policy.privileged_transition(not is_subscribed)
        if not is_subscribed and gateway_data and  self.mlproxy.is_subscribed(
                rs, rs.user.persona_id, mailinglist_data['gateway']):
            may_toggle = True
        return self.render(rs, "show_mailinglist", {
            'mailinglist_data': mailinglist_data, 'sub_address': sub_address,
            'is_subscribed': is_subscribed, 'gateway_data': gateway_data,
            'event_data': event_data, 'assembly_data': assembly_data,
            'may_toggle': may_toggle})

    @access("ml_admin")
    def change_mailinglist_form(self, rs, mailinglist_id):
        """Render form."""
        mailinglist_data = self.mlproxy.get_mailinglist(rs, mailinglist_id)
        mailinglists = self.mlproxy.list_mailinglists(rs)
        events = self.eventproxy.list_events(rs, past=False)
        assemblies = self.assemblyproxy.list_assemblies(rs)
        merge_dicts(rs.values, mailinglist_data)
        return self.render(rs, "change_mailinglist", {
            'mailinglist_data': mailinglist_data, 'mailinglists': mailinglists,
            'events': events, 'assemblies': assemblies})

    @access("ml_admin", modi={"POST"})
    @REQUESTdata(("audience_policy", "enum_audiencepolicy"),
                 ("registration_stati", "[enum_registrationpartstati]"))
    @REQUESTdatadict(
        "title", "address", "description", "sub_policy", "mod_policy",
        "notes", "attachment_policy", "subject_prefix", "maxsize",
        "is_active", "gateway", "event_id", "assembly_id")
    def change_mailinglist(self, rs, mailinglist_id, audience_policy,
                           registration_stati, data):
        """Modify simple attributes of mailinglists."""
        data['id'] = mailinglist_id
        data['audience_policy'] = audience_policy
        data['registration_stati'] = registration_stati
        data = check(rs, "mailinglist_data", data)
        if rs.errors:
            return self.change_mailinglist_form(rs, mailinglist_id)
        code = self.mlproxy.set_mailinglist(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "ml/show_mailinglist")

    @access("ml")
    @REQUESTdata(("codes", "[int]"), ("start", "int_or_None"),
                 ("stop", "int_or_None"))
    @mailinglist_guard()
    def view_ml_log(self, rs, mailinglist_id, codes, start, stop):
        """View activities pertaining to one list."""
        start = start or 0
        stop = stop or 50
        ## no validation since the input stays valid, even if some options
        ## are lost
        log = self.mlproxy.retrieve_log(rs, codes, mailinglist_id, start, stop)
        personas = (
            {entry['submitted_by'] for entry in log}
            | {entry['persona_id'] for entry in log if entry['persona_id']})
        persona_data = self.coreproxy.get_personas(rs, personas)
        mailinglist_data = self.mlproxy.get_mailinglist(rs, mailinglist_id)
        return self.render(rs, "view_ml_log", {
            'log': log, 'persona_data': persona_data,
            'mailinglist_data': mailinglist_data})

    @access("ml")
    @mailinglist_guard()
    def management(self, rs, mailinglist_id):
        """Render form."""
        mailinglist_data = self.mlproxy.get_mailinglist(rs, mailinglist_id)
        subscribers = self.mlproxy.subscribers(rs, mailinglist_id)
        requests = self.mlproxy.list_requests(rs, mailinglist_id)
        personas = (set(mailinglist_data['moderators'])
                    | set(subscribers.keys()) | set(requests))
        persona_data = self.coreproxy.get_personas(rs, personas)
        subscribers = sorted(subscribers,
                             key=lambda anid: name_key(persona_data[anid]))
        return self.render(rs, "management", {
            'mailinglist_data': mailinglist_data, 'subscribers': subscribers,
            'requests': requests, 'persona_data': persona_data})

    @access("ml", modi={"POST"})
    @REQUESTdata(("moderator_id", "cdedbid"))
    @mailinglist_guard()
    def add_moderator(self, rs, mailinglist_id, moderator_id):
        """Promote persona to moderator."""
        if rs.errors:
            return self.management(rs, mailinglist_id)
        mailinglist_data = self.mlproxy.get_mailinglist(rs, mailinglist_id)
        data = {
            'id': mailinglist_id,
            'moderators': set(mailinglist_data['moderators']) | {moderator_id},
        }
        code = self.mlproxy.set_mailinglist(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "ml/management")

    @access("ml", modi={"POST"})
    @REQUESTdata(("moderator_id", "int"))
    @mailinglist_guard()
    def remove_moderator(self, rs, mailinglist_id, moderator_id):
        """Demote persona from moderator status."""
        if rs.errors:
            return self.management(rs, mailinglist_id)
        mailinglist_data = self.mlproxy.get_mailinglist(rs, mailinglist_id)
        data = {
            'id': mailinglist_id,
            'moderators': set(mailinglist_data['moderators']) - {moderator_id},
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
            return self.management(rs, mailinglist_id)
        mailinglist_data = self.mlproxy.get_mailinglist(rs, mailinglist_id)
        data = {
            'id': mailinglist_id,
            'whitelist': set(mailinglist_data['whitelist']) | {email},
        }
        code = self.mlproxy.set_mailinglist(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "ml/management")


    @access("ml", modi={"POST"})
    @REQUESTdata(("email", "email"))
    @mailinglist_guard()
    def remove_whitelist(self, rs, mailinglist_id, email):
        """Withdraw privilege of writing to list."""
        if rs.errors:
            return self.management(rs, mailinglist_id)
        mailinglist_data = self.mlproxy.get_mailinglist(rs, mailinglist_id)
        data = {
            'id': mailinglist_id,
            'whitelist': set(mailinglist_data['whitelist']) - {email},
        }
        code = self.mlproxy.set_mailinglist(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "ml/management")

    @access("ml", modi={"POST"})
    @REQUESTdata(("persona_id", "int"), ("ack", "bool"))
    @mailinglist_guard()
    def decide_request(self, rs, mailinglist_id, persona_id, ack):
        """Evaluate whether to admit subscribers."""
        if rs.errors:
            return self.management(rs, mailinglist_id)
        code = self.mlproxy.decide_request(rs, mailinglist_id, persona_id, ack)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "ml/management")

    @access("ml", modi={"POST"})
    @REQUESTdata(("subscriber_id", "cdedbid"))
    @mailinglist_guard()
    def add_subscriber(self, rs, mailinglist_id, subscriber_id):
        """Administratively subscribe somebody."""
        if rs.errors:
            return self.management(rs, mailinglist_id)
        code = self.mlproxy.change_subscription_state(
            rs, mailinglist_id, subscriber_id, subscribe=True)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "ml/management")

    @access("ml", modi={"POST"})
    @REQUESTdata(("subscriber_id", "int"))
    @mailinglist_guard()
    def remove_subscriber(self, rs, mailinglist_id, subscriber_id):
        """Administratively unsubscribe somebody."""
        if rs.errors:
            return self.management(rs, mailinglist_id)
        code = self.mlproxy.change_subscription_state(
            rs, mailinglist_id, subscriber_id, subscribe=False)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "ml/management")

    @access("ml", modi={"POST"})
    @REQUESTdata(("subscribe", "bool"))
    def subscribe_or_unsubscribe(self, rs, mailinglist_id, subscribe):
        """Change own subscription state."""
        code = self.mlproxy.change_subscription_state(
            rs, mailinglist_id, rs.user.persona_id, subscribe)
        self.notify_return_code(
            rs, code, pending="Subscription request awaits moderation.")
        return self.redirect(rs, "ml/show_mailinglist")

    @access("ml", modi={"POST"})
    @REQUESTdata(("email", "email"))
    def change_address(self, rs, mailinglist_id, email):
        """Modify address to which emails are delivered for this list.

        If this address has not been used before, we verify it.
        """
        if rs.errors:
            return self.show_mailinglist(rs, mailinglist_id)
        is_subscribed = self.mlproxy.is_subscribed(rs, rs.user.persona_id,
                                                   mailinglist_id)
        if not is_subscribed:
            rs.notify("error", "Not subscribed.")
            return self.redirect(rs, "ml/show_mailinglist")
        mailinglist_data = self.mlproxy.get_mailinglist(rs, mailinglist_id)
        policy = const.SubscriptionPolicy(mailinglist_data['sub_policy'])
        may_toggle = not policy.privileged_transition(False)
        if not may_toggle:
            rs.notify("warning", "Disallowed to change address.")
            return self.redirect(rs, "ml/show_mailinglist")

        subscriptions = self.mlproxy.subscriptions(rs, rs.user.persona_id)
        if email in subscriptions.values():
            code = self.mlproxy.change_subscription_state(
                mailinglist_id, rs.user.persona_id, subscribe=True,
                address=email)
            self.notify_return_code(rs, code)
        else:
            user_data = self.coreproxy.get_ml_user(rs, rs.user.persona_id)
            self.do_mail(
                rs, "confirm_address",
                {'To': (email,),
                 'Subject': "Confirm email address for CdE mailing list"},
                {'user_data': user_data, 'mailinglist_data': mailinglist_data,
                 'email': self.encode_parameter(
                     "ml/do_address_change", "email", email),})
            rs.notify("info", "Confirmation email sent.")
        return self.redirect(rs, "ml/show_mailinglist")

    @access("ml")
    @REQUESTdata(("email", "#email"))
    def do_address_change(self, rs, mailinglist_id, email):
        """Successful verification for new address in :py:meth:`change_address`.

        This is not a POST since the link is shared via email.
        """
        if rs.errors:
            rs.notify("error", "Link expired.")
            return self.redirect(rs, "ml/show_mailinglist")
        is_subscribed = self.mlproxy.is_subscribed(rs, rs.user.persona_id,
                                                   mailinglist_id)
        if not is_subscribed:
            rs.notify("error", "Not subscribed.")
            return self.redirect(rs, "ml/show_mailinglist")
        mailinglist_data = self.mlproxy.get_mailinglist(rs, mailinglist_id)
        policy = const.SubscriptionPolicy(mailinglist_data['sub_policy'])
        may_toggle = not policy.privileged_transition(False)
        if not may_toggle:
            rs.notify("warning", "Disallowed to change address.")
            return self.redirect(rs, "ml/show_mailinglist")

        code = self.mlproxy.change_subscription_state(
            rs, mailinglist_id, rs.user.persona_id, subscribe=True,
            address=email)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "ml/show_mailinglist")

    @access("ml")
    @mailinglist_guard()
    def check_states(self, rs, mailinglist_id):
        """Test all explicit subscriptions for consistency with audience."""
        mailinglist_data = self.mlproxy.get_mailinglist(rs, mailinglist_id)
        problems = self.mlproxy.check_states_one(rs, mailinglist_id)
        persona_data = self.coreproxy.get_personas(rs, problems)
        return self.render(rs, "check_states", {
            'mailinglist_data': mailinglist_data, 'problems': problems,
            'persona_data': persona_data})

