#!/usr/bin/env python3

"""Services for the core realm."""

import cgitb
import hashlib
import logging
import sys
import uuid

import psycopg2.extensions

from cdedb.frontend.common import (
    AbstractFrontend, REQUESTdata, REQUESTdatadict, access, basic_redirect,
    check_validation as check, merge_dicts, request_data_extractor)
from cdedb.common import (
    ProxyShim, glue, pairwise, extract_roles, privilege_tier, unwrap)
from cdedb.backend.core import CoreBackend
from cdedb.backend.event import EventBackend
from cdedb.backend.past_event import PastEventBackend
from cdedb.query import QUERY_SPECS, QueryOperators, mangle_query_input
from cdedb.database.connection import Atomizer
from cdedb.validation import (
    _PERSONA_CDE_CREATION as CDE_TRANSITION_FIELDS,
    _PERSONA_EVENT_CREATION as EVENT_TRANSITION_FIELDS)
import cdedb.database.constants as const

class CoreFrontend(AbstractFrontend):
    """Note that there is no user role since the basic distinction is between
    anonymous access and personas. """
    realm = "core"
    logger = logging.getLogger(__name__)

    def __init__(self, configpath):
        """
        :type configpath: str
        """
        super().__init__(configpath)
        self.coreproxy = ProxyShim(CoreBackend(configpath))
        self.eventproxy = ProxyShim(EventBackend(configpath))
        self.pasteventproxy = ProxyShim(PastEventBackend(configpath))

    def finalize_session(self, rs):
        super().finalize_session(rs)

    @classmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

    @access("anonymous")
    @REQUESTdata(("wants", "#str_or_None"))
    def index(self, rs, wants=None):
        """Basic entry point.

        :param wants: URL to redirect to upon login
        """
        if wants:
            rs.values['wants'] = self.encode_parameter("core/login", "wants",
                                                       wants)
        return self.render(rs, "index")

    @access("anonymous")
    @REQUESTdata(("kind", "printable_ascii"))
    def error(self, rs, kind):
        """Fault page.

        This may happen upon a database serialization failure during
        concurrent accesses. Other errors are bugs.
        """
        if kind not in {"general", "database"}:
            kind = "general"
        return self.render(rs, "error", {'kind': kind})

    @access("core_admin")
    def meta_info_form(self, rs):
        """Render form."""
        info = self.coreproxy.get_meta_info(rs)
        merge_dicts(rs.values, info)
        return self.render(rs, "meta_info", {'keys': self.conf.META_INFO_KEYS})

    @access("core_admin", modi={"POST"})
    def change_meta_info(self, rs):
        """Change the meta info constants."""
        data_params = tuple((key, "any") for key in self.conf.META_INFO_KEYS)
        data = request_data_extractor(rs, data_params)
        data = check(rs, "meta_info", data, keys=self.conf.META_INFO_KEYS)
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
            rs.notify("error", "Login failure.")
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
            rs.notify("error", "Link expired.")
            return self.redirect(rs, "core/index")

        roles = extract_roles(rs.ambience['persona'])
        may_admin_edit = bool(rs.user.roles & privilege_tier(roles))
        if (rs.ambience['persona']['is_archived']
                and "core_admin" not in rs.user.roles):
            raise PrivilegeError("Only admins may view archived datasets.")

        ALL_ACCESS_LEVELS = {
            "persona", "ml", "assembly", "event", "cde", "core", "admin"}
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
                raise PrivilegeError("Access to non-searchable member data.")
            access_levels.add("cde")
        ## Orgas see their participants
        if "event" not in access_levels:
            for event_id in self.eventproxy.orga_info(rs, rs.user.persona_id):
                if self.eventproxy.list_registrations(rs, event_id, persona_id):
                    access_levels.add("event")
                    break
        ## Mailinglist moderators get no special treatment since this wouldn't
        ## gain them anything
        pass

        ## Retrieve data
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
                "is_assembly_realm", "is_member", "is_searchable",
                "cloud_account", "is_archived", "balance", "decided_search",
                "trial_member", "bub_search")
            for key in masks:
                if key in data:
                    del data[key]
        if "admin" not in access_levels and "notes" in data:
            del data['notes']

        ## Add participation info
        participation_info = None
        if {"event", "cde"} & access_levels and {"event", "cde"} & roles:
            participation_info = self.pasteventproxy.participation_info(
                rs, persona_id)

        return self.render(rs, "show_user", {
            'data': data, 'participation_info': participation_info,
            'may_admin_edit': may_admin_edit})

    @access("core_admin")
    def show_history(self, rs, persona_id):
        """Display user history."""
        history = self.coreproxy.changelog_get_history(rs, persona_id,
                                                       generations=None)
        current_generation = self.coreproxy.changelog_get_generation(
            rs, persona_id)
        current = history[current_generation]
        fields = current.keys()
        history_log = {f: {e['generation']: e[f] for e in history.values()}
                       for f in fields}
        constants = {f: tuple(y for x, y in pairwise(sorted(history.keys()))
                              if history[x][f] == history[y][f])
                     for f in fields}
        return self.render(rs, "show_history", {'entries': history_log,
                                                'constants': constants,
                                                'current': current})

    @access("core_admin")
    @REQUESTdata(("id_to_show", "cdedbid"), ("realm", "str"))
    def admin_show_user(self, rs, id_to_show, realm):
        """Allow admins to view any user data set.

        The realm parameter selects which view on the data set is requested.
        """
        if rs.errors or not "{}_admin".format(realm) in rs.user.roles:
            return self.redirect(rs, "core/index")
        return self.redirect_show_user(rs, id_to_show, realm)

    @access("persona")
    def change_user_form(self, rs):
        """Render form."""
        generation = self.coreproxy.changelog_get_generation(
            rs, rs.user.persona_id)
        data = unwrap(self.coreproxy.changelog_get_history(
            rs, rs.user.persona_id, (generation,)))
        if data['change_status'] == const.MemberChangeStati.pending:
            rs.notify("info", "Change pending.")
        del data['change_note']
        merge_dicts(rs.values, data)
        return self.render(rs, "change_user", {'username': data['username']})

    @access("persona", modi={"POST"})
    @REQUESTdata(("generation", "int"))
    @REQUESTdatadict(
        "display_name", "family_name", "given_names", "title",
        "name_supplement", "telephone", "mobile", "address_supplement",
        "address", "postal_code", "location", "country",
        "address_supplement2", "address2", "postal_code2", "location2",
        "country2", "weblink", "specialisation", "affiliation", "timeline",
        "interests", "free_form", "bub_search")
    def change_user(self, rs, generation, data):
        """Change own data set."""
        data['id'] = rs.user.persona_id
        data = check(rs, "persona", data)
        if rs.errors:
            return self.change_user_form(rs)
        change_note = "Normal dataset change."
        code = self.coreproxy.change_persona(rs, data, generation=generation,
                                             change_note=change_note)
        self.notify_return_code(rs, code)
        if code < 0:
            ## send a mail since changes needing review should be seldom enough
            self.do_mail(
                rs, "pending_changes",
                {'To': (self.conf.MANAGEMENT_ADDRESS,),
                 'Subject': 'CdEDB pending changes',})
        return self.redirect_show_user(rs, rs.user.persona_id)

    @access("core_admin")
    @REQUESTdata(("CSV", "bool"), ("is_search", "bool"))
    def user_search(self, rs, CSV, is_search):
        """Perform search.

        CSV signals whether the output should be a csv-file or an
        ordinary HTML-page.

        is_search signals whether the page was requested by an actual
        query or just to display the search form.
        """
        spec = QUERY_SPECS['qview_core_user']
        ## mangle the input, so we can prefill the form
        query_input = mangle_query_input(rs, spec)
        if is_search:
            query = check(rs, "query_input", query_input, "query",
                          spec=spec, allow_empty=False)
        else:
            query = None
        events = self.pasteventproxy.list_past_events(rs)
        choices = {'pevent_id': events}
        default_queries = self.conf.DEFAULT_QUERIES['qview_core_user']
        params = {
            'spec': spec, 'choices': choices, 'default_queries': default_queries,
            'query': query}
        ## Tricky logic: In case of no validation errors we perform a query
        if not rs.errors and is_search:
            query.scope = "qview_core_user"
            result = self.coreproxy.submit_general_query(rs, query)
            params['result'] = result
            if CSV:
                data = self.fill_template(rs, 'web', 'csv_search_result', params)
                return self.send_file(rs, data=data, inline=False,
                                      filename=self.i18n("result.txt", rs.lang))
        else:
            rs.values['is_search'] = is_search = False
        return self.render(rs, "user_search", params)

    @access("core_admin")
    @REQUESTdata(("CSV", "bool"), ("is_search", "bool"))
    def archived_user_search(self, rs, CSV, is_search):
        """Perform search.

        Archived users are somewhat special since they are not visible
        otherwise.
        """
        spec = QUERY_SPECS['qview_archived_persona']
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
            if CSV:
                data = self.fill_template(rs, 'web', 'csv_search_result', params)
                return self.send_file(rs, data=data, inline=False,
                                      filename=self.i18n("result.txt", rs.lang))
        else:
            rs.values['is_search'] = is_search = False
        return self.render(rs, "archived_user_search", params)

    @access("core_admin")
    def admin_change_user_form(self, rs, persona_id):
        """Render form."""
        generation = self.coreproxy.changelog_get_generation(
            rs, persona_id)
        data = unwrap(self.coreproxy.changelog_get_history(
            rs, persona_id, (generation,)))
        if data['change_status'] == const.MemberChangeStati.pending:
            rs.notify("info", "Change pending.")
        del data['change_note']
        merge_dicts(rs.values, data)
        return self.render(rs, "admin_change_user")


    @access("core_admin", modi={"POST"})
    @REQUESTdata(("generation", "int"), ("change_note", "str_or_None"))
    @REQUESTdatadict(
        "display_name", "family_name", "given_names", "title",
        "name_supplement", "birth_name", "gender", "birthday", "telephone",
        "mobile", "address_supplement", "address", "postal_code",
        "location", "country", "address_supplement2", "address2",
        "postal_code2", "location2", "country2", "weblink",
        "specialisation", "affiliation", "timeline", "interests",
        "free_form", "bub_search", "cloud_account", "notes")
    def admin_change_user(self, rs, persona_id, generation, change_note, data):
        """Privileged edit of data set."""
        data['id'] = persona_id
        ## remove realm specific attributes if persona does not belong to the
        ## realm
        if not rs.ambience['persona']['is_cde_realm']:
            for attr in ("birth_name", "address_supplement2", "address2",
                         "postal_code2", "location2", "country2", "weblink",
                         "specialisation", "affiliation", "timeline",
                         "interests", "free_form", "bub_search"):
                del data[attr]
        if (not rs.ambience['persona']['is_cde_realm']
                and not rs.ambience['persona']['is_event_realm']):
            for attr in ("title", "name_supplement", "gender", "birthday",
                         "telephone", "mobile", "address_supplement",
                         "address", "postal_code", "location", "country"):
                del data[attr]
        data = check(rs, "persona", data)
        if rs.errors:
            rs.notify("error", "Failed validation.")
            return self.admin_change_user_form(rs, persona_id)
        code = self.coreproxy.change_persona(rs, data, generation=generation,
                                             change_note=change_note)
        self.notify_return_code(rs, code)
        return self.redirect_show_user(rs, persona_id)

    @access("admin")
    def change_privileges_form(self, rs, persona_id):
        """Render form."""
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
        merge_dicts(rs.values, rs.ambience['persona'])
        if (target_realm
                and rs.ambience['persona']['is_{}_realm'.format(target_realm)]):
            rs.notify("warning", "No promotion necessary.")
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
            return self.promote_user_form(rs, persona_id)
        code = self.coreproxy.change_persona_realms(rs, data)
        self.notify_return_code(rs, code)
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
            rs.errors.append(("new_password", ValueError("No match.")))
            rs.errors.append(("new_password2", ValueError("No match.")))
        new_password = check(rs, "password_strength", new_password,
                             "new_password")
        if rs.errors:
            return self.change_password_form(rs)
        code, message = self.coreproxy.change_password(
            rs, rs.user.persona_id, old_password, new_password)
        self.notify_return_code(rs, code, success="Password changed.",
                                error=message)
        if not code:
            rs.errors.append(("old_password", ValueError("Wrong password.")))
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
        """First send a confirmation mail, to prevent an adversary from
        changing random passwords."""
        if rs.errors:
            return self.reset_password_form(rs)
        exists = self.coreproxy.verify_existence(rs, email)
        if not exists:
            rs.errors.append(("email", ValueError("Nonexistant user.")))
            return self.reset_password_form(rs)
        success, message = self.coreproxy.make_reset_cookie(rs, email)
        if not success:
            rs.notify("error", message)
        self.do_mail(
            rs, "reset_password",
            {'To': (email,), 'Subject': 'CdEDB password reset'},
            {'email': self.encode_parameter(
                "core/do_password_reset_form", "email", email,
                timeout=self.conf.EMAIL_PARAMETER_TIMEOUT),
             'cookie': message})
        self.logger.info("Sent password reset mail to {} for IP {}.".format(
            email, rs.request.remote_addr))
        rs.notify("success", "Email sent.")
        return self.redirect(rs, "core/index")

    @access("anonymous")
    @REQUESTdata(("email", "#email"), ("cookie", "str"))
    def do_password_reset_form(self, rs, email, cookie):
        """Second form. Pretty similar to first form, but now we know, that
        the account owner actually wants the reset."""
        if rs.errors:
            rs.notify("error", "Link expired.")
            return self.redirect(rs, "core/reset_password_form")
        rs.values['email'] = self.encode_parameter(
            "core/do_password_reset", "email", email,
            timeout=self.conf.EMAIL_PARAMETER_TIMEOUT)
        return self.render(rs, "do_password_reset")

    @access("anonymous", modi={"POST"})
    @REQUESTdata(("email", "#email"), ("new_password", "str"),
                 ("cookie", "str"))
    def do_password_reset(self, rs, email, new_password, cookie):
        """Now we can reset to a new password."""
        if rs.errors:
            rs.notify("error", "Link expired.")
            return self.redirect(rs, "core/reset_password_form")
        new_password = check(rs, "password_strength", new_password,
                             "new_password")
        if rs.errors:
            rs.notify("error", "Password to weak.")
            rs.values['email'] = self.encode_parameter(
                "core/do_password_reset", "email", email)
            return self.redirect(rs, "core/do_password_reset")
        code, message = self.coreproxy.reset_password(rs, email, new_password,
                                                      cookie=cookie)
        self.notify_return_code(rs, code, success="Password reset.",
                                error=message)
        if not code:
            return self.redirect(rs, "core/reset_password_form")
        else:
            return self.redirect(rs, "core/index")

    @access("core_admin", modi={"POST"})
    def admin_password_reset(self, rs, persona_id):
        """Administrative password reset."""
        data = self.coreproxy.get_persona(rs, persona_id)
        code, message = self.coreproxy.make_reset_cookie(rs, data['username'])
        if code:
            code, message = self.coreproxy.new_password(
                rs, data['username'], cookie=message)
        self.notify_return_code(rs, code, success="Password reset.",
                                error=message)
        if not code:
            return self.redirect_show_user(rs, persona_id)
        else:
            self.do_mail(rs, "password_reset_done",
                         {'To': (data['username'],),
                          'Subject': 'CdEDB password reset successful'},
                         {'password': message})
            return self.redirect_show_user(rs, persona_id)

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
                      'Subject': 'CdEDB username change'},
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
            rs.notify("error", "Link expired.")
            return self.redirect(rs, "core/change_username_form")
        rs.values['new_username'] = self.encode_parameter(
            "core/do_username_change", "new_username", new_username,
            timeout=self.conf.EMAIL_PARAMETER_TIMEOUT)
        return self.render(rs, "do_username_change")

    @access("persona", modi={"POST"})
    @REQUESTdata(('new_username', '#email'), ('password', 'str'))
    def do_username_change(self, rs, new_username, password):
        """Now we can do the actual change."""
        if rs.errors:
            rs.notify("error", "Link expired")
            return self.redirect(rs, "core/change_username_form")
        code, message = self.coreproxy.change_username(
            rs, rs.user.persona_id, new_username, password)
        self.notify_return_code(rs, code, success="Username changed.",
                                error=message)
        if not code:
            return self.redirect(rs, "core/username_change_form")
        else:
            return self.redirect(rs, "core/index")

    @access("core_admin")
    def admin_username_change_form(self, rs, persona_id):
        """Render form."""
        data = self.coreproxy.get_persona(rs, persona_id)
        return self.render(rs, "admin_username_change", {'data': data})

    @access("core_admin", modi={"POST"})
    @REQUESTdata(('new_username', 'email_or_None'))
    def admin_username_change(self, rs, persona_id, new_username):
        """Change username without verification."""
        if rs.errors:
            return self.redirect(rs, "core/admin_username_change_form")
        code, message = self.coreproxy.change_username(
            rs, persona_id, new_username, password=None)
        self.notify_return_code(rs, code, success="Username changed.",
                                error=message)
        if not code:
            return self.redirect(rs, "core/admin_username_change_form")
        else:
            return self.redirect_show_user(rs, persona_id)

    @access("core_admin", modi={"POST"})
    @REQUESTdata(("activity", "bool"))
    def toggle_activity(self, rs, persona_id, activity):
        """Enable/disable an account."""
        if rs.errors:
            return self.redirect_show_user(rs, persona_id)
        data = {
            'id': persona_id,
            'is_active': activity,
        }
        change_note = "Toggling activity to {}.".format(activity)
        code = self.coreproxy.change_persona(rs, data, may_wait=False,
                                             change_note=change_note)
        self.notify_return_code(rs, code)
        return self.redirect_show_user(rs, persona_id)

    @access("anonymous")
    def genesis_request_form(self, rs):
        """Render form."""
        return self.render(rs, "genesis_request")

    @access("anonymous", modi={"POST"})
    @REQUESTdatadict("username", "notes", "given_names", "family_name", "realm")
    def genesis_request(self, rs, data):
        """Voice the desire to become a persona.

        This initiates the genesis process.
        """
        data = check(rs, "genesis_case", data, creation=True)
        if not rs.errors and len(data['notes']) > self.conf.MAX_RATIONALE:
            rs.errors.append(("notes", ValueError("Too long.")))
        if rs.errors:
            return self.genesis_request_form(rs)
        case_id = self.coreproxy.genesis_request(rs, data)
        if not case_id:
            rs.notify("error", "Failed.")
            return self.genesis_request_form(rs)
        self.do_mail(
            rs, "genesis_verify",
            {'To': (data['username'],), 'Subject': 'CdEDB account request'},
            {'case_id': self.encode_parameter(
                "core/genesis_verify", "case_id", case_id,
                timeout=self.conf.EMAIL_PARAMETER_TIMEOUT),
             'given_names': data['given_names'],
             'family_name': data['family_name'],})
        rs.notify("success", "Email sent.")
        return self.redirect(rs, "core/index")

    @access("anonymous")
    @REQUESTdata(("case_id", "#int"))
    def genesis_verify(self, rs, case_id):
        """Verify the email address entered in :py:meth:`genesis_request`.

        This is not a POST since the link is shared via email.
        """
        if rs.errors:
            rs.notify("error", "Link expired.")
            return self.genesis_request_form(rs)
        code = self.coreproxy.genesis_verify(rs, case_id)
        self.notify_return_code(rs, code, success="Email verified.",
                                error="Verification failed.")
        if not code:
            return self.redirect(rs, "core/genesis_request_form")
        return self.redirect(rs, "core/index")

    @access("core_admin")
    def genesis_list_cases(self, rs):
        """Compile a list of genesis cases to review."""
        stati = (const.GenesisStati.to_review, const.GenesisStati.approved)
        data = self.coreproxy.genesis_list_cases(rs, stati=stati)
        review_ids = tuple(
            k for k in data
            if data[k]['case_status'] == const.GenesisStati.to_review)
        to_review = self.coreproxy.genesis_get_cases(rs, review_ids)
        approved = {k: v for k, v in data.items()
                    if v['case_status'] == const.GenesisStati.approved}
        return self.render(rs, "genesis_list_cases", {
            'to_review': to_review, 'approved': approved,})

    @access("core_admin", modi={"POST"})
    @REQUESTdata(("case_status", "enum_genesisstati"),
                 ("realm", "realm"))
    def genesis_decide(self, rs, case_id, case_status, realm):
        """Approve or decline a genensis case.

        This sends an email with the link of the final creation page or a
        rejection note to the applicant.
        """
        if rs.errors:
            return self.genesis_list_cases(rs)
        case = self.coreproxy.genesis_get_case(rs, case_id)
        if case['case_status'] != const.GenesisStati.to_review:
            rs.notify("error", "Case not to review.")
            return self.genesis_list_cases(rs)
        data = {
            'id': case_id,
            'realm': realm,
            'case_status': case_status,
            'reviewer': rs.user.persona_id,
        }
        if case_status == const.GenesisStati.approved:
            data['secret'] = str(uuid.uuid4())
        code = self.coreproxy.genesis_modify_case(rs, data)
        if not code:
            rs.notify("error", "Failed.")
            return rs.genesis_list_cases(rs)
        case = self.coreproxy.genesis_get_case(rs, case_id)
        if case_status == const.GenesisStati.approved:
            self.do_mail(
                rs, "genesis_approved",
                {'To': (case['username'],),
                 'Subject': 'CdEDB account approved'},
                {'case': case, 'realm': realm})
            rs.notify("success", "Case approved.")
        else:
            self.do_mail(
                rs, "genesis_declined",
                {'To': (case['username'],),
                 'Subject': 'CdEDB account declined'},
                {'case': case,})
            rs.notify("info", "Case rejected.")
        return self.redirect(rs, "core/genesis_list_cases")

    @access("core_admin", modi={"POST"})
    def genesis_timeout(self, rs, case_id):
        """Abandon a genesis case.

        If a genesis case is approved, but the applicant loses interest,
        it remains dangling. Thus this enables to archive them.
        """
        case = self.coreproxy.genesis_get_case(rs, case_id)
        if case['case_status'] != const.GenesisStati.approved:
            rs.notify("error", "Case not approved.")
            return self.genesis_list_cases(rs)
        data = {
            'id': case_id,
            'case_status': const.GenesisStati.timeout,
            'reviewer': rs.user.persona_id,
        }
        code = self.coreproxy.genesis_modify_case(rs, data)
        self.notify_return_code(rs, code, success="Case abandoned.")
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
            rs.notify("warning", "Persona has no pending change.")
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
        message = "Change comitted." if ack else "Change dropped."
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
        personas = (
            {entry['submitted_by'] for entry in log if entry['submitted_by']}
            | {entry['reviewed_by'] for entry in log if entry['reviewed_by']}
            | {entry['persona_id'] for entry in log if entry['persona_id']})
        persona_data = self.coreproxy.get_personas(rs, personas)
        return self.render(rs, "view_changelog_meta", {
            'log': log, 'persona_data': persona_data})

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
        personas = (
            {entry['submitted_by'] for entry in log if entry['submitted_by']}
            | {entry['persona_id'] for entry in log if entry['persona_id']})
        user_data = self.coreproxy.get_personas(rs, personas)
        return self.render(rs, "view_log", {'log': log, 'user_data': user_data})

