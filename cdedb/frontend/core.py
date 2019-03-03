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

from cdedb.frontend.common import (
    AbstractFrontend, REQUESTdata, REQUESTdatadict, access, basic_redirect,
    check_validation as check, request_extractor, REQUESTfile,
    request_dict_extractor, event_usage, querytoparams_filter, ml_usage,
    csv_output, query_result_to_json, enum_entries_filter)
from cdedb.common import (
    n_, ProxyShim, pairwise, extract_roles, unwrap, PrivilegeError, name_key,
    now, merge_dicts, ArchiveError, open_utf8, implied_realms,
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
                for mailinglist_id, mailinglist in moderator.items():
                    requests = self.mlproxy.list_requests(rs, mailinglist_id)
                    mailinglist['requests'] = len(requests)
                dashboard['moderator'] = moderator
            # visible and open events
            if "event" in rs.user.roles:
                event_ids = self.eventproxy.list_visible_events(rs)
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
        # TODO add samesite="Lax", as soon as we switched to Debian
        #  Buster/Werkzeug 0.14 to mitigate CSRF attacks
        rs.response.set_cookie("sessionkey", sessionkey, httponly=True,
                               secure=True)
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
    @REQUESTdata(("confirm_id", "#int"), ("quote_me", "bool"),
                 ("event_id", "id_or_None"), ("ml_id", "id_or_None"))
    def show_user(self, rs, persona_id, confirm_id, quote_me, event_id, ml_id):
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
        """
        if persona_id != confirm_id or rs.errors:
            rs.notify("error", n_("Link expired."))
            return self.index(rs)
        if (rs.ambience['persona']['is_archived']
                and "core_admin" not in rs.user.roles):
            raise PrivilegeError(n_("Only admins may view archived datasets."))

        is_relative_admin = self.coreproxy.is_relative_admin(rs, persona_id)

        ALL_ACCESS_LEVELS = {
            "persona", "ml", "assembly", "event", "cde", "core", "admin",
            "orga", "moderator"}
        # The basic access level provides only the name (this should only
        # happen in case of un-quoted searchable member access)
        access_levels = {"persona"}
        # Let users see themselves
        if persona_id == rs.user.persona_id:
            access_levels.update(rs.user.roles)
            access_levels.add("core")
        # Core admins see everything
        if "core_admin" in rs.user.roles:
            access_levels.update(ALL_ACCESS_LEVELS)
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
                raise PrivilegeError(n_(
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
        # Mailinglist moderators see their subscribers
        if ml_id:
            is_moderator = (
                    "ml_admin" in rs.user.roles
                    or ml_id in self.mlproxy.moderator_info(rs,
                                                            rs.user.persona_id))
            is_subscriber = self.mlproxy.is_subscribed(rs, persona_id, ml_id)
            if is_moderator and is_subscriber:
                access_levels.add("ml")
                # the moderator access level currently does nothing, but we
                # add it anyway to be less confusing
                access_levels.add("moderator")

        # Retrieve data
        #
        # This is the basic mechanism for restricting access, since we only
        # add attributes for which an access level is provided.
        roles = extract_roles(rs.ambience['persona'])
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
            if "core" in access_levels:
                user_lastschrift = self.cdeproxy.list_lastschrift(
                    rs, persona_ids=(persona_id,), active=True)
                data['has_lastschrift'] = len(user_lastschrift) > 0
        if "admin" in access_levels:
            data.update(self.coreproxy.get_total_persona(rs, persona_id))

        # Cull unwanted data
        if not ('is_cde_realm' in data and data['is_cde_realm']) and 'foto' in data:
            del data['foto']
        if "core" not in access_levels:
            masks = (
                "is_active", "is_admin", "is_core_admin", "is_cde_admin",
                "is_event_admin", "is_ml_admin", "is_assembly_admin",
                "is_cde_realm", "is_event_realm", "is_ml_realm",
                "is_assembly_realm", "is_searchable",
                "is_archived", "balance", "decided_search",
                "trial_member", "bub_search")
            for key in masks:
                if key in data:
                    del data[key]
            if "orga" not in access_levels and "is_member" in data:
                del data["is_member"]
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
        return self.render(rs, "show_user", {
            'data': data, 'past_events': past_events,
            'is_relative_admin': is_relative_admin, 'quoteable': quoteable})

    @access("core_admin", "cde_admin", "event_admin", "ml_admin",
            "assembly_admin")
    def show_history(self, rs, persona_id):
        """Display user history."""
        if not self.coreproxy.is_relative_admin(rs, persona_id):
            raise PrivilegeError(n_("Not a relative admin."))
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
                   QueryOperators.similar, t) for t in terms]
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
    @REQUESTdata(("phrase", "str"), ("kind", "str"), ("aux", "id_or_None"))
    def select_persona(self, rs, phrase, kind, aux):
        """Provide data for inteligent input fields.

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
        """
        if rs.errors:
            return self.send_json(rs, {})

        spec_additions = {}
        search_additions = []
        mailinglist = None
        event = None
        num_preview_personas = (self.conf.NUM_PREVIEW_PERSONAS_CORE_ADMIN
                                if {"core_admin", "admin"} & rs.user.roles
                                else self.conf.NUM_PREVIEW_PERSONAS)
        if kind == "admin_persona":
            if not {"core_admin", "admin"} & rs.user.roles:
                raise PrivilegeError(n_("Not privileged."))
        elif kind == "past_event_user":
            if "cde_admin" not in rs.user.roles:
                raise PrivilegeError(n_("Not privileged."))
            search_additions.append(
                ("is_event_realm", QueryOperators.equal, True))
        elif kind == "pure_assembly_user":
            if "assembly_admin" not in rs.user.roles:
                raise PrivilegeError(n_("Not privileged."))
            search_additions.append(
                ("is_assembly_realm", QueryOperators.equal, True))
            search_additions.append(
                ("is_member", QueryOperators.equal, False))
        elif kind == "mod_ml_user" and aux:
            mailinglist = self.mlproxy.get_mailinglist(rs, aux)
            if "ml_admin" not in rs.user.roles:
                if rs.user.persona_id not in mailinglist['moderators']:
                    raise PrivilegeError(n_("Not privileged."))
            search_additions.append(
                ("is_ml_realm", QueryOperators.equal, True))
        elif kind == "event_admin_user":
            if "event_admin" not in rs.user.roles:
                raise PrivilegeError(n_("Not privileged."))
            search_additions.append(
                ("is_event_realm", QueryOperators.equal, True))
        elif kind == "orga_event_user" and aux:
            event = self.eventproxy.get_event(rs, aux)
            if "event_admin" not in rs.user.roles:
                if rs.user.persona_id not in event['orgas']:
                    raise PrivilegeError(n_("Not privileged."))
            search_additions.append(
                ("is_event_realm", QueryOperators.equal, True))
        else:
            return self.send_json(rs, {})

        data = None

        # Core admins and super admins are allowed to search by raw ID or
        # CDEDB-ID
        if {"core_admin", "admin"} & rs.user.roles:
            anid, errs = validate.check_cdedbid(phrase, "phrase")
            if not errs:
                data = self.coreproxy.get_persona(rs, anid)
            else:
                anid, errs = validate.check_id(phrase, "phrase")
                if not errs:
                    data = self.coreproxy.get_persona(rs, anid)

        # Don't query, if search phrase is too short
        if not data and len(phrase) < self.conf.NUM_PREVIEW_CHARS:
            return self.send_json(rs, {})

        terms = []
        if data is None:
            terms = tuple(t.strip() for t in phrase.split(' ') if t)
            search = [("username,family_name,given_names,display_name",
                       QueryOperators.similar, t) for t in terms]
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
            persona_ids = tuple(e['id'] for e in data)
            personas = self.coreproxy.get_personas(rs, persona_ids)
            pol = const.AudiencePolicy(mailinglist['audience_policy'])
            data = tuple(
                e for e in data
                if pol.check(extract_roles(personas[e['id']])))

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
            searched_email = any(t in entry['username'] and '@' in t and len(
                t) > self.conf.NUM_PREVIEW_CHARS for t in terms)
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
                "timeline", "interests", "free_form", "bub_search"}
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
        change_note = n_("Normal dataset change.")
        code = self.coreproxy.change_persona(rs, data, generation=generation,
                                             change_note=change_note)
        self.notify_return_code(rs, code)
        if code < 0:
            # send a mail since changes needing review should be seldom enough
            self.do_mail(
                rs, "pending_changes",
                {'To': (self.conf.MANAGEMENT_ADDRESS,),
                 'Subject': n_('CdEDB pending changes'),
                 })
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
                    for field in csvfield.split(','):
                        fields.append(field.split('.')[-1])
                if download == "csv":
                    csv_data = csv_output(result, fields, substitutions=choices)
                    return self.send_file(
                        rs, data=csv_data, inline=False,
                        filename=rs.gettext("result.csv"))
                elif download == "json":
                    json_data = query_result_to_json(result, fields,
                                                     substitutions=choices)
                    return self.send_file(
                        rs, data=json_data, inline=False,
                        filename=rs.gettext("result.json"))
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
                    for field in csvfield.split(','):
                        fields.append(field.split('.')[-1])
                if download == "csv":
                    csv_data = csv_output(result, fields, substitutions=choices)
                    return self.send_file(
                        rs, data=csv_data, inline=False,
                        filename=rs.gettext("result.csv"))
                elif download == "json":
                    json_data = query_result_to_json(result, fields,
                                                     substitutions=choices)
                    return self.send_file(
                        rs, data=json_data, inline=False,
                        filename=rs.gettext("result.json"))
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
        if rs.user.roles & {"core_admin", "admin"}:
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
            raise PrivilegeError(n_("Not a relative admin."))
        if rs.ambience['persona']['is_archived']:
            rs.notify("error", n_("Persona is archived."))
            return self.redirect_show_user(rs, persona_id)

        generation = self.coreproxy.changelog_get_generation(
            rs, persona_id)
        data = unwrap(self.coreproxy.changelog_get_history(
            rs, persona_id, (generation,)))
        del data['change_note']
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
            raise PrivilegeError(n_("Not a relative admin."))

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
                "bub_search", "is_searchable"}
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

    @access("admin")
    def change_privileges_form(self, rs, persona_id):
        """Render form."""
        if rs.ambience['persona']['is_archived']:
            rs.notify("error", n_("Persona is archived."))
            return self.redirect_show_user(rs, persona_id)
        merge_dicts(rs.values, rs.ambience['persona'])
        return self.render(rs, "change_privileges")

    @access("admin", modi={"POST"})
    @REQUESTdata(
        ("is_admin", "bool"), ("is_core_admin", "bool"),
        ("is_cde_admin", "bool"), ("is_event_admin", "bool"),
        ("is_ml_admin", "bool"), ("is_assembly_admin", "bool"))
    def change_privileges(self, rs, persona_id, is_admin, is_core_admin,
                          is_cde_admin, is_event_admin, is_ml_admin,
                          is_assembly_admin):
        """Grant or revoke admin bits."""
        if rs.errors:
            return self.change_privileges_form(rs, persona_id)
        data = {
            "id": persona_id,
            "is_admin": is_admin,
            "is_core_admin": is_core_admin,
            "is_cde_admin": is_cde_admin,
            "is_event_admin": is_event_admin,
            "is_ml_admin": is_ml_admin,
            "is_assembly_admin": is_assembly_admin,
        }
        code = self.coreproxy.change_admin_bits(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect_show_user(rs, persona_id)

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
            active_permit = None
            for lastschrift in lastschrifts.values():
                if not lastschrift['revoked_at']:
                    active_permit = lastschrift['id']
            if active_permit:
                data = {
                    'id': active_permit,
                    'revoked_at': now(),
                }
                code = self.cdeproxy.set_lastschrift(rs, data)
                self.notify_return_code(rs, code, success=n_("Permit revoked."))

        return self.redirect_show_user(rs, persona_id)

    @access("cde")
    def get_foto(self, rs, foto):
        """Retrieve profile picture."""
        path = self.conf.STORAGE_DIR / "foto" / foto
        return self.send_file(rs, path=path)

    @access("cde")
    def set_foto_form(self, rs, persona_id):
        """Render form."""
        if rs.user.persona_id != persona_id and not self.is_admin(rs):
            raise PrivilegeError(n_("Not privileged."))
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
            raise PrivilegeError(n_("Not privileged."))
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
                              ValueError(n_("Passwords don't match."))))
            rs.errors.append(("new_password2",
                              ValueError(n_("Passwords don't match."))))
            rs.notify("error", n_("Passwords don't match."))
            return self.change_password_form(rs)
        # Provide user-specific data to consider it when calculating
        # password strength.
        inputs = (rs.user.username.replace('@', ' ').split() +
                  rs.user.given_names.replace('-', ' ').split() +
                  rs.user.family_name.replace('-', ' ').split())
        admin = any("admin" in role for role in rs.user.roles)
        new_password = check(rs, "password_strength", new_password,
                             "new_password", admin=admin,
                             inputs=inputs)
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
            success, message = self.coreproxy.make_reset_cookie(rs, email)
        except PrivilegeError:
            admin_exception = True
        if admin_exception:
            self.do_mail(
                rs, "admin_no_reset_password",
                {'To': (email,), 'Subject': n_('CdEDB password reset')})
            msg = "Sent password reset denial mail to admin {} for IP {}."
            self.logger.info(msg.format(email, rs.request.remote_addr))
            rs.notify("success", n_("Email sent."))
        elif not success:
            rs.notify("error", message)
        else:
            self.do_mail(
                rs, "reset_password",
                {'To': (email,), 'Subject': n_('CdEDB password reset')},
                {'email': self.encode_parameter(
                    "core/do_password_reset_form", "email", email),
                    'cookie': message})
            msg = "Sent password reset mail to {} for IP {}."
            self.logger.info(msg.format(email, rs.request.remote_addr))
            rs.notify("success", n_("Email sent."))
        return self.redirect(rs, "core/index")

    @access("core_admin", modi={"POST"})
    def admin_send_password_reset_link(self, rs, persona_id):
        """Generate a password reset email for an arbitrary persona.

        This is the only way to reset the password of an administrator (for
        security reasons).
        """
        if rs.errors:
            return self.redirect_show_user(rs, persona_id)
        email = rs.ambience['persona']['username']
        success, message = self.coreproxy.make_reset_cookie(rs, email)
        if not success:
            rs.notify("error", message)
        else:
            self.do_mail(
                rs, "reset_password",
                {'To': (email,), 'Subject': n_('CdEDB password reset')},
                {'email': self.encode_parameter(
                    "core/do_password_reset_form", "email", email),
                    'cookie': message})
            msg = "Sent password reset mail to {} for admin {}."
            self.logger.info(msg.format(email, rs.user.persona_id))
            rs.notify("success", n_("Email sent."))
        return self.redirect_show_user(rs, persona_id)

    @access("anonymous")
    @REQUESTdata(("email", "#email"), ("cookie", "str"))
    def do_password_reset_form(self, rs, email, cookie):
        """Second form.

        Pretty similar to first form, but now we know, that the account
        owner actually wants the reset.
        """
        if rs.errors:
            rs.notify("error", n_("Link expired."))
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
            rs.notify("error", n_("Link expired."))
            return self.reset_password_form(rs)
        if new_password != new_password2:
            rs.errors.append(("new_password",
                              ValueError(n_("Passwords don't match."))))
            rs.errors.append(("new_password2",
                              ValueError(n_("Passwords don't match."))))
            rs.notify("error", n_("Passwords don't match."))
            return self.change_password_form(rs)
        # Provide user-specific data to consider it when calculating
        # password strength.
        inputs = email.replace('@', ' ').split()
        new_password = check(rs, "password_strength", new_password,
                             "new_password", inputs=inputs)
        if rs.errors:
            if any(name == "new_password" for name, _ in rs.errors):
                rs.notify("error", n_("Password too weak."))
            # Redirect so that encoded parameter works.
            params = {
                'email': self.encode_parameter(
                    "core/do_password_reset_form", "email", email),
                'cookie': cookie}
            return self.redirect(rs, 'core/do_password_reset_form', params)
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
        if rs.errors:
            return self.change_username_form(rs)
        self.do_mail(rs, "change_username",
                     {'To': (new_username,),
                      'Subject': n_('CdEDB username change')},
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
            rs.notify("error", n_("Link expired."))
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
            rs.notify("error", n_("Link expired."))
            return self.change_username_form(rs)
        code, message = self.coreproxy.change_username(
            rs, rs.user.persona_id, new_username, password)
        self.notify_return_code(rs, code, success=n_("Username changed."),
                                error=message)
        if not code:
            return self.redirect(rs, "core/username_change_form")
        else:
            return self.redirect(rs, "core/index")

    @access("core_admin", "cde_admin", "event_admin", "ml_admin",
            "assembly_admin")
    def admin_username_change_form(self, rs, persona_id):
        """Render form."""
        if not self.coreproxy.is_relative_admin(rs, persona_id):
            raise PrivilegeError(n_("Not a relative admin."))
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
            raise PrivilegeError(n_("Not a relative admin."))
        if rs.errors:
            return self.admin_username_change_form(rs, persona_id)
        code, message = self.coreproxy.change_username(
            rs, persona_id, new_username, password=None)
        self.notify_return_code(rs, code, success=n_("Username changed."),
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
            raise PrivilegeError(n_("Not a relative admin."))
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
        return self.render(rs, "genesis_request",
                           {'max_rationale': self.conf.MAX_RATIONALE})

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
        if not rs.errors and len(data['notes']) > self.conf.MAX_RATIONALE:
            rs.errors.append(("notes", ValueError(n_("Rationale too long."))))
        if rs.errors:
            return self.genesis_request_form(rs)
        if self.coreproxy.verify_existence(rs, data['username']):
            rs.notify("error",
                      n_("Email address already in DB. Reset password."))
            return self.redirect(rs, "core/index")
        # We have to force a None here since the template should not have a
        # null option for event cases and the validator for ml users
        # requires this
        if data['realm'] == "ml":
            data['gender'] = None
        case_id = self.coreproxy.genesis_request(rs, data)
        if not case_id:
            rs.notify("error", n_("Failed."))
            return self.genesis_request_form(rs)
        self.do_mail(rs, "genesis_verify",
                     {'To': (data['username'],),
                      'Subject': n_('CdEDB account request'),
                      },
                     {
                         'case_id': self.encode_parameter(
                             "core/genesis_verify", "case_id", case_id),
                         'given_names': data['given_names'],
                         'family_name': data['family_name'],
                     })
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
            rs.notify("error", n_("Link expired."))
            return self.genesis_request_form(rs)
        code, realm = self.coreproxy.genesis_verify(rs, case_id)
        self.notify_return_code(
            rs, code,
            error=n_("Verification failed. Please contact the administrators."),
            success=n_("Email verified. Wait for moderation. "
                       "You will be notified by mail."))
        if not code:
            return self.redirect(rs, "core/genesis_request_form")
        notify = self.conf.MANAGEMENT_ADDRESS
        if realm == "event":
            notify = self.conf.EVENT_ADMIN_ADDRESS
        if realm == "ml":
            notify = self.conf.ML_ADMIN_ADDRESS
        self.do_mail(
            rs, "genesis_request",
            {'To': (notify,),
             'Subject': n_('CdEDB account request'),
             })
        return self.redirect(rs, "core/index")

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
    def genesis_modify_form(self, rs, case_id):
        """View a specific case and present the option to edit it."""
        case = self.coreproxy.genesis_get_case(rs, case_id)
        if (not self.is_admin(rs)
                and "{}_admin".format(case['realm']) not in rs.user.roles):
            raise PrivilegeError(n_("Not privileged."))
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
            raise PrivilegeError(n_("Not privileged."))
        if case['case_status'] != const.GenesisStati.to_review:
            rs.notify("error", n_("Case not to review."))
            return self.genesis_list_cases(rs)
        code = self.coreproxy.genesis_modify_case(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "core/genesis_list_cases")

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
            raise PrivilegeError(n_("Not privileged."))
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
            success, cookie = self.coreproxy.make_reset_cookie(rs,
                                                               case['username'])
            self.do_mail(
                rs, "genesis_approved",
                {'To': (case['username'],),
                 'Subject': n_('CdEDB account created'),
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
                 'Subject': n_('CdEDB account declined')},
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
    @REQUESTdata(("ack_delete", "bool"))
    def archive_persona(self, rs, persona_id, ack_delete):
        """Move a persona to the attic."""
        if not ack_delete:
            rs.errors.append(("ack_delete", ValueError(n_("Must be checked."))))
        if rs.errors:
            return self.redirect_show_user(rs, persona_id)

        try:
            code = self.coreproxy.archive_persona(rs, persona_id)
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
            rs.errors.append(("ack_delete", ValueError(n_("Must be checked."))))
        if rs.errors:
            return self.redirect_show_user(rs, persona_id)

        code = self.coreproxy.purge_persona(rs, persona_id)
        self.notify_return_code(rs, code)
        return self.redirect_show_user(rs, persona_id)

    @access("core_admin")
    @REQUESTdata(("stati", "[int]"), ("start", "non_negative_int_or_None"),
                 ("stop", "non_negative_int_or_None"))
    def view_changelog_meta(self, rs, stati, start, stop):
        """View changelog activity."""
        start = start or 0
        stop = stop or 50
        # no validation since the input stays valid, even if some options
        # are lost
        log = self.coreproxy.retrieve_changelog_meta(rs, stati, start, stop)
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
                 ("start", "non_negative_int_or_None"),
                 ("stop", "non_negative_int_or_None"))
    def view_log(self, rs, codes, persona_id, start, stop):
        """View activity."""
        start = start or 0
        stop = stop or 50
        # no validation since the input stays valid, even if some options
        # are lost
        log = self.coreproxy.retrieve_log(rs, codes, persona_id, start, stop)
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
        with open_utf8(filename) as f:
            rawtext = f.read()
        emailtext = quopri.decodestring(rawtext).decode('utf-8')
        return self.render(rs, "debug_email", {'emailtext': emailtext})
