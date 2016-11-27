#!/usr/bin/env python3

"""Services for the core realm."""

import collections
import copy
import csv
import hashlib
import io
import json
import os.path
import uuid

from cdedb.frontend.common import (
    AbstractFrontend, REQUESTdata, REQUESTdatadict, access, basic_redirect,
    check_validation as check, merge_dicts, request_extractor, REQUESTfile,
    request_dict_extractor, event_usage, querytoparams_filter, ml_usage,
    csv_output, query_result_to_json)
from cdedb.common import (
    _, ProxyShim, pairwise, extract_roles, privilege_tier, unwrap,
    PrivilegeError, name_key, now, glue)
from cdedb.backend.core import CoreBackend
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
        self.assemblyproxy = ProxyShim(AssemblyBackend(configpath))
        self.mlproxy = ProxyShim(MlBackend(configpath))
        self.eventproxy = ProxyShim(EventBackend(configpath))
        self.pasteventproxy = ProxyShim(PastEventBackend(configpath))

    def finalize_session(self, rs, auxilliary=False):
        super().finalize_session(rs, auxilliary=auxilliary)

    @classmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

    @access("anonymous")
    @event_usage
    @ml_usage
    @REQUESTdata(("wants", "#str_or_None"))
    def index(self, rs, wants=None):
        """Basic entry point.

        :param wants: URL to redirect to upon login
        """
        if wants:
            rs.values['wants'] = self.encode_parameter("core/login", "wants",
                                                       wants)
        meta_info = self.coreproxy.get_meta_info(rs)
        dashboard = {}
        if rs.user.persona_id:
            ## genesis cases
            if {"core_admin", "event_admin", "ml_admin"} & rs.user.roles:
                realms = []
                if {"core_admin", "event_admin"} & rs.user.roles:
                    realms.append("event")
                if {"core_admin", "ml_admin"} & rs.user.roles:
                    realms.append("ml")
                data = self.coreproxy.genesis_list_cases(
                    rs, stati=(const.GenesisStati.to_review,), realms=realms)
                dashboard['genesis_cases'] = len(data)
            ## pending changes
            if self.is_admin(rs):
                data = self.coreproxy.changelog_get_changes(
                    rs, stati=(const.MemberChangeStati.pending,))
                dashboard['pending_changes'] = len(data)
            ## events organized
            orga_info = self.eventproxy.orga_info(rs, rs.user.persona_id)
            if orga_info:
                orga = {}
                events = self.eventproxy.get_events(rs, orga_info)
                today = now().date()
                for event_id, event in events.items():
                    start = min(part['part_begin'] for part in event['parts'].values()) \
                            if event['parts'] else None
                    if (not start or start >= today
                            or abs(start.year - today.year) < 2):
                        regs = self.eventproxy.list_registrations(rs,
                                                                  event['id'])
                        event['registrations'] = len(regs)
                        orga[event_id] = event
                dashboard['orga'] = orga
                dashboard['today'] = today
            ## mailinglists moderated
            moderator_info = self.mlproxy.moderator_info(rs, rs.user.persona_id)
            if moderator_info:
                moderator = self.mlproxy.get_mailinglists(rs, moderator_info)
                for mailinglist_id, mailinglist in moderator.items():
                    requests = self.mlproxy.list_requests(rs, mailinglist_id)
                    mailinglist['requests'] = len(requests)
                dashboard['moderator'] = moderator
            ## open events
            if "event" in rs.user.roles:
                event_ids = self.eventproxy.list_open_events(rs)
                events = self.eventproxy.get_events(rs, event_ids.keys())
                final = {}
                for event_id, event in events.items():
                    if event_id not in orga_info:
                        event['start'] = \
                            min(part['part_begin'] for part in event['parts'].values()) \
                            if event['parts'] else None
                        event['end'] = \
                            max(part['part_end'] for part in event['parts'].values()) \
                            if event['parts'] else None
                        registration = self.eventproxy.list_registrations(
                            rs, event_id, rs.user.persona_id)
                        event['registration'] = bool(registration)
                        final[event_id] = event
                if final:
                    dashboard['events'] = final
            ## open assemblies
            if "assembly" in rs.user.roles:
                assembly_ids = self.assemblyproxy.list_assemblies(
                    rs, is_active=True)
                assemblies = self.assemblyproxy.get_assemblies(
                    rs, assembly_ids.keys())
                final = {}
                for assembly_id, assembly in assemblies.items():
                    assembly['does_attend'] = self.assemblyproxy.does_attend(
                        rs, assembly_id=assembly_id)
                    if assembly['does_attend'] or assembly['signup_end'] > now():
                        final[assembly_id] = assembly
                if final:
                    dashboard['assemblies'] = final
        return self.render(rs, "index", {
            'meta_info': meta_info, 'dashboard': dashboard})

    @access("anonymous")
    @REQUESTdata(("kind", "printable_ascii"), ("message", "str_or_None"))
    def error(self, rs, kind, message):
        """Fault page.

        This may happen upon a database serialization failure during
        concurrent accesses or because of a used up quota. Other errors are
        bugs.
        """
        return self.render(rs, "error", {'kind': kind, 'message': message})

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

        :param wants: URL to redirect to
        """
        if rs.errors:
            return self.index(rs)
        sessionkey = self.coreproxy.login(rs, username, password,
                                          rs.request.remote_addr)
        if not sessionkey:
            rs.notify("error", _("Login failure."))
            rs.errors.extend((("username", ValueError()),
                              ("password", ValueError())))
            return self.index(rs)
        if wants:
            basic_redirect(rs, wants)
        else:
            self.redirect(rs, "cde/consent_decision_form")
        rs.response.set_cookie("sessionkey", sessionkey)
        return rs.response

    @access("persona", modi={"POST"})
    def logout(self, rs):
        """Invalidate session."""
        self.coreproxy.logout(rs)
        self.redirect(rs, "core/index")
        rs.response.delete_cookie("sessionkey")
        return rs.response

    @access("persona")
    def mydata(self, rs):
        """Convenience entry point for own data."""
        return self.redirect_show_user(rs, rs.user.persona_id)

    @access("persona")
    @event_usage
    @REQUESTdata(("confirm_id", "#int"), ("quote_me", "bool"))
    def show_user(self, rs, persona_id, confirm_id, quote_me):
        """Display user details.

        This has an additional encoded parameter to make links to this
        target unguessable. Thus it is more difficult to algorithmically
        extract user data from the web frontend.

        The quote_me parameter controls access to member datasets by
        other members. Since there is a quota you only want to retrieve
        them if explicitly asked for.
        """
        if persona_id != confirm_id or rs.errors:
            rs.notify("error", _("Link expired."))
            return self.index(rs)
        if (rs.ambience['persona']['is_archived']
                and "core_admin" not in rs.user.roles):
            raise PrivilegeError(_("Only admins may view archived datasets."))

        is_relative_admin = self.coreproxy.is_relative_admin(rs, persona_id)

        ALL_ACCESS_LEVELS = {
            "persona", "ml", "assembly", "event", "cde", "core", "admin",
            "orga"}
        access_levels = {"persona"}
        ## Let users see themselves
        if persona_id == rs.user.persona_id:
            access_levels.update(rs.user.roles)
            access_levels.add("core")
        ## Core admins see everything
        if "core_admin" in rs.user.roles:
            access_levels.update(ALL_ACCESS_LEVELS)
        ## Other admins see their realm
        for realm in ("ml", "assembly", "event", "cde"):
            if "{}_admin" in rs.user.roles:
                access_levels.add(realm)
        ## Members see other members (modulo quota)
        if "searchable" in rs.user.roles and quote_me:
            if not rs.ambience['persona']['is_searchable']:
                raise PrivilegeError(_("Access to non-searchable member data."))
            access_levels.add("cde")
        ## Orgas see their participants
        if "event" not in access_levels:
            for event_id in self.eventproxy.orga_info(rs, rs.user.persona_id):
                if self.eventproxy.list_registrations(rs, event_id, persona_id):
                    access_levels.add("event")
                    access_levels.add("orga")
                    break
        ## Mailinglist moderators get no special treatment since this wouldn't
        ## gain them anything
        pass

        ## Retrieve data
        roles = extract_roles(rs.ambience['persona'])
        data = self.coreproxy.get_persona(rs, persona_id)
        if "ml" in access_levels and "ml" in roles:
            data.update(self.coreproxy.get_ml_user(rs, persona_id))
        if "assembly" in access_levels and "assembly" in roles:
            data.update(self.coreproxy.get_assembly_user(rs, persona_id))
        if "event" in access_levels and "event" in roles:
            data.update(self.coreproxy.get_event_user(rs, persona_id))
        if "cde" in access_levels and "cde" in roles:
            data.update(self.coreproxy.get_cde_user(rs, persona_id))
        if "admin" in access_levels:
            data.update(self.coreproxy.get_total_persona(rs, persona_id))

        ## Cull unwanted data
        if not "core" in access_levels:
            masks = (
                "is_active", "is_admin", "is_core_admin", "is_cde_admin",
                "is_event_admin", "is_ml_admin", "is_assembly_admin",
                "is_cde_realm", "is_event_realm", "is_ml_realm",
                "is_assembly_realm", "is_searchable",
                "cloud_account", "is_archived", "balance", "decided_search",
                "trial_member", "bub_search")
            for key in masks:
                if key in data:
                    del data[key]
            if not "orga" in access_levels and "is_member" in data:
                del data["is_member"]
        if not is_relative_admin and "notes" in data:
            del data['notes']

        ## Add participation info
        participation_info = None
        if {"event", "cde"} & access_levels and {"event", "cde"} & roles:
            participation_info = self.pasteventproxy.participation_info(
                rs, persona_id)

        return self.render(rs, "show_user", {
            'data': data, 'participation_info': participation_info,
            'is_relative_admin': is_relative_admin})

    @access("core_admin", "cde_admin", "event_admin", "ml_admin",
            "assembly_admin")
    def show_history(self, rs, persona_id):
        """Display user history."""
        if not self.coreproxy.is_relative_admin(rs, persona_id):
            raise PrivilegeError(_("Not a relative admin."))
        if rs.ambience['persona']['is_archived']:
            rs.notify("error", _("Persona is archived."))
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
                ## Somewhat involved determination of a field being constant.
                ##
                ## Basically it's done by the following line, except we
                ## don't want to mask a change that was rejected and then
                ## resubmitted and accepted.
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
        ## Track the omitted information whether a new value finally got
        ## committed or not.
        ##
        ## This is necessary since we only show those data points, where the
        ## data (e.g. the name) changes. This does especially not detect
        ## meta-data changes (e.g. the change-status).
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
            return self.redirect_show_user(rs, anid)
        anid, errs = validate.check_id(phrase, "phrase")
        if not errs:
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
            ## TODO make this accessible
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
            rs.notify("warning", _("No account found."))
            return self.index(rs)

    @access("persona")
    @REQUESTdata(("phrase", "str"), ("kind", "str"), ("aux", "id_or_None"))
    def select_persona(self, rs, phrase, kind, aux):
        """Provide data for inteligent input fields.

        This searches for users by name so they can be easily selected
        without entering their numerical ids. This is for example
        intended for addition of orgas to events.

        The aux parameter allows to supply an additional id for example
        in the case of a moderator this would be the relevant
        mailinglist id.
        """
        if rs.errors:
            return self.send_json(rs, {})

        spec_additions = {}
        search_additions = []
        mailinglist = None
        num_preview_personas = self.conf.NUM_PREVIEW_PERSONAS
        if kind == "persona":
            if "core_admin" not in rs.user.roles:
                raise PrivilegeError(_("Not privileged."))
        elif kind == "member":
            if "cde_admin" not in rs.user.roles:
                raise PrivilegeError(_("Not privileged."))
            search_additions.append(
                ("is_member", QueryOperators.equal, True))
        elif kind == "cde_user":
            if "cde_admin" not in rs.user.roles:
                raise PrivilegeError(_("Not privileged."))
            search_additions.append(
                ("is_cde_realm", QueryOperators.equal, True))
        elif kind == "event_user":
            if "event_admin" not in rs.user.roles:
                raise PrivilegeError(_("Not privileged."))
            search_additions.append(
                ("is_event_realm", QueryOperators.equal, True))
        elif kind == "assembly_user":
            if "assembly_admin" not in rs.user.roles:
                raise PrivilegeError(_("Not privileged."))
            search_additions.append(
                ("is_assembly_realm", QueryOperators.equal, True))
        elif kind == "pure_assembly_user":
            if "assembly_admin" not in rs.user.roles:
                raise PrivilegeError(_("Not privileged."))
            search_additions.append(
                ("is_assembly_realm", QueryOperators.equal, True))
            search_additions.append(
                ("is_member", QueryOperators.equal, False))
        elif kind == "ml_user":
            if "ml_admin" not in rs.user.roles:
                raise PrivilegeError(_("Not privileged."))
            search_additions.append(
                ("is_ml_realm", QueryOperators.equal, True))
        elif kind == "mod_ml_user":
            mailinglist = self.mlproxy.get_mailinglist(rs, aux)
            if "ml_admin" not in rs.user.roles:
                num_preview_personas //= 2
                if rs.user.persona_id not in mailinglist['moderators']:
                    raise PrivilegeError(_("Not privileged."))
            search_additions.append(
                ("is_ml_realm", QueryOperators.equal, True))
        else:
            return self.send_json(rs, {})

        data = None
        anid, errs = validate.check_cdedbid(phrase, "phrase")
        if not errs:
            data = self.get_personas(rs, anid)
        else:
            anid, errs = validate.check_id(phrase, "phrase")
            if not errs:
                data = self.get_personas(rs, anid)
        if data:
            data = unwrap(data)
        if not data and len(phrase) < self.conf.NUM_PREVIEW_CHARS:
            return self.send_json(rs, {})

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
            data = self.coreproxy.submit_general_query(rs, query)

        if mailinglist:
            persona_ids = tuple(e['id'] for e in data)
            personas = self.coreproxy.get_personas(rs, persona_ids)
            pol = const.AudiencePolicy(mailinglist['audience_policy'])
            data = tuple(
                e for e in data
                if pol.check(extract_roles(personas[e['id']])))

        if len(data) > num_preview_personas:
            tmp = sorted(data, key=lambda e: e['id'])
            data = tmp[:num_preview_personas]

        counter = collections.defaultdict(lambda: 0)
        def formatter(entry, verbose=False):
            if verbose:
                return "{} {} ({})".format(
                    entry['given_names'], entry['family_name'],
                    entry['username'])
            else:
                return "{} {}".format(
                    entry['given_names'], entry['family_name'])
        for entry in data:
            counter[formatter(entry)] += 1
        ret = []
        for entry in sorted(data, key=name_key):
            verbose = counter[formatter(entry)] > 1
            ret.append(
                {
                    'id': entry['id'],
                    'name': formatter(entry, verbose),
                    'display_name': entry['display_name'],
                    'email': entry['username'],
                })
        return self.send_json(rs, {'personas': ret})

    @access("persona")
    def change_user_form(self, rs):
        """Render form."""
        generation = self.coreproxy.changelog_get_generation(
            rs, rs.user.persona_id)
        data = unwrap(self.coreproxy.changelog_get_history(
            rs, rs.user.persona_id, (generation,)))
        if data['change_status'] == const.MemberChangeStati.pending:
            rs.notify("info", _("Change pending."))
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
        change_note = rs.gettext("Normal dataset change.")
        code = self.coreproxy.change_persona(rs, data, generation=generation,
                                             change_note=change_note)
        self.notify_return_code(rs, code)
        if code < 0:
            ## send a mail since changes needing review should be seldom enough
            self.do_mail(
                rs, "pending_changes",
                {'To': (self.conf.MANAGEMENT_ADDRESS,),
                 'Subject': _('CdEDB pending changes'),})
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
            ## mangle the input, so we can prefill the form
            query_input = mangle_query_input(rs, spec)
            query = check(rs, "query_input", query_input, "query",
                          spec=spec, allow_empty=False)
        events = self.pasteventproxy.list_past_events(rs)
        choices = {'pevent_id': events}
        default_queries = self.conf.DEFAULT_QUERIES['qview_core_user']
        params = {
            'spec': spec, 'choices': choices,
            'default_queries': default_queries, 'query': query}
        ## Tricky logic: In case of no validation errors we perform a query
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
        ## mangle the input, so we can prefill the form
        query_input = mangle_query_input(rs, spec)
        if is_search:
            query = check(rs, "query_input", query_input, "query", spec=spec,
                          allow_empty=False)
        else:
            query = None
        events = self.pasteventproxy.list_past_events(rs)
        choices = {'pevent_id': events,
                   'gender': self.enum_choice(rs, const.Genders)}
        default_queries = self.conf.DEFAULT_QUERIES['qview_archived_persona']
        params = {
            'spec': spec, 'choices': choices,
            'default_queries': default_queries, 'query': query}
        ## Tricky logic: In case of no validation errors we perform a query
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

    @access("core_admin", "cde_admin", "event_admin", "ml_admin",
            "assembly_admin")
    def admin_change_user_form(self, rs, persona_id):
        """Render form."""
        if not self.coreproxy.is_relative_admin(rs, persona_id):
            raise PrivilegeError(_("Not a relative admin."))
        if rs.ambience['persona']['is_archived']:
            rs.notify("error", _("Persona is archived."))
            return self.redirect_show_user(rs, persona_id)

        generation = self.coreproxy.changelog_get_generation(
            rs, persona_id)
        data = unwrap(self.coreproxy.changelog_get_history(
            rs, persona_id, (generation,)))
        del data['change_note']
        merge_dicts(rs.values, data)
        if data['change_status'] == const.MemberChangeStati.pending:
            rs.notify("info", _("Change pending."))
        return self.render(rs, "admin_change_user")

    @access("core_admin", "cde_admin", "event_admin", "ml_admin",
            "assembly_admin", modi={"POST"})
    @REQUESTdata(("generation", "int"), ("change_note", "str_or_None"))
    def admin_change_user(self, rs, persona_id, generation, change_note):
        """Privileged edit of data set."""
        if not self.coreproxy.is_relative_admin(rs, persona_id):
            raise PrivilegeError(_("Not a relative admin."))

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
                "bub_search"}
        }
        attributes = REALM_ATTRIBUTES['persona']
        roles = extract_roles(rs.ambience['persona'])
        for realm in ('ml', 'assembly', 'event', 'cde'):
            if realm in roles:
                attributes = attributes.union(REALM_ATTRIBUTES[realm])
        data = request_dict_extractor(rs, attributes)
        data['id'] = persona_id
        data = check(rs, "persona", data)
        if rs.errors:
            rs.notify("error", _("Failed validation."))
            return self.admin_change_user_form(rs, persona_id)

        code = self.coreproxy.change_persona(rs, data, generation=generation,
                                             change_note=change_note)
        self.notify_return_code(rs, code)
        return self.redirect_show_user(rs, persona_id)

    @access("admin")
    def change_privileges_form(self, rs, persona_id):
        """Render form."""
        if rs.ambience['persona']['is_archived']:
            rs.notify("error", _("Persona is archived."))
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
        if rs.errors:
            return self.index(rs)
        if rs.ambience['persona']['is_archived']:
            rs.notify("error", _("Persona is archived."))
            return self.redirect_show_user(rs, persona_id)
        merge_dicts(rs.values, rs.ambience['persona'])
        if (target_realm
                and rs.ambience['persona']['is_{}_realm'.format(target_realm)]):
            rs.notify("warning", _("No promotion necessary."))
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
            ## remove irrelevant keys, due to the possible combinations it is
            ## rather lengthy to specify the exact set of them
            del data[key]
        persona = self.coreproxy.get_total_persona(rs, persona_id)
        merge_dicts(data, persona)
        ## Specific fixes by target realm
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
        ## implicit addition of realms as semantically sensible
        if target_realm == "cde":
            data['is_event_realm'] = True
            data['is_assembly_realm'] = True
        if target_realm in ("cde", "event", "assembly"):
            data['is_ml_realm'] = True
        data = check(rs, "persona", data, transition=True)
        if rs.errors:
            return self.promote_user_form(rs, persona_id, target_realm)
        code = self.coreproxy.change_persona_realms(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect_show_user(rs, persona_id)

    @access("cde_admin")
    def modify_membership_form(self, rs, persona_id):
        """Render form."""
        if rs.ambience['persona']['is_archived']:
            rs.notify("error", _("Persona is archived."))
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
        return self.redirect_show_user(rs, persona_id)

    @access("cde")
    def get_foto(self, rs, foto):
        """Retrieve profile picture."""
        path = os.path.join(self.conf.STORAGE_DIR, "foto", foto)
        return self.send_file(rs, path=path)

    @access("cde")
    def set_foto_form(self, rs, persona_id):
        """Render form."""
        if rs.user.persona_id != persona_id and not self.is_admin(rs):
            raise PrivilegeError(_("Not privileged."))
        if rs.ambience['persona']['is_archived']:
            rs.notify("error", _("Persona is archived."))
            return self.redirect_show_user(rs, persona_id)
        foto = self.coreproxy.get_cde_user(rs, persona_id)['foto']
        return self.render(rs, "set_foto", {'foto': foto})

    @access("cde", modi={"POST"})
    @REQUESTfile("foto")
    def set_foto(self, rs, persona_id, foto):
        """Set profile picture."""
        if rs.user.persona_id != persona_id and not self.is_admin(rs):
            raise PrivilegeError(_("Not privileged."))
        foto = check(rs, 'profilepic_or_None', foto, "foto")
        if rs.errors:
            return self.set_foto_form(rs, persona_id)
        previous = self.coreproxy.get_cde_user(rs, persona_id)['foto']
        myhash = None
        if foto:
            myhash = hashlib.sha512()
            myhash.update(foto)
            myhash = myhash.hexdigest()
            path = os.path.join(self.conf.STORAGE_DIR, 'foto', myhash)
            if not os.path.isfile(path):
                with open(path, 'wb') as f:
                    f.write(foto)
        with Atomizer(rs):
            code = self.coreproxy.change_foto(rs, persona_id, foto=myhash)
            if previous:
                if not self.coreproxy.foto_usage(rs, previous):
                    path = os.path.join(self.conf.STORAGE_DIR, 'foto', previous)
                    os.remove(path)
        self.notify_return_code(rs, code, success=_("Foto updated."))
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
                              ValueError(_("Passwords don't match."))))
            rs.errors.append(("new_password2",
                              ValueError(_("Passwords don't match."))))
            rs.notify("error", _("Passwords don't match."))
        new_password = check(rs, "password_strength", new_password, "strength")
        if rs.errors:
            if any(name == "strength" for name, _ in rs.errors):
                rs.notify("error", _("Password too weak."))
            return self.change_password_form(rs)
        code, message = self.coreproxy.change_password(
            rs, rs.user.persona_id, old_password, new_password)
        self.notify_return_code(rs, code, success=_("Password changed."),
                                error=message)
        if not code:
            rs.errors.append(("old_password", ValueError(_("Wrong password."))))
            self.logger.info(
                "Unsuccessful password change for persona {}.".format(
                    rs.user.persona_id))
            return self.change_password_form(rs)
        else:
            return self.redirect(rs, "core/index")

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
            rs.errors.append(("email", ValueError(_("Nonexistant user."))))
            return self.reset_password_form(rs)
        success, message = self.coreproxy.make_reset_cookie(rs, email)
        if not success:
            rs.notify("error", message)
        else:
            self.do_mail(
                rs, "reset_password",
                {'To': (email,), 'Subject': _('CdEDB password reset')},
                {'email': self.encode_parameter(
                    "core/do_password_reset_form", "email", email,
                    timeout=self.conf.EMAIL_PARAMETER_TIMEOUT),
                 'cookie': message})
            self.logger.info("Sent password reset mail to {} for IP {}.".format(
                email, rs.request.remote_addr))
            rs.notify("success", _("Email sent."))
        return self.redirect(rs, "core/index")

    @access("anonymous")
    @REQUESTdata(("email", "#email"), ("cookie", "str"))
    def do_password_reset_form(self, rs, email, cookie):
        """Second form.

        Pretty similar to first form, but now we know, that the account
        owner actually wants the reset.
        """
        if rs.errors:
            rs.notify("error", _("Link expired."))
            return self.reset_password_form(rs)
        rs.values['email'] = self.encode_parameter(
            "core/do_password_reset", "email", email,
            timeout=self.conf.EMAIL_PARAMETER_TIMEOUT)
        return self.render(rs, "do_password_reset")

    @access("anonymous", modi={"POST"})
    @REQUESTdata(("email", "#email"), ("new_password", "str"),
                 ("new_password2", "str"), ("cookie", "str"))
    def do_password_reset(self, rs, email, new_password, new_password2, cookie):
        """Now we can reset to a new password."""
        if rs.errors:
            rs.notify("error", _("Link expired."))
            return self.reset_password_form(rs)
        if new_password != new_password2:
            rs.errors.append(("new_password",
                              ValueError(_("Passwords don't match."))))
            rs.errors.append(("new_password2",
                              ValueError(_("Passwords don't match."))))
            rs.notify("error", _("Passwords don't match."))
        new_password = check(rs, "password_strength", new_password, "strength")
        if rs.errors:
            if any(name == "strength" for name, _ in rs.errors):
                rs.notify("error", _("Password too weak."))
            ## Redirect so that encoded parameter works.
            params = {
                'email': self.encode_parameter(
                    "core/do_password_reset_form", "email", email),
                'cookie': cookie}
            return self.redirect(rs, 'core/do_password_reset_form', params)
        code, message = self.coreproxy.reset_password(rs, email, new_password,
                                                      cookie=cookie)
        self.notify_return_code(rs, code, success=_("Password reset."),
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
                      'Subject': _('CdEDB username change')},
                     {'new_username': self.encode_parameter(
                         "core/do_username_change_form", "new_username",
                         new_username,
                         timeout=self.conf.EMAIL_PARAMETER_TIMEOUT)})
        self.logger.info("Sent username change mail to {} for {}.".format(
            new_username, rs.user.username))
        rs.notify("success", "Email sent.")
        return self.redirect(rs, "core/index")

    @access("persona")
    @REQUESTdata(("new_username", "#email"))
    def do_username_change_form(self, rs, new_username):
        """Email is now verified or we are admin."""
        if rs.errors:
            rs.notify("error", _("Link expired."))
            return self.change_username_form(rs)
        rs.values['new_username'] = self.encode_parameter(
            "core/do_username_change", "new_username", new_username,
            timeout=self.conf.EMAIL_PARAMETER_TIMEOUT)
        return self.render(rs, "do_username_change")

    @access("persona", modi={"POST"})
    @REQUESTdata(('new_username', '#email'), ('password', 'str'))
    def do_username_change(self, rs, new_username, password):
        """Now we can do the actual change."""
        if rs.errors:
            rs.notify("error", _("Link expired"))
            return self.change_username_form(rs)
        code, message = self.coreproxy.change_username(
            rs, rs.user.persona_id, new_username, password)
        self.notify_return_code(rs, code, success=_("Username changed."),
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
            raise PrivilegeError(_("Not a relative admin."))
        if rs.ambience['persona']['is_archived']:
            rs.notify("error", _("Persona is archived."))
            return self.redirect_show_user(rs, persona_id)
        data = self.coreproxy.get_persona(rs, persona_id)
        return self.render(rs, "admin_username_change", {'data': data})

    @access("core_admin", "cde_admin", "event_admin", "ml_admin",
            "assembly_admin", modi={"POST"})
    @REQUESTdata(('new_username', 'email_or_None'))
    def admin_username_change(self, rs, persona_id, new_username):
        """Change username without verification."""
        if not self.coreproxy.is_relative_admin(rs, persona_id):
            raise PrivilegeError(_("Not a relative admin."))
        if rs.errors:
            return self.admin_username_change_form(rs, persona_id)
        code, message = self.coreproxy.change_username(
            rs, persona_id, new_username, password=None)
        self.notify_return_code(rs, code, success=_("Username changed."),
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
            raise PrivilegeError(_("Not a relative admin."))
        if rs.errors:
            # Redirect for encoded parameter
            return self.redirect_show_user(rs, persona_id)
        if rs.ambience['persona']['is_archived']:
            rs.notify("error", _("Persona is archived."))
            return self.redirect_show_user(rs, persona_id)
        data = {
            'id': persona_id,
            'is_active': activity,
        }
        change_note = rs.gettext("Toggling activity to {activity}.").format(
            activity=activity)
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
    @REQUESTdatadict("username", "notes", "given_names", "family_name", "realm")
    def genesis_request(self, rs, data):
        """Voice the desire to become a persona.

        This initiates the genesis process.
        """
        data = check(rs, "genesis_case", data, creation=True)
        if not rs.errors and len(data['notes']) > self.conf.MAX_RATIONALE:
            rs.errors.append(("notes", ValueError(_("Rationale too long."))))
        if rs.errors:
            return self.genesis_request_form(rs)
        if self.coreproxy.verify_existence(rs, data['username']):
            rs.notify("error",
                      _("Email address already in DB. Reset password."))
            return self.redirect(rs, "core/index")
        case_id = self.coreproxy.genesis_request(rs, data)
        if not case_id:
            rs.notify("error", _("Failed."))
            return self.genesis_request_form(rs)
        self.do_mail(
            rs, "genesis_verify",
            {'To': (data['username'],), 'Subject': _('CdEDB account request')},
            {'case_id': self.encode_parameter(
                "core/genesis_verify", "case_id", case_id,
                timeout=self.conf.EMAIL_PARAMETER_TIMEOUT),
             'given_names': data['given_names'],
             'family_name': data['family_name'],})
        rs.notify(
            "success",
            _("Email sent. Please follow the link contained in the email."))
        return self.redirect(rs, "core/index")

    @access("anonymous")
    @REQUESTdata(("case_id", "#int"))
    def genesis_verify(self, rs, case_id):
        """Verify the email address entered in :py:meth:`genesis_request`.

        This is not a POST since the link is shared via email.
        """
        if rs.errors:
            rs.notify("error", _("Link expired."))
            return self.genesis_request_form(rs)
        code, realm = self.coreproxy.genesis_verify(rs, case_id)
        self.notify_return_code(
            rs, code,
            error=_("Verification failed. Please contact the administrators."),
            success=_("Email verified. Wait for moderation. "
                      "You will be notified by mail."))
        notify = None
        if realm == "event":
            notify = self.conf.EVENT_ADMIN_ADDRESS
        if realm == "ml":
            notify = self.conf.ML_ADMIN_ADDRESS
        if notify:
            self.do_mail(
                rs, "genesis_request",
                {'To': (notify,),
                 'Subject': _('CdEDB account request'),})
        if not code:
            return self.redirect(rs, "core/genesis_request_form")
        return self.redirect(rs, "core/index")

    @access("core_admin", "event_admin", "ml_admin")
    def genesis_list_cases(self, rs):
        """Compile a list of genesis cases to review."""
        stati = (const.GenesisStati.to_review, const.GenesisStati.approved)
        realms = []
        if {"core_admin", "event_admin"} & rs.user.roles:
            realms.append("event")
        if {"core_admin", "ml_admin"} & rs.user.roles:
            realms.append("ml")
        data = self.coreproxy.genesis_list_cases(rs, stati=stati, realms=realms)
        review_ids = tuple(
            k for k in data
            if data[k]['case_status'] == const.GenesisStati.to_review)
        to_review = self.coreproxy.genesis_get_cases(rs, review_ids)
        approved = {k: v for k, v in data.items()
                    if v['case_status'] == const.GenesisStati.approved}
        return self.render(rs, "genesis_list_cases", {
            'to_review': to_review, 'approved': approved,})

    @access("core_admin", "event_admin", "ml_admin", modi={"POST"})
    @REQUESTdata(("case_status", "enum_genesisstati"),
                 ("realm", "realm_or_None"))
    def genesis_decide(self, rs, case_id, case_status, realm):
        """Approve or decline a genensis case.

        This sends an email with the link of the final creation page or a
        rejection note to the applicant.
        """
        if rs.errors:
            return self.genesis_list_cases(rs)
        case = self.coreproxy.genesis_get_case(rs, case_id)
        if (not self.is_admin(rs)
                and "{}_admin".format(case['realm']) not in rs.user.roles):
            raise PrivilegeError(_("Not privileged."))
        if case['case_status'] != const.GenesisStati.to_review:
            rs.notify("error", _("Case not to review."))
            return self.genesis_list_cases(rs)
        data = {
            'id': case_id,
            'case_status': case_status,
            'reviewer': rs.user.persona_id,
        }
        if realm:
            data['realm'] = realm
        if case_status == const.GenesisStati.approved:
            data['secret'] = str(uuid.uuid4())
        code = self.coreproxy.genesis_modify_case(rs, data)
        if not code:
            rs.notify("error", _("Failed."))
            return rs.genesis_list_cases(rs)
        case = self.coreproxy.genesis_get_case(rs, case_id)
        if case_status == const.GenesisStati.approved:
            self.do_mail(
                rs, "genesis_approved",
                {'To': (case['username'],),
                 'Subject': _('CdEDB account approved')},
                {'case': case,})
            rs.notify("success", _("Case approved."))
        else:
            self.do_mail(
                rs, "genesis_declined",
                {'To': (case['username'],),
                 'Subject': _('CdEDB account declined')},
                {'case': case,})
            rs.notify("info", _("Case rejected."))
        return self.redirect(rs, "core/genesis_list_cases")

    @access("core_admin", "event_admin", "ml_admin", modi={"POST"})
    def genesis_timeout(self, rs, case_id):
        """Abandon a genesis case.

        If a genesis case is approved, but the applicant loses interest,
        it remains dangling. Thus this enables to archive them.
        """
        case = self.coreproxy.genesis_get_case(rs, case_id)
        if (not self.is_admin(rs)
                and "{}_admin".format(case['realm']) not in rs.user.roles):
            raise PrivilegeError(_("Not privileged."))
        if case['case_status'] != const.GenesisStati.approved:
            rs.notify("error", _("Case not approved."))
            return self.genesis_list_cases(rs)
        data = {
            'id': case_id,
            'case_status': const.GenesisStati.timeout,
            'reviewer': rs.user.persona_id,
        }
        code = self.coreproxy.genesis_modify_case(rs, data)
        self.notify_return_code(rs, code, success=_("Case abandoned."))
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
            rs.notify("warning", _("Persona has no pending change."))
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
        message = _("Change committed.") if ack else _("Change dropped.")
        self.notify_return_code(rs, code, success=message)
        return self.redirect(rs, "core/list_pending_changes")

    @access("core_admin")
    @REQUESTdata(("stati", "[int]"), ("start", "int_or_None"),
                 ("stop", "int_or_None"))
    def view_changelog_meta(self, rs, stati, start, stop):
        """View changelog activity."""
        start = start or 0
        stop = stop or 50
        ## no validation since the input stays valid, even if some options
        ## are lost
        log = self.coreproxy.retrieve_changelog_meta(rs, stati, start, stop)
        persona_ids = (
            {entry['submitted_by'] for entry in log if entry['submitted_by']}
            | {entry['reviewed_by'] for entry in log if entry['reviewed_by']}
            | {entry['persona_id'] for entry in log if entry['persona_id']})
        personas = self.coreproxy.get_personas(rs, persona_ids)
        return self.render(rs, "view_changelog_meta", {
            'log': log, 'personas': personas})

    @access("core_admin")
    @REQUESTdata(("codes", "[int]"), ("persona_id", "cdedbid_or_None"),
                 ("start", "int_or_None"), ("stop", "int_or_None"))
    def view_log(self, rs, codes, persona_id, start, stop):
        """View activity."""
        start = start or 0
        stop = stop or 50
        ## no validation since the input stays valid, even if some options
        ## are lost
        log = self.coreproxy.retrieve_log(rs, codes, persona_id, start, stop)
        persona_ids = (
            {entry['submitted_by'] for entry in log if entry['submitted_by']}
            | {entry['persona_id'] for entry in log if entry['persona_id']})
        personas = self.coreproxy.get_personas(rs, persona_ids)
        return self.render(rs, "view_log", {'log': log, 'personas': personas})

