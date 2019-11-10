#!/usr/bin/env python3

"""Services for the core realm."""

import collections
import copy
import hashlib
import os
import pathlib
import quopri
import tempfile
import datetime
import operator

import magic
import werkzeug.exceptions

from cdedb.frontend.common import (
    AbstractFrontend, REQUESTdata, REQUESTdatadict, access, basic_redirect,
    check_validation as check, request_extractor, REQUESTfile,
    request_dict_extractor, event_usage, querytoparams_filter, ml_usage,
    csv_output, query_result_to_json, enum_entries_filter, periodic)
from cdedb.common import (
    n_, ProxyShim, pairwise, extract_roles, unwrap, PrivilegeError, name_key,
    now, merge_dicts, ArchiveError, implied_realms, SubscriptionActions,
    REALM_INHERITANCE)
from cdedb.backend.core import CoreBackend
from cdedb.backend.cde import CdEBackend
from cdedb.backend.assembly import AssemblyBackend
from cdedb.backend.ml import MlBackend
from cdedb.backend.event import EventBackend
from cdedb.backend.past_event import PastEventBackend
from cdedb.query import QUERY_SPECS, mangle_query_input, Query, QueryOperators
from cdedb.database.connection import Atomizer
from cdedb.validation import (
    _PERSONA_CDE_CREATION as CDE_TRANSITION_FIELDS,
    _PERSONA_EVENT_CREATION as EVENT_TRANSITION_FIELDS)
import cdedb.database.constants as const
import cdedb.validation as validate


class CoreFrontend(AbstractFrontend):
    """Note that there is no user role since the basic distinction is between
    anonymous access and personas. """
    realm = "core"

    def __init__(self, configpath):
        """
        :type configpath: str
        """
        super().__init__(configpath)
        self.coreproxy = ProxyShim(CoreBackend(configpath))
        self.cdeproxy = ProxyShim(CdEBackend(configpath))
        self.assemblyproxy = ProxyShim(AssemblyBackend(configpath))
        self.mlproxy = ProxyShim(MlBackend(configpath))
        self.eventproxy = ProxyShim(EventBackend(configpath))
        self.pasteventproxy = ProxyShim(PastEventBackend(configpath))

    def finalize_session(self, rs, connpool, auxilliary=False):
        super().finalize_session(rs, connpool, auxilliary=auxilliary)

    @classmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

    @access("anonymous")
    @event_usage
    @ml_usage
    @REQUESTdata(("wants", "#str_or_None"))
    def index(self, rs, wants=None):
        """Basic entry point.

        :type rs: :py:class:`cdedb.common.RequestState`
        :param wants: URL to redirect to upon login
        """
        meta_info = self.coreproxy.get_meta_info(rs)
        dashboard = {}
        if not rs.user.persona_id:
            if wants:
                rs.values['wants'] = self.encode_parameter(
                    "core/login", "wants", wants,
                    timeout=self.conf.UNCRITICAL_PARAMETER_TIMEOUT)
            return self.render(rs, "login", {'meta_info': meta_info})

        else:
            # Redirect to wanted page, if user meanwhile logged in
            if wants:
                return basic_redirect(rs, wants)

            # genesis cases
            if {"core_admin", "event_admin", "ml_admin"} & rs.user.roles:
                realms = []
                if {"core_admin", "event_admin"} & rs.user.roles:
                    realms.append("event")
                if {"core_admin", "ml_admin"} & rs.user.roles:
                    realms.append("ml")
                data = self.coreproxy.genesis_list_cases(
                    rs, stati=(const.GenesisStati.to_review,), realms=realms)
                dashboard['genesis_cases'] = len(data)
            # pending changes
            if self.is_admin(rs):
                data = self.coreproxy.changelog_get_changes(
                    rs, stati=(const.MemberChangeStati.pending,))
                dashboard['pending_changes'] = len(data)
            # pending privilege changes
            if "meta_admin" in rs.user.roles:
                stati = (const.PrivilegeChangeStati.pending,)
                data = self.coreproxy.list_privilege_changes(
                    rs, stati=stati)
                dashboard['privilege_changes'] = len(data)
            # events organized
            orga_info = self.eventproxy.orga_info(rs, rs.user.persona_id)
            if orga_info:
                orga = {}
                events = self.eventproxy.get_events(rs, orga_info)
                present = now()
                for event_id, event in events.items():
                    begin = event['begin']
                    if (not begin or begin >= present.date()
                            or abs(begin.year - present.year) < 2):
                        regs = self.eventproxy.list_registrations(rs,
                                                                  event['id'])
                        event['registrations'] = len(regs)
                        orga[event_id] = event
                dashboard['orga'] = orga
                dashboard['present'] = present
            # mailinglists moderated
            moderator_info = self.mlproxy.moderator_info(rs, rs.user.persona_id)
            if moderator_info:
                moderator = self.mlproxy.get_mailinglists(rs, moderator_info)
                sub_request = const.SubscriptionStates.pending
                for mailinglist_id, mailinglist in moderator.items():
                    requests = self.mlproxy.get_subscription_states(
                        rs, mailinglist_id, states=(sub_request,))
                    mailinglist['requests'] = len(requests)
                dashboard['moderator'] = moderator
            # visible and open events
            if "event" in rs.user.roles:
                event_ids = self.eventproxy.list_db_events(
                    rs, visible=True, current=True, archived=False)
                events = self.eventproxy.get_events(rs, event_ids.keys())
                final = {}
                for event_id, event in events.items():
                    if event_id not in orga_info:
                        registration = self.eventproxy.list_registrations(
                            rs, event_id, rs.user.persona_id)
                        event['registration'] = bool(registration)
                        # Skip event, if the registration begins more than
                        # 2 weeks in future
                        if event['registration_start'] and \
                                now() + datetime.timedelta(weeks=2) < \
                                event['registration_start']:
                            continue
                        # Skip events, that are over or are not registerable
                        # anymore
                        if event['registration_hard_limit'] and \
                                now() > event['registration_hard_limit'] \
                                and not event['registration'] \
                                or now().date() > event['end']:
                            continue
                        final[event_id] = event
                if final:
                    dashboard['events'] = final
            # open assemblies
            if "assembly" in rs.user.roles:
                assembly_ids = self.assemblyproxy.list_assemblies(
                    rs, is_active=True)
                assemblies = self.assemblyproxy.get_assemblies(
                    rs, assembly_ids.keys())
                final = {}
                for assembly_id, assembly in assemblies.items():
                    assembly['does_attend'] = self.assemblyproxy.does_attend(
                        rs, assembly_id=assembly_id)
                    if (assembly['does_attend']
                            or assembly['signup_end'] > now()):
                        final[assembly_id] = assembly
                if final:
                    dashboard['assemblies'] = final
            return self.render(rs, "index", {
                'meta_info': meta_info, 'dashboard': dashboard})

    @access("core_admin")
    def meta_info_form(self, rs):
        """Render form."""
        info = self.coreproxy.get_meta_info(rs)
        merge_dicts(rs.values, info)
        return self.render(rs, "meta_info")

    @access("core_admin", modi={"POST"})
    def change_meta_info(self, rs):
        """Change the meta info constants."""
        info = self.coreproxy.get_meta_info(rs)
        data_params = tuple((key, "str_or_None") for key in info)
        data = request_extractor(rs, data_params)
        data = check(rs, "meta_info", data, keys=info.keys())
        if rs.errors:
            return self.meta_info_form(rs)
        code = self.coreproxy.set_meta_info(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "core/meta_info_form")

    @access("anonymous", modi={"POST"})
    @REQUESTdata(("username", "printable_ascii"), ("password", "str"),
                 ("wants", "#str_or_None"))
    def login(self, rs, username, password, wants):
        """Create session.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type username: printable_ascii
        :type password: str
        :param wants: URL to redirect to
        """
        if rs.errors:
            return self.index(rs)
        sessionkey = self.coreproxy.login(rs, username, password,
                                          rs.request.remote_addr)
        if not sessionkey:
            rs.notify("error", n_("Login failure."))
            rs.errors.extend((("username", ValueError()),
                              ("password", ValueError())))
            return self.index(rs)

        if wants:
            basic_redirect(rs, wants)
        elif "member" in rs.user.roles and "searchable" not in rs.user.roles:
            data = self.coreproxy.get_cde_user(rs, rs.user.persona_id)
            if not data['decided_search']:
                self.redirect(rs, "cde/consent_decision_form")
            else:
                self.redirect(rs, "core/index")
        else:
            self.redirect(rs, "core/index")
        rs.response.set_cookie("sessionkey", sessionkey, httponly=True,
                               secure=True, samesite="Lax")
        return rs.response

    # We don't check anti CSRF tokens here, since logging does not harm anyone.
    @access("persona", modi={"POST"}, check_anti_csrf=False)
    def logout(self, rs):
        """Invalidate session."""
        self.coreproxy.logout(rs)
        self.redirect(rs, "core/index")
        rs.response.delete_cookie("sessionkey")
        return rs.response

    @access("anonymous", modi={"POST"})
    @REQUESTdata(("locale", "printable_ascii"), ("wants", "#str_or_None"))
    def change_locale(self, rs, locale, wants):
        """Set 'locale' cookie to override default locale for this user/browser.

        :type rs: :py:class:`cdedb.common.RequestState`
        :param locale: The target locale
        :param wants: URL to redirect to (typically URL of the previous page)
        """
        if wants:
            basic_redirect(rs, wants)
        else:
            self.redirect(rs, "core/index")

        if locale in self.conf.I18N_LANGUAGES:
            rs.response.set_cookie(
                "locale", locale,
                expires=now() + datetime.timedelta(days=10 * 365))
        else:
            rs.notify("error", n_("Unsupported locale"))
        return rs.response

    @access("persona")
    def mydata(self, rs):
        """Convenience entry point for own data."""
        return self.redirect_show_user(rs, rs.user.persona_id)

    @access("persona")
    @event_usage
    @ml_usage
    @REQUESTdata(("confirm_id", "#int"), ("quote_me", "bool"),
                 ("event_id", "id_or_None"), ("ml_id", "id_or_None"))
    def show_user(self, rs, persona_id, confirm_id, quote_me, event_id, ml_id,
                  internal=False):
        """Display user details.

        This has an additional encoded parameter to make links to this
        target unguessable. Thus it is more difficult to algorithmically
        extract user data from the web frontend.

        The quote_me parameter controls access to member datasets by
        other members. Since there is a quota you only want to retrieve
        them if explicitly asked for.

        The event_id and ml_id parameters control access in the context of
        events and mailinglists, so that orgas and moderators can see their
        users. This has the additional property, that event/ml admins count
        as if they are always orga/moderator (otherwise they would observe
        breakage).

        The internal parameter signals that the call is from another
        frontend function and not an incoming request. This allows to access
        this endpoint without a redirect to preserve validation results.
        """
        if (persona_id != confirm_id or rs.errors) and not internal:
            return self.index(rs)
        if (rs.ambience['persona']['is_archived']
                and "core_admin" not in rs.user.roles):
            raise werkzeug.exceptions.Forbidden(
                n_("Only admins may view archived datasets."))

        is_relative_admin = self.coreproxy.is_relative_admin(rs, persona_id)

        ALL_ACCESS_LEVELS = {
            "persona", "ml", "assembly", "event", "cde", "core", "meta",
            "orga", "moderator"}
        # The basic access level provides only the name (this should only
        # happen in case of un-quoted searchable member access)
        access_levels = {"persona"}
        # Let users see themselves
        if persona_id == rs.user.persona_id:
            access_levels.update(ALL_ACCESS_LEVELS)
        # Core admins see everything
        if "core_admin" in rs.user.roles:
            access_levels.update(ALL_ACCESS_LEVELS)
        # Meta admins are meta
        if "meta_admin" in rs.user.roles:
            access_levels.add("meta")
        # Other admins see their realm if they are relative admin
        if is_relative_admin:
            # Relative admins can see core data
            access_levels.add("core")
            for realm in ("ml", "assembly", "event", "cde"):
                if "{}_admin".format(realm) in rs.user.roles:
                    access_levels.add(realm)
        # Members see other members (modulo quota)
        if "searchable" in rs.user.roles and quote_me:
            if (not rs.ambience['persona']['is_searchable']
                    and "cde_admin" not in access_levels):
                raise werkzeug.exceptions.Forbidden(n_(
                    "Access to non-searchable member data."))
            access_levels.add("cde")
        # Orgas see their participants
        if event_id:
            is_orga = ("event_admin" in rs.user.roles
                       or event_id in self.eventproxy.orga_info(
                        rs, rs.user.persona_id))
            is_participant = self.eventproxy.list_registrations(
                rs, event_id, persona_id)
            if is_orga and is_participant:
                access_levels.add("event")
                access_levels.add("orga")
        # Mailinglist moderators see all users related to their mailinglist.
        # This excludes users with relation "unsubscribed", because they are not
        # directly shown on the management sites.
        if ml_id:
            is_moderator = (
                    "ml_admin" in rs.user.roles
                    or ml_id in self.mlproxy.moderator_info(
                        rs, rs.user.persona_id))
            if is_moderator:
                relevant_stati = [s for s in const.SubscriptionStates
                                  if s != const.SubscriptionStates.unsubscribed]
                if persona_id in self.mlproxy.get_subscription_states(
                        rs, ml_id, states=relevant_stati):
                    access_levels.add("ml")
                    # the moderator access level currently does nothing, but we
                    # add it anyway to be less confusing
                    access_levels.add("moderator")

        # Retrieve data
        #
        # This is the basic mechanism for restricting access, since we only
        # add attributes for which an access level is provided.
        roles = extract_roles(rs.ambience['persona'], introspection_only=True)
        data = self.coreproxy.get_persona(rs, persona_id)
        # The base version of the data set should only contain the name,
        # however the PERSONA_CORE_FIELDS also contain the email address
        # which we must delete beforehand.
        del data['username']
        if "ml" in access_levels and "ml" in roles:
            data.update(self.coreproxy.get_ml_user(rs, persona_id))
        if "assembly" in access_levels and "assembly" in roles:
            data.update(self.coreproxy.get_assembly_user(rs, persona_id))
        if "event" in access_levels and "event" in roles:
            data.update(self.coreproxy.get_event_user(rs, persona_id))
        if "cde" in access_levels and "cde" in roles:
            data.update(self.coreproxy.get_cde_user(rs, persona_id))
            if "core" in access_levels and "member" in roles:
                user_lastschrift = self.cdeproxy.list_lastschrift(
                    rs, persona_ids=(persona_id,), active=True)
                data['has_lastschrift'] = len(user_lastschrift) > 0
        if is_relative_admin:
            # This is a bit involved to not contaminate the data dict
            # with keys which are not applicable to the requested persona
            total = self.coreproxy.get_total_persona(rs, persona_id)
            data['notes'] = total['notes']

        # Cull unwanted data
        if (not ('is_cde_realm' in data and data['is_cde_realm'])
                 and 'foto' in data):
            del data['foto']
        if "core" not in access_levels:
            masks = ["balance", "decided_search", "trial_member", "bub_search",
                     "is_searchable"]
            if "meta" not in access_levels:
                masks.extend([
                    "is_active", "is_meta_admin", "is_core_admin",
                    "is_cde_admin", "is_event_admin", "is_ml_admin",
                    "is_assembly_admin", "is_cde_realm", "is_event_realm",
                    "is_ml_realm", "is_assembly_realm", "is_archived"])
            if "orga" not in access_levels and not is_relative_admin:
                masks.append("is_member")
            for key in masks:
                if key in data:
                    del data[key]
        if not is_relative_admin and "notes" in data:
            del data['notes']

        # Add past event participation info
        past_events = None
        if "cde" in access_levels and {"event", "cde"} & roles:
            participation_info = self.pasteventproxy.participation_info(
                rs, persona_id)
            # Group participation data by pevent_id: First get distinct past
            # events from participation data, afterwards add dict of courses
            past_events = {
                pi['pevent_id']: {
                    k: pi[k]
                    for k in ('pevent_id', 'event_name', 'tempus', 'is_orga')}
                for pi in participation_info}
            for past_event_id, past_event in past_events.items():
                past_event['courses'] = {
                    pi['pcourse_id']: {
                        k: pi[k]
                        for k in ('pcourse_id', 'course_name', 'nr',
                                  'is_instructor')}
                    for pi in participation_info
                    if (pi['pevent_id'] == past_event_id and
                        pi['pcourse_id'] is not None)
                }

        # Check whether we should display an option for using the quota
        quoteable = (not quote_me
                     and "cde" not in access_levels
                     and "searchable" in rs.user.roles
                     and rs.ambience['persona']['is_searchable'])

        meta_info = self.coreproxy.get_meta_info(rs)

        return self.render(rs, "show_user", {
            'data': data, 'past_events': past_events, 'meta_info': meta_info,
            'is_relative_admin': is_relative_admin, 'quoteable': quoteable})

    @access("core_admin", "cde_admin", "event_admin", "ml_admin",
            "assembly_admin")
    def show_history(self, rs, persona_id):
        """Display user history."""
        if not self.coreproxy.is_relative_admin(rs, persona_id):
            raise werkzeug.exceptions.Forbidden(n_("Not a relative admin."))
        if rs.ambience['persona']['is_archived']:
            rs.notify("error", n_("Persona is archived."))
            return self.redirect_show_user(rs, persona_id)
        history = self.coreproxy.changelog_get_history(rs, persona_id,
                                                       generations=None)
        current_generation = self.coreproxy.changelog_get_generation(
            rs, persona_id)
        current = history[current_generation]
        fields = current.keys()
        stati = const.MemberChangeStati
        constants = {}
        for f in fields:
            total_const = tuple()
            tmp = []
            already_committed = False
            for x, y in pairwise(sorted(history.keys())):
                if history[x]['change_status'] == stati.committed:
                    already_committed = True
                # Somewhat involved determination of a field being constant.
                #
                # Basically it's done by the following line, except we
                # don't want to mask a change that was rejected and then
                # resubmitted and accepted.
                is_constant = history[x][f] == history[y][f]
                if (history[x]['change_status'] == stati.nacked
                        and not already_committed):
                    is_constant = False
                if is_constant:
                    tmp.append(y)
                else:
                    already_committed = False
                    if tmp:
                        total_const += tuple(tmp)
                        tmp = []
            if tmp:
                total_const += tuple(tmp)
            constants[f] = total_const
        pending = {i for i in history
                   if history[i]['change_status'] == stati.pending}
        # Track the omitted information whether a new value finally got
        # committed or not.
        #
        # This is necessary since we only show those data points, where the
        # data (e.g. the name) changes. This does especially not detect
        # meta-data changes (e.g. the change-status).
        eventual_status = {f: {gen: entry['change_status']
                               for gen, entry in history.items()
                               if gen not in constants[f]}
                           for f in fields}
        for f in fields:
            for gen in sorted(history):
                if gen in constants[f]:
                    anchor = max(g for g in eventual_status[f] if g < gen)
                    this_status = history[gen]['change_status']
                    if this_status == stati.committed:
                        eventual_status[f][anchor] = stati.committed
                    if (this_status == stati.nacked
                            and eventual_status[f][anchor] != stati.committed):
                        eventual_status[f][anchor] = stati.nacked
                    if (this_status == stati.pending
                            and (eventual_status[f][anchor]
                                 not in (stati.committed, stati.nacked))):
                        eventual_status[f][anchor] = stati.pending
        persona_ids = {e['submitted_by'] for e in history.values()}
        persona_ids = persona_ids | {e['reviewed_by'] for e in history.values()
                                     if e['reviewed_by']}
        personas = self.coreproxy.get_personas(rs, persona_ids)
        return self.render(rs, "show_history", {
            'entries': history, 'constants': constants, 'current': current,
            'pending': pending, 'eventual_status': eventual_status,
            'personas': personas})

    @access("core_admin")
    @REQUESTdata(("phrase", "str"))
    def admin_show_user(self, rs, phrase):
        """Allow admins to view any user data set.

        The search phrase may be anything: a numeric id (wellformed with
        check digit or without) or a string matching the data set.
        """
        if rs.errors:
            return self.index(rs)
        anid, errs = validate.check_cdedbid(phrase, "phrase")
        if not errs:
            if self.coreproxy.verify_ids(rs, (anid,)):
                return self.redirect_show_user(rs, anid)
        anid, errs = validate.check_id(phrase, "phrase")
        if not errs:
            if self.coreproxy.verify_ids(rs, (anid,)):
                return self.redirect_show_user(rs, anid)
        terms = tuple(t.strip() for t in phrase.split(' ') if t)
        search = [("username,family_name,given_names,display_name",
                   QueryOperators.match, t) for t in terms]
        spec = copy.deepcopy(QUERY_SPECS["qview_core_user"])
        spec["username,family_name,given_names,display_name"] = "str"
        query = Query(
            "qview_core_user",
            spec,
            ("personas.id",),
            search,
            (("personas.id", True),))
        result = self.coreproxy.submit_general_query(rs, query)
        if len(result) == 1:
            return self.redirect_show_user(rs, result[0]["id"])
        elif len(result) > 0:
            # TODO make this accessible
            pass
        query = Query(
            "qview_core_user",
            spec,
            ("personas.id", "username", "family_name", "given_names",
             "display_name"),
            [('fulltext', QueryOperators.containsall, terms)],
            (("personas.id", True),))
        result = self.coreproxy.submit_general_query(rs, query)
        if len(result) == 1:
            return self.redirect_show_user(rs, result[0]["id"])
        elif len(result) > 0:
            params = querytoparams_filter(query)
            rs.values.update(params)
            return self.user_search(rs, is_search=True, download=None,
                                    query=query)
        else:
            rs.notify("warning", n_("No account found."))
            return self.index(rs)

    @access("persona")
    @event_usage
    @ml_usage
    @REQUESTdata(("phrase", "str"), ("kind", "str"), ("aux", "id_or_None"),
                 ("variant", "non_negative_int_or_None"))
    def select_persona(self, rs, phrase, kind, aux, variant=None):
        """Provide data for intelligent input fields.

        This searches for users by name so they can be easily selected
        without entering their numerical ids. This is for example
        intended for addition of orgas to events.

        The kind parameter specifies the purpose of the query which decides
        the privilege level required and the basic search paramaters.

        Allowed kinds:

        - ``admin_persona``: Search for users as core_admin
        - ``past_event_user``: Search for an event user to add to a past
          event as cde_admin
        - ``pure_assembly_user``: Search for an assembly only user as
          assembly_admin
        - ``ml_admin_user``: Search for a mailinglist user as ml_admin
        - ``mod_ml_user``: Search for a mailinglist user as a moderator
        - ``event_admin_user``: Search an event user as event_admin (for
          creating events)
        - ``orga_event_user``: Search for an event user as event orga

        The aux parameter allows to supply an additional id for example
        in the case of a moderator this would be the relevant
        mailinglist id.

        Required aux value based on the 'kind':
        * mod_ml_user: Id of the mailinglist you are moderator of
        * orga_event_user: Id of the event you are orga of

        The variant parameter allows to supply an additional integer to
        distinguish between different variants of a given search kind.
        Usually, this will be an enum member marking the kind of action taken.

        Possible variants based on the 'kind':
        * mod_ml_user: Which action you are going to execute on this user.
          A member of the SubscriptionActions enum.
        """
        if rs.errors:
            return self.send_json(rs, {})

        spec_additions = {}
        search_additions = []
        mailinglist = None
        event = None
        num_preview_personas = (self.conf.NUM_PREVIEW_PERSONAS_CORE_ADMIN
                                if {"core_admin"} & rs.user.roles
                                else self.conf.NUM_PREVIEW_PERSONAS)
        if kind == "admin_persona":
            if not {"core_admin", "cde_admin"} & rs.user.roles:
                raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        elif kind == "past_event_user":
            if "cde_admin" not in rs.user.roles:
                raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
            search_additions.append(
                ("is_event_realm", QueryOperators.equal, True))
        elif kind == "pure_assembly_user":
            if "assembly_admin" not in rs.user.roles:
                raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
            search_additions.append(
                ("is_assembly_realm", QueryOperators.equal, True))
            search_additions.append(
                ("is_member", QueryOperators.equal, False))
        elif kind == "ml_admin_user":
            if "ml_admin" not in rs.user.roles:
                raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
            search_additions.append(
                ("is_ml_realm", QueryOperators.equal, True))
        elif kind == "mod_ml_user" and aux:
            mailinglist = self.mlproxy.get_mailinglist(rs, aux)
            if not self.mlproxy.may_manage(rs, aux):
                raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
            search_additions.append(
                ("is_ml_realm", QueryOperators.equal, True))
        elif kind == "event_admin_user":
            if "event_admin" not in rs.user.roles:
                raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
            search_additions.append(
                ("is_event_realm", QueryOperators.equal, True))
        elif kind == "orga_event_user" and aux:
            event = self.eventproxy.get_event(rs, aux)
            if "event_admin" not in rs.user.roles:
                if rs.user.persona_id not in event['orgas']:
                    raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
            search_additions.append(
                ("is_event_realm", QueryOperators.equal, True))
        else:
            return self.send_json(rs, {})

        data = None

        # Core admins and meta admins are allowed to search by raw ID or
        # CDEDB-ID
        if "core_admin" in rs.user.roles:
            anid, errs = validate.check_cdedbid(phrase, "phrase")
            if not errs:
                tmp = self.coreproxy.get_personas(rs, (anid,))
                if tmp:
                    data = [unwrap(tmp)]
            else:
                anid, errs = validate.check_id(phrase, "phrase")
                if not errs:
                    tmp = self.coreproxy.get_personas(rs, (anid,))
                    if tmp:
                        data = [unwrap(tmp)]

        # Don't query, if search phrase is too short
        if not data and len(phrase) < self.conf.NUM_PREVIEW_CHARS:
            return self.send_json(rs, {})

        terms = []
        if data is None:
            terms = tuple(t.strip() for t in phrase.split(' ') if t)
            valid = True
            for t in terms:
                _, errs = validate.check_non_regex(t, "phrase")
                if errs:
                    valid = False
            if not valid:
                data = []
            else:
                search = [("username,family_name,given_names,display_name",
                           QueryOperators.match, t) for t in terms]
                search.extend(search_additions)
                spec = copy.deepcopy(QUERY_SPECS["qview_core_user"])
                spec["username,family_name,given_names,display_name"] = "str"
                spec.update(spec_additions)
                query = Query(
                    "qview_core_user", spec,
                    ("personas.id", "username", "family_name", "given_names",
                     "display_name"), search, (("personas.id", True),))
                data = self.coreproxy.submit_select_persona_query(rs, query)

        # Filter result to get only valid audience, if mailinglist is given
        if mailinglist:
            pol = const.MailinglistInteractionPolicy
            action = check(rs, "enum_subscriptionactions_or_None", variant)
            if rs.errors:
                return self.send_json(rs, {})
            if action == SubscriptionActions.add_subscriber:
                allowed_pols = {pol.opt_out, pol.opt_in, pol.moderated_opt_in,
                                pol.invitation_only}
                data = self.mlproxy.filter_personas_by_policy(
                    rs, mailinglist, data, allowed_pols)

        # Strip data to contain at maximum `num_preview_personas` results
        if len(data) > num_preview_personas:
            tmp = sorted(data, key=lambda e: e['id'])
            data = tmp[:num_preview_personas]

        def name(x):
            return "{} {}".format(x['given_names'], x['family_name'])

        # Check if name occurs multiple times to add email address in this case
        counter = collections.defaultdict(lambda: 0)
        for entry in data:
            counter[name(entry)] += 1

        # Generate return JSON list
        ret = []
        for entry in sorted(data, key=name_key):
            result = {
                'id': entry['id'],
                'name': name(entry),
                'display_name': entry['display_name'],
            }
            # Email/username is only delivered if we have relative_admins
            # rights, a search term with an @ (and more) matches the mail
            # address, or the mail address is required to distinguish equally
            # named users
            searched_email = any(
                '@' in t and len(t) > self.conf.NUM_PREVIEW_CHARS
                and entry['username'] and t in entry['username']
                for t in terms)
            if counter[name(entry)] > 1 or searched_email or \
                    self.coreproxy.is_relative_admin(rs, entry['id']):
                result['email'] = entry['username']
            ret.append(result)
        return self.send_json(rs, {'personas': ret})

    @access("persona")
    def change_user_form(self, rs):
        """Render form."""
        generation = self.coreproxy.changelog_get_generation(
            rs, rs.user.persona_id)
        data = unwrap(self.coreproxy.changelog_get_history(
            rs, rs.user.persona_id, (generation,)))
        if data['change_status'] == const.MemberChangeStati.pending:
            rs.notify("info", n_("Change pending."))
        del data['change_note']
        merge_dicts(rs.values, data)
        return self.render(rs, "change_user", {'username': data['username']})

    @access("persona", modi={"POST"})
    @REQUESTdata(("generation", "int"))
    def change_user(self, rs, generation):
        """Change own data set."""
        REALM_ATTRIBUTES = {
            'persona': {
                "display_name", "family_name", "given_names", "title",
                "name_supplement"},
            'ml': set(),
            'assembly': set(),
            'event': {
                "telephone", "mobile", "address_supplement", "address",
                "postal_code", "location", "country"},
            'cde': {
                "telephone", "mobile", "address_supplement", "address",
                "postal_code", "location", "country",
                "address_supplement2", "address2", "postal_code2", "location2",
                "country2", "weblink", "specialisation", "affiliation",
                "timeline", "interests", "free_form",
                "birth_name"}
        }
        attributes = REALM_ATTRIBUTES['persona']
        for realm in ('ml', 'assembly', 'event', 'cde'):
            if realm in rs.user.roles:
                attributes = attributes.union(REALM_ATTRIBUTES[realm])
        data = request_dict_extractor(rs, attributes)
        data['id'] = rs.user.persona_id
        data = check(rs, "persona", data)
        if rs.errors:
            return self.change_user_form(rs)
        change_note = "Normale Änderung."
        code = self.coreproxy.change_persona(rs, data, generation=generation,
                                             change_note=change_note)
        self.notify_return_code(rs, code)
        return self.redirect_show_user(rs, rs.user.persona_id)

    @access("core_admin")
    @REQUESTdata(("download", "str_or_None"), ("is_search", "bool"))
    def user_search(self, rs, download, is_search, query=None):
        """Perform search.

        The parameter ``download`` signals whether the output should be a
        file. It can either be "csv" or "json" for a corresponding
        file. Otherwise an ordinary HTML-page is served.

        is_search signals whether the page was requested by an actual
        query or just to display the search form.

        If the parameter query is specified this query is executed
        instead. This is meant for calling this function
        programmatically.
        """
        spec = copy.deepcopy(QUERY_SPECS['qview_core_user'])
        if query:
            query = check(rs, "query", query, "query")
        elif is_search:
            # mangle the input, so we can prefill the form
            query_input = mangle_query_input(rs, spec)
            query = check(rs, "query_input", query_input, "query",
                          spec=spec, allow_empty=False)
        events = self.pasteventproxy.list_past_events(rs)
        choices = {
            'pevent_id': collections.OrderedDict(
                sorted(events.items(), key=operator.itemgetter(0)))}
        choices_lists = {k: list(v.items()) for k, v in choices.items()}
        default_queries = self.conf.DEFAULT_QUERIES['qview_core_user']
        params = {
            'spec': spec, 'choices': choices, 'choices_lists': choices_lists,
            'default_queries': default_queries, 'query': query}
        # Tricky logic: In case of no validation errors we perform a query
        if not rs.errors and is_search:
            query.scope = "qview_core_user"
            result = self.coreproxy.submit_general_query(rs, query)
            params['result'] = result
            if download:
                fields = []
                for csvfield in query.fields_of_interest:
                    fields.extend(csvfield.split(','))
                if download == "csv":
                    csv_data = csv_output(result, fields, substitutions=choices)
                    return self.send_csv_file(
                        rs, data=csv_data, inline=False,
                        filename="user_search_result.csv")
                elif download == "json":
                    json_data = query_result_to_json(result, fields,
                                                     substitutions=choices)
                    return self.send_file(
                        rs, data=json_data, inline=False,
                        filename="user_search_result.json")
        else:
            rs.values['is_search'] = is_search = False
        return self.render(rs, "user_search", params)

    @access("core_admin")
    @REQUESTdata(("download", "str_or_None"), ("is_search", "bool"))
    def archived_user_search(self, rs, download, is_search):
        """Perform search.

        Archived users are somewhat special since they are not visible
        otherwise.
        """
        spec = copy.deepcopy(QUERY_SPECS['qview_archived_persona'])
        # mangle the input, so we can prefill the form
        query_input = mangle_query_input(rs, spec)
        if is_search:
            query = check(rs, "query_input", query_input, "query", spec=spec,
                          allow_empty=False)
        else:
            query = None
        events = self.pasteventproxy.list_past_events(rs)
        choices = {
            'pevent_id': collections.OrderedDict(
                sorted(events.items(), key=operator.itemgetter(0))),
            'gender': collections.OrderedDict(
                enum_entries_filter(const.Genders, rs.gettext))
        }
        choices_lists = {k: list(v.items()) for k, v in choices.items()}
        default_queries = self.conf.DEFAULT_QUERIES['qview_archived_persona']
        params = {
            'spec': spec, 'choices': choices, 'choices_lists': choices_lists,
            'default_queries': default_queries, 'query': query}
        # Tricky logic: In case of no validation errors we perform a query
        if not rs.errors and is_search:
            query.scope = "qview_archived_persona"
            result = self.coreproxy.submit_general_query(rs, query)
            params['result'] = result
            if download:
                fields = []
                for csvfield in query.fields_of_interest:
                    fields.extend(csvfield.split(','))
                if download == "csv":
                    csv_data = csv_output(result, fields, substitutions=choices)
                    return self.send_csv_file(
                        rs, data=csv_data, inline=False,
                        filename="archived_user_search_result.csv")
                elif download == "json":
                    json_data = query_result_to_json(result, fields,
                                                     substitutions=choices)
                    return self.send_file(
                        rs, data=json_data, inline=False,
                        filename="archived_user_search_result.json")
        else:
            rs.values['is_search'] = is_search = False
        return self.render(rs, "archived_user_search", params)

    @staticmethod
    def admin_bits(rs):
        """Determine realms this admin can see.

        This is somewhat involved due to realm inheritance.

        :type rs: :py:class:`cdedb.common.RequestState`
        :rtype: {str}
        """
        ret = set()
        if "core_admin" in rs.user.roles:
            ret |= REALM_INHERITANCE.keys()
        for realm in REALM_INHERITANCE:
            if "{}_admin".format(realm) in rs.user.roles:
                ret |= {realm} | implied_realms(realm)
        return ret

    @access("core_admin", "cde_admin", "event_admin", "ml_admin",
            "assembly_admin")
    def admin_change_user_form(self, rs, persona_id):
        """Render form."""
        if not self.coreproxy.is_relative_admin(rs, persona_id):
            raise werkzeug.exceptions.Forbidden(n_("Not a relative admin."))
        if rs.ambience['persona']['is_archived']:
            rs.notify("error", n_("Persona is archived."))
            return self.redirect_show_user(rs, persona_id)

        if not self.conf.CDEDB_OFFLINE_DEPLOYMENT:
            generation = self.coreproxy.changelog_get_generation(
                rs, persona_id)
            data = unwrap(self.coreproxy.changelog_get_history(
                rs, persona_id, (generation,)))
            del data['change_note']
        else:
            data = self.coreproxy.get_event_user(rs, persona_id)
            data['change_status'] = None
            data['generation'] = -1
        merge_dicts(rs.values, data)
        if data['change_status'] == const.MemberChangeStati.pending:
            rs.notify("info", n_("Change pending."))
        return self.render(rs, "admin_change_user",
                           {'admin_bits': self.admin_bits(rs)})

    @access("core_admin", "cde_admin", "event_admin", "ml_admin",
            "assembly_admin", modi={"POST"})
    @REQUESTdata(("generation", "int"), ("change_note", "str_or_None"))
    def admin_change_user(self, rs, persona_id, generation, change_note):
        """Privileged edit of data set."""
        if not self.coreproxy.is_relative_admin(rs, persona_id):
            raise werkzeug.exceptions.Forbidden(n_("Not a relative admin."))

        REALM_ATTRIBUTES = {
            'persona': {
                "display_name", "family_name", "given_names", "title",
                "name_supplement", "notes"},
            'ml': set(),
            'assembly': set(),
            'event': {
                "gender", "birthday", "telephone", "mobile",
                "address_supplement", "address", "postal_code", "location",
                "country"},
            'cde': {
                "gender", "birthday", "telephone", "mobile",
                "address_supplement", "address", "postal_code", "location",
                "country",
                "birth_name", "address_supplement2", "address2", "postal_code2",
                "location2", "country2", "weblink", "specialisation",
                "affiliation", "timeline", "interests", "free_form",
                "is_searchable"}
        }
        attributes = REALM_ATTRIBUTES['persona']
        roles = extract_roles(rs.ambience['persona'])
        for realm in ('ml', 'assembly', 'event', 'cde'):
            if realm in roles and realm in self.admin_bits(rs):
                attributes = attributes.union(REALM_ATTRIBUTES[realm])
        data = request_dict_extractor(rs, attributes)
        data['id'] = persona_id
        data = check(rs, "persona", data)
        if rs.errors:
            return self.admin_change_user_form(rs, persona_id)

        code = self.coreproxy.change_persona(rs, data, generation=generation,
                                             change_note=change_note)
        self.notify_return_code(rs, code)
        return self.redirect_show_user(rs, persona_id)

    @access("persona")
    def view_admins(self, rs):
        """Render list of all admins of the users realms."""

        admins = {
            # meta admins
            "meta": self.coreproxy.list_admins(rs, "meta"),
            "core": self.coreproxy.list_admins(rs, "core"),
        }

        display_realms = REALM_INHERITANCE.keys() & rs.user.roles
        if "cde" in display_realms:
            display_realms.add("finance")
        for realm in display_realms:
            admins[realm] = self.coreproxy.list_admins(rs, realm)

        persona_ids = set()
        for adminlist in admins.values():
            persona_ids |= set(adminlist)
        personas = self.coreproxy.get_personas(rs, persona_ids)

        return self.render(
            rs, "view_admins", {"admins": admins, 'personas': personas})

    @access("meta_admin")
    def change_privileges_form(self, rs, persona_id):
        """Render form."""
        if rs.ambience['persona']['is_archived']:
            rs.notify("error", n_("Persona is archived."))
            return self.redirect_show_user(rs, persona_id)

        stati = (const.PrivilegeChangeStati.pending,)
        case_ids = self.coreproxy.list_privilege_changes(rs, persona_id, stati)
        if case_ids:
            rs.notify("error", n_("Resolve pending privilege change first."))
            case_id = unwrap(case_ids, keys=True)
            return self.redirect(
                rs, "core/show_privilege_change", {"case_id": case_id})

        merge_dicts(rs.values, rs.ambience['persona'])
        return self.render(rs, "change_privileges")

    @access("meta_admin", modi={"POST"})
    @REQUESTdata(
        ("is_meta_admin", "bool"), ("is_core_admin", "bool"),
        ("is_cde_admin", "bool"), ("is_finance_admin", "bool"),
        ("is_event_admin", "bool"), ("is_ml_admin", "bool"),
        ("is_assembly_admin", "bool"), ("notes", "str"))
    def change_privileges(self, rs, persona_id, is_meta_admin, is_core_admin,
                          is_cde_admin, is_finance_admin, is_event_admin,
                          is_ml_admin, is_assembly_admin, notes):
        """Grant or revoke admin bits."""
        if rs.errors:
            return self.change_privileges_form(rs, persona_id)

        stati = (const.PrivilegeChangeStati.pending,)
        case_ids = self.coreproxy.list_privilege_changes(rs, persona_id, stati)
        if case_ids:
            rs.notify("error", n_("Resolve pending privilege change first."))
            case_id = unwrap(case_ids, keys=True)
            return self.redirect(
                rs, "core/show_privilege_change", {"case_id": case_id})

        persona = self.coreproxy.get_persona(rs, persona_id)

        data = {
            "persona_id": persona_id,
            "notes": notes,
        }

        admin_keys = {"is_meta_admin", "is_core_admin", "is_cde_admin",
                      "is_finance_admin", "is_event_admin", "is_ml_admin",
                      "is_assembly_admin"}

        for key in admin_keys:
            if locals()[key] != persona[key]:
                data[key] = locals()[key]

        # see also cdedb.frontend.templates.core.change_privileges
        # and initialize_privilege_change in cdedb.backend.core

        errors = []

        if (any(k in data for k in
                ["is_meta_admin", "is_core_admin", "is_cde_admin"])
                and not rs.ambience['persona']['is_cde_realm']):
            errors.append(n_(
                "Cannot grant meta, core or CdE admin privileges to non CdE "
                "users."))

        if data.get('is_finance_admin'):
            if (data.get('is_cde_admin') is False
                    or (not rs.ambience['persona']['is_cde_admin']
                        and not data.get('is_cde_admin'))):
                errors.append(n_(
                    "Cannot grant finance admin privileges to non CdE admins."))

        if "is_ml_admin" in data and not rs.ambience['persona']['is_ml_realm']:
            errors.append(n_(
                "Cannot grant mailinglist admin privileges to non mailinglist "
                "users."))

        if ("is_event_admin" in data and
                not rs.ambience['persona']['is_event_realm']):
            errors.append(n_(
                "Cannot grant event admin privileges to non event users."))

        if ("is_assembly_admin" in data and
                not rs.ambience['persona']['is_assembly_realm']):
            errors.append(n_(
                "Cannot grant assembly admin privileges to non assembly "
                "users."))

        if "is_meta_admin" in data and data["persona_id"] == rs.user.persona_id:
            errors.append(n_("Cannot modify own meta admin privileges."))

        if errors:
            for e in errors:
                rs.notify("error", e)
            return self.change_privileges_form(rs, persona_id)

        if admin_keys & data.keys():
            code = self.coreproxy.initialize_privilege_change(rs, data)
            self.notify_return_code(
                rs, code, success=n_("Privilege change waiting for approval by "
                                     "another Meta-Admin."))
        else:
            rs.notify("info", n_("No changes were made."))
        return self.redirect_show_user(rs, persona_id)

    @access("meta_admin")
    def list_privilege_changes(self, rs):
        """Show list of privilege changes pending review."""
        case_ids = self.coreproxy.list_privilege_changes(
            rs, stati=(const.PrivilegeChangeStati.pending,))

        cases = self.coreproxy.get_privilege_changes(rs, case_ids)
        cases = {e["persona_id"]: e for e in cases.values()}

        personas = self.coreproxy.get_personas(rs, cases.keys())

        cases = collections.OrderedDict(
            sorted(cases.items(), key=lambda item: name_key(personas[item[0]])))

        return self.render(rs, "list_privilege_changes",
                           {"cases": cases, "personas": personas})

    @access("meta_admin")
    def show_privilege_change(self, rs, case_id):
        """Show detailed infromation about pending privilege change."""
        case = self.coreproxy.get_privilege_change(rs, case_id)
        if case["status"] != const.PrivilegeChangeStati.pending:
            rs.notify("error", n_("Privilege change not pending."))
            return self.redirect(rs, "core/list_privilege_changes")

        if (case["is_meta_admin"] is not None
            and case["persona_id"] == rs.user.persona_id):
            rs.notify(
                "info", n_("This privilege change is affecting your Meta-Admin"
                           " privileges, so it has to be approved by another "
                           "Meta-Admin."))
        if case["submitted_by"] == rs.user.persona_id:
            rs.notify(
                "info", n_("This privilege change was submitted by you, so it "
                           "has to be approved by another Meta-Admin."))

        persona = self.coreproxy.get_persona(rs, case["persona_id"])
        submitter = self.coreproxy.get_persona(rs, case["submitted_by"])

        return self.render(rs, "show_privilege_change",
                           {"case": case, "persona": persona,
                            "submitter": submitter})

    @access("meta_admin", modi={"POST"})
    @REQUESTdata(("ack", "bool"))
    def decide_privilege_change(self, rs, case_id, ack):
        """Approve or reject a privilege change."""
        case = self.coreproxy.get_privilege_change(rs, case_id)
        if case["status"] != const.PrivilegeChangeStati.pending:
            rs.notify("error", n_("Privilege change not pending."))
            return self.redirect(rs, "core/list_privilege_changes")
        if not ack:
            case_status = const.PrivilegeChangeStati.rejected
        else:
            case_status = const.PrivilegeChangeStati.approved
            if (case["is_meta_admin"] is not None
                and case['persona_id'] == rs.user.persona_id):
                raise werkzeug.exceptions.Forbidden(
                    n_("Cannot modify own meta admin privileges."))
            if rs.user.persona_id == case["submitted_by"]:
                raise werkzeug.exceptions.Forbidden(
                    n_("Only a different admin than the submitter "
                       "may approve a privilege change."))
        code = self.coreproxy.finalize_privilege_change(
            rs, case_id, case_status)
        self.notify_return_code(
            rs, code, success=(n_("Change committed.")
                               if ack else n_("Change rejected.")))
        return self.redirect(rs, "core/list_privilege_changes")

    @periodic("privilege_change_remind", period=24)
    def privilege_change_remind(self, rs, store):
        """Cron job for privilege changes to review.

        Send a reminder after four hours and then daily.
        """
        current = now()
        ids = self.coreproxy.list_privilege_changes(
            rs, stati=(const.PrivilegeChangeStati.pending,))
        data = self.coreproxy.get_privilege_changes(rs, ids)
        old = set(store.get('ids', [])) & set(data)
        new = set(data) - set(old)
        remind = False
        if any(data[anid]['ctime'] + datetime.timedelta(hours=4) < current
               for anid in new):
            remind = True
        if old and current.timestamp() > store.get('tstamp', 0) + 24*60*60:
            remind = True
        if remind:
            notify = (self.conf.META_ADMIN_ADDRESS,)
            self.do_mail(
                rs, "privilege_change_remind",
                {'To': tuple(notify),
                 'Subject': "Offene Änderungen von Admin-Privilegien"},
                {'count': len(data)})
            store = {
                'tstamp': current.timestamp(),
                'ids': list(data),
            }
        return store

    @access("core_admin")
    @REQUESTdata(("target_realm", "realm_or_None"))
    def promote_user_form(self, rs, persona_id, target_realm):
        """Render form.

        This has two parts. If the target realm is absent, we let the
        admin choose one. If it is present we present a mask to promote
        the user.
        """
        if rs.ambience['persona']['is_archived']:
            rs.notify("error", n_("Persona is archived."))
            return self.redirect_show_user(rs, persona_id)
        merge_dicts(rs.values, rs.ambience['persona'])
        if (target_realm
                and rs.ambience['persona']['is_{}_realm'.format(target_realm)]):
            rs.notify("warning", n_("No promotion necessary."))
            return self.redirect_show_user(rs, persona_id)
        return self.render(rs, "promote_user")

    @access("core_admin", modi={"POST"})
    @REQUESTdata(("target_realm", "realm_or_None"))
    @REQUESTdatadict(
        "title", "name_supplement", "birthday", "gender", "free_form",
        "telephone", "mobile", "address", "address_supplement", "postal_code",
        "location", "country")
    def promote_user(self, rs, persona_id, target_realm, data):
        """Add a new realm to the users ."""
        for key in tuple(k for k in data.keys() if not data[k]):
            # remove irrelevant keys, due to the possible combinations it is
            # rather lengthy to specify the exact set of them
            del data[key]
        persona = self.coreproxy.get_total_persona(rs, persona_id)
        merge_dicts(data, persona)
        # Specific fixes by target realm
        if target_realm == "cde":
            reference = CDE_TRANSITION_FIELDS()
            for key in ('trial_member', 'decided_search', 'bub_search'):
                if data[key] is None:
                    data[key] = False
        elif target_realm == "event":
            reference = EVENT_TRANSITION_FIELDS()
        else:
            reference = {}
        for key in tuple(data.keys()):
            if key not in reference and key != 'id':
                del data[key]
        data['is_{}_realm'.format(target_realm)] = True
        for realm in implied_realms(target_realm):
            data['is_{}_realm'.format(realm)] = True
        data = check(rs, "persona", data, transition=True)
        if rs.errors:
            return self.promote_user_form(rs, persona_id)
        code = self.coreproxy.change_persona_realms(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect_show_user(rs, persona_id)

    @access("cde_admin")
    def modify_membership_form(self, rs, persona_id):
        """Render form."""
        if rs.ambience['persona']['is_archived']:
            rs.notify("error", n_("Persona is archived."))
            return self.redirect_show_user(rs, persona_id)
        return self.render(rs, "modify_membership")

    @access("cde_admin", modi={"POST"})
    @REQUESTdata(("is_member", "bool"))
    def modify_membership(self, rs, persona_id, is_member):
        """Change association status.

        This is CdE-functionality so we require a cde_admin instead of a
        core_admin.
        """
        if rs.errors:
            return self.modify_membership_form(rs, persona_id)
        code = self.coreproxy.change_membership(rs, persona_id, is_member)
        self.notify_return_code(rs, code)

        if not is_member:
            lastschrift_ids = self.cdeproxy.list_lastschrift(
                rs, persona_ids=(persona_id,), active=None)
            lastschrifts = self.cdeproxy.get_lastschrifts(
                rs, lastschrift_ids.keys())
            active_permits = []
            for lastschrift in lastschrifts.values():
                if not lastschrift['revoked_at']:
                    active_permits.append(lastschrift['id'])
            if active_permits:
                active_transactions = []
                transaction_ids = self.cdeproxy.list_lastschrift_transactions(
                    rs, lastschrift_ids=active_permits,
                    stati=(const.LastschriftTransactionStati.issued,))
                if transaction_ids:
                    subject = ("Einzugsermächtigung zu ausstehender "
                               "Lastschrift widerrufen.")
                    self.do_mail(rs, "pending_lastschrift_revoked",
                                 {'To': (self.conf.MANAGEMENT_ADDRESS,),
                                  'Subject': subject},
                                 {'persona_id': persona_id})
                for active_permit in active_permits:
                    data = {
                        'id': active_permit,
                        'revoked_at': now(),
                    }
                    code = self.cdeproxy.set_lastschrift(rs, data)
                    self.notify_return_code(rs, code,
                                            success=n_("Permit revoked."))

        return self.redirect_show_user(rs, persona_id)

    @access("cde")
    def get_foto(self, rs, foto):
        """Retrieve profile picture."""
        path = self.conf.STORAGE_DIR / "foto" / foto
        mimetype = magic.from_file(str(path), mime=True)
        return self.send_file(rs, path=path, mimetype=mimetype)

    @access("cde")
    def set_foto_form(self, rs, persona_id):
        """Render form."""
        if rs.user.persona_id != persona_id and not self.is_admin(rs):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        if rs.ambience['persona']['is_archived']:
            rs.notify("error", n_("Persona is archived."))
            return self.redirect_show_user(rs, persona_id)
        foto = self.coreproxy.get_cde_user(rs, persona_id)['foto']
        return self.render(rs, "set_foto", {'foto': foto})

    @access("cde", modi={"POST"})
    @REQUESTfile("foto")
    @REQUESTdata(("delete", "bool"))
    def set_foto(self, rs, persona_id, foto, delete):
        """Set profile picture."""
        if rs.user.persona_id != persona_id and not self.is_admin(rs):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        foto = check(rs, 'profilepic_or_None', foto, "foto")
        if not foto and not delete:
            rs.errors.append(("foto", ValueError("Mustn't be empty.")))
        if rs.errors:
            return self.set_foto_form(rs, persona_id)
        previous = self.coreproxy.get_cde_user(rs, persona_id)['foto']
        myhash = None
        if foto:
            myhash = hashlib.sha512()
            myhash.update(foto)
            myhash = myhash.hexdigest()
            path = self.conf.STORAGE_DIR / 'foto' / myhash
            if not path.exists():
                with open(str(path), 'wb') as f:
                    f.write(foto)
        with Atomizer(rs):
            code = self.coreproxy.change_foto(rs, persona_id, foto=myhash)
            if previous:
                if not self.coreproxy.foto_usage(rs, previous):
                    path = self.conf.STORAGE_DIR / 'foto' / previous
                    if path.exists():
                        path.unlink()
        self.notify_return_code(rs, code, success=n_("Foto updated."))
        return self.redirect_show_user(rs, persona_id)

    @access("persona")
    def change_password_form(self, rs):
        """Render form."""
        return self.render(rs, "change_password")

    @access("persona", modi={"POST"})
    @REQUESTdata(("old_password", "str"), ("new_password", "str"),
                 ("new_password2", "str"))
    def change_password(self, rs, old_password, new_password, new_password2):
        """Update your own password."""
        if new_password != new_password2:
            rs.errors.append(("new_password",
                              ValueError(n_("Passwords don’t match."))))
            rs.errors.append(("new_password2",
                              ValueError(n_("Passwords don’t match."))))
            rs.notify("error", n_("Passwords don’t match."))
            return self.change_password_form(rs)

        new_password, errs = self.coreproxy.check_password_strength(
            rs, new_password, persona_id=rs.user.persona_id,
            argname="new_password")
        rs.errors.extend(errs)

        if rs.errors:
            if any(name == "new_password" for name, _ in rs.errors):
                rs.notify("error", n_("Password too weak."))
            return self.change_password_form(rs)
        code, message = self.coreproxy.change_password(
            rs, old_password, new_password)
        self.notify_return_code(rs, code, success=n_("Password changed."),
                                error=message)
        if not code:
            rs.errors.append(
                ("old_password", ValueError(n_("Wrong password."))))
            self.logger.info(
                "Unsuccessful password change for persona {}.".format(
                    rs.user.persona_id))
            return self.change_password_form(rs)
        else:
            return self.redirect_show_user(rs, rs.user.persona_id)

    @access("anonymous")
    def reset_password_form(self, rs):
        """Render form.

        This starts the process of anonymously resetting a password.
        """
        return self.render(rs, "reset_password")

    @access("anonymous")
    @REQUESTdata(("email", "email"))
    def send_password_reset_link(self, rs, email):
        """Send a confirmation mail.

        To prevent an adversary from changing random passwords.
        """
        if rs.errors:
            return self.reset_password_form(rs)
        exists = self.coreproxy.verify_existence(rs, email)
        if not exists:
            rs.errors.append(("email", ValueError(n_("Nonexistant user."))))
            return self.reset_password_form(rs)
        admin_exception = False
        try:
            success, message = self.coreproxy.make_reset_cookie(
                rs, email, self.conf.PARAMETER_TIMEOUT)
        except PrivilegeError:
            admin_exception = True
        else:
            if not success:
                rs.notify("error", message)
            else:
                self.do_mail(
                    rs, "reset_password",
                    {'To': (email,), 'Subject': "CdEDB Passwort zurücksetzen"},
                    {'email': self.encode_parameter(
                        "core/do_password_reset_form", "email", email,
                        timeout=self.conf.PARAMETER_TIMEOUT),
                        'cookie': message})
                msg = "Sent password reset mail to {} for IP {}."
                self.logger.info(msg.format(email, rs.request.remote_addr))
                rs.notify("success", n_("Email sent."))
        if admin_exception:
            self.do_mail(
                rs, "admin_no_reset_password",
                {'To': (email,), 'Subject': "CdEDB Passwort zurücksetzen"})
            msg = "Sent password reset denial mail to admin {} for IP {}."
            self.logger.info(msg.format(email, rs.request.remote_addr))
            rs.notify("success", n_("Email sent."))
        return self.redirect(rs, "core/index")

    @access("core_admin", "cde_admin", "event_admin", "ml_admin",
            "assembly_admin", modi={"POST"})
    def admin_send_password_reset_link(self, rs, persona_id):
        """Generate a password reset email for an arbitrary persona.

        This is the only way to reset the password of an administrator (for
        security reasons).
        """
        if rs.errors:
            return self.redirect_show_user(rs, persona_id)
        if not self.coreproxy.is_relative_admin(rs, persona_id):
            raise PrivilegeError(n_("Not a relative admin."))
        email = rs.ambience['persona']['username']
        success, message = self.coreproxy.make_reset_cookie(
            rs, email, timeout=self.conf.EMAIL_PARAMETER_TIMEOUT)
        if not success:
            rs.notify("error", message)
        else:
            self.do_mail(
                rs, "reset_password",
                {'To': (email,), 'Subject': "CdEDB Passwort zurücksetzen"},
                {'email': self.encode_parameter(
                    "core/do_password_reset_form", "email", email,
                    timeout=self.conf.EMAIL_PARAMETER_TIMEOUT),
                    'cookie': message})
            msg = "Sent password reset mail to {} for admin {}."
            self.logger.info(msg.format(email, rs.user.persona_id))
            rs.notify("success", n_("Email sent."))
        return self.redirect_show_user(rs, persona_id)

    @access("anonymous")
    @REQUESTdata(("email", "#email"), ("cookie", "str"))
    def do_password_reset_form(self, rs, email, cookie, internal=False):
        """Second form.

        Pretty similar to first form, but now we know, that the account
        owner actually wants the reset.

        The internal parameter signals that the call is from another
        frontend function and not an incoming request. This prevents
        validation from changing the target again.
        """
        if rs.errors and not internal:
            # Clean errors prior to displaying a new form for the first step
            rs.errors = []
            rs.notify("info", n_("Please try again."))
            return self.reset_password_form(rs)
        rs.values['email'] = self.encode_parameter(
            "core/do_password_reset", "email", email)
        return self.render(rs, "do_password_reset")

    @access("anonymous", modi={"POST"})
    @REQUESTdata(("email", "#email"), ("new_password", "str"),
                 ("new_password2", "str"), ("cookie", "str"))
    def do_password_reset(self, rs, email, new_password, new_password2, cookie):
        """Now we can reset to a new password."""
        if rs.errors:
            return self.reset_password_form(rs)
        if new_password != new_password2:
            rs.errors.append(("new_password",
                              ValueError(n_("Passwords don’t match."))))
            rs.errors.append(("new_password2",
                              ValueError(n_("Passwords don’t match."))))
            rs.notify("error", n_("Passwords don’t match."))
            return self.change_password_form(rs)
        new_password, errs = self.coreproxy.check_password_strength(
            rs, new_password, email=email, argname="new_password")
        rs.errors.extend(errs)

        if rs.errors:
            if any(name == "new_password" for name, _ in rs.errors):
                rs.notify("error", n_("Password too weak."))
            return self.do_password_reset_form(rs, email=email, cookie=cookie,
                                               internal=True)
        code, message = self.coreproxy.reset_password(rs, email, new_password,
                                                      cookie=cookie)
        self.notify_return_code(rs, code, success=n_("Password reset."),
                                error=message)
        if not code:
            return self.redirect(rs, "core/reset_password_form")
        else:
            return self.redirect(rs, "core/index")

    @access("persona")
    def change_username_form(self, rs):
        """Render form."""
        return self.render(rs, "change_username")

    @access("persona")
    @REQUESTdata(("new_username", "email"))
    def send_username_change_link(self, rs, new_username):
        """First verify new name with test email."""
        if new_username == rs.user.username:
            rs.errors.append(("new_username", ValueError(n_(
                "Must be different from current email address."))))
        if not rs.errors and self.coreproxy.verify_existence(rs, new_username):
            rs.errors.append(("new_username", ValueError(n_("Name collision."))))
        if rs.errors:
            return self.change_username_form(rs)
        self.do_mail(rs, "change_username",
                     {'To': (new_username,),
                      'Subject': "CdEDB Neue E-Mail-Adresse verifizieren"},
                     {'new_username': self.encode_parameter(
                         "core/do_username_change_form", "new_username",
                         new_username)})
        self.logger.info("Sent username change mail to {} for {}.".format(
            new_username, rs.user.username))
        rs.notify("success", "Email sent.")
        return self.redirect(rs, "core/index")

    @access("persona")
    @REQUESTdata(("new_username", "#email"))
    def do_username_change_form(self, rs, new_username):
        """Email is now verified or we are admin."""
        if rs.errors:
            return self.change_username_form(rs)
        rs.values['new_username'] = self.encode_parameter(
            "core/do_username_change", "new_username", new_username)
        return self.render(rs, "do_username_change", {
            'raw_email': new_username})

    @access("persona", modi={"POST"})
    @REQUESTdata(('new_username', '#email'), ('password', 'str'))
    def do_username_change(self, rs, new_username, password):
        """Now we can do the actual change."""
        if rs.errors:
            return self.change_username_form(rs)
        code, message = self.coreproxy.change_username(
            rs, rs.user.persona_id, new_username, password)
        self.notify_return_code(rs, code, success=n_("Email address changed."),
                                error=message)
        if not code:
            return self.redirect(rs, "core/change_username_form")
        else:
            self.do_mail(rs, "username_change_info",
                         {'To': (rs.user.username,),
                          'Subject': "Deine E-Mail-Adresse wurde geändert"},
                         {'new_username': new_username})
            return self.redirect(rs, "core/index")

    @access("core_admin", "cde_admin", "event_admin", "ml_admin",
            "assembly_admin")
    def admin_username_change_form(self, rs, persona_id):
        """Render form."""
        if not self.coreproxy.is_relative_admin(rs, persona_id):
            raise werkzeug.exceptions.Forbidden(n_("Not a relative admin."))
        if rs.ambience['persona']['is_archived']:
            rs.notify("error", n_("Persona is archived."))
            return self.redirect_show_user(rs, persona_id)
        data = self.coreproxy.get_persona(rs, persona_id)
        return self.render(rs, "admin_username_change", {'data': data})

    @access("core_admin", "cde_admin", "event_admin", "ml_admin",
            "assembly_admin", modi={"POST"})
    @REQUESTdata(('new_username', 'email_or_None'))
    def admin_username_change(self, rs, persona_id, new_username):
        """Change username without verification."""
        if not self.coreproxy.is_relative_admin(rs, persona_id):
            raise werkzeug.exceptions.Forbidden(n_("Not a relative admin."))
        if rs.errors:
            return self.admin_username_change_form(rs, persona_id)
        code, message = self.coreproxy.change_username(
            rs, persona_id, new_username, password=None)
        self.notify_return_code(rs, code, success=n_("Email address changed."),
                                error=message)
        if not code:
            return self.redirect(rs, "core/admin_username_change_form")
        else:
            return self.redirect_show_user(rs, persona_id)

    @access("core_admin", "cde_admin", "event_admin", "ml_admin",
            "assembly_admin", modi={"POST"})
    @REQUESTdata(("activity", "bool"))
    def toggle_activity(self, rs, persona_id, activity):
        """Enable/disable an account."""
        if not self.coreproxy.is_relative_admin(rs, persona_id):
            raise werkzeug.exceptions.Forbidden(n_("Not a relative admin."))
        if rs.errors:
            # Redirect for encoded parameter
            return self.redirect_show_user(rs, persona_id)
        if rs.ambience['persona']['is_archived']:
            rs.notify("error", n_("Persona is archived."))
            return self.redirect_show_user(rs, persona_id)
        data = {
            'id': persona_id,
            'is_active': activity,
        }
        change_note = "Aktivierungsstatus auf {activity} geändert.".format(
            activity="aktiv" if activity else "inaktiv")
        code = self.coreproxy.change_persona(rs, data, may_wait=False,
                                             change_note=change_note)
        self.notify_return_code(rs, code)
        return self.redirect_show_user(rs, persona_id)

    @access("anonymous")
    def genesis_request_form(self, rs):
        """Render form."""
        allowed_genders = set(const.Genders) - {const.Genders.not_specified}
        return self.render(rs, "genesis_request",
                           {'max_rationale': self.conf.MAX_RATIONALE,
                            'allowed_genders': allowed_genders})

    @access("anonymous", modi={"POST"})
    @REQUESTdatadict(
        "notes", "realm", "username", "given_names", "family_name", "gender",
        "birthday", "telephone", "mobile", "address_supplement", "address",
        "postal_code", "location", "country")
    def genesis_request(self, rs, data):
        """Voice the desire to become a persona.

        This initiates the genesis process.
        """
        data = check(rs, "genesis_case", data, creation=True)
        if data is None:
            return self.genesis_request_form(rs)
        if len(data['notes']) > self.conf.MAX_RATIONALE:
            rs.errors.append(("notes", ValueError(n_("Rationale too long."))))
        # We dont actually want not_specified as a valid option for event users.
        if data.get('realm') == "event":
            if data['gender'] == const.Genders.not_specified:
                rs.errors.append(
                    ("gender", ValueError(n_(
                        "Must specify gender for event realm."))))
        # We have to force a None here since the template should not have a
        # null option for event cases and the validator for ml users
        # requires this
        elif data.get('realm') == "ml":
            data['gender'] = None
        if rs.errors:
            return self.genesis_request_form(rs)
        if self.coreproxy.verify_existence(rs, data['username']):
            case_id = self.coreproxy.genesis_case_by_email(
                rs, data['username'])
            if case_id:
                # TODO this case is kind of a hack since it throws
                # away the information entered by the user, but in
                # theory this should not happen too often (reality
                # notwithstanding)
                rs.notify("info",
                          n_("Confirmation email has been resent."))
            else:
                rs.notify("error",
                          n_("Email address already in DB. Reset password."))
                return self.redirect(rs, "core/index")
        else:
            case_id = self.coreproxy.genesis_request(rs, data)
        if not case_id:
            rs.notify("error", n_("Failed."))
            return self.genesis_request_form(rs)
        self.do_mail(rs, "genesis_verify",
                     {'To': (data['username'],),
                      'Subject': "CdEDB Accountanfrage verifizieren",},
                     {'case_id': self.encode_parameter(
                         "core/genesis_verify", "case_id", case_id),
                      'given_names': data['given_names'],
                      'family_name': data['family_name'],})
        rs.notify(
            "success",
            n_("Email sent. Please follow the link contained in the email."))
        return self.redirect(rs, "core/index")

    @access("anonymous")
    @REQUESTdata(("case_id", "#int"))
    def genesis_verify(self, rs, case_id):
        """Verify the email address entered in :py:meth:`genesis_request`.

        This is not a POST since the link is shared via email.
        """
        if rs.errors:
            return self.genesis_request_form(rs)
        code, realm = self.coreproxy.genesis_verify(rs, case_id)
        self.notify_return_code(
            rs, code,
            error=n_("Verification failed. Please contact the administrators."),
            success=n_("Email verified. Wait for moderation. "
                       "You will be notified by mail."))
        if not code:
            return self.redirect(rs, "core/genesis_request_form")
        return self.redirect(rs, "core/index")

    @periodic("genesis_remind")
    def genesis_remind(self, rs, store):
        """Cron job for genesis cases to review.

        Send a reminder after four hours and then daily.
        """
        current = now()
        data = self.coreproxy.genesis_list_cases(
            rs, stati=(const.GenesisStati.to_review,))
        old = set(store.get('ids', [])) & set(data)
        new = set(data) - set(old)
        remind = False
        if any(data[id]['ctime'] + datetime.timedelta(hours=4) < current
               for id in new):
            remind = True
        if old and current.timestamp() > store.get('tstamp', 0) + 24*60*60:
            remind = True
        if remind:
            event_count = len(self.coreproxy.genesis_list_cases(
                rs, stati=(const.GenesisStati.to_review,), realms=["event"]))
            ml_count = len(self.coreproxy.genesis_list_cases(
                rs, stati=(const.GenesisStati.to_review,), realms=["ml"]))
            notify = {self.conf.MANAGEMENT_ADDRESS}
            if event_count:
                notify |= {self.conf.EVENT_ADMIN_ADDRESS}
            if ml_count:
                notify |= {self.conf.ML_ADMIN_ADDRESS}
            self.do_mail(
                rs, "genesis_requests_pending",
                {'To': tuple(notify),
                 'Subject': "Offene CdEDB Accountanfragen"},
                {'count': len(data)})
            store = {
                'tstamp': current.timestamp(),
                'ids': list(data),
            }
        return store

    @periodic("genesis_forget", period=96)
    def genesis_forget(self, rs, store):
        """Cron job for deleting unconfirmed or rejected genesis cases.

        This allows the username to be used once more.
        """
        stati = (const.GenesisStati.unconfirmed, const.GenesisStati.rejected)
        cases = self.coreproxy.genesis_list_cases(
            rs, stati=stati)

        delete = tuple(case["id"] for case in cases.values() if
                       case["ctime"] < now() - self.conf.PARAMETER_TIMEOUT)

        count = 0
        for case_id in delete:
            count += self.coreproxy.delete_genesis_case(
                rs, case_id)

        if count:
            self.logger.info(
                "genesis_forget: Deleted {} genesis cases.".format(count))

        return store

    @access("core_admin", "event_admin", "ml_admin")
    def genesis_list_cases(self, rs):
        """Compile a list of genesis cases to review."""
        realms = []
        if {"core_admin", "event_admin"} & rs.user.roles:
            realms.append("event")
        if {"core_admin", "ml_admin"} & rs.user.roles:
            realms.append("ml")
        data = self.coreproxy.genesis_list_cases(
            rs, stati=(const.GenesisStati.to_review,), realms=realms)
        cases = self.coreproxy.genesis_get_cases(rs, set(data))
        event_cases = {k: v for k, v in cases.items() if v['realm'] == 'event'}
        ml_cases = {k: v for k, v in cases.items() if v['realm'] == 'ml'}
        return self.render(rs, "genesis_list_cases", {
            'ml_cases': ml_cases, 'event_cases': event_cases})

    @access("core_admin", "event_admin", "ml_admin")
    def genesis_show_case(self, rs, case_id):
        """View a specific case."""
        case = self.coreproxy.genesis_get_case(rs, case_id)
        if (not self.is_admin(rs)
                and "{}_admin".format(case['realm']) not in rs.user.roles):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        reviewer = None
        if case['reviewer']:
            reviewer = self.coreproxy.get_persona(rs, case['reviewer'])
        return self.render(rs, "genesis_show_case", {
            'case': case, 'reviewer': reviewer})

    @access("core_admin", "event_admin", "ml_admin")
    def genesis_modify_form(self, rs, case_id):
        """Edit a specific case it."""
        case = self.coreproxy.genesis_get_case(rs, case_id)
        if (not self.is_admin(rs)
                and "{}_admin".format(case['realm']) not in rs.user.roles):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        if case['case_status'] != const.GenesisStati.to_review:
            rs.notify("error", n_("Case not to review."))
            return self.genesis_list_cases(rs)
        merge_dicts(rs.values, case)
        return self.render(rs, "genesis_modify_form")

    @access("core_admin", "event_admin", "ml_admin", modi={"POST"})
    @REQUESTdatadict(
        "notes", "realm", "username", "given_names", "family_name", "gender",
        "birthday", "telephone", "mobile", "address_supplement", "address",
        "postal_code", "location", "country")
    def genesis_modify(self, rs, case_id, data):
        """Edit a case to fix potential issues before creation."""
        data['id'] = case_id
        data = check(rs, "genesis_case", data)
        if rs.errors:
            return self.genesis_modify_form(rs, case_id)
        case = self.coreproxy.genesis_get_case(rs, case_id)
        if (not self.is_admin(rs)
                and "{}_admin".format(case['realm']) not in rs.user.roles):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        if case['case_status'] != const.GenesisStati.to_review:
            rs.notify("error", n_("Case not to review."))
            return self.genesis_list_cases(rs)
        code = self.coreproxy.genesis_modify_case(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "core/genesis_show_case")

    @access("core_admin", "event_admin", "ml_admin", modi={"POST"})
    @REQUESTdata(("case_status", "enum_genesisstati"))
    def genesis_decide(self, rs, case_id, case_status):
        """Approve or decline a genensis case.

        This either creates a new account or declines account creation.
        """
        if rs.errors:
            return self.genesis_list_cases(rs)
        case = self.coreproxy.genesis_get_case(rs, case_id)
        if (not self.is_admin(rs)
                and "{}_admin".format(case['realm']) not in rs.user.roles):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        if case['case_status'] != const.GenesisStati.to_review:
            rs.notify("error", n_("Case not to review."))
            return self.genesis_list_cases(rs)
        data = {
            'id': case_id,
            'case_status': case_status,
            'reviewer': rs.user.persona_id,
        }
        with Atomizer(rs):
            code = self.coreproxy.genesis_modify_case(rs, data)
            persona_id = bool(code)
            if code and data['case_status'] == const.GenesisStati.approved:
                persona_id = self.coreproxy.genesis(rs, case_id)
        if not persona_id:
            rs.notify("error", n_("Failed."))
            return rs.genesis_list_cases(rs)
        if case_status == const.GenesisStati.approved:
            success, cookie = self.coreproxy.make_reset_cookie(
                rs, case['username'], timeout=self.conf.EMAIL_PARAMETER_TIMEOUT)
            self.do_mail(
                rs, "genesis_approved",
                {'To': (case['username'],),
                 'Subject': "CdEDB-Account erstellt",
                 },
                {'case': case,
                 'email': self.encode_parameter(
                     "core/do_password_reset_form", "email", case['username'],
                     timeout=self.conf.EMAIL_PARAMETER_TIMEOUT),
                 'cookie': cookie,
                 })
            rs.notify("success", n_("Case approved."))
        else:
            self.do_mail(
                rs, "genesis_declined",
                {'To': (case['username'],),
                 'Subject': "CdEDB Accountanfrage abgelehnt"},
                {'case': case,
                 })
            rs.notify("info", n_("Case rejected."))
        return self.redirect(rs, "core/genesis_list_cases")

    @access("core_admin")
    def list_pending_changes(self, rs):
        """List non-committed changelog entries."""
        pending = self.coreproxy.changelog_get_changes(
            rs, stati=(const.MemberChangeStati.pending,))
        return self.render(rs, "list_pending_changes", {'pending': pending})

    @periodic("pending_changelog_remind")
    def pending_changelog_remind(self, rs, store):
        """Cron job for pending changlog entries to decide.

        Send a reminder after twelve hours and then daily.
        """
        current = now()
        data = self.coreproxy.changelog_get_changes(
            rs, stati=(const.MemberChangeStati.pending,))
        ids = {"{}/{}".format(id, e['generation']) for id, e in data.items()}
        old = set(store.get('ids', [])) & ids
        new = ids - set(old)
        remind = False
        if any(data[int(id.split('/')[0])]['ctime']
               + datetime.timedelta(hours=12) < current
               for id in new):
            remind = True
        if old and current.timestamp() > store.get('tstamp', 0) + 24*60*60:
            remind = True
        if remind:
            self.do_mail(
                rs, "changelog_requests_pending",
                {'To': (self.conf.MANAGEMENT_ADDRESS,),
                 'Subject': "Offene CdEDB Accountänderungen"},
                {'count': len(data)})
            store = {
                'tstamp': current.timestamp(),
                'ids': list(ids),
            }
        return store

    @access("core_admin")
    def inspect_change(self, rs, persona_id):
        """Look at a pending change."""
        history = self.coreproxy.changelog_get_history(rs, persona_id,
                                                       generations=None)
        pending = history[max(history)]
        if pending['change_status'] != const.MemberChangeStati.pending:
            rs.notify("warning", n_("Persona has no pending change."))
            return self.list_pending_changes(rs)
        current = history[max(
            key for key in history
            if (history[key]['change_status']
                == const.MemberChangeStati.committed))]
        diff = {key for key in pending if current[key] != pending[key]}
        return self.render(rs, "inspect_change", {
            'pending': pending, 'current': current, 'diff': diff})

    @access("core_admin", modi={"POST"})
    @REQUESTdata(("generation", "int"), ("ack", "bool"))
    def resolve_change(self, rs, persona_id, generation, ack):
        """Make decision."""
        if rs.errors:
            return self.list_pending_changes(rs)
        code = self.coreproxy.changelog_resolve_change(rs, persona_id,
                                                       generation, ack)
        message = n_("Change committed.") if ack else n_("Change dropped.")
        self.notify_return_code(rs, code, success=message)
        return self.redirect(rs, "core/list_pending_changes")

    @access("core_admin", "cde_admin", modi={"POST"})
    @REQUESTdata(("ack_delete", "bool"), ("note", "str"))
    def archive_persona(self, rs, persona_id, ack_delete, note):
        """Move a persona to the attic."""
        if not ack_delete:
            rs.errors.append(("ack_delete",
                              ValueError(n_("Must be checked."))))
        if not note:
            rs.notify("error", n_("Must supply archival note."))
        if rs.errors:
            return self.show_user(rs, persona_id, confirm_id=persona_id,
                                  internal=True)

        try:
            code = self.coreproxy.archive_persona(rs, persona_id, note)
        except ArchiveError as e:
            rs.notify("error", e.args[0])
            code = 0
        self.notify_return_code(rs, code)
        return self.redirect_show_user(rs, persona_id)

    @access("core_admin", "cde_admin", modi={"POST"})
    def dearchive_persona(self, rs, persona_id):
        """Reinstate a persona from the attic."""
        if rs.errors:
            return self.redirect_show_user(rs, persona_id)

        code = self.coreproxy.dearchive_persona(rs, persona_id)
        self.notify_return_code(rs, code)
        return self.redirect_show_user(rs, persona_id)

    @access("core_admin", "cde_admin", modi={"POST"})
    @REQUESTdata(("ack_delete", "bool"))
    def purge_persona(self, rs, persona_id, ack_delete):
        """Delete all identifying information for a persona."""
        if not ack_delete:
            rs.errors.append(("ack_delete",
                              ValueError(n_("Must be checked."))))
        if rs.errors:
            return self.redirect_show_user(rs, persona_id)

        code = self.coreproxy.purge_persona(rs, persona_id)
        self.notify_return_code(rs, code)
        return self.redirect_show_user(rs, persona_id)

    @access("core_admin")
    @REQUESTdata(("stati", "[int]"), ("start", "non_negative_int_or_None"),
                 ("submitted_by", "cdedbid_or_None"),
                 ("reviewed_by", "cdedbid_or_None"),
                 ("persona_id", "cdedbid_or_None"),
                 ("additional_info", "str_or_None"),
                 ("stop", "non_negative_int_or_None"),
                 ("time_start", "datetime_or_None"),
                 ("time_stop", "datetime_or_None"))
    def view_changelog_meta(self, rs, stati, start, stop, persona_id,
                            submitted_by, additional_info, time_start,
                            time_stop, reviewed_by):
        """View changelog activity."""
        start = start or 0
        stop = stop or 50
        # no validation since the input stays valid, even if some options
        # are lost
        log = self.coreproxy.retrieve_changelog_meta(
            rs, stati, start, stop, persona_id=persona_id,
            submitted_by=submitted_by, additional_info=additional_info,
            time_start=time_start, time_stop=time_stop, reviewed_by=reviewed_by)
        persona_ids = (
                {entry['submitted_by'] for entry in log if
                 entry['submitted_by']}
                | {entry['reviewed_by'] for entry in log if
                   entry['reviewed_by']}
                | {entry['persona_id'] for entry in log if entry['persona_id']})
        personas = self.coreproxy.get_personas(rs, persona_ids)
        return self.render(rs, "view_changelog_meta", {
            'log': log, 'personas': personas})

    @access("core_admin")
    @REQUESTdata(("codes", "[int]"), ("persona_id", "cdedbid_or_None"),
                 ("submitted_by", "cdedbid_or_None"),
                 ("additional_info", "str_or_None"),
                 ("start", "non_negative_int_or_None"),
                 ("stop", "non_negative_int_or_None"),
                 ("time_start", "datetime_or_None"),
                 ("time_stop", "datetime_or_None"))
    def view_log(self, rs, codes, start, stop, persona_id, submitted_by,
                 additional_info, time_start, time_stop):
        """View activity."""
        start = start or 0
        stop = stop or 50
        # no validation since the input stays valid, even if some options
        # are lost
        log = self.coreproxy.retrieve_log(
            rs, codes=codes, start=start, stop=stop, persona_id=persona_id,
            submitted_by=submitted_by, additional_info=additional_info,
            time_start=time_start, time_stop=time_stop)
        persona_ids = (
                {entry['submitted_by'] for entry in log if
                 entry['submitted_by']}
                | {entry['persona_id'] for entry in log if entry['persona_id']})
        personas = self.coreproxy.get_personas(rs, persona_ids)
        return self.render(rs, "view_log", {'log': log, 'personas': personas})

    @access("anonymous")
    def debug_email(self, rs, token):
        """Debug functionality to view emails stored to HDD.

        In test instances emails are stored to disk since most of the time
        no real email addresses are given. This creates the problem that
        those are only readable with access to the file system, which most
        test users won't have.

        In production this will not be active, but should be harmless anyway
        since no mails will be saved to disk.

        The token parameter cannot contain slashes as this is prevented by
        werkzeug.
        """
        if not self.conf.CDEDB_DEV:
            return self.redirect(rs, "core/index")
        filename = pathlib.Path(tempfile.gettempdir(),
                                "cdedb-mail-{}.txt".format(token))
        with open(filename) as f:
            rawtext = f.read()
        emailtext = quopri.decodestring(rawtext).decode('utf-8')
        return self.render(rs, "debug_email", {'emailtext': emailtext})

    def get_cron_store(self, rs, name):
        return self.coreproxy.get_cron_store(rs, name)

    def set_cron_store(self, rs, name, data):
        return self.coreproxy.set_cron_store(rs, name, data)
