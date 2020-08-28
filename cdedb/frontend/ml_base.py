#!/usr/bin/env python3

"""Base class providing fundamental ml services."""

import copy
from datetime import datetime
import collections
from typing import Dict, Any, Optional, Collection

import mailmanclient
import werkzeug
from werkzeug import Response

from cdedb.frontend.common import (
    REQUESTdata, REQUESTdatadict, access, csv_output, periodic,
    check_validation as check, mailinglist_guard,
    cdedbid_filter as cdedbid, keydictsort_filter,
    calculate_db_logparams, calculate_loglinks)
from cdedb.frontend.uncommon import AbstractUserFrontend
from cdedb.query import QUERY_SPECS, mangle_query_input
from cdedb.common import (
    n_, merge_dicts, SubscriptionError, SubscriptionActions, now, EntitySorter,
    RequestState, CdEDBObject, PathLike, CdEDBObjectMap, unwrap)
import cdedb.database.constants as const
from cdedb.config import SecretsConfig

from cdedb.ml_type_aux import (
    MailinglistGroup, TYPE_MAP, ADDITIONAL_TYPE_FIELDS, get_type)


class MlBaseFrontend(AbstractUserFrontend):
    realm = "ml"

    user_management = {
        "persona_getter": lambda obj: obj.coreproxy.get_ml_user,
    }

    def __init__(self, configpath: PathLike = None):
        super().__init__(configpath)
        secrets = SecretsConfig(configpath)
        self.mailman_create_client = lambda url, user: mailmanclient.Client(
            url, user, secrets["MAILMAN_PASSWORD"])
        self.mailman_template_password = (
            lambda: secrets["MAILMAN_BASIC_AUTH_PASSWORD"])

    @classmethod
    def is_admin(cls, rs: RequestState) -> bool:
        return super().is_admin(rs)

    @access("ml")
    def index(self, rs: RequestState) -> Response:
        """Render start page."""
        mailinglists = self.mlproxy.list_mailinglists(rs)
        mailinglist_infos = self.mlproxy.get_mailinglists(rs, mailinglists)
        sub_states = const.SubscriptionStates.subscribing_states()
        subscriptions = self.mlproxy.get_user_subscriptions(
            rs, rs.user.persona_id, states=sub_states)
        grouped: Dict[MailinglistGroup, CdEDBObjectMap]
        grouped = collections.defaultdict(dict)
        for mailinglist_id, title in mailinglists.items():
            group_id = self.mlproxy.get_ml_type(rs, mailinglist_id).sortkey
            grouped[group_id][mailinglist_id] = {
                'title': title,
                'id': mailinglist_id
            }
        return self.render(rs, "index", {
            'groups': MailinglistGroup,
            'mailinglists': grouped,
            'subscriptions': subscriptions,
            'mailinglist_infos': mailinglist_infos})

    @access("ml_admin")
    def create_user_form(self, rs: RequestState) -> Response:
        defaults = {
            'is_member': False,
            'bub_search': False,
        }
        merge_dicts(rs.values, defaults)
        return super().create_user_form(rs)

    @access("ml_admin", modi={"POST"})
    @REQUESTdatadict(
        "given_names", "family_name", "display_name", "notes", "username")
    def create_user(self, rs: RequestState, data: Dict[str, Any],
                    ignore_warnings: bool = False) -> Response:
        defaults = {
            'is_cde_realm': False,
            'is_event_realm': False,
            'is_ml_realm': True,
            'is_assembly_realm': False,
            'is_active': True,
        }
        data.update(defaults)
        return super().create_user(rs, data, ignore_warnings)

    @access("ml_admin")
    @REQUESTdata(("download", "str_or_None"), ("is_search", "bool"))
    def user_search(self, rs: RequestState, download: str,
                    is_search: bool) -> Response:
        """Perform search."""
        spec = copy.deepcopy(QUERY_SPECS['qview_persona'])
        # mangle the input, so we can prefill the form
        query_input = mangle_query_input(rs, spec)
        if is_search:
            query = check(rs, "query_input", query_input, "query",
                          spec=spec, allow_empty=False)
        else:
            query = None
        default_queries = self.conf["DEFAULT_QUERIES"]['qview_ml_user']
        params = {
            'spec': spec, 'default_queries': default_queries, 'choices': {},
            'choices_lists': {}, 'query': query}
        # Tricky logic: In case of no validation errors we perform a query
        if not rs.has_validation_errors() and is_search:
            query.scope = "qview_persona"
            result = self.mlproxy.submit_general_query(rs, query)
            params['result'] = result
            if download:
                return self.send_query_download(
                    rs, result, fields=query.fields_of_interest, kind=download,
                    filename="user_search_result")
        else:
            rs.values['is_search'] = False
        return self.render(rs, "user_search", params)

    @access("ml")
    def list_mailinglists(self, rs: RequestState) -> Response:
        """Show all mailinglists you can administrate.

        ml_admins can administrate all mailinglists."""
        mailinglists = self.mlproxy.list_mailinglists(
            rs, active_only=False, managed='admin').keys()
        return self._build_mailinglist_list(rs, "list_mailinglists",
                                            mailinglists)

    @access("ml")
    def moderated_mailinglists(self, rs: RequestState) -> Response:
        """Show all moderated mailinglists."""
        return self._build_mailinglist_list(rs, "moderated_mailinglists",
                                            rs.user.moderator)

    def _build_mailinglist_list(self, rs: RequestState, endpoint: str,
                                mailinglists: Collection[int]) -> Response:
        """Collect all information required to build a comprehensive overview.

        For a collection of given mailinglist ids, this retrieves all relevant
        information. Querying mailinglists you have no access to will lead to
        a privilege error."""
        mailinglist_infos = self.mlproxy.get_mailinglists(rs, mailinglists)
        sub_states = const.SubscriptionStates.subscribing_states()
        subscriptions = self.mlproxy.get_user_subscriptions(
            rs, rs.user.persona_id, states=sub_states)
        grouped: Dict[MailinglistGroup, CdEDBObjectMap]
        grouped = collections.defaultdict(dict)
        for ml_id in mailinglists:
            group_id = self.mlproxy.get_ml_type(rs, ml_id).sortkey
            grouped[group_id][ml_id] = {
                'title': mailinglist_infos[ml_id]['title'], 'id': ml_id}
        event_ids = self.eventproxy.list_db_events(rs)
        events = {}
        for event_id in event_ids:
            event = self.eventproxy.get_event(rs, event_id)
            visible = (
                    "event_admin" in rs.user.roles
                    or rs.user.persona_id in event['orgas']
                    or event['is_visible'])
            events[event_id] = {'title': event['title'], 'is_visible': visible}
        assemblies = self.assemblyproxy.list_assemblies(rs)
        for assembly_id in assemblies:
            assemblies[assembly_id]['is_visible'] = \
                self.assemblyproxy.may_assemble(rs, assembly_id=assembly_id)
        subs = self.mlproxy.get_many_subscription_states(
            rs, mailinglist_ids=mailinglists, states=sub_states)
        for ml_id in subs:
            mailinglist_infos[ml_id]['num_subscribers'] = len(subs[ml_id])
        return self.render(rs, endpoint, {
            'groups': MailinglistGroup,
            'mailinglists': grouped,
            'subscriptions': subscriptions,
            'mailinglist_infos': mailinglist_infos,
            'events': events,
            'assemblies': assemblies})

    @access("ml")
    @REQUESTdata(("ml_type", "enum_mailinglisttypes_or_None"))
    def create_mailinglist_form(self, rs: RequestState,
                                ml_type: const.MailinglistTypes) -> Response:
        """Render form."""
        rs.ignore_validation_errors()
        if ml_type is None:
            available_types = self.mlproxy.get_available_types(rs)
            return self.render(
                rs, "create_mailinglist", {
                    'available_types': available_types,
                    'ml_type': None,
                })
        else:
            atype = TYPE_MAP[ml_type]
            if not atype.is_relevant_admin(rs.user):
                rs.append_validation_error(
                    ("ml_type", ValueError(n_(
                        "May not create mailinglist of this type."))))
            available_domains = atype.domains
            additional_fields = [f for f, _ in atype.get_additional_fields()]
            if "event_id" in additional_fields:
                event_ids = self.eventproxy.list_db_events(rs)
                events = self.eventproxy.get_events(rs, event_ids)
            else:
                events = {}
            assemblies = (self.assemblyproxy.list_assemblies(rs)
                          if "assembly_id" in additional_fields else [])
            return self.render(rs, "create_mailinglist", {
                'events': events,
                'assemblies': assemblies,
                'ml_type': ml_type,
                'available_domains': available_domains,
                'additional_fields': additional_fields,
            })

    @access("ml", modi={"POST"})
    @REQUESTdatadict(
        "title", "local_part", "domain", "description", "mod_policy",
        "attachment_policy", "ml_type", "subject_prefix",
        "maxsize", "is_active", "notes", *ADDITIONAL_TYPE_FIELDS)
    @REQUESTdata(("ml_type", "enum_mailinglisttypes"),
                 ("moderators", "cdedbid_csv_list"))
    def create_mailinglist(self, rs: RequestState, data: Dict[str, Any],
                           ml_type: const.MailinglistTypes,
                           moderators: Collection[int]) -> Response:
        """Make a new list."""
        data["moderators"] = moderators
        data['ml_type'] = ml_type
        data = check(rs, "mailinglist", data, creation=True)
        if not self.coreproxy.verify_ids(rs, moderators, is_archived=False):
            rs.append_validation_error(
                ("moderators", ValueError(n_(
                    "Some of these users do not exist or are archived."))))
        if not self.coreproxy.verify_personas(rs, moderators, {"ml"}):
            rs.append_validation_error(
                ("moderators", ValueError(n_(
                    "Some of these users are not ml-users."))))
        if rs.has_validation_errors():
            return self.create_mailinglist_form(rs, ml_type=ml_type)
        # Check if mailinglist address is unique
        try:
            self.mlproxy.validate_address(rs, data)
        except ValueError as e:
            rs.extend_validation_errors([("local_part", e), ("domain", e)])

        if rs.has_validation_errors():
            return self.create_mailinglist_form(rs, ml_type=ml_type)

        new_id = self.mlproxy.create_mailinglist(rs, data)
        self.notify_return_code(rs, new_id)
        return self.redirect(rs, "ml/show_mailinglist", {
            'mailinglist_id': new_id})

    @access("ml")
    @REQUESTdata(("codes", "[int]"), ("mailinglist_id", "id_or_None"),
                 ("persona_id", "cdedbid_or_None"),
                 ("submitted_by", "cdedbid_or_None"),
                 ("additional_info", "str_or_None"),
                 ("offset", "int_or_None"),
                 ("length", "positive_int_or_None"),
                 ("time_start", "datetime_or_None"),
                 ("time_stop", "datetime_or_None"))
    def view_log(self, rs: RequestState, codes: Collection[const.MlLogCodes],
                 mailinglist_id: Optional[int], offset: Optional[int],
                 length: Optional[int], persona_id: Optional[int],
                 submitted_by: Optional[int], additional_info: Optional[str],
                 time_start: Optional[datetime],
                 time_stop: Optional[datetime]) -> Response:
        """View activities."""
        length = length or self.conf["DEFAULT_LOG_LENGTH"]
        # length is the requested length, _length the theoretically
        # shown length for an infinite amount of log entries.
        _offset, _length = calculate_db_logparams(offset, length)

        # no validation since the input stays valid, even if some options
        # are lost
        rs.ignore_validation_errors()
        db_mailinglist_ids = {mailinglist_id} if mailinglist_id else None

        relevant_mls = self.mlproxy.list_mailinglists(rs, active_only=False,
                                                      managed='managed')
        relevant_set = set(relevant_mls)
        if not self.is_admin(rs):
            if db_mailinglist_ids is None:
                db_mailinglist_ids = relevant_set
            elif not db_mailinglist_ids <= relevant_set:
                db_mailinglist_ids = db_mailinglist_ids | relevant_set
                rs.notify("warning", n_(
                    "Not privileged to view log for all these mailinglists."))

        total, log = self.mlproxy.retrieve_log(
            rs, codes, db_mailinglist_ids, _offset, _length,
            persona_id=persona_id, submitted_by=submitted_by,
            additional_info=additional_info,
            time_start=time_start, time_stop=time_stop)
        persona_ids = (
                {entry['submitted_by'] for entry in log if
                 entry['submitted_by']}
                | {entry['persona_id'] for entry in log if entry['persona_id']})
        personas = self.coreproxy.get_personas(rs, persona_ids)
        log_mailinglist_ids = {entry['mailinglist_id']
                               for entry in log if entry['mailinglist_id']}
        mailinglists = self.mlproxy.get_mailinglists(rs, log_mailinglist_ids)
        loglinks = calculate_loglinks(rs, total, offset, length)
        return self.render(rs, "view_log", {
            'log': log, 'total': total, 'length': _length, 'personas': personas,
            'mailinglists': mailinglists, 'relevant_mailinglists': relevant_mls,
            'loglinks': loglinks})

    @access("ml")
    def show_mailinglist(self, rs: RequestState,
                         mailinglist_id: int) -> Response:
        """Details of a list."""
        assert rs.user.persona_id is not None
        ml = rs.ambience['mailinglist']
        state = self.mlproxy.get_subscription(
            rs, rs.user.persona_id, mailinglist_id=mailinglist_id)

        if not self.mlproxy.may_view(rs, ml):
            raise werkzeug.exceptions.Forbidden()

        sub_address = None
        if state and state.is_subscribed():
            sub_address = self.mlproxy.get_subscription_address(
                rs, mailinglist_id, rs.user.persona_id, explicits_only=True)

        event = None
        if ml['event_id']:
            event = self.eventproxy.get_event(rs, ml['event_id'])
            event['is_visible'] = (
                "event_admin" in rs.user.roles
                or rs.user.persona_id in event['orgas']
                or event['is_visible'])

        assembly = None
        if ml['assembly_id']:
            all_assemblies = self.assemblyproxy.list_assemblies(rs)
            assembly = all_assemblies[ml['assembly_id']]
            assembly['is_visible'] = self.assemblyproxy.may_assemble(
                rs, assembly_id=assembly['id'])

        interaction_policy = self.mlproxy.get_interaction_policy(
            rs, rs.user.persona_id, mailinglist=ml)
        personas = self.coreproxy.get_personas(rs, ml['moderators'])
        moderators = collections.OrderedDict(
            (anid, personas[anid]) for anid in sorted(
                personas,
                key=lambda anid: EntitySorter.persona(personas[anid])))

        return self.render(rs, "show_mailinglist", {
            'sub_address': sub_address, 'state': state,
            'interaction_policy': interaction_policy, 'event': event,
            'assembly': assembly, 'moderators': moderators})

    @access("ml")
    @mailinglist_guard()
    def change_mailinglist_form(self, rs: RequestState,
                                mailinglist_id: int) -> Response:
        """Render form."""
        atype = TYPE_MAP[rs.ambience['mailinglist']['ml_type']]
        available_domains = atype.domains
        additional_fields = [f for f, _ in atype.get_additional_fields()]
        if "event_id" in additional_fields:
            event_ids = self.eventproxy.list_db_events(rs)
            events = self.eventproxy.get_events(rs, event_ids)
            sorted_events = keydictsort_filter(events, EntitySorter.event)
            event_entries = [(k, v['title']) for k, v in sorted_events]
        else:
            event_entries = []
        if "assembly_id" in additional_fields:
            assemblies = self.assemblyproxy.list_assemblies(rs)
            sorted_assemblies = keydictsort_filter(
                assemblies, EntitySorter.assembly)
            assembly_entries = [(k, v['title']) for k, v in sorted_assemblies]
        else:
            assembly_entries = []
        merge_dicts(rs.values, rs.ambience['mailinglist'])
        if not self.mlproxy.is_relevant_admin(
                rs, mailinglist=rs.ambience['mailinglist']):
            rs.notify("info",
                      n_("Only Admins may change mailinglist configuration."))
        return self.render(rs, "change_mailinglist", {
            'event_entries': event_entries,
            'assembly_entries': assembly_entries,
            'available_domains': available_domains,
            'additional_fields': additional_fields,
        })

    @access("ml", modi={"POST"})
    @mailinglist_guard(allow_moderators=False)
    @REQUESTdatadict(
        "title", "local_part", "domain", "description", "mod_policy",
        "notes", "attachment_policy", "ml_type", "subject_prefix", "maxsize",
        "is_active", *ADDITIONAL_TYPE_FIELDS)
    def change_mailinglist(self, rs: RequestState, mailinglist_id: int,
                           data: CdEDBObject) -> Response:
        """Modify simple attributes of mailinglists."""
        data['id'] = mailinglist_id
        data = check(rs, "mailinglist", data)
        if rs.has_validation_errors():
            return self.change_mailinglist_form(rs, mailinglist_id)
        if data['ml_type'] != rs.ambience['mailinglist']['ml_type']:
            rs.append_validation_error(
                ("ml_type", ValueError(n_(
                    "Mailinglist Type cannot be changed here."))))
        # Check if mailinglist address is unique
        try:
            self.mlproxy.validate_address(rs, data)
        except ValueError as e:
            rs.extend_validation_errors([("local_part", e), ("domain", e)])

        if rs.has_validation_errors():
            return self.change_mailinglist_form(rs, mailinglist_id)
        code = self.mlproxy.set_mailinglist(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "ml/show_mailinglist")

    @access("ml")
    @mailinglist_guard(allow_moderators=False)
    def change_ml_type_form(self, rs: RequestState,
                            mailinglist_id: int) -> Response:
        """Render form."""
        available_types = self.mlproxy.get_available_types(rs)
        event_ids = self.eventproxy.list_db_events(rs)
        events = self.eventproxy.get_events(rs, event_ids)
        assemblies = self.assemblyproxy.list_assemblies(rs)
        merge_dicts(rs.values, rs.ambience['mailinglist'])
        return self.render(rs, "change_ml_type", {
            'available_types': available_types,
            'events': events,
            'assemblies': assemblies,
        })

    @access("ml", modi={"POST"})
    @mailinglist_guard(allow_moderators=False)
    @REQUESTdatadict("ml_type", *ADDITIONAL_TYPE_FIELDS)
    def change_ml_type(self, rs: RequestState, mailinglist_id: int,
                       data: CdEDBObject) -> Response:
        ml = rs.ambience['mailinglist']
        data['id'] = mailinglist_id
        new_type = get_type(data['ml_type'])
        if ml['domain'] not in new_type.domains:
            data['domain'] = new_type.domains[0]
        data = check(rs, 'mailinglist', data)
        if rs.has_validation_errors():
            return self.change_ml_type_form(rs, mailinglist_id)

        code = self.mlproxy.set_mailinglist(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "ml/change_mailinglist")

    @access("ml", modi={"POST"})
    @mailinglist_guard(allow_moderators=False)
    @REQUESTdata(("ack_delete", "bool"))
    def delete_mailinglist(self, rs: RequestState, mailinglist_id: int,
                           ack_delete: bool) -> Response:
        """Remove a mailinglist."""
        if not ack_delete:
            rs.append_validation_error(
                ("ack_delete", ValueError(n_("Must be checked."))))
        if rs.has_validation_errors():
            return self.show_mailinglist(rs, mailinglist_id)

        code = self.mlproxy.delete_mailinglist(
            rs, mailinglist_id, cascade={"subscriptions", "log", "addresses",
                                         "whitelist", "moderators"})

        self.notify_return_code(rs, code)
        return self.redirect(rs, "ml/list_mailinglists")

    @access("ml")
    @REQUESTdata(("codes", "[int]"), ("persona_id", "cdedbid_or_None"),
                 ("submitted_by", "cdedbid_or_None"),
                 ("additional_info", "str_or_None"),
                 ("offset", "int_or_None"),
                 ("length", "positive_int_or_None"),
                 ("time_start", "datetime_or_None"),
                 ("time_stop", "datetime_or_None"))
    @mailinglist_guard()
    def view_ml_log(self, rs: RequestState, mailinglist_id: int,
                    codes: Collection[const.MlLogCodes], offset: Optional[int],
                    length: Optional[int], persona_id: Optional[int],
                    submitted_by: Optional[int], additional_info: Optional[str],
                    time_start: Optional[datetime],
                    time_stop: Optional[datetime]) -> Response:
        """View activities pertaining to one list."""
        length = length or self.conf["DEFAULT_LOG_LENGTH"]
        # length is the requested length, _length the theoretically
        # shown length for an infinite amount of log entries.
        _offset, _length = calculate_db_logparams(offset, length)

        # no validation since the input stays valid, even if some options
        # are lost
        rs.ignore_validation_errors()
        total, log = self.mlproxy.retrieve_log(
            rs, codes, [mailinglist_id], _offset, _length,
            persona_id=persona_id, submitted_by=submitted_by,
            additional_info=additional_info, time_start=time_start,
            time_stop=time_stop)
        persona_ids = (
                {entry['submitted_by'] for entry in log if
                 entry['submitted_by']}
                | {entry['persona_id'] for entry in log if entry['persona_id']})
        personas = self.coreproxy.get_personas(rs, persona_ids)
        loglinks = calculate_loglinks(rs, total, offset, length)
        return self.render(rs, "view_ml_log", {
            'log': log, 'total': total, 'length': _length, 'personas': personas,
            'loglinks': loglinks
        })

    @access("ml")
    @mailinglist_guard()
    def management(self, rs: RequestState, mailinglist_id: int) -> Response:
        """Render form."""
        sub_states = const.SubscriptionStates.subscribing_states()
        subscribers = self.mlproxy.get_subscription_states(
            rs, mailinglist_id, states=sub_states)
        explicits = self.mlproxy.get_subscription_addresses(
            rs, mailinglist_id, explicits_only=True)
        explicits = {k: v for (k, v) in explicits.items() if v is not None}
        requests = self.mlproxy.get_subscription_states(
            rs, mailinglist_id, states=(const.SubscriptionStates.pending,))
        persona_ids = (set(rs.ambience['mailinglist']['moderators'])
                       | set(subscribers.keys()) | set(requests))
        personas = self.coreproxy.get_personas(rs, persona_ids)
        subscribers = collections.OrderedDict(
            (anid, personas[anid]) for anid in sorted(
                subscribers,
                key=lambda anid: EntitySorter.persona(personas[anid])))
        moderators = collections.OrderedDict(
            (anid, personas[anid]) for anid in sorted(
                rs.ambience['mailinglist']['moderators'],
                key=lambda anid: EntitySorter.persona(personas[anid])))
        requests = collections.OrderedDict(
            (anid, personas[anid]) for anid in sorted(
            requests, key=lambda anid: EntitySorter.persona(personas[anid])))
        return self.render(rs, "management", {
            'subscribers': subscribers, 'requests': requests,
            'moderators': moderators, 'explicits': explicits})

    @access("ml")
    @mailinglist_guard()
    def show_subscription_details(self, rs: RequestState,
                                  mailinglist_id: int) -> Response:
        """Render form."""
        subscription_overrides = self.mlproxy.get_subscription_states(
            rs, mailinglist_id,
            states=(const.SubscriptionStates.subscription_override,))
        unsubscription_overrides = self.mlproxy.get_subscription_states(
            rs, mailinglist_id,
            states=(const.SubscriptionStates.unsubscription_override,))
        persona_ids = (set(rs.ambience['mailinglist']['moderators'])
                       | set(subscription_overrides.keys())
                       | set(unsubscription_overrides.keys()))
        personas = self.coreproxy.get_personas(rs, persona_ids)
        subscription_overrides = collections.OrderedDict(
            (anid, personas[anid]) for anid in sorted(
                subscription_overrides,
                key=lambda anid: EntitySorter.persona(personas[anid])))
        unsubscription_overrides = collections.OrderedDict(
            (anid, personas[anid]) for anid in sorted(
                unsubscription_overrides,
                key=lambda anid: EntitySorter.persona(personas[anid])))
        return self.render(rs, "show_subscription_details", {
            'subscription_overrides': subscription_overrides,
            'unsubscription_overrides': unsubscription_overrides})

    @access("ml")
    @mailinglist_guard()
    def download_csv_subscription_states(self, rs: RequestState,
                                         mailinglist_id: int) -> Response:
        """Create CSV file with all subscribers and their subscription state"""
        personas_state = self.mlproxy.get_subscription_states(
            rs, mailinglist_id)
        if not personas_state:
            rs.notify("info", n_("Empty File."))
            return self.redirect(rs, "ml/management")
        personas = self.coreproxy.get_personas(rs, personas_state.keys())
        addresses = self.mlproxy.get_subscription_addresses(
            rs, mailinglist_id, explicits_only=True)
        columns = ['db_id', 'given_names', 'family_name', 'subscription_state',
                   'email', 'subscription_address']
        output = []

        for persona in personas:
            pair = {
                'db_id': cdedbid(persona),
                'given_names': personas[persona]['given_names'],
                'family_name': personas[persona]['family_name'],
                'subscription_state': personas_state[persona].name,
                'email': personas[persona]['username'],
            }
            if persona in addresses:
                pair['subscription_address'] = addresses[persona]
            else:
                pair['subscription_address'] = ""

            output.append(pair)

        csv_data = csv_output(
            sorted(output, key=lambda e: EntitySorter.persona(
                personas[int(e["db_id"][3:-2])])),
            columns)
        return self.send_csv_file(
            rs, data=csv_data, inline=False,
            filename="{}_subscription_states.csv".format(
                rs.ambience['mailinglist']['id']))

    @access("ml", modi={"POST"})
    @REQUESTdata(("moderators", "cdedbid_csv_list"))
    @mailinglist_guard()
    def add_moderators(self, rs: RequestState, mailinglist_id: int,
                       moderators: Collection[int]) -> Response:
        """Promote personas to moderator."""
        if rs.has_validation_errors():
            return self.management(rs, mailinglist_id)

        moderators = set(moderators)
        if not self.coreproxy.verify_ids(rs, moderators, is_archived=False):
            rs.append_validation_error(
                ("moderators", ValueError(n_(
                    "Some of these users do not exist or are archived."))))
        verified = set(self.coreproxy.verify_personas(rs, moderators, {"ml"}))
        if not verified == moderators:
            rs.append_validation_error(
                ("moderators", ValueError(n_(
                    "Some of these users are not ml-users."))))
        if rs.has_validation_errors():
            return self.management(rs, mailinglist_id)

        moderators |= set(rs.ambience['mailinglist']['moderators'])
        code = self.mlproxy.set_moderators(rs, mailinglist_id, moderators)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "ml/management")

    @access("ml", modi={"POST"})
    @REQUESTdata(("moderator_id", "id"))
    @mailinglist_guard()
    def remove_moderator(self, rs: RequestState, mailinglist_id: int,
                         moderator_id: int) -> Response:
        """Demote persona from moderator status."""
        moderators = set(rs.ambience['mailinglist']['moderators'])
        if moderator_id is not None and moderator_id not in moderators:
            rs.append_validation_error(
                ("moderator_id", ValueError(n_("User is no moderator."))))
        if rs.has_validation_errors():
            return self.management(rs, mailinglist_id)
        if (moderator_id == rs.user.persona_id
                and not self.mlproxy.is_relevant_admin(
                    rs, mailinglist_id=mailinglist_id)):
            rs.notify("error",
                      n_("Not allowed to remove yourself as moderator."))
            return self.management(rs, mailinglist_id)

        moderators -= {moderator_id}
        if not moderators:
            rs.notify("error", n_("Cannot remove last moderator."))
        else:
            code = self.mlproxy.set_moderators(
                rs, mailinglist_id, moderators)
            self.notify_return_code(rs, code)
        return self.redirect(rs, "ml/management")

    @access("ml", modi={"POST"})
    @REQUESTdata(("email", "email"))
    @mailinglist_guard()
    def add_whitelist(self, rs: RequestState, mailinglist_id: int,
                      email: str) -> Response:
        """Allow address to write to the list."""
        if rs.has_validation_errors():
            return self.show_subscription_details(rs, mailinglist_id)

        whitelist = set(rs.ambience['mailinglist']['whitelist']) | {email}
        code = self.mlproxy.set_whitelist(rs, mailinglist_id, whitelist)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "ml/show_subscription_details")

    @access("ml", modi={"POST"})
    @REQUESTdata(("email", "email"))
    @mailinglist_guard()
    def remove_whitelist(self, rs: RequestState, mailinglist_id: int,
                         email: str) -> Response:
        """Withdraw privilege of writing to list."""
        if rs.has_validation_errors():
            return self.show_subscription_details(rs, mailinglist_id)

        whitelist = set(rs.ambience['mailinglist']['whitelist']) - {email}
        code = self.mlproxy.set_whitelist(rs, mailinglist_id, whitelist)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "ml/show_subscription_details")

    def _subscription_action_handler(self, rs: RequestState,
                                     action: SubscriptionActions,
                                     **kwargs: Any) -> None:
        """Un-inlined code from all single subscription action initiating endpoints."""
        try:
            code = self.mlproxy.do_subscription_action(rs, action, **kwargs)
        except SubscriptionError as se:
            rs.notify(se.kind, se.msg)
        else:
            self.notify_return_code(rs, code)

    def _subscription_multi_action_handler(self, rs: RequestState,
                                           field: str,
                                           action: SubscriptionActions,
                                           mailinglist_id: int,
                                           persona_ids: Collection[int]) -> None:
        """Un-inlined code from all multi subscription action initiating endpoints.

        Falls back to _subscription_action_handler if only a single action is
        done."""
        if not self.coreproxy.verify_ids(rs, persona_ids, is_archived=False):
            rs.append_validation_error(
                (field, ValueError(n_(
                    "Some of these users do not exist or are archived."))))
            self.notify_return_code(rs, 0)
            return

        # Use different error pattern if only one action is done
        if len(persona_ids) == 1:
            self._subscription_action_handler(rs, action,
                mailinglist_id=mailinglist_id, persona_id=unwrap(persona_ids))

        # Iterate over all subscriber_ids
        code = 0
        # This tracks whether every single action failed with
        # an error of kind "info".
        infos_only = True
        for persona_id in persona_ids:
            try:
                code += self.mlproxy.do_subscription_action(rs, action,
                    mailinglist_id=mailinglist_id, persona_id=persona_id)
                infos_only = False
            except SubscriptionError as se:
                rs.notify(se.multikind, se.msg)
                if se.multikind != 'info':
                    infos_only = False
        if infos_only:
            self.notify_return_code(rs, -1, pending=n_("Action had no effect."))
        else:
            self.notify_return_code(rs, code)

    @access("ml", modi={"POST"})
    @REQUESTdata(("persona_id", "id"))
    @mailinglist_guard()
    def approve_request(self, rs: RequestState, mailinglist_id: int,
                        persona_id: int) -> Response:
        """Evaluate whether to admit subscribers."""
        if rs.has_validation_errors():
            return self.management(rs, mailinglist_id)
        self._subscription_action_handler(
            rs, SubscriptionActions.approve_request,
            mailinglist_id=mailinglist_id, persona_id=persona_id)
        return self.redirect(rs, "ml/management")

    @access("ml", modi={"POST"})
    @REQUESTdata(("persona_id", "id"))
    @mailinglist_guard()
    def deny_request(self, rs: RequestState, mailinglist_id: int,
                     persona_id: int) -> Response:
        """Evaluate whether to admit subscribers."""
        if rs.has_validation_errors():
            return self.management(rs, mailinglist_id)
        self._subscription_action_handler(
            rs, SubscriptionActions.deny_request,
            mailinglist_id=mailinglist_id, persona_id=persona_id)
        return self.redirect(rs, "ml/management")

    @access("ml", modi={"POST"})
    @REQUESTdata(("persona_id", "id"))
    @mailinglist_guard()
    def block_request(self, rs: RequestState, mailinglist_id: int,
                      persona_id: int) -> Response:
        """Evaluate whether to admit subscribers."""
        if rs.has_validation_errors():
            return self.management(rs, mailinglist_id)
        self._subscription_action_handler(
            rs, SubscriptionActions.block_request,
            mailinglist_id=mailinglist_id, persona_id=persona_id)
        return self.redirect(rs, "ml/management")

    @access("ml", modi={"POST"})
    @REQUESTdata(("subscriber_ids", "cdedbid_csv_list"))
    @mailinglist_guard()
    def add_subscribers(self, rs: RequestState, mailinglist_id: int,
                        subscriber_ids: Collection[int]) -> Response:
        """Administratively subscribe somebody."""
        if rs.has_validation_errors():
            return self.management(rs, mailinglist_id)
        self._subscription_multi_action_handler(
            rs, 'subscriber_ids', SubscriptionActions.add_subscriber,
            mailinglist_id=mailinglist_id, persona_ids=subscriber_ids)
        if rs.has_validation_errors():
            return self.management(rs, mailinglist_id)
        else:
            return self.redirect(rs, "ml/management")

    @access("ml", modi={"POST"})
    @REQUESTdata(("subscriber_id", "id"))
    @mailinglist_guard()
    def remove_subscriber(self, rs: RequestState, mailinglist_id: int,
                          subscriber_id: int) -> Response:
        """Administratively unsubscribe somebody."""
        if rs.has_validation_errors():
            return self.management(rs, mailinglist_id)
        self._subscription_action_handler(
            rs, SubscriptionActions.remove_subscriber,
            mailinglist_id=mailinglist_id, persona_id=subscriber_id)
        return self.redirect(rs, "ml/management")

    @access("ml", modi={"POST"})
    @REQUESTdata(("modsubscriber_ids", "cdedbid_csv_list"))
    @mailinglist_guard()
    def add_subscription_overrides(self, rs: RequestState, mailinglist_id: int,
                                   modsubscriber_ids: Collection[int]) -> Response:
        """Administratively subscribe somebody with moderator override."""
        if rs.has_validation_errors():
            return self.show_subscription_details(rs, mailinglist_id)
        self._subscription_multi_action_handler(
            rs, 'modsubscriber_ids', SubscriptionActions.add_subscription_override,
            mailinglist_id=mailinglist_id, persona_ids=modsubscriber_ids)
        if rs.has_validation_errors():
            return self.show_subscription_details(rs, mailinglist_id)
        else:
            return self.redirect(rs, "ml/show_subscription_details")

    @access("ml", modi={"POST"})
    @REQUESTdata(("modsubscriber_id", "id"))
    @mailinglist_guard()
    def remove_subscription_override(self, rs: RequestState,
                                     mailinglist_id: int,
                                     modsubscriber_id: int) -> Response:
        """Administratively remove somebody with moderator override."""
        if rs.has_validation_errors():
            return self.show_subscription_details(rs, mailinglist_id)
        self._subscription_action_handler(
            rs, SubscriptionActions.remove_subscription_override,
            mailinglist_id=mailinglist_id, persona_id=modsubscriber_id)
        return self.redirect(rs, "ml/show_subscription_details")

    @access("ml", modi={"POST"})
    @REQUESTdata(("modunsubscriber_ids", "cdedbid_csv_list"))
    @mailinglist_guard()
    def add_unsubscription_overrides(self, rs: RequestState, mailinglist_id: int,
                                     modunsubscriber_ids: Collection[int]) -> Response:
        """Administratively block somebody."""
        if rs.has_validation_errors():
            return self.show_subscription_details(rs, mailinglist_id)
        self._subscription_multi_action_handler(
            rs, 'modunsubscriber_ids', SubscriptionActions.add_unsubscription_override,
            mailinglist_id=mailinglist_id, persona_ids=modunsubscriber_ids)
        if rs.has_validation_errors():
            return self.show_subscription_details(rs, mailinglist_id)
        else:
            return self.redirect(rs, "ml/show_subscription_details")

    @access("ml", modi={"POST"})
    @REQUESTdata(("modunsubscriber_id", "id"))
    @mailinglist_guard()
    def remove_unsubscription_override(self, rs: RequestState,
                                       mailinglist_id: int,
                                       modunsubscriber_id: int) -> Response:
        """Administratively remove block."""
        if rs.has_validation_errors():
            return self.show_subscription_details(rs, mailinglist_id)
        self._subscription_action_handler(
            rs, SubscriptionActions.remove_unsubscription_override,
            mailinglist_id=mailinglist_id, persona_id=modunsubscriber_id)
        return self.redirect(rs, "ml/show_subscription_details")

    @access("ml", modi={"POST"})
    def subscribe(self, rs: RequestState, mailinglist_id: int) -> Response:
        """Change own subscription state to subscribed or pending."""
        if rs.has_validation_errors():
            return self.show_mailinglist(rs, mailinglist_id)
        self._subscription_action_handler(
            rs, SubscriptionActions.subscribe,
            mailinglist_id=mailinglist_id)
        return self.redirect(rs, "ml/show_mailinglist")

    @access("ml", modi={"POST"})
    def request_subscription(self, rs: RequestState,
                             mailinglist_id: int) -> Response:
        """Change own subscription state to subscribed or pending."""
        if rs.has_validation_errors():
            return self.show_mailinglist(rs, mailinglist_id)
        self._subscription_action_handler(
            rs, SubscriptionActions.request_subscription,
            mailinglist_id=mailinglist_id)
        return self.redirect(rs, "ml/show_mailinglist")

    @access("ml", modi={"POST"})
    def unsubscribe(self, rs: RequestState, mailinglist_id: int) -> Response:
        """Change own subscription state to unsubscribed."""
        if rs.has_validation_errors():
            return self.show_mailinglist(rs, mailinglist_id)
        self._subscription_action_handler(
            rs, SubscriptionActions.unsubscribe,
            mailinglist_id=mailinglist_id)
        return self.redirect(rs, "ml/show_mailinglist")

    @access("ml", modi={"POST"})
    def cancel_subscription(self, rs: RequestState,
                            mailinglist_id: int) -> Response:
        """Cancel subscription request."""
        if rs.has_validation_errors():
            return self.show_mailinglist(rs, mailinglist_id)
        self._subscription_action_handler(
            rs, SubscriptionActions.cancel_request,
            mailinglist_id=mailinglist_id)
        return self.redirect(rs, "ml/show_mailinglist")

    @access("ml", modi={"POST"})
    @REQUESTdata(("email", "email_or_None"))
    def change_address(self, rs: RequestState, mailinglist_id: int,
                       email: str) -> Response:
        """Modify address to which emails are delivered for this list.

        If this address has not been used before, we verify it.
        """
        assert rs.user.persona_id is not None
        if rs.has_validation_errors():
            return self.show_mailinglist(rs, mailinglist_id)
        if not self._check_address_change_requirements(rs, mailinglist_id,
                                                       bool(email)):
            return self.redirect(rs, "ml/show_mailinglist")

        known_addresses = self.mlproxy.get_persona_addresses(rs)
        if not email:
            code = self.mlproxy.remove_subscription_address(
                rs, mailinglist_id=mailinglist_id,
                persona_id=rs.user.persona_id)
            self.notify_return_code(rs, code)
        elif email in known_addresses:
            code = self.mlproxy.set_subscription_address(
                rs, mailinglist_id=mailinglist_id,
                persona_id=rs.user.persona_id, email=email)
            self.notify_return_code(rs, code)
        else:
            self.do_mail(
                rs, "confirm_address",
                {'To': (email,),
                 'Subject': "E-Mail-Adresse für Mailingliste bestätigen"},
                {'email': self.encode_parameter(
                    "ml/do_address_change", "email", email,
                    rs.user.persona_id)})
            rs.notify("info", n_("Confirmation email sent."))
        return self.redirect(rs, "ml/show_mailinglist")

    @access("ml")
    @REQUESTdata(("email", "#email"))
    def do_address_change(self, rs: RequestState, mailinglist_id: int,
                          email: str) -> Response:
        """Successful verification for new address in :py:meth:`change_address`.

        This is not a POST since the link is shared via email.
        """
        assert rs.user.persona_id is not None
        if rs.has_validation_errors():
            return self.show_mailinglist(rs, mailinglist_id)
        if not self._check_address_change_requirements(rs, mailinglist_id,
                                                       False):
            return self.redirect(rs, "ml/show_mailinglist")

        code = self.mlproxy.set_subscription_address(
            rs, mailinglist_id=mailinglist_id, persona_id=rs.user.persona_id,
            email=email)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "ml/show_mailinglist")

    def _check_address_change_requirements(self, rs: RequestState,
                                           mailinglist_id: int,
                                           setting: bool) -> bool:
        """Check if all conditions required to change a subscription adress
        are fulfilled.

        :rtype: bool
        """
        assert rs.user.persona_id is not None
        is_subscribed = self.mlproxy.is_subscribed(
            rs, rs.user.persona_id, mailinglist_id)
        if not is_subscribed:
            rs.notify("error", n_("Not subscribed."))
            return False
        policy = self.mlproxy.get_interaction_policy(
            rs, persona_id=rs.user.persona_id,
            mailinglist=rs.ambience['mailinglist'])
        if setting and policy == const.MailinglistInteractionPolicy.mandatory:
            rs.notify("error", n_("Disallowed to change address."))
            return False
        return True

    @periodic("subscription_request_remind")
    def subscription_request_remind(self, rs: RequestState,
                                    store: CdEDBObject) -> CdEDBObject:
        """Send reminder email to moderators for pending subrequests."""
        ml_ids = self.mlproxy.list_mailinglists(rs)
        current = now().timestamp()
        for ml_id in ml_ids:
            requests = self.mlproxy.get_subscription_states(
                rs, ml_id, states=(const.SubscriptionStates.pending,))
            requests = list(requests)  # convert from dict which breaks JSON

            ml_store = store.get(str(ml_id))
            if ml_store is None:
                ml_store = {
                    'persona_ids': requests,
                    'tstamp': 0
                }

            if requests:
                new_request = set(requests) - set(ml_store['persona_ids'])
                if new_request or current > ml_store['tstamp'] + 7*24*60*60:
                    ml_store['tstamp'] = current
                    ml = self.mlproxy.get_mailinglist(rs, ml_id)
                    owner = ml['address'].replace("@", "-owner@")
                    self.do_mail(rs, "subscription_request_remind",
                                 {'To': (owner,),
                                  'Subject': "Offene Abonnement-Anfragen"},
                                 {'count_all': len(requests), 'ml': ml,
                                  'count_new': len(new_request)})

            ml_store['persona_ids'] = requests
            store[str(ml_id)] = ml_store
        return store

    @periodic("write_subscription_states")
    def write_subscription_states(self, rs: RequestState,
                                  store: CdEDBObject) -> CdEDBObject:
        """Write the current state of implicit subscribers to the database."""
        mailinglist_ids = self.mlproxy.list_mailinglists(rs)

        for ml_id in mailinglist_ids:
            self.mlproxy.write_subscription_states(rs, ml_id)

        return store
