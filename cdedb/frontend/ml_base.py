#!/usr/bin/env python3

"""Base class providing fundamental ml services."""

import collections
import copy
from datetime import datetime
from typing import Any, Collection, Dict, Optional, Set, cast

import werkzeug
from werkzeug import Response

import cdedb.database.constants as const
import cdedb.validationtypes as vtypes
from cdedb.common import (
    MOD_ALLOWED_FIELDS, PRIVILEGE_MOD_REQUIRING_FIELDS, PRIVILEGED_MOD_ALLOWED_FIELDS,
    CdEDBObject, CdEDBObjectMap, EntitySorter, PathLike, PrivilegeError, RequestState,
    SubscriptionActions, SubscriptionError, merge_dicts, n_, now, unwrap,
)
from cdedb.frontend.common import (
    REQUESTdata, REQUESTdatadict, access, calculate_db_logparams, calculate_loglinks,
    cdedbid_filter as cdedbid, check_validation as check, csv_output,
    keydictsort_filter, mailinglist_guard, periodic,
)
from cdedb.frontend.uncommon import AbstractUserFrontend
from cdedb.ml_type_aux import (
    ADDITIONAL_TYPE_FIELDS, TYPE_MAP, MailinglistGroup, get_type,
)
from cdedb.query import QUERY_SPECS, Query, mangle_query_input


class MlBaseFrontend(AbstractUserFrontend):
    realm = "ml"

    def __init__(self, configpath: PathLike = None):
        super().__init__(configpath)

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

    @access("ml_admin", modi={"POST"})
    def manually_write_subscription_states(self, rs: RequestState) -> Response:
        """Write subscription states of all mailinglists now.

        This will usually be done by a cron job, but sometimes it can be nice to trigger
        this immediately.
        """
        mailinglist_ids = self.mlproxy.list_mailinglists(rs)

        code = 1
        for ml_id in mailinglist_ids:
            code *= self.mlproxy.write_subscription_states(rs, ml_id)
        self.notify_return_code(rs, code)

        return self.redirect(rs, "ml/index")

    @access("core_admin", "ml_admin")
    def create_user_form(self, rs: RequestState) -> Response:
        defaults = {
            'is_member': False,
            'bub_search': False,
        }
        merge_dicts(rs.values, defaults)
        return super().create_user_form(rs)

    @access("core_admin", "ml_admin", modi={"POST"})
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

    @access("core_admin", "ml_admin")
    @REQUESTdata("download", "is_search")
    def user_search(self, rs: RequestState, download: Optional[str],
                    is_search: bool) -> Response:
        """Perform search."""
        spec = copy.deepcopy(QUERY_SPECS['qview_persona'])
        # mangle the input, so we can prefill the form
        query_input = mangle_query_input(rs, spec)
        query: Optional[Query] = None
        if is_search:
            query = check(rs, vtypes.QueryInput,
                query_input, "query", spec=spec, allow_empty=False)
        default_queries = self.conf["DEFAULT_QUERIES"]['qview_ml_user']
        params = {
            'spec': spec, 'default_queries': default_queries, 'choices': {},
            'choices_lists': {}, 'query': query}
        # Tricky logic: In case of no validation errors we perform a query
        if not rs.has_validation_errors() and is_search and query:
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
        event_ids = self.eventproxy.list_events(rs)
        events = self.eventproxy.get_events(rs, event_ids)
        for event in events.values():
            event['is_visible'] = ("event_admin" in rs.user.roles
                                   or rs.user.persona_id in event['orgas']
                                   or event['is_visible'])
        assemblies = self.assemblyproxy.list_assemblies(rs)
        for assembly_id, assembly in assemblies.items():
            assembly['is_visible'] = self.assemblyproxy.may_assemble(
                rs, assembly_id=assembly_id)
        subs = self.mlproxy.get_many_subscription_states(
            rs, mailinglist_ids=mailinglists, states=sub_states)
        mailman = self.get_mailman()
        for ml_id, ml in mailinglist_infos.items():
            ml['num_subscribers'] = len(subs[ml_id])
            ml['held_mails'] = mailman.get_held_message_count(ml)

        return self.render(rs, endpoint, {
            'groups': MailinglistGroup,
            'mailinglists': grouped,
            'subscriptions': subscriptions,
            'mailinglist_infos': mailinglist_infos,
            'events': events,
            'assemblies': assemblies})

    @access("ml")
    @REQUESTdata("ml_type")
    def create_mailinglist_form(self, rs: RequestState,
                                ml_type: Optional[const.MailinglistTypes]) -> Response:
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
            additional_fields = atype.get_additional_fields().keys()
            if "event_id" in additional_fields:
                event_ids = self.eventproxy.list_events(rs)
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
                'maxsize_default': atype.maxsize_default,
            })

    @access("ml", modi={"POST"})
    @REQUESTdatadict(
        "title", "local_part", "domain", "description", "mod_policy",
        "attachment_policy", "ml_type", "subject_prefix",
        "maxsize", "is_active", "notes", *ADDITIONAL_TYPE_FIELDS.items())
    @REQUESTdata("ml_type", "moderators")
    def create_mailinglist(self, rs: RequestState, data: Dict[str, Any],
                           ml_type: const.MailinglistTypes,
                           moderators: vtypes.CdedbIDList) -> Response:
        """Make a new list."""
        data["moderators"] = moderators
        data['ml_type'] = ml_type
        data = check(rs, vtypes.Mailinglist, data, creation=True)
        if not self.coreproxy.verify_ids(rs, moderators, is_archived=False):
            rs.append_validation_error(
                ("moderators", ValueError(n_(
                    "Some of these users do not exist or are archived."))))
        if not self.coreproxy.verify_personas(rs, moderators, {"ml"}):
            rs.append_validation_error(
                ("moderators", ValueError(n_(
                    "Some of these users are not ml users."))))
        if rs.has_validation_errors():
            return self.create_mailinglist_form(rs, ml_type=ml_type)
        assert data is not None
        # Check if mailinglist address is unique
        try:
            self.mlproxy.validate_address(rs, data)
        except ValueError as e:
            rs.extend_validation_errors([("local_part", e), ("domain", e)])

        if rs.has_validation_errors():
            return self.create_mailinglist_form(rs, ml_type=ml_type)
        assert data is not None

        new_id = self.mlproxy.create_mailinglist(rs, data)
        self.notify_return_code(rs, new_id)
        return self.redirect(rs, "ml/show_mailinglist", {
            'mailinglist_id': new_id})

    @access("ml")
    @REQUESTdata("codes", "mailinglist_id", "persona_id", "submitted_by",
                 "change_note", "offset", "length", "time_start", "time_stop")
    def view_log(self, rs: RequestState, codes: Collection[const.MlLogCodes],
                 mailinglist_id: Optional[vtypes.ID], offset: Optional[int],
                 length: Optional[vtypes.PositiveInt],
                 persona_id: Optional[vtypes.CdedbID],
                 submitted_by: Optional[vtypes.CdedbID],
                 change_note: Optional[str],
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
        relevant_set: Set[vtypes.ID] = set(relevant_mls)  # type: ignore
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
            change_note=change_note,
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
        allow_unsub = self.mlproxy.get_ml_type(rs, mailinglist_id).allow_unsub
        personas = self.coreproxy.get_personas(rs, ml['moderators'])
        moderators = collections.OrderedDict(
            (anid, personas[anid]) for anid in sorted(
                personas,
                key=lambda anid: EntitySorter.persona(personas[anid])))

        return self.render(rs, "show_mailinglist", {
            'sub_address': sub_address, 'state': state,
            'interaction_policy': interaction_policy, 'allow_unsub': allow_unsub,
            'event': event, 'assembly': assembly, 'moderators': moderators})

    @access("ml")
    @mailinglist_guard()
    def change_mailinglist_form(self, rs: RequestState,
                                mailinglist_id: int) -> Response:
        """Render form."""
        atype = TYPE_MAP[rs.ambience['mailinglist']['ml_type']]
        available_domains = atype.domains
        additional_fields = atype.get_additional_fields().keys()
        if "event_id" in additional_fields:
            event_ids = self.eventproxy.list_events(rs)
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
        # privileged is only set if there are actually fields,
        # requiring privileged access
        privileged = (self.mlproxy.may_manage(rs, mailinglist_id, privileged=True)
                      or not (additional_fields & PRIVILEGE_MOD_REQUIRING_FIELDS))
        return self.render(rs, "change_mailinglist", {
            'event_entries': event_entries,
            'assembly_entries': assembly_entries,
            'available_domains': available_domains,
            'additional_fields': additional_fields,
            'privileged': privileged,
        })

    @access("ml", modi={"POST"})
    @mailinglist_guard()
    @REQUESTdatadict(
        "title", "local_part", "domain", "description", "mod_policy",
        "notes", "attachment_policy", "ml_type", "subject_prefix", "maxsize",
        "is_active", *ADDITIONAL_TYPE_FIELDS.items())
    def change_mailinglist(self, rs: RequestState, mailinglist_id: int,
                           data: CdEDBObject) -> Response:
        """Modify simple attributes of mailinglists."""
        data['id'] = mailinglist_id

        if self.mlproxy.is_relevant_admin(rs, mailinglist_id=mailinglist_id):
            # admins may change everything except ml_type which got its own site
            allowed = set(data) - {'ml_type'}
        elif self.mlproxy.is_moderator(rs, mailinglist_id, privileged=True):
            allowed = PRIVILEGED_MOD_ALLOWED_FIELDS
        else:
            allowed = MOD_ALLOWED_FIELDS

        # we discard every entry of not allowed fields silently
        for key in set(data) - allowed:
            data[key] = rs.ambience['mailinglist'][key]

        data = check(rs, vtypes.Mailinglist, data)
        if rs.has_validation_errors():
            return self.change_mailinglist_form(rs, mailinglist_id)
        assert data is not None

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
        event_ids = self.eventproxy.list_events(rs)
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
    @REQUESTdatadict("ml_type", *ADDITIONAL_TYPE_FIELDS.items())
    def change_ml_type(self, rs: RequestState, mailinglist_id: int,
                       data: CdEDBObject) -> Response:
        ml = rs.ambience['mailinglist']
        data['id'] = mailinglist_id
        new_type = get_type(data['ml_type'])
        if ml['domain'] not in new_type.domains:
            data['domain'] = new_type.domains[0]
        data = check(rs, vtypes.Mailinglist, data)
        if rs.has_validation_errors():
            return self.change_ml_type_form(rs, mailinglist_id)
        assert data is not None

        code = self.mlproxy.set_mailinglist(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "ml/change_mailinglist")

    @access("ml", modi={"POST"})
    @mailinglist_guard(allow_moderators=False)
    @REQUESTdata("ack_delete")
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
    @mailinglist_guard()
    @REQUESTdata("codes", "persona_id", "submitted_by", "change_note", "offset",
                 "length", "time_start", "time_stop")
    def view_ml_log(self, rs: RequestState, mailinglist_id: int,
                    codes: Collection[const.MlLogCodes], offset: Optional[int],
                    length: Optional[vtypes.PositiveInt],
                    persona_id: Optional[vtypes.CdedbID],
                    submitted_by: Optional[vtypes.CdedbID],
                    change_note: Optional[str],
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
            change_note=change_note, time_start=time_start,
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
        privileged = self.mlproxy.may_manage(rs, mailinglist_id, privileged=True)
        return self.render(rs, "management", {
            'subscribers': subscribers, 'requests': requests,
            'moderators': moderators, 'explicits': explicits,
            'privileged': privileged})

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
        privileged = self.mlproxy.may_manage(rs, mailinglist_id, privileged=True)
        return self.render(rs, "show_subscription_details", {
            'subscription_overrides': subscription_overrides,
            'unsubscription_overrides': unsubscription_overrides,
            'privileged': privileged})

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
    @mailinglist_guard()
    @REQUESTdata("moderators")
    def add_moderators(self, rs: RequestState, mailinglist_id: int,
                       moderators: vtypes.CdedbIDList) -> Response:
        """Promote personas to moderator."""
        if rs.has_validation_errors():
            return self.management(rs, mailinglist_id)

        moderators = set(moderators)
        if not self.coreproxy.verify_ids(rs, moderators, is_archived=False):
            rs.append_validation_error(
                ("moderators", ValueError(n_(
                    "Some of these users do not exist or are archived."))))
        if not self.coreproxy.verify_personas(rs, moderators, {"ml"}):
            rs.append_validation_error(
                ("moderators", ValueError(n_(
                    "Some of these users are not ml users."))))
        if rs.has_validation_errors():
            return self.management(rs, mailinglist_id)

        moderators |= set(rs.ambience['mailinglist']['moderators'])
        code = self.mlproxy.set_moderators(rs, mailinglist_id, moderators)
        self.notify_return_code(rs, code, info=n_("Action had no effect."))
        return self.redirect(rs, "ml/management")

    @access("ml", modi={"POST"})
    @mailinglist_guard()
    @REQUESTdata("moderator_id")
    def remove_moderator(self, rs: RequestState, mailinglist_id: int,
                         moderator_id: vtypes.ID) -> Response:
        """Demote persona from moderator status."""
        moderators = set(rs.ambience['mailinglist']['moderators'])
        if moderator_id is not None and moderator_id not in moderators:  # type: ignore
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
    @mailinglist_guard()
    @REQUESTdata("email")
    def add_whitelist(self, rs: RequestState, mailinglist_id: int,
                      email: vtypes.Email) -> Response:
        """Allow address to write to the list."""
        if rs.has_validation_errors():
            return self.show_subscription_details(rs, mailinglist_id)

        whitelist = set(rs.ambience['mailinglist']['whitelist']) | {email}
        code = self.mlproxy.set_whitelist(rs, mailinglist_id, whitelist)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "ml/show_subscription_details")

    @access("ml", modi={"POST"})
    @mailinglist_guard()
    @REQUESTdata("email")
    def remove_whitelist(self, rs: RequestState, mailinglist_id: int,
                         email: vtypes.Email) -> Response:
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
        except PrivilegeError as pe:
            rs.notify("error", n_("Not privileged to change subscriptions."))
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
            return
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
            except PrivilegeError as pe:
                infos_only = False
                rs.notify("error",
                          n_("Not privileged to change subscriptions."))
        if infos_only:
            self.notify_return_code(rs, -1, info=n_("Action had no effect."))
        else:
            self.notify_return_code(rs, code)

    @access("ml", modi={"POST"})
    @mailinglist_guard(requires_privilege=True)
    @REQUESTdata("persona_id")
    def approve_request(self, rs: RequestState, mailinglist_id: int,
                        persona_id: vtypes.ID) -> Response:
        """Evaluate whether to admit subscribers."""
        if rs.has_validation_errors():
            return self.management(rs, mailinglist_id)
        self._subscription_action_handler(
            rs, SubscriptionActions.approve_request,
            mailinglist_id=mailinglist_id, persona_id=persona_id)
        return self.redirect(rs, "ml/management")

    @access("ml", modi={"POST"})
    @mailinglist_guard(requires_privilege=True)
    @REQUESTdata("persona_id")
    def deny_request(self, rs: RequestState, mailinglist_id: int,
                     persona_id: vtypes.ID) -> Response:
        """Evaluate whether to admit subscribers."""
        if rs.has_validation_errors():
            return self.management(rs, mailinglist_id)
        self._subscription_action_handler(
            rs, SubscriptionActions.deny_request,
            mailinglist_id=mailinglist_id, persona_id=persona_id)
        return self.redirect(rs, "ml/management")

    @access("ml", modi={"POST"})
    @mailinglist_guard(requires_privilege=True)
    @REQUESTdata("persona_id")
    def block_request(self, rs: RequestState, mailinglist_id: int,
                      persona_id: vtypes.ID) -> Response:
        """Evaluate whether to admit subscribers."""
        if rs.has_validation_errors():
            return self.management(rs, mailinglist_id)
        self._subscription_action_handler(
            rs, SubscriptionActions.block_request,
            mailinglist_id=mailinglist_id, persona_id=persona_id)
        return self.redirect(rs, "ml/management")

    @access("ml", modi={"POST"})
    @mailinglist_guard(requires_privilege=True)
    @REQUESTdata("subscriber_ids")
    def add_subscribers(self, rs: RequestState, mailinglist_id: int,
                        subscriber_ids: vtypes.CdedbIDList) -> Response:
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
    @mailinglist_guard(requires_privilege=True)
    @REQUESTdata("subscriber_id")
    def remove_subscriber(self, rs: RequestState, mailinglist_id: int,
                          subscriber_id: vtypes.ID) -> Response:
        """Administratively unsubscribe somebody."""
        if rs.has_validation_errors():
            return self.management(rs, mailinglist_id)
        self._subscription_action_handler(
            rs, SubscriptionActions.remove_subscriber,
            mailinglist_id=mailinglist_id, persona_id=subscriber_id)
        return self.redirect(rs, "ml/management")

    @access("ml", modi={"POST"})
    @mailinglist_guard(requires_privilege=True)
    @REQUESTdata("modsubscriber_ids")
    def add_subscription_overrides(self, rs: RequestState, mailinglist_id: int,
                                   modsubscriber_ids: vtypes.CdedbIDList) -> Response:
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
    @mailinglist_guard(requires_privilege=True)
    @REQUESTdata("modsubscriber_id")
    def remove_subscription_override(self, rs: RequestState,
                                     mailinglist_id: int,
                                     modsubscriber_id: vtypes.ID) -> Response:
        """Administratively remove somebody with moderator override."""
        if rs.has_validation_errors():
            return self.show_subscription_details(rs, mailinglist_id)
        self._subscription_action_handler(
            rs, SubscriptionActions.remove_subscription_override,
            mailinglist_id=mailinglist_id, persona_id=modsubscriber_id)
        return self.redirect(rs, "ml/show_subscription_details")

    @access("ml", modi={"POST"})
    @mailinglist_guard(requires_privilege=True)
    @REQUESTdata("modunsubscriber_ids")
    def add_unsubscription_overrides(self, rs: RequestState, mailinglist_id: int,
                                     modunsubscriber_ids: vtypes.CdedbIDList
                                     ) -> Response:
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
    @mailinglist_guard(requires_privilege=True)
    @REQUESTdata("modunsubscriber_id")
    def remove_unsubscription_override(self, rs: RequestState,
                                       mailinglist_id: int,
                                       modunsubscriber_id: vtypes.ID) -> Response:
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
    @REQUESTdata("email")
    def change_address(self, rs: RequestState, mailinglist_id: int,
                       email: Optional[vtypes.Email]) -> Response:
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
    @REQUESTdata("#email")
    def do_address_change(self, rs: RequestState, mailinglist_id: int,
                          email: vtypes.Email) -> Response:
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
        if setting and not self.mlproxy.get_ml_type(rs, mailinglist_id).allow_unsub:
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
