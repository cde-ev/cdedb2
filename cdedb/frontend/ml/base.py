#!/usr/bin/env python3

"""Base class providing fundamental ml services."""

import collections
from datetime import datetime
from typing import Any, Collection, Dict, Optional, Set

import werkzeug
from werkzeug import Response

import cdedb.database.constants as const
import cdedb.validationtypes as vtypes
from cdedb.common import (
    FULL_MOD_REQUIRING_FIELDS, LOG_FIELDS_COMMON, MOD_ALLOWED_FIELDS,
    RESTRICTED_MOD_ALLOWED_FIELDS, CdEDBObject, CdEDBObjectMap, EntitySorter, PathLike,
    PrivilegeError, RequestState, merge_dicts, n_, now, unwrap, xsorted,
)
from cdedb.filter import keydictsort_filter
from cdedb.frontend.common import (
    AbstractUserFrontend, REQUESTdata, REQUESTdatadict, access, calculate_db_logparams,
    calculate_loglinks, cdedbid_filter as cdedbid, check_validation as check,
    csv_output, mailinglist_guard, periodic,
)
from cdedb.ml_type_aux import (
    ADDITIONAL_TYPE_FIELDS, TYPE_MAP, MailinglistGroup, get_type,
)
from cdedb.query import QueryScope
from cdedb.subman.exceptions import SubscriptionError
from cdedb.subman.machine import SubscriptionAction
from cdedb.validation import (
    ALL_MAILINGLIST_FIELDS, PERSONA_FULL_ML_CREATION, filter_none,
)


class MlBaseFrontend(AbstractUserFrontend):
    realm = "ml"

    def __init__(self, configpath: PathLike = None):
        super().__init__(configpath)

    @classmethod
    def is_admin(cls, rs: RequestState) -> bool:
        return super().is_admin(rs)

    @access("ml")
    def index(self, rs: RequestState) -> Response:
        """Render start page.

        Beware that this function relies on the assumption that the user is logged in,
        as enforced by `@access`. If not, an error in the backend will be raised.
        """
        assert rs.user.persona_id is not None
        mailinglists = self.mlproxy.list_mailinglists(rs)
        mailinglist_infos = self.mlproxy.get_mailinglists(rs, mailinglists)
        sub_states = const.SubscriptionState.subscribing_states()
        subscriptions = self.mlproxy.get_user_subscriptions(
            rs, rs.user.persona_id,
            states=sub_states | {const.SubscriptionState.pending})
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
        if rs.has_validation_errors():  # pragma: no cover
            return self.index(rs)
        mailinglist_ids = self.mlproxy.list_mailinglists(rs)

        code = self.mlproxy.write_subscription_states(rs, mailinglist_ids)
        rs.notify_return_code(code)

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
    @REQUESTdatadict(*filter_none(PERSONA_FULL_ML_CREATION))
    def create_user(self, rs: RequestState, data: Dict[str, Any]) -> Response:
        defaults = {
            'is_cde_realm': False,
            'is_event_realm': False,
            'is_ml_realm': True,
            'is_assembly_realm': False,
            'is_active': True,
        }
        data.update(defaults)
        return super().create_user(rs, data)

    @access("core_admin", "ml_admin")
    @REQUESTdata("download", "is_search")
    def user_search(self, rs: RequestState, download: Optional[str],
                    is_search: bool) -> Response:
        """Perform search."""
        return self.generic_user_search(
            rs, download, is_search, QueryScope.ml_user, QueryScope.ml_user,
            self.mlproxy.submit_general_query)

    @access("core_admin", "ml_admin")
    @REQUESTdata("download", "is_search")
    def archived_user_search(self, rs: RequestState, download: Optional[str],
                             is_search: bool) -> Response:
        """Perform search.

        Archived users are somewhat special since they are not visible
        otherwise.
        """
        return self.generic_user_search(
            rs, download, is_search,
            QueryScope.archived_persona, QueryScope.archived_persona,
            self.mlproxy.submit_general_query, endpoint="archived_user_search")

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
        assert rs.user.persona_id is not None
        mailinglist_infos = self.mlproxy.get_mailinglists(rs, mailinglists)
        sub_states = const.SubscriptionState.subscribing_states()
        subscriptions = self.mlproxy.get_user_subscriptions(
            rs, rs.user.persona_id,
            states=sub_states | {const.SubscriptionState.pending})
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
    @REQUESTdatadict(*ALL_MAILINGLIST_FIELDS)
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
        # Check if mailinglist address is unique and valid
        try:
            self.mlproxy.validate_address(rs, data)
        except ValueError as e:
            rs.extend_validation_errors([("local_part", e), ("domain", e)])

        if rs.has_validation_errors():
            return self.create_mailinglist_form(rs, ml_type=ml_type)
        assert data is not None

        new_id = self.mlproxy.create_mailinglist(rs, data)
        rs.notify_return_code(new_id)
        return self.redirect(rs, "ml/show_mailinglist", {
            'mailinglist_id': new_id})

    @access("ml_admin")
    def merge_accounts_form(self, rs: RequestState) -> Response:
        """Render form."""
        return self.render(rs, "merge_accounts")

    @access("ml_admin", modi={"POST"})
    @REQUESTdata("source_persona_id", "target_persona_id", "clone_addresses")
    def merge_accounts(self, rs: RequestState,
                       source_persona_id: vtypes.CdedbID,
                       target_persona_id: vtypes.CdedbID,
                       clone_addresses: bool) -> Response:
        """Merge a ml only user (source) into an other user (target).

        This mirrors the subscription states and moderator privileges of the source
        to the target.

        Make sure that the two users are not related to the same mailinglist. Otherwise,
        this function will abort.
        """
        if rs.has_validation_errors():
            return self.merge_accounts_form(rs)
        if not self.coreproxy.verify_id(rs, source_persona_id, is_archived=False):
            rs.append_validation_error(
                ("source_persona_id", ValueError(n_(
                    "User does not exist or is archived."))))
        if not self.coreproxy.verify_id(rs, target_persona_id, is_archived=False):
            rs.append_validation_error(
                ("target_persona_id", ValueError(n_(
                    "User does not exist or is archived."))))
        if not self.coreproxy.verify_persona(rs, source_persona_id,
                                             allowed_roles={"ml"}):
            rs.append_validation_error(
                ("source_persona_id", ValueError(n_(
                    "Source persona must be a ml-only user and no admin."))))
        if source_persona_id == target_persona_id:
            rs.append_validation_error(
                ("target_persona_id", ValueError(n_(
                    "Can not merge user into himself."))))
        if rs.has_validation_errors():
            return self.merge_accounts_form(rs)
        code = self.mlproxy.merge_accounts(
            rs, source_persona_id, target_persona_id, clone_addresses)
        if not code:
            return self.merge_accounts_form(rs)
        rs.notify_return_code(code)
        return self.redirect(rs, "ml/merge_accounts")

    @access("ml")
    @REQUESTdata(*LOG_FIELDS_COMMON, "mailinglist_id")
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
            'loglinks': loglinks, 'may_view': lambda ml: self.mlproxy.may_view(rs, ml),
        })

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

        subscription_policy = self.mlproxy.get_subscription_policy(
            rs, rs.user.persona_id, mailinglist=ml)
        allow_unsub = self.mlproxy.get_ml_type(rs, mailinglist_id).allow_unsub
        personas = self.coreproxy.get_personas(rs, ml['moderators'])
        moderators = collections.OrderedDict(
            (anid, personas[anid]) for anid in xsorted(
                personas,
                key=lambda anid: EntitySorter.persona(personas[anid])))

        return self.render(rs, "show_mailinglist", {
            'sub_address': sub_address, 'state': state,
            'subscription_policy': subscription_policy, 'allow_unsub': allow_unsub,
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
        # restricted is only set if there are actually fields to which access is
        # restricted
        has_restricted_fields = additional_fields & FULL_MOD_REQUIRING_FIELDS
        restricted = (not self.mlproxy.may_manage(rs, mailinglist_id,
                                                  allow_restricted=False)
                      and has_restricted_fields)
        return self.render(rs, "change_mailinglist", {
            'event_entries': event_entries,
            'assembly_entries': assembly_entries,
            'available_domains': available_domains,
            'additional_fields': additional_fields,
            'restricted': restricted,
        })

    @access("ml", modi={"POST"})
    @mailinglist_guard()
    @REQUESTdatadict(*ALL_MAILINGLIST_FIELDS)
    def change_mailinglist(self, rs: RequestState, mailinglist_id: int,
                           data: CdEDBObject) -> Response:
        """Modify simple attributes of mailinglists."""
        data['id'] = mailinglist_id

        if self.mlproxy.is_relevant_admin(rs, mailinglist_id=mailinglist_id):
            # admins may change everything except ml_type which got its own site
            allowed = set(data) - {'ml_type'}
        elif self.mlproxy.is_moderator(rs, mailinglist_id, allow_restricted=False):
            allowed = MOD_ALLOWED_FIELDS
        else:
            allowed = RESTRICTED_MOD_ALLOWED_FIELDS

        # we discard every entry of not allowed fields silently
        for key in set(data) - allowed:
            data[key] = rs.ambience['mailinglist'][key]

        data = check(rs, vtypes.Mailinglist, data)
        if rs.has_validation_errors():
            return self.change_mailinglist_form(rs, mailinglist_id)
        assert data is not None

        # Check if mailinglist address is unique and valid
        try:
            self.mlproxy.validate_address(rs, data)
        except ValueError as e:
            rs.extend_validation_errors([("local_part", e), ("domain", e)])

        if rs.has_validation_errors():
            return self.change_mailinglist_form(rs, mailinglist_id)
        code = self.mlproxy.set_mailinglist(rs, data)
        rs.notify_return_code(code)
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
    @REQUESTdatadict(*ADDITIONAL_TYPE_FIELDS.items())
    @REQUESTdata("ml_type")
    def change_ml_type(self, rs: RequestState, mailinglist_id: int,
                       ml_type: str, data: CdEDBObject) -> Response:
        ml = rs.ambience['mailinglist']
        data['id'] = mailinglist_id
        data['ml_type'] = ml_type
        data['domain'] = ml['domain']
        new_type = get_type(data['ml_type'])
        if data['domain'] not in new_type.domains:
            data['domain'] = new_type.domains[0]
        data = check(rs, vtypes.Mailinglist, data)
        if rs.has_validation_errors():
            return self.change_ml_type_form(rs, mailinglist_id)
        assert data is not None

        code = self.mlproxy.set_mailinglist(rs, data)
        rs.notify_return_code(code)
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

        rs.notify_return_code(code)
        return self.redirect(rs, "ml/list_mailinglists")

    @access("ml")
    @mailinglist_guard()
    @REQUESTdata(*LOG_FIELDS_COMMON)
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
        sub_states = const.SubscriptionState.subscribing_states()
        subscribers = self.mlproxy.get_subscription_states(
            rs, mailinglist_id, states=sub_states)
        explicits = self.mlproxy.get_subscription_addresses(
            rs, mailinglist_id, explicits_only=True)
        explicits = {k: v for (k, v) in explicits.items() if v is not None}
        requests = self.mlproxy.get_subscription_states(
            rs, mailinglist_id, states=(const.SubscriptionState.pending,))
        persona_ids = (set(rs.ambience['mailinglist']['moderators'])
                       | set(subscribers.keys()) | set(requests))
        personas = self.coreproxy.get_personas(rs, persona_ids)
        subscribers = collections.OrderedDict(
            (anid, personas[anid]) for anid in xsorted(
                subscribers,
                key=lambda anid: EntitySorter.persona(personas[anid])))
        moderators = collections.OrderedDict(
            (anid, personas[anid]) for anid in xsorted(
                rs.ambience['mailinglist']['moderators'],
                key=lambda anid: EntitySorter.persona(personas[anid])))
        requests = collections.OrderedDict(
            (anid, personas[anid]) for anid in xsorted(
            requests, key=lambda anid: EntitySorter.persona(personas[anid])))
        restricted = not self.mlproxy.may_manage(rs, mailinglist_id,
                                                 allow_restricted=False)
        allow_unsub = self.mlproxy.get_ml_type(rs, mailinglist_id).allow_unsub
        return self.render(rs, "management", {
            'subscribers': subscribers, 'requests': requests,
            'moderators': moderators, 'explicits': explicits,
            'restricted': restricted, 'allow_unsub': allow_unsub})

    @access("ml")
    @mailinglist_guard()
    def advanced_management(self, rs: RequestState, mailinglist_id: int) -> Response:
        """Render form."""
        subscription_overrides = self.mlproxy.get_subscription_states(
            rs, mailinglist_id,
            states=(const.SubscriptionState.subscription_override,))
        unsubscription_overrides = self.mlproxy.get_subscription_states(
            rs, mailinglist_id,
            states=(const.SubscriptionState.unsubscription_override,))
        all_unsubscriptions = self.mlproxy.get_subscription_states(
            rs, mailinglist_id, states=(const.SubscriptionState.unsubscribed,))
        redundant_unsubscriptions = self.mlproxy.get_redundant_unsubscriptions(
            rs, mailinglist_id)
        persona_ids = (set(rs.ambience['mailinglist']['moderators'])
                       | set(subscription_overrides.keys())
                       | set(unsubscription_overrides.keys())
                       | set(all_unsubscriptions.keys()))
        personas = self.coreproxy.get_personas(rs, persona_ids)
        subscription_overrides = collections.OrderedDict(
            (anid, personas[anid]) for anid in xsorted(
                subscription_overrides,
                key=lambda anid: EntitySorter.persona(personas[anid])))
        unsubscription_overrides = collections.OrderedDict(
            (anid, personas[anid]) for anid in xsorted(
                unsubscription_overrides,
                key=lambda anid: EntitySorter.persona(personas[anid])))
        all_unsubscriptions = collections.OrderedDict(
            (anid, personas[anid]) for anid in xsorted(
                all_unsubscriptions,
                key=lambda anid: EntitySorter.persona(personas[anid])))
        restricted = not self.mlproxy.may_manage(rs, mailinglist_id,
                                                 allow_restricted=False)
        return self.render(rs, "advanced_management", {
            'subscription_overrides': subscription_overrides,
            'unsubscription_overrides': unsubscription_overrides,
            'all_unsubscriptions': all_unsubscriptions,
            'redundant_unsubscriptions': redundant_unsubscriptions,
            'restricted': restricted})

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
        columns = ['db_id', 'given_names', 'display_name', 'family_name',
                   'subscription_state', 'email', 'subscription_address']
        output = []

        for persona in personas:
            pair = {
                'db_id': cdedbid(persona),
                'given_names': personas[persona]['given_names'],
                'display_name': personas[persona]['display_name'],
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
            xsorted(output, key=lambda e: EntitySorter.persona(
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

        code = self.mlproxy.add_moderators(rs, mailinglist_id, moderators)
        rs.notify_return_code(code, error=n_("Action had no effect."))
        return self.redirect(rs, "ml/management")

    @access("ml", modi={"POST"})
    @mailinglist_guard()
    @REQUESTdata("moderator_id")
    def remove_moderator(self, rs: RequestState, mailinglist_id: int,
                         moderator_id: vtypes.ID) -> Response:
        """Demote persona from moderator status."""
        moderators = set(rs.ambience['mailinglist']['moderators'])
        if moderator_id not in moderators:
            rs.append_validation_error(
                ("moderator_id", ValueError(n_("User is no moderator."))))
        if rs.has_validation_errors():
            return self.management(rs, mailinglist_id)
        if (moderator_id == rs.user.persona_id
                and not self.mlproxy.is_relevant_admin(
                    rs, mailinglist_id=mailinglist_id)):
            rs.notify("error", n_("Not allowed to remove yourself as moderator."))
            return self.management(rs, mailinglist_id)

        if {moderator_id} == moderators:
            rs.notify("error", n_("Cannot remove last moderator."))
        else:
            code = self.mlproxy.remove_moderator(rs, mailinglist_id, moderator_id)
            rs.notify_return_code(code)
        return self.redirect(rs, "ml/management")

    @access("ml", modi={"POST"})
    @mailinglist_guard()
    @REQUESTdata("email")
    def add_whitelist(self, rs: RequestState, mailinglist_id: int,
                      email: vtypes.Email) -> Response:
        """Allow address to write to the list."""
        if rs.has_validation_errors():
            return self.advanced_management(rs, mailinglist_id)

        code = self.mlproxy.add_whitelist_entry(rs, mailinglist_id, email)
        rs.notify_return_code(code, error=n_("Action had no effect."))
        return self.redirect(rs, "ml/advanced_management")

    @access("ml", modi={"POST"})
    @mailinglist_guard()
    @REQUESTdata("email")
    def remove_whitelist(self, rs: RequestState, mailinglist_id: int,
                         email: vtypes.Email) -> Response:
        """Withdraw privilege of writing to list."""
        if rs.has_validation_errors():
            return self.advanced_management(rs, mailinglist_id)

        code = self.mlproxy.remove_whitelist_entry(rs, mailinglist_id, email)
        rs.notify_return_code(code)
        return self.redirect(rs, "ml/advanced_management")

    def _subscription_action_handler(self, rs: RequestState,
                                     action: SubscriptionAction,
                                     **kwargs: Any) -> None:
        """Un-inlined code from all single subscription action initiating endpoints."""
        try:
            code = self.mlproxy.do_subscription_action(rs, action, **kwargs)
        except SubscriptionError as se:
            rs.notify(se.kind, se.msg)
        except PrivilegeError:
            rs.notify("error", n_("Not privileged to change subscriptions."))
        else:
            rs.notify_return_code(code)

    def _subscription_multi_action_handler(self, rs: RequestState,
                                           field: str,
                                           action: SubscriptionAction,
                                           mailinglist_id: int,
                                           persona_ids: Collection[int]) -> None:
        """Un-inlined code from all multi subscription action initiating endpoints.

        Falls back to _subscription_action_handler if only a single action is
        done."""
        if not self.coreproxy.verify_ids(rs, persona_ids, is_archived=False):
            rs.append_validation_error(
                (field, ValueError(n_(
                    "Some of these users do not exist or are archived."))))
            rs.notify_return_code(0)
            return

        # Use different error pattern if only one action is done
        if len(persona_ids) == 1:
            self._subscription_action_handler(rs, action, mailinglist_id=mailinglist_id,
                                              persona_id=unwrap(persona_ids))
            return
        # Iterate over all subscriber_ids
        code = 0
        # This tracks whether every single action failed with
        # an error of kind "info".
        infos_only = True
        for persona_id in persona_ids:
            try:
                code += self.mlproxy.do_subscription_action(
                    rs, action, mailinglist_id=mailinglist_id, persona_id=persona_id)
                infos_only = False
            except SubscriptionError as se:
                rs.notify("warning" if se.kind == "error" else se.kind, se.msg)
                if se.kind != 'info':
                    infos_only = False
            except PrivilegeError:
                infos_only = False
                rs.notify("error", n_("Not privileged to change subscriptions."))
        if infos_only:
            rs.notify_return_code(-1, info=n_("Action had no effect."))
        else:
            rs.notify_return_code(code)

    @access("ml", modi={"POST"})
    @mailinglist_guard(requires_privilege=True)
    @REQUESTdata("persona_id", "action")
    def handle_request(self, rs: RequestState, mailinglist_id: int,
                       persona_id: vtypes.ID, action: str) -> Response:
        """Evaluate whether to admit subscribers."""
        action_map = {
            'accept': SubscriptionAction.approve_request,
            'reject': SubscriptionAction.deny_request,
            'block': SubscriptionAction.block_request
        }
        if rs.has_validation_errors() or action not in action_map:
            return self.management(rs, mailinglist_id)
        if not self.coreproxy.verify_id(rs, persona_id, is_archived=False):
            rs.notify("error", n_("User does not exist or is archived."))
            return self.management(rs, mailinglist_id)
        self._subscription_action_handler(
            rs, action=action_map[action], mailinglist_id=mailinglist_id,
            persona_id=persona_id)
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
            rs, 'subscriber_ids', SubscriptionAction.add_subscriber,
            mailinglist_id=mailinglist_id, persona_ids=subscriber_ids)
        if rs.has_validation_errors():
            return self.management(rs, mailinglist_id)
        else:
            return self.redirect(rs, "ml/management")

    @access("ml_admin", modi={"POST"})
    @mailinglist_guard(requires_privilege=True)
    @REQUESTdata("subscriber_id")
    def readd_subscriber(self, rs: RequestState, mailinglist_id: int,
                         subscriber_id: vtypes.ID) -> Response:
        """Administratively subscribe somebody previously unsubscribed.

        This is used as a shortcut to re-subscribe an unsubscribed user from the list
        of all unsubscriptions.

        Note that this requires ml admin privileges, even if this is allowed for
        moderators in the backend. We want to prevent our moderators from being
        unnecessarily confused, since we can not imagine a real use case for them here.
        """
        if rs.has_validation_errors():
            return self.advanced_management(rs, mailinglist_id)
        if not self.coreproxy.verify_id(rs, subscriber_id, is_archived=False):
            rs.notify("error", n_("User does not exist or is archived."))
            return self.advanced_management(rs, mailinglist_id)
        self._subscription_action_handler(
            rs, SubscriptionAction.add_subscriber,
            mailinglist_id=mailinglist_id, persona_id=subscriber_id)
        return self.redirect(rs, "ml/advanced_management")

    @access("ml", modi={"POST"})
    @mailinglist_guard(requires_privilege=True)
    @REQUESTdata("subscriber_id")
    def remove_subscriber(self, rs: RequestState, mailinglist_id: int,
                          subscriber_id: vtypes.ID) -> Response:
        """Administratively unsubscribe somebody."""
        if rs.has_validation_errors():
            return self.management(rs, mailinglist_id)
        if not self.coreproxy.verify_id(rs, subscriber_id, is_archived=False):
            rs.notify("error", n_("User does not exist or is archived."))
            return self.management(rs, mailinglist_id)
        self._subscription_action_handler(
            rs, SubscriptionAction.remove_subscriber,
            mailinglist_id=mailinglist_id, persona_id=subscriber_id)
        return self.redirect(rs, "ml/management")

    @access("ml_admin", modi={"POST"})
    @REQUESTdata("unsubscription_id")
    @mailinglist_guard(requires_privilege=True)
    def reset_unsubscription(self, rs: RequestState, mailinglist_id: int,
                             unsubscription_id: vtypes.ID) -> Response:
        """Administratively reset an unsubscription state.

        This is the only way to remove an explicit association of an user with a
        mailinglist. It replaces the explicit with an implict unsubscribtion.

        This should be used with care, since it may delete a conscious decision of the
        user about his relation to this mailinglist.

        Note that this requires ml admin privileges, even if this is allowed for
        moderators in the backend. We want to prevent our moderators from being
        unnecessarily confused, since we can not imagine a real use case for them here.
        """
        if rs.has_validation_errors():
            return self.advanced_management(rs, mailinglist_id)
        if not self.coreproxy.verify_id(rs, unsubscription_id, is_archived=False):
            rs.notify("error", n_("User does not exist or is archived."))
            return self.advanced_management(rs, mailinglist_id)
        self._subscription_action_handler(
            rs, SubscriptionAction.reset,
            mailinglist_id=mailinglist_id, persona_id=unsubscription_id)
        return self.redirect(rs, "ml/advanced_management")

    @access("ml", modi={"POST"})
    @mailinglist_guard(requires_privilege=True)
    @REQUESTdata("modsubscriber_ids")
    def add_subscription_overrides(self, rs: RequestState, mailinglist_id: int,
                                   modsubscriber_ids: vtypes.CdedbIDList) -> Response:
        """Administratively subscribe somebody with moderator override."""
        if rs.has_validation_errors():
            return self.advanced_management(rs, mailinglist_id)
        self._subscription_multi_action_handler(
            rs, 'modsubscriber_ids', SubscriptionAction.add_subscription_override,
            mailinglist_id=mailinglist_id, persona_ids=modsubscriber_ids)
        if rs.has_validation_errors():
            return self.advanced_management(rs, mailinglist_id)
        else:
            return self.redirect(rs, "ml/advanced_management")

    @access("ml", modi={"POST"})
    @mailinglist_guard(requires_privilege=True)
    @REQUESTdata("modsubscriber_id")
    def remove_subscription_override(self, rs: RequestState,
                                     mailinglist_id: int,
                                     modsubscriber_id: vtypes.ID) -> Response:
        """Administratively remove somebody with moderator override."""
        if rs.has_validation_errors():
            return self.advanced_management(rs, mailinglist_id)
        if not self.coreproxy.verify_id(rs, modsubscriber_id, is_archived=False):
            rs.notify("error", n_("User does not exist or is archived."))
            return self.advanced_management(rs, mailinglist_id)
        self._subscription_action_handler(
            rs, SubscriptionAction.remove_subscription_override,
            mailinglist_id=mailinglist_id, persona_id=modsubscriber_id)
        return self.redirect(rs, "ml/advanced_management")

    @access("ml", modi={"POST"})
    @mailinglist_guard(requires_privilege=True)
    @REQUESTdata("modunsubscriber_ids")
    def add_unsubscription_overrides(self, rs: RequestState, mailinglist_id: int,
                                     modunsubscriber_ids: vtypes.CdedbIDList
                                     ) -> Response:
        """Administratively block somebody."""
        if rs.has_validation_errors():
            return self.advanced_management(rs, mailinglist_id)
        self._subscription_multi_action_handler(
            rs, 'modunsubscriber_ids', SubscriptionAction.add_unsubscription_override,
            mailinglist_id=mailinglist_id, persona_ids=modunsubscriber_ids)
        if rs.has_validation_errors():
            return self.advanced_management(rs, mailinglist_id)
        else:
            return self.redirect(rs, "ml/advanced_management")

    @access("ml", modi={"POST"})
    @mailinglist_guard(requires_privilege=True)
    @REQUESTdata("modunsubscriber_id")
    def remove_unsubscription_override(self, rs: RequestState,
                                       mailinglist_id: int,
                                       modunsubscriber_id: vtypes.ID) -> Response:
        """Administratively remove block."""
        if rs.has_validation_errors():
            return self.advanced_management(rs, mailinglist_id)
        if not self.coreproxy.verify_id(rs, modunsubscriber_id, is_archived=False):
            rs.notify("error", n_("User does not exist or is archived."))
            return self.advanced_management(rs, mailinglist_id)
        self._subscription_action_handler(
            rs, SubscriptionAction.remove_unsubscription_override,
            mailinglist_id=mailinglist_id, persona_id=modunsubscriber_id)
        return self.redirect(rs, "ml/advanced_management")

    @access("ml", modi={"POST"})
    def subscribe(self, rs: RequestState, mailinglist_id: int) -> Response:
        """Change own subscription state to subscribed or pending."""
        if rs.has_validation_errors():
            return self.show_mailinglist(rs, mailinglist_id)
        self._subscription_action_handler(
            rs, SubscriptionAction.subscribe,
            mailinglist_id=mailinglist_id)
        return self.redirect(rs, "ml/show_mailinglist")

    @access("ml", modi={"POST"})
    def request_subscription(self, rs: RequestState, mailinglist_id: int) -> Response:
        """Change own subscription state to subscribed or pending."""
        if rs.has_validation_errors():
            return self.show_mailinglist(rs, mailinglist_id)
        self._subscription_action_handler(
            rs, SubscriptionAction.request_subscription,
            mailinglist_id=mailinglist_id)
        return self.redirect(rs, "ml/show_mailinglist")

    @access("ml", modi={"POST"})
    def unsubscribe(self, rs: RequestState, mailinglist_id: int) -> Response:
        """Change own subscription state to unsubscribed."""
        if rs.has_validation_errors():
            return self.show_mailinglist(rs, mailinglist_id)
        self._subscription_action_handler(
            rs, SubscriptionAction.unsubscribe,
            mailinglist_id=mailinglist_id)
        return self.redirect(rs, "ml/show_mailinglist")

    @access("ml", modi={"POST"})
    def cancel_subscription(self, rs: RequestState, mailinglist_id: int) -> Response:
        """Cancel subscription request."""
        if rs.has_validation_errors():
            return self.show_mailinglist(rs, mailinglist_id)
        self._subscription_action_handler(
            rs, SubscriptionAction.cancel_request,
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
            rs.notify_return_code(code)
        elif email in known_addresses:
            code = self.mlproxy.set_subscription_address(
                rs, mailinglist_id=mailinglist_id,
                persona_id=rs.user.persona_id, email=email)
            rs.notify_return_code(code)
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
        rs.notify_return_code(code)
        return self.redirect(rs, "ml/show_mailinglist")

    def _check_address_change_requirements(self, rs: RequestState,
                                           mailinglist_id: int,
                                           setting: bool) -> bool:
        """Check if all conditions required to change a subscription adress
        are fulfilled.
        """
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
                rs, ml_id, states=(const.SubscriptionState.pending,))
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

        self.mlproxy.write_subscription_states(rs, mailinglist_ids)

        return store
