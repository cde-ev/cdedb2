#!/usr/bin/env python3

"""Basic services for the core realm."""

import collections
import datetime
import decimal
import io
import itertools
import operator
import pathlib
import quopri
import tempfile
from typing import Any, Dict, List, Optional, Set, Tuple

import magic
import segno
import segno.helpers
import werkzeug.exceptions
from werkzeug import Response

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
from cdedb.common import (
    CdEDBObject, CdEDBObjectMap, DefaultReturnCode, Realm, RequestState, User,
    make_persona_name, merge_dicts, now, pairwise, sanitize_filename, unwrap,
)
from cdedb.common.exceptions import ArchiveError, PrivilegeError, ValidationWarning
from cdedb.common.fields import (
    META_INFO_FIELDS, PERSONA_ASSEMBLY_FIELDS, PERSONA_CDE_FIELDS, PERSONA_CORE_FIELDS,
    PERSONA_EVENT_FIELDS, PERSONA_ML_FIELDS, PERSONA_STATUS_FIELDS,
    REALM_SPECIFIC_GENESIS_FIELDS,
)
from cdedb.common.i18n import format_country_code, get_localized_country_codes
from cdedb.common.n_ import n_
from cdedb.common.query import Query, QueryOperators, QueryScope, QuerySpecEntry
from cdedb.common.query.log_filter import ChangelogLogFilter, CoreLogFilter
from cdedb.common.roles import (
    ADMIN_KEYS, ADMIN_VIEWS_COOKIE_NAME, ALL_ADMIN_VIEWS, REALM_ADMINS,
    REALM_INHERITANCE, extract_roles, implied_realms,
)
from cdedb.common.sorting import EntitySorter, xsorted
from cdedb.common.validation.validate import (
    PERSONA_CDE_CREATION as CDE_TRANSITION_FIELDS,
    PERSONA_EVENT_CREATION as EVENT_TRANSITION_FIELDS,
)
from cdedb.filter import enum_entries_filter, markdown_parse_safe, money_filter
from cdedb.frontend.common import (
    AbstractFrontend, Headers, REQUESTdata, REQUESTdatadict, REQUESTfile,
    TransactionObserver, access, basic_redirect, check_validation as check,
    check_validation_optional as check_optional, inspect_validation as inspect,
    make_membership_fee_reference, periodic, request_dict_extractor, request_extractor,
)
from cdedb.models.ml import MailinglistGroup
from cdedb.uncommon.submanshim import SubscriptionPolicy

# Name of each realm
USER_REALM_NAMES = {
    "cde": n_("CdE user / Member"),
    "event": n_("Event user"),
    "assembly": n_("Assembly user"),
    "ml": n_("Mailinglist user"),
}


class CoreBaseFrontend(AbstractFrontend):
    """Note that there is no user role since the basic distinction is between
    anonymous access and personas. """
    realm = "core"

    @classmethod
    def is_admin(cls, rs: RequestState) -> bool:
        return super().is_admin(rs)

    @access("anonymous")
    @REQUESTdata("#wants")
    def index(self, rs: RequestState, wants: Optional[str] = None) -> Response:
        """Basic entry point.

        :param wants: URL to redirect to upon login
        """
        rs.ignore_validation_errors()  # drop an invalid "wants"
        meta_info = self.coreproxy.get_meta_info(rs)
        dashboard: CdEDBObject = {}
        if not rs.user.persona_id:
            if wants:
                rs.values['wants'] = self.encode_parameter(
                    "core/login", "wants", wants,
                    persona_id=rs.user.persona_id,
                    timeout=self.conf["UNCRITICAL_PARAMETER_TIMEOUT"])
            return self.render(rs, "login", {'meta_info': meta_info})

        else:
            # Redirect to wanted page, if user meanwhile logged in
            if wants:
                return basic_redirect(rs, wants)

            # genesis cases
            genesis_realms = []
            for realm in REALM_SPECIFIC_GENESIS_FIELDS:
                if {"core_admin", "{}_admin".format(realm)} & rs.user.roles:
                    genesis_realms.append(realm)
            if genesis_realms and "genesis" in rs.user.admin_views:
                data = self.coreproxy.genesis_list_cases(
                    rs, stati=(const.GenesisStati.to_review,),
                    realms=genesis_realms)
                dashboard['genesis_cases'] = len(data)
            # pending changes
            if {"core_user", "cde_user", "event_user"} & rs.user.admin_views:
                data = self.coreproxy.changelog_get_pending_changes(rs)
                dashboard['pending_changes'] = len(data)
            # pending privilege changes
            if "meta_admin" in rs.user.admin_views:
                stati = (const.PrivilegeChangeStati.pending,)
                data = self.coreproxy.list_privilege_changes(
                    rs, stati=stati)
                dashboard['privilege_changes'] = len(data)
            # events organized
            orga_info = self.eventproxy.orga_info(rs, rs.user.persona_id)
            if orga_info:
                orga = {}
                orga_registrations = {}
                events = self.eventproxy.get_events(rs, orga_info)
                present = now()
                for event_id, event in events.items():
                    if (event.begin >= present.date()
                            or abs(event.begin.year - present.year) < 2):
                        regs = self.eventproxy.list_registrations(rs, event.id)
                        orga_registrations[event_id] = len(regs)
                        orga[event_id] = event
                dashboard['orga'] = orga
                dashboard['orga_registrations'] = orga_registrations
                dashboard['present'] = present
            # mailinglists moderated
            moderator_info = self.mlproxy.moderator_info(rs, rs.user.persona_id)
            if moderator_info:
                mailinglists = self.mlproxy.get_mailinglists(rs, moderator_info)
                mailman = self.get_mailman()
                moderator: Dict[int, Dict[str, Any]] = {}
                for ml_id, ml in mailinglists.items():
                    requests = self.mlproxy.get_subscription_states(
                        rs, ml_id, states=(const.SubscriptionState.pending,))
                    moderator[ml_id] = {
                        "id": ml.id,
                        "title": ml.title,
                        "is_active": ml.is_active,
                        "requests": len(requests),
                        "held_mails": mailman.get_held_message_count(ml),
                    }
                dashboard['moderator'] = {k: v for k, v in moderator.items()
                                          if v['is_active']}
            # visible and open events
            if "event" in rs.user.roles:
                event_ids = self.eventproxy.list_events(
                    rs, visible=True, current=True, archived=False)
                events = self.eventproxy.get_events(rs, event_ids.keys())
                final: dict[int, Any] = {}
                events_registration: dict[int, Optional[bool]] = {}
                events_payment_pending: dict[int, bool] = {}
                for event_id, event in events.items():
                    registration, payment_pending = (
                        self.eventproxy.get_registration_payment_info(rs, event_id))
                    # Skip event, if the registration begins more than 2 weeks in future
                    if event.registration_start and \
                            now() + datetime.timedelta(weeks=2) < \
                            event.registration_start:
                        continue
                    # Skip events, that are over or are not registerable anymore
                    if (event.registration_hard_limit
                            and now() > event.registration_hard_limit
                            and not registration
                            or now().date() > event.end):
                        continue
                    final[event_id] = event
                    events_registration[event_id] = registration
                    events_payment_pending[event_id] = payment_pending
                dashboard['events'] = final
                dashboard['events_registration'] = events_registration
                dashboard['events_payment_pending'] = events_payment_pending
            # open assemblies
            if "assembly" in rs.user.roles:
                assembly_ids = self.assemblyproxy.list_assemblies(
                    rs, is_active=True, restrictive=True)
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
    def meta_info_form(self, rs: RequestState) -> Response:
        """Render form."""
        info = self.coreproxy.get_meta_info(rs)
        merge_dicts(rs.values, info)
        return self.render(rs, "meta_info",
                           {"meta_info": info, "hard_lockdown": self.conf["LOCKDOWN"]})

    @access("core_admin", modi={"POST"})
    def change_meta_info(self, rs: RequestState) -> Response:
        """Change the meta info constants."""
        info = self.coreproxy.get_meta_info(rs)
        data_params: vtypes.TypeMapping = {
            key: Optional[str]  # type: ignore[misc]
            for key in META_INFO_FIELDS
        }
        data = request_extractor(rs, data_params)
        data = check(rs, vtypes.MetaInfo, data, keys=info.keys())
        if rs.has_validation_errors():  # pragma: no cover
            return self.meta_info_form(rs)
        assert data is not None
        code = self.coreproxy.set_meta_info(rs, data)
        rs.notify_return_code(code)
        return self.redirect(rs, "core/meta_info_form")

    @access("anonymous", modi={"POST"})
    @REQUESTdata("username", "password", "#wants")
    def login(self, rs: RequestState, username: vtypes.Email,
              password: str, wants: Optional[str]) -> Response:
        """Create session.

        :param wants: URL to redirect to
        """
        if rs.has_validation_errors():
            return self.index(rs)
        sessionkey = self.coreproxy.login(rs, username, password,
                                          rs.request.remote_addr)
        if not sessionkey:
            rs.notify("error", n_("Login failure."))
            rs.extend_validation_errors(
                (("username", ValueError()), ("password", ValueError())))
            rs.ignore_validation_errors()
            return self.index(rs)

        if wants:
            response = basic_redirect(rs, wants)
        elif "member" in rs.user.roles:
            data = self.coreproxy.get_cde_user(rs, rs.user.persona_id)
            if not data['decided_search']:
                response = self.redirect(rs, "cde/consent_decision_form")
            else:
                response = self.redirect(rs, "core/index")
        else:
            response = self.redirect(rs, "core/index")
        response.set_cookie("sessionkey", sessionkey,
                            httponly=True, secure=True, samesite="Lax")
        return response

    # We don't check anti CSRF tokens here, since logging does not harm anyone.
    @access("persona", modi={"POST"}, check_anti_csrf=False)
    def logout(self, rs: RequestState) -> Response:
        """Invalidate the current session."""
        self.coreproxy.logout(rs)
        response = self.redirect(rs, "core/index")
        response.delete_cookie("sessionkey")
        return response

    # Check for anti CSRF here, since this affects multiple sessions.
    @access("persona", modi={"POST"})
    def logout_all(self, rs: RequestState) -> Response:
        """Invalidate all sessions for the current user."""
        if rs.has_validation_errors():  # pragma: no cover
            return self.index(rs)
        count = self.coreproxy.logout(rs, other_sessions=True)
        rs.notify(
            "success", n_("%(count)s session(s) terminated."), {'count': count})
        # Unset persona_id so the notification is encoded correctly.
        rs.user.persona_id = None
        ret = self.redirect(rs, "core/index")
        ret.delete_cookie("sessionkey")
        return ret

    @periodic("deactivate_old_sessions", period=4 * 24)
    def deactivate_old_sessions(self, rs: RequestState, store: CdEDBObject
                                ) -> CdEDBObject:
        """Once per day deactivate old sessions."""
        count = self.coreproxy.deactivate_old_sessions(rs)
        self.logger.info(f"Deactivated {count} old sessions.")
        store["total"] = store.get("total", 0) + count
        return store

    @periodic("clean_session_log", period=4 * 24 * 30)
    def clean_session_log(self, rs: RequestState, store: CdEDBObject) -> CdEDBObject:
        """Once per month, cleanup old inactive sessions."""
        count = self.coreproxy.clean_session_log(rs)
        self.logger.info(f"Deleted {count} old entries from the session log.")
        store["total"] = store.get("total", 0) + count
        return store

    @access("anonymous", modi={"POST"})
    @REQUESTdata("locale", "#wants")
    def change_locale(self, rs: RequestState, locale: vtypes.PrintableASCII,
                      wants: Optional[str]) -> Response:
        """Set 'locale' cookie to override default locale for this user/browser.

        :param locale: The target locale
        :param wants: URL to redirect to (typically URL of the previous page)
        """
        rs.ignore_validation_errors()  # missing values are ok
        if wants:
            response = basic_redirect(rs, wants)
        else:
            response = self.redirect(rs, "core/index")

        if locale in self.conf["I18N_LANGUAGES"]:
            response.set_cookie(
                "locale", locale,
                expires=now() + datetime.timedelta(days=10 * 365))
        else:
            rs.notify("error", n_("Unsupported locale"))
        return response

    @access("persona", modi={"POST"}, check_anti_csrf=False)
    @REQUESTdata("view_specifier", "#wants")
    def modify_active_admin_views(self, rs: RequestState,
                                  view_specifier: vtypes.PrintableASCII,
                                  wants: Optional[str]) -> Response:
        """
        Enable or disable admin views for the current user.

        A list of possible admin views for the current user is returned by
        User.available_admin_views. The user may enable or disable any of them.

        :param view_specifier: A "+" or "-", followed by a commaseperated string
            of admin view names. If prefixed by "+", they are enabled, otherwise
            they are disabled.
        :param wants: URL to redirect to (typically URL of the previous page)
        """
        if wants:
            response = basic_redirect(rs, wants)
        else:
            response = self.redirect(rs, "core/index")

        # Exit early on validation errors
        if rs.has_validation_errors():
            return response

        enabled_views = set(rs.request.cookies.get(ADMIN_VIEWS_COOKIE_NAME, "")
                            .split(','))
        changed_views = set(view_specifier[1:].split(','))
        enable = view_specifier[0] == "+"
        if enable:
            enabled_views.update(changed_views)
        else:
            enabled_views -= changed_views
        response.set_cookie(
            ADMIN_VIEWS_COOKIE_NAME,
            ",".join(enabled_views & ALL_ADMIN_VIEWS),
            expires=now() + datetime.timedelta(days=10 * 365))
        return response

    @access("ml", modi={"POST"}, check_anti_csrf=False)
    @REQUESTdata("md_str")
    def markdown_parse(self, rs: RequestState, md_str: str) -> Response:  # pylint: disable=no-self-use
        if rs.has_validation_errors():
            return Response("", mimetype='text/plain')
        html_str = markdown_parse_safe(md_str)
        return Response(html_str, mimetype='text/plain')

    @access("searchable", "cde_admin")
    @REQUESTdata("#confirm_id")
    def download_vcard(self, rs: RequestState, persona_id: int, confirm_id: int
                       ) -> Response:
        if persona_id != confirm_id or rs.has_validation_errors():
            return self.index(rs)

        vcard = self._create_vcard(rs, persona_id)
        persona = self.coreproxy.get_persona(rs, persona_id)
        filename = sanitize_filename(make_persona_name(persona))

        return self.send_file(rs, data=vcard, mimetype='text/vcard',
                              filename=f'{filename}.vcf')

    @access("searchable", "cde_admin")
    @REQUESTdata("#confirm_id")
    def qr_vcard(self, rs: RequestState, persona_id: int, confirm_id: int) -> Response:
        if persona_id != confirm_id or rs.has_validation_errors():
            return self.index(rs)

        vcard = self._create_vcard(rs, persona_id)

        buffer = io.BytesIO()
        segno.make_qr(vcard).save(buffer, kind='svg', scale=4)

        return self.send_file(rs, afile=buffer, mimetype="image/svg+xml")

    def _create_vcard(self, rs: RequestState, persona_id: int) -> str:
        """
        Generate a vCard string for a user to be delivered to a client.

        :return: The serialized vCard (as in a vcf file)
        """
        if not {'searchable', 'cde_admin'} & rs.user.roles:
            raise werkzeug.exceptions.Forbidden(n_("No cde access to profile."))

        if "cde_admin" not in rs.user.roles and not self.coreproxy.verify_persona(
                rs, persona_id, required_roles=['searchable']):
            raise werkzeug.exceptions.Forbidden(n_(
                "Access to non-searchable member data."))

        persona = self.coreproxy.get_cde_user(rs, persona_id)

        vcard = segno.helpers.make_vcard_data(
            name=";".join((persona['family_name'], persona['given_names'], "",
                           persona['title'] or "", persona['name_supplement'] or "")),
            displayname=make_persona_name(persona, only_given_names=True),
            nickname=persona['display_name'],
            birthday=(
                persona['birthday']
                if persona['birthday'] != datetime.date.min else None
            ),
            street=persona['address'],
            city=persona['location'],
            zipcode=persona['postal_code'],
            country=rs.gettext(format_country_code(persona['country'])),
            email=persona['username'],
            homephone=persona['telephone'],
            cellphone=persona['mobile'],
        )
        return vcard

    @access("persona")
    def mydata(self, rs: RequestState) -> Response:
        """Convenience entry point for own data."""
        assert rs.user.persona_id is not None
        return self.redirect_show_user(rs, rs.user.persona_id)

    @access("persona")
    @REQUESTdata("#confirm_id", "quote_me", "event_id", "ml_id")
    def show_user(self, rs: RequestState, persona_id: int, confirm_id: int,
                  quote_me: bool, event_id: Optional[vtypes.ID],
                  ml_id: Optional[vtypes.ID], internal: bool = False) -> Response:
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
        assert rs.user.persona_id is not None
        if (persona_id != confirm_id or rs.has_validation_errors()) and not internal:
            return self.index(rs)

        is_relative_admin = self.coreproxy.is_relative_admin(rs, persona_id)
        is_relative_or_meta_admin = self.coreproxy.is_relative_admin(
            rs, persona_id, allow_meta_admin=True)

        is_relative_admin_view = self.coreproxy.is_relative_admin_view(
            rs, persona_id)
        is_relative_or_meta_admin_view = self.coreproxy.is_relative_admin_view(
            rs, persona_id, allow_meta_admin=True)

        if (rs.ambience['persona']['is_archived']
                and not is_relative_admin):
            raise werkzeug.exceptions.Forbidden(
                n_("Only admins may view archived datasets."))

        all_access_levels = {
            "persona", "ml", "assembly", "event", "cde", "core", "meta",
            "orga", "moderator"}
        # kind of view with which the user is shown (f.e. relative_admin, orga)
        # relevant to determinate which admin view toggles will be shown
        access_mode = set()
        # The basic access level provides only the name (this should only
        # happen in case of un-quoted searchable member access)
        access_levels = {"persona"}
        # Let users see themselves
        if persona_id == rs.user.persona_id:
            access_levels.update(all_access_levels)
        # Core admins see everything
        if ("core_admin" in rs.user.roles
                and "core_user" in rs.user.admin_views):
            access_levels.update(all_access_levels)
        # Meta admins are meta
        if ("meta_admin" in rs.user.roles
                and "meta_admin" in rs.user.admin_views):
            access_levels.add("meta")
        # There are administraive buttons on this page for all of these admins.
        # All of these admins should see the Account Requests in the nav
        # event_admins and ml_admins additionally always get links to the respective
        # realm data.
        if {"core_admin", "cde_admin", "event_admin", "ml_admin"} & rs.user.roles:
            access_mode.add("any_admin")
        # Other admins see their realm if they are relative admin
        if is_relative_admin:
            access_mode.add("any_admin")
            for realm in ("ml", "assembly", "event", "cde"):
                if (f"{realm}_admin" in rs.user.roles
                        and f"{realm}_user" in rs.user.admin_views):
                    # Relative admins can see core data
                    access_levels.add("core")
                    access_levels.add(realm)
        # Members see other members (modulo quota)
        if "searchable" in rs.user.roles and quote_me:
            if (not (rs.ambience['persona']['is_member'] and
                     rs.ambience['persona']['is_searchable'])
                    and "cde_admin" not in access_levels):
                raise werkzeug.exceptions.Forbidden(n_(
                    "Access to non-searchable member data."))
            access_levels.add("cde")
        # Orgas see their participants
        if event_id:
            is_admin = "event_admin" in rs.user.roles
            is_viewing_admin = is_admin and "event_orga" in rs.user.admin_views
            is_orga = event_id in self.eventproxy.orga_info(
                rs, rs.user.persona_id)
            if is_orga or is_admin:
                is_participant = self.eventproxy.list_registrations(
                    rs, event_id, persona_id)
                if (is_orga or is_viewing_admin) and is_participant:
                    access_levels.add("event")
                    access_levels.add("orga")
                # Admins who are also orgas can not disable this admin view
                if is_admin and not is_orga and is_participant:
                    access_mode.add("orga")
        # Mailinglist moderators see all users related to their mailinglist.
        # This excludes users with relation "unsubscribed", since their email address
        # is not relevant.
        if ml_id:
            # determinate if the user is relevant admin of this mailinglist
            ml_type = self.mlproxy.get_ml_type(rs, ml_id)
            is_admin = ml_type.is_relevant_admin(rs.user)
            is_moderator = ml_id in self.mlproxy.moderator_info(
                rs, rs.user.persona_id)
            # Admins who are also moderators can not disable this admin view
            if is_admin and not is_moderator:
                access_mode.add("moderator")
            relevant_stati = [s for s in const.SubscriptionState
                              if s not in {const.SubscriptionState.unsubscribed,
                                           const.SubscriptionState.none}]
            if is_moderator or ml_type.has_moderator_view(rs.user):
                subscriptions = self.mlproxy.get_subscription_states(
                    rs, ml_id, states=relevant_stati)
                if persona_id in subscriptions:
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
            data.update(self.coreproxy.get_event_user(rs, persona_id, event_id))
        if "cde" in access_levels and "cde" in roles:
            data.update(self.coreproxy.get_cde_user(rs, persona_id))
            if "core" in access_levels:
                user_lastschrift = self.cdeproxy.list_lastschrift(
                    rs, persona_ids=(persona_id,), active=True)
                data['has_lastschrift'] = bool(user_lastschrift)
        if is_relative_or_meta_admin and is_relative_or_meta_admin_view:
            # This is a bit involved to not contaminate the data dict
            # with keys which are not applicable to the requested persona
            total = self.coreproxy.get_total_persona(rs, persona_id)
            data['notes'] = total['notes']
            data['username'] = total['username']

        # Determinate if vcard should be visible
        data['show_vcard'] = "cde" in access_levels and "cde" in roles

        # Cull unwanted data
        if not ('is_cde_realm' in data and data['is_cde_realm']) and 'foto' in data:
            del data['foto']
        # hide the donation property if no active lastschrift exists, to avoid confusion
        if "donation" in data and not data.get("has_lastschrift"):
            del data["donation"]
        # relative admins, core admins and the user himself got "core"
        if "core" not in access_levels:
            masks = ["balance", "decided_search", "trial_member", "bub_search",
                     "is_searchable", "paper_expuls", "donation"]
            if "meta" not in access_levels:
                masks.extend([
                    "is_active", "is_meta_admin", "is_core_admin",
                    "is_cde_admin", "is_event_admin", "is_ml_admin",
                    "is_assembly_admin", "is_cde_realm", "is_event_realm",
                    "is_ml_realm", "is_assembly_realm", "is_archived",
                    "notes"])
            if "orga" not in access_levels:
                masks.extend(["is_member", "gender", "pronouns_nametag"])
            for key in masks:
                if key in data:
                    del data[key]

        # Add past event participation info
        past_events = None
        if "cde" in access_levels and {"event", "cde"} & roles:
            past_events = self.pasteventproxy.participation_info(rs, persona_id)

        # Retrieve number of active sessions if the user is viewing his own profile
        active_session_count = None
        if rs.user.persona_id == persona_id:
            active_session_count = self.coreproxy.count_active_sessions(rs)

        # Check whether we should display an option for using the quota
        quoteable = (not quote_me
                     and "cde" not in access_levels
                     and "searchable" in rs.user.roles
                     and rs.ambience['persona']['is_member']
                     and rs.ambience['persona']['is_searchable'])

        meta_info = self.coreproxy.get_meta_info(rs)
        reference = make_membership_fee_reference(data)

        return self.render(rs, "show_user", {
            'data': data, 'past_events': past_events, 'meta_info': meta_info,
            'is_relative_admin_view': is_relative_admin_view, 'reference': reference,
            'quoteable': quoteable, 'access_mode': access_mode,
            'active_session_count': active_session_count, 'ADMIN_KEYS': ADMIN_KEYS,
        })

    @access("member")
    def my_lastschrift(self, rs: RequestState) -> Response:
        """Convenience entry point to view own lastschrift.

        This is only in the core frontend to stay consistent in the path naming scheme.
        """
        return self.redirect(rs, "cde/lastschrift_show",
                             {"persona_id": rs.user.persona_id})

    @access("event")
    def show_user_events(self, rs: RequestState, persona_id: vtypes.ID) -> Response:
        """Render overview which events a given user is registered for."""
        if not (self.coreproxy.is_relative_admin(rs, persona_id)
                or "event_admin" in rs.user.roles or rs.user.persona_id == persona_id):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        if not self.coreproxy.verify_id(rs, persona_id, is_archived=False):
            # reconnoitre_ambience leads to 404 if user does not exist at all.
            rs.notify("error", n_("Persona is archived."))
            return self.redirect_show_user(rs, persona_id)

        registrations = self.eventproxy.list_persona_registrations(rs, persona_id)
        registration_ids: Dict[int, int] = {}
        registration_parts: Dict[int, Dict[int, const.RegistrationPartStati]] = {}
        for event_id, reg in registrations.items():
            registration_ids[event_id] = unwrap(reg.keys())
            registration_parts[event_id] = unwrap(reg.values())
        events = self.eventproxy.get_events(rs, registrations.keys())
        return self.render(rs, "show_user_events",
                           {'events': events, 'registration_ids': registration_ids,
                            'registration_parts': registration_parts})

    @access("event")
    def show_user_events_self(self, rs: RequestState) -> Response:
        """Shorthand to view event registrations for oneself."""
        return self.redirect(rs, "core/show_user_events",
                             {'persona_id': rs.user.persona_id})

    @access("ml")
    def show_user_mailinglists(self, rs: RequestState, persona_id: vtypes.ID
                               ) -> Response:
        """Render overview of mailinglist data of a certain user."""
        if not (self.coreproxy.is_relative_admin(rs, persona_id)
                or "ml_admin" in rs.user.roles or rs.user.persona_id == persona_id):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        if not self.coreproxy.verify_id(rs, persona_id, is_archived=False):
            # reconnoitre_ambience leads to 404 if user does not exist at all.
            rs.notify("error", n_("Persona is archived."))
            return self.redirect_show_user(rs, persona_id)

        subscriptions = self.mlproxy.get_user_subscriptions(rs, persona_id)
        mailinglists = self.mlproxy.get_mailinglists(rs, subscriptions.keys())
        addresses = self.mlproxy.get_user_subscription_addresses(rs, persona_id)

        grouped: Dict[MailinglistGroup, CdEDBObjectMap]
        grouped = collections.defaultdict(dict)
        for mailinglist_id, ml in mailinglists.items():
            grouped[ml.sortkey][mailinglist_id] = {
                'title': ml.title,
                'id': mailinglist_id,
                'address': addresses.get(mailinglist_id),
                'is_active': ml.is_active,
            }

        return self.render(rs, "show_user_mailinglists", {
            'groups': MailinglistGroup,
            'mailinglists': grouped,
            'subscriptions': subscriptions})

    @access("ml")
    def show_user_mailinglists_self(self, rs: RequestState) -> Response:
        """Redirect to use `self` instead of persona_id to make ambience work."""
        return self.redirect(rs, "core/show_user_mailinglists",
                             {'persona_id': rs.user.persona_id})

    @access(*REALM_ADMINS)
    def show_history(self, rs: RequestState, persona_id: int) -> Response:
        """Display user history."""
        if not self.coreproxy.is_relative_admin(rs, persona_id):
            raise werkzeug.exceptions.Forbidden(n_("Not a relative admin."))
        history = self.coreproxy.changelog_get_history(rs, persona_id, generations=None)
        # retrieve the latest version of the changelog, including pending ones
        current_generation = self.coreproxy.changelog_get_generation(rs, persona_id)
        current = history[current_generation]
        # do not use the latest changelog version, since we want to highlight any
        # inconsistencies between latest changelog generation and core.personas
        inconsistencies = self.coreproxy.get_changelog_inconsistencies(rs, persona_id)
        # to display the differences between the latest committed changelog generation
        # and the state in core.personas
        committed = self.coreproxy.get_total_persona(rs, persona_id)
        fields = current.keys()
        stati = const.PersonaChangeStati
        constants = {}
        for f in fields:
            total_const: List[int] = []
            tmp: List[int] = []
            already_committed = False
            for x, y in pairwise(xsorted(history.keys())):
                if history[x]['code'] == stati.committed:
                    already_committed = True
                # Somewhat involved determination of a field being constant.
                #
                # Basically it's done by the following line, except we
                # don't want to mask a change that was rejected and then
                # resubmitted and accepted.
                is_constant = history[x][f] == history[y][f]
                if (history[x]['code'] == stati.nacked
                        and not already_committed):
                    is_constant = False
                if is_constant:
                    tmp.append(y)
                else:
                    already_committed = False
                    if tmp:
                        total_const.extend(tmp)
                        tmp = []
            if tmp:
                total_const.extend(tmp)
            constants[f] = total_const
        pending = {i for i in history
                   if history[i]['code'] == stati.pending}
        # Track the omitted information whether a new value finally got
        # committed or not.
        #
        # This is necessary since we only show those data points, where the
        # data (e.g. the name) changes. This does especially not detect
        # meta-data changes (e.g. the change-status).
        eventual_status = {f: {gen: entry['code']
                               for gen, entry in history.items()
                               if gen not in constants[f]}
                           for f in fields}
        for f in fields:
            for gen in xsorted(history):
                if gen in constants[f]:
                    anchor = max(g for g in eventual_status[f] if g < gen)
                    this_status = history[gen]['code']
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
            'personas': personas, 'ADMIN_KEYS': ADMIN_KEYS,
            'inconsistencies': inconsistencies or [],
            'committed': committed,
        })

    @access("core_admin")
    @REQUESTdata("phrase", "include_archived")
    def admin_show_user(self, rs: RequestState, phrase: str, include_archived: bool
                        ) -> Response:
        """Allow admins to view any user data set.

        The search phrase may be anything: a numeric id (wellformed with
        check digit or without) or a string matching the data set.

        :param: include_archived: If True, allow archived users to be found.
        """
        if rs.has_validation_errors():
            return self.index(rs)
        anid, errs = inspect(vtypes.CdedbID, phrase, argname="phrase")
        if not errs:
            assert anid is not None
            if self.coreproxy.verify_id(rs, anid, is_archived=None):
                return self.redirect_show_user(rs, anid)
        anid, errs = inspect(vtypes.ID, phrase, argname="phrase")
        if not errs:
            assert anid is not None
            if self.coreproxy.verify_id(rs, anid, is_archived=None):
                return self.redirect_show_user(rs, anid)

        scope = QueryScope.all_core_users if include_archived else QueryScope.core_user
        terms = tuple(t.strip() for t in phrase.split(' ') if t)
        key = "username,family_name,given_names,display_name"
        spec = scope.get_spec()
        spec[key] = QuerySpecEntry("str", "")
        query = Query(
            scope=scope,
            spec=spec,
            fields_of_interest=("personas.id", "family_name", "given_names",
                                "display_name", "username"),
            constraints=[(key, QueryOperators.match, t) for t in terms],
            order=(("personas.id", True),),
        )
        result = self.coreproxy.submit_general_query(rs, query)
        if len(result) == 1:
            return self.redirect_show_user(rs, result[0]["id"])

        # Precise search didn't uniquely match, hence a fulltext search now. Results
        # will be a superset of the above, since all relevant fields are in fulltext.
        query.constraints = [('fulltext', QueryOperators.containsall, terms)]
        result = self.coreproxy.submit_general_query(rs, query)
        if len(result) == 1:
            return self.redirect_show_user(rs, result[0]["id"])
        elif result:
            params = query.serialize_to_url()
            rs.values.update(params)
            return self.user_search(rs, is_search=True, download=None, query=query)
        else:
            rs.notify("warning", n_("No account found."))
            return self.index(rs)

    @access("persona")
    @REQUESTdata("phrase", "kind", "aux")
    def select_persona(self, rs: RequestState, phrase: str, kind: str,
                       aux: Optional[vtypes.ID]) -> Response:
        """Provide data for intelligent input fields.

        This searches for users by name so they can be easily selected
        without entering their numerical ids. This is for example
        intended for addition of orgas to events.

        The kind parameter specifies the purpose of the query which decides
        the privilege level required and the basic search paramaters.

        Allowed kinds:

        - ``admin_persona``: Search for users as core_admin, cde_admin or auditor.
        - ``admin_all_users``: Like ``admin_persona``, but for archived users.
        - ``cde_user``: Search for a cde user as cde_admin.
        - ``past_event_user``: Search for an event user to add to a past
          event as cde_admin
        - ``pure_assembly_user``: Search for an assembly only user as
          assembly_admin or presider. Needed for external_signup.
        - ``assembly_user``: Search for an assembly user as assembly_admin or presider
        - ``ml_user``: Search for a mailinglist user as ml_admin or moderator
        - ``pure_ml_user``: Search for an assembly only user as ml_admin.
          Needed for the account merger.
        - ``ml_subscriber``: Search for a mailinglist user for subscription purposes.
          Needed for add_subscriber action only.
        - ``event_user``: Search an event user as event_admin or orga

        The aux parameter allows to supply an additional id for example
        in the case of a moderator this would be the relevant
        mailinglist id.

        Required aux value based on the 'kind':

        * ``ml_subscriber``: Id of the mailinglist for context
        """
        if rs.has_validation_errors():
            return self.send_json(rs, {})

        search_additions = []
        scope = QueryScope.core_user
        mailinglist = None
        num_preview_personas = (self.conf["NUM_PREVIEW_PERSONAS_CORE_ADMIN"]
                                if {"core_admin"} & rs.user.roles
                                else self.conf["NUM_PREVIEW_PERSONAS"])
        if kind == "admin_persona":
            if not {"core_admin", "cde_admin", "auditor"} & rs.user.roles:
                raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        elif kind == "admin_all_users":
            if "core_admin" not in rs.user.roles:
                raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
            scope = QueryScope.all_core_users
        elif kind == "cde_user":
            if not {"cde_admin", "auditor"} & rs.user.roles:
                raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
            search_additions.append(
                ("is_cde_realm", QueryOperators.equal, True))
        elif kind == "past_event_user":
            if not {"cde_admin", "auditor"} & rs.user.roles:
                raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
            search_additions.append(
                ("is_event_realm", QueryOperators.equal, True))
        elif kind == "pure_assembly_user":
            # No check by assembly, as this behaves identical for each assembly.
            if not rs.user.presider and "assembly_admin" not in rs.user.roles:
                raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
            search_additions.append(
                ("is_assembly_realm", QueryOperators.equal, True))
            search_additions.append(
                ("is_member", QueryOperators.equal, False))
        elif kind == "assembly_user":
            # No check by assembly, as this behaves identical for each assembly.
            if not (rs.user.presider or {"assembly_admin", "auditor"} & rs.user.roles):
                raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
            search_additions.append(
                ("is_assembly_realm", QueryOperators.equal, True))
        elif kind == "event_user":
            # No check by event, as this behaves identical for each event.
            if not (rs.user.orga or {"event_admin", "auditor"} & rs.user.roles):
                raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
            search_additions.append(
                ("is_event_realm", QueryOperators.equal, True))
        elif kind == "ml_user":
            relevant_admin_roles = {"core_admin", "cde_admin", "event_admin", "auditor",
                                    "assembly_admin", "cdelokal_admin", "ml_admin"}
            # No check by mailinglist, as this behaves identical for each list.
            if not (rs.user.moderator or relevant_admin_roles & rs.user.roles):
                raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
            search_additions.append(
                ("is_ml_realm", QueryOperators.equal, True))
        elif kind == "pure_ml_user":
            if "ml_admin" not in rs.user.roles:
                raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
            search_additions.extend((
                ("is_ml_realm", QueryOperators.equal, True),
                ("is_assembly_realm", QueryOperators.equal, False),
                ("is_event_realm", QueryOperators.equal, False)))
        elif kind == "ml_subscriber":
            if aux is None:
                raise werkzeug.exceptions.BadRequest(n_(
                    "Must provide id of the associated mailinglist to use this kind."))
            # In this case, the return value depends on the respective mailinglist.
            mailinglist = self.mlproxy.get_mailinglist(rs, aux)
            if not self.mlproxy.may_manage(rs, aux, allow_restricted=False):
                raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
            search_additions.append(
                ("is_ml_realm", QueryOperators.equal, True))
        else:
            return self.send_json(rs, {})

        data: Optional[Tuple[CdEDBObject, ...]] = None

        # Core admins are allowed to search by raw ID or CDEDB-ID
        if "core_admin" in rs.user.roles:
            anid: Optional[vtypes.ID]
            anid, errs = inspect(vtypes.CdedbID, phrase, argname="phrase")
            if not errs:
                assert anid is not None
                tmp = self.coreproxy.get_personas(rs, (anid,))
                if tmp:
                    data = (unwrap(tmp),)
            else:
                anid, errs = inspect(vtypes.ID, phrase, argname="phrase")
                if not errs:
                    assert anid is not None
                    tmp = self.coreproxy.get_personas(rs, (anid,))
                    if tmp:
                        data = (unwrap(tmp),)

        # Don't query, if search phrase is too short
        if not data and len(phrase) < self.conf["NUM_PREVIEW_CHARS"]:
            return self.send_json(rs, {})

        terms: Tuple[str, ...] = tuple()
        if data is None:
            terms = tuple(t.strip() for t in phrase.split(' ') if t)
            valid = True
            for t in terms:
                _, errs = inspect(vtypes.NonRegex, t, argname="phrase")
                if errs:
                    valid = False
            if not valid:
                data = tuple()
            else:
                search: List[Tuple[str, QueryOperators, Any]]
                key = "username,family_name,given_names,display_name"
                search = [(key, QueryOperators.match, t) for t in terms]
                search.extend(search_additions)
                spec = scope.get_spec()
                spec[key] = QuerySpecEntry("str", "")
                query = Query(
                    scope, spec,
                    ("personas.id", "username", "family_name", "given_names",
                     "display_name"), search, (("personas.id", True),))
                data = self.coreproxy.submit_select_persona_query(rs, query)

        # Filter result to get only users allowed to be a subscriber of a list,
        # which potentially are no subscriber yet.
        if mailinglist:
            data = self.mlproxy.filter_personas_by_policy(
                rs, mailinglist, data, SubscriptionPolicy.addable_policies())

        # Strip data to contain at maximum `num_preview_personas` results
        if len(data) > num_preview_personas:
            data = tuple(xsorted(
                data, key=lambda e: e['id'])[:num_preview_personas])

        # Check if name occurs multiple times to add email address in this case
        counter: Dict[str, int] = collections.defaultdict(lambda: 0)
        for entry in data:
            counter[make_persona_name(entry)] += 1

        # Generate return JSON list
        ret = []
        for entry in xsorted(data, key=EntitySorter.persona):
            name = make_persona_name(entry)
            result = {
                'id': entry['id'],
                'name': name,
            }
            # Email/username is only delivered if we have relative_admins
            # rights, a search term with an @ (and more) matches the mail
            # address, or the mail address is required to distinguish equally
            # named users
            searched_email = any(
                '@' in t and len(t) > self.conf["NUM_PREVIEW_CHARS"]
                and entry['username'] and t in entry['username']
                for t in terms)
            if counter[name] > 1 or searched_email or \
                    self.coreproxy.is_relative_admin(rs, entry['id']):
                result['email'] = entry['username']
            ret.append(result)
        return self.send_json(rs, {'personas': ret})

    def _changeable_persona_fields(self, rs: RequestState, user: User,
                                   restricted: bool = True) -> Set[str]:
        """Helper to retrieve the appropriate fields for (admin_)change_user.

        :param restricted: If True, only return fields the user may change
            themselves, i.e. remove the restricted fields.
        """
        assert user.persona_id is not None
        ret: Set[str] = set()
        # some fields are of no interest here.
        hidden_fields = set(PERSONA_STATUS_FIELDS) | {"id", "username"}
        hidden_cde_fields = (hidden_fields - {"is_searchable"}) | {
            "balance", "bub_search", "decided_search", "foto", "trial_member"}
        roles_to_fields = {
            "persona": (set(PERSONA_CORE_FIELDS) | {"notes"}) - hidden_fields,
            "ml": set(PERSONA_ML_FIELDS) - hidden_fields,
            "assembly": set(PERSONA_ASSEMBLY_FIELDS) - hidden_fields,
            "event": set(PERSONA_EVENT_FIELDS) - hidden_fields,
            "cde": (set(PERSONA_CDE_FIELDS) - hidden_cde_fields),
        }
        for role, fields in roles_to_fields.items():
            if role in user.roles:
                ret |= fields

        # hide the donation property if no active lastschrift exists, to avoid confusion
        if "donation" in ret and not self.cdeproxy.list_lastschrift(
                rs, [user.persona_id], active=True):
            ret.remove("donation")

        restricted_fields = {"notes", "birthday", "is_searchable"}
        if restricted:
            ret -= restricted_fields

        return ret

    @access("persona")
    def change_user_form(self, rs: RequestState) -> Response:
        """Render form."""
        assert rs.user.persona_id is not None
        generation = self.coreproxy.changelog_get_generation(
            rs, rs.user.persona_id)
        data = unwrap(self.coreproxy.changelog_get_history(
            rs, rs.user.persona_id, (generation,)))
        if data['code'] == const.PersonaChangeStati.pending:
            rs.notify("info", n_("Change pending."))
        del data['change_note']
        merge_dicts(rs.values, data)
        # The values of rs.values are converted to strings if there was a validation
        #  error. This is a bit hacky, but ensures that donation is always a decimal.
        if rs.values.get("donation") is not None:
            rs.values["donation"] = decimal.Decimal(rs.values["donation"])
        shown_fields = self._changeable_persona_fields(rs, rs.user, restricted=True)
        return self.render(rs, "change_user", {
            'username': data['username'],
            'shown_fields': shown_fields,
            'min_donation': self.conf["MINIMAL_LASTSCHRIFT_DONATION"],
            'max_donation': self.conf["MAXIMAL_LASTSCHRIFT_DONATION"]
        })

    @access("persona", modi={"POST"})
    @REQUESTdata("generation")
    def change_user(self, rs: RequestState, generation: int) -> Response:
        """Change own data set."""
        assert rs.user.persona_id is not None
        attributes = self._changeable_persona_fields(rs, rs.user, restricted=True)
        data = request_dict_extractor(rs, attributes)
        data['id'] = rs.user.persona_id
        data = check(rs, vtypes.Persona, data, "persona")
        # take special care for annual donations in combination with lastschrift
        if (data and "donation" in data
                and (lastschrift_ids := self.cdeproxy.list_lastschrift(
                        rs, [rs.user.persona_id], active=True))):
            current = self.coreproxy.get_cde_user(rs, rs.user.persona_id)
            min_donation = self.conf["MINIMAL_LASTSCHRIFT_DONATION"]
            max_donation = self.conf["MAXIMAL_LASTSCHRIFT_DONATION"]
            # The user may specify only donations between a specific minimal and maximal
            # value. However, admins may change this to arbitrary values, so we allow
            # to surpass the check if the user didn't change the donation's amount.
            if (current["donation"] != data["donation"]
                    and not min_donation <= data["donation"] <= max_donation):
                rs.append_validation_error(("donation", ValueError(
                    n_("Lastschrift donation must be between %(min)s and %(max)s."),
                    {"min": money_filter(min_donation),
                     "max": money_filter(max_donation)})))
            lastschrift = self.cdeproxy.get_lastschrift(
                rs, unwrap(lastschrift_ids.keys()))
            # "Enforce" consent of the account holder if the user changed his donation.
            if (current["donation"] != data["donation"]
                    and lastschrift["account_owner"] and not rs.ignore_warnings):
                msg = n_("You are not the owner of the linked bank account. Make sure"
                         " the owner agreed to the change before submitting it here.")
                rs.append_validation_error(("donation", ValidationWarning(msg)))
        if data and data.get('gender') == const.Genders.not_specified:
            rs.append_validation_error(('gender', ValueError(n_("Must not be empty."))))
        if rs.has_validation_errors():
            return self.change_user_form(rs)
        assert data is not None
        change_note = "Normale Änderung."
        code = self.coreproxy.change_persona(
            rs, data, generation=generation, change_note=change_note)
        rs.notify_return_code(code)
        return self.redirect_show_user(rs, rs.user.persona_id)

    @access("core_admin")
    @REQUESTdata("download", "is_search")
    def user_search(self, rs: RequestState, download: Optional[str], is_search: bool,
                    query: Optional[Query] = None) -> Response:
        """Perform search."""
        events = self.pasteventproxy.list_past_events(rs)
        choices: Dict[str, Dict[Any, str]] = {
            'pevent_id': collections.OrderedDict(
                xsorted(events.items(), key=operator.itemgetter(1))),
            'gender': collections.OrderedDict(
                enum_entries_filter(
                    const.Genders,
                    rs.gettext if download is None else rs.default_gettext)),
            'country': collections.OrderedDict(get_localized_country_codes(rs)),
        }
        if query and query.scope == QueryScope.core_user:
            query.constraints.append(("is_archived", QueryOperators.equal, False))
            query.scope = QueryScope.all_core_users
        return self.generic_user_search(
            rs, download, is_search, QueryScope.all_core_users,
            self.coreproxy.submit_general_query, choices=choices, query=query)

    @access("core_admin")
    def create_user_form(self, rs: RequestState) -> Response:
        realms = USER_REALM_NAMES.copy()
        if self.conf["CDEDB_OFFLINE_DEPLOYMENT"]:
            del realms["assembly"]
            del realms["ml"]
        return self.render(rs, "create_user", {'realms': realms})

    @access("core_admin")
    @REQUESTdata("realm")
    def create_user(self, rs: RequestState, realm: str) -> Response:
        if realm not in USER_REALM_NAMES.keys():
            rs.append_validation_error(("realm",
                                        ValueError(n_("No valid realm."))))
        if rs.has_validation_errors():
            return self.create_user_form(rs)
        return self.redirect(rs, realm + "/create_user")

    @staticmethod
    def admin_bits(rs: RequestState) -> Set[Realm]:
        """Determine realms this admin can see.

        This is somewhat involved due to realm inheritance.
        """
        ret = {"persona"}
        if "core_admin" in rs.user.roles:
            ret |= REALM_INHERITANCE.keys()
        for realm in REALM_INHERITANCE:
            if "{}_admin".format(realm) in rs.user.roles:
                ret |= {realm} | implied_realms(realm)
        return ret

    @access(*REALM_ADMINS)
    def admin_change_user_form(self, rs: RequestState, persona_id: int) -> Response:
        """Render form."""
        if not self.coreproxy.is_relative_admin(rs, persona_id):
            raise werkzeug.exceptions.Forbidden(n_("Not a relative admin."))
        if rs.ambience['persona']['is_archived']:
            rs.notify("error", n_("Persona is archived."))
            return self.redirect_show_user(rs, persona_id)

        generation = self.coreproxy.changelog_get_generation(
            rs, persona_id)
        data = unwrap(self.coreproxy.changelog_get_history(
            rs, persona_id, (generation,)))
        del data['change_note']
        merge_dicts(rs.values, data)
        # The values of rs.values are converted to strings if there was a validation
        #  error. This is a bit hacky, but ensures that donation is always a decimal.
        if rs.values.get("donation") is not None:
            rs.values["donation"] = decimal.Decimal(rs.values["donation"])
        if data['code'] == const.PersonaChangeStati.pending:
            rs.notify("info", n_("Change pending."))
        roles = extract_roles(rs.ambience['persona'], introspection_only=True)
        user = User(persona_id=persona_id, roles=roles)
        shown_fields = self._changeable_persona_fields(rs, user, restricted=False)
        return self.render(rs, "admin_change_user", {
            'admin_bits': self.admin_bits(rs),
            'shown_fields': shown_fields,
        })

    @access(*REALM_ADMINS, modi={"POST"})
    @REQUESTdata("generation", "change_note")
    def admin_change_user(self, rs: RequestState, persona_id: int,
                          generation: int, change_note: Optional[str]) -> Response:
        """Privileged edit of data set."""
        if not self.coreproxy.is_relative_admin(rs, persona_id):
            raise werkzeug.exceptions.Forbidden(n_("Not a relative admin."))
        # Assure we don't accidently change the original.
        roles = extract_roles(rs.ambience['persona'], introspection_only=True)
        user = User(persona_id=persona_id, roles=roles)
        attributes = self._changeable_persona_fields(rs, user, restricted=False)
        data = request_dict_extractor(rs, attributes)
        data['id'] = persona_id
        data = check(rs, vtypes.Persona, data)
        # take special care for annual donations in combination with lastschrift
        if (data and "donation" in data and self.cdeproxy.list_lastschrift(
                rs, [persona_id], active=True)):
            min_donation = self.conf["MINIMAL_LASTSCHRIFT_DONATION"]
            max_donation = self.conf["MAXIMAL_LASTSCHRIFT_DONATION"]
            # The user may specify only donations between a specific minimal and maximal
            # value. However, admins may change this to arbitrary values.
            if (not min_donation <= data["donation"] <= max_donation
                    and not rs.ignore_warnings):
                rs.append_validation_error(("donation", ValidationWarning(
                    n_("Lastschrift donation is outside of %(min)s and %(max)s."
                       " The user will not be able to change this amount by himself."),
                    {"min": money_filter(min_donation),
                     "max": money_filter(max_donation)})))
        if rs.has_validation_errors():
            return self.admin_change_user_form(rs, persona_id)
        assert data is not None
        code = self.coreproxy.change_persona(
            rs, data, generation=generation, change_note=change_note)
        rs.notify_return_code(code)
        return self.redirect_show_user(rs, persona_id)

    @access("persona")
    def view_admins(self, rs: RequestState) -> Response:
        """Render list of all admins of the users realms."""

        admins = {
            # meta admins
            "meta": self.coreproxy.list_admins(rs, "meta"),
            "core": self.coreproxy.list_admins(rs, "core"),
        }

        display_realms = rs.user.roles.intersection(REALM_INHERITANCE)
        if "cde" in display_realms:
            display_realms.add("finance")
            display_realms.add("auditor")
        if "ml" in display_realms:
            display_realms.add("cdelokal")
        for realm in display_realms:
            admins[realm] = self.coreproxy.list_admins(rs, realm)

        persona_ids = set(itertools.chain.from_iterable(admins.values()))
        personas = self.coreproxy.get_personas(rs, persona_ids)

        for admin in admins:
            admins[admin] = xsorted(
                admins[admin],
                key=lambda anid: EntitySorter.persona(personas[anid])
            )

        return self.render(
            rs, "view_admins", {"admins": admins, 'personas': personas})

    @access("meta_admin")
    def change_privileges_form(self, rs: RequestState, persona_id: int
                               ) -> Response:
        """Render form."""
        if rs.ambience['persona']['is_archived']:
            rs.notify("error", n_("Persona is archived."))
            return self.redirect_show_user(rs, persona_id)

        stati = (const.PrivilegeChangeStati.pending,)
        privilege_change_ids = self.coreproxy.list_privilege_changes(
            rs, persona_id, stati)
        if privilege_change_ids:
            rs.notify("error", n_("Resolve pending privilege change first."))
            privilege_change_id = unwrap(privilege_change_ids.keys())
            return self.redirect(
                rs, "core/show_privilege_change",
                {"privilege_change_id": privilege_change_id})

        merge_dicts(rs.values, rs.ambience['persona'])
        return self.render(rs, "change_privileges")

    @access("meta_admin", modi={"POST"})
    @REQUESTdata(*ADMIN_KEYS, "notes")
    def change_privileges(self, rs: RequestState, persona_id: int,
                          is_meta_admin: bool, is_core_admin: bool,
                          is_cde_admin: bool, is_finance_admin: bool,
                          is_event_admin: bool, is_ml_admin: bool,
                          is_assembly_admin: bool, is_cdelokal_admin: bool,
                          is_auditor: bool, notes: str) -> Response:
        """Grant or revoke admin bits."""
        if rs.has_validation_errors():
            return self.change_privileges_form(rs, persona_id)

        stati = (const.PrivilegeChangeStati.pending,)
        case_ids = self.coreproxy.list_privilege_changes(rs, persona_id, stati)
        if case_ids:
            rs.notify("error", n_("Resolve pending privilege change first."))
            case_id = unwrap(case_ids.keys())
            return self.redirect(
                rs, "core/show_privilege_change", {"case_id": case_id})

        reason_map = {
            "is_cde_realm": rs.gettext("non-cde user"),
            "is_event_realm": rs.gettext("non-event user"),
            "is_ml_realm": rs.gettext("non-ml user"),
            "is_assembly_realm": rs.gettext("non-assembly user"),
            "is_cde_admin": rs.gettext("non-cde admin"),
        }
        persona = self.coreproxy.get_persona(rs, persona_id)
        data = {
            "persona_id": persona_id,
            "notes": notes,
        }
        for admin, required in ADMIN_KEYS.items():
            if locals()[admin] != persona[admin]:
                data[admin] = locals()[admin]
            if data.get(admin):
                err = (admin, ValueError(n_(
                    "Cannot grant this privilege to %(reason)s."),
                    {"reason": reason_map.get(required, n_("this user"))}))
                if data.get(required) is False:
                    rs.append_validation_error(err)
                if not rs.ambience["persona"][required] and not data.get(required):
                    rs.append_validation_error(err)

        if "is_meta_admin" in data and data["persona_id"] == rs.user.persona_id:
            rs.append_validation_error(("is_meta_admin", ValueError(n_(
                "Cannot modify own meta admin privileges."))))

        if rs.has_validation_errors():
            return self.change_privileges_form(rs, persona_id)

        if ADMIN_KEYS & data.keys():
            code = self.coreproxy.initialize_privilege_change(rs, data)
            rs.notify_return_code(code, success=n_("Privilege change waiting for"
                                                   " approval by another Meta-Admin."))
            if not code:
                return self.change_privileges_form(rs, persona_id)
        else:
            rs.notify("info", n_("No changes were made."))
        return self.redirect_show_user(rs, persona_id)

    @access("meta_admin")
    def list_privilege_changes(self, rs: RequestState) -> Response:
        """Show list of privilege changes pending review."""
        case_ids = self.coreproxy.list_privilege_changes(
            rs, stati=(const.PrivilegeChangeStati.pending,))

        cases = self.coreproxy.get_privilege_changes(rs, case_ids)
        cases = {e["persona_id"]: e for e in cases.values()}

        personas = self.coreproxy.get_personas(rs, cases.keys())

        cases = collections.OrderedDict(
            xsorted(cases.items(),
                    key=lambda item: EntitySorter.persona(personas[item[0]])))

        return self.render(rs, "list_privilege_changes",
                           {"cases": cases, "personas": personas})

    @access("meta_admin")
    def show_privilege_change(self, rs: RequestState, privilege_change_id: int
                              ) -> Response:
        """Show detailed infromation about pending privilege change."""
        privilege_change = rs.ambience['privilege_change']
        if privilege_change["status"] != const.PrivilegeChangeStati.pending:
            rs.notify("error", n_("Privilege change not pending."))
            return self.redirect(rs, "core/list_privilege_changes")

        if (privilege_change["is_meta_admin"] is not None
                and privilege_change["persona_id"] == rs.user.persona_id):
            rs.notify(
                "info", n_("This privilege change is affecting your Meta-Admin"
                           " privileges, so it has to be approved by another "
                           "Meta-Admin."))
        if privilege_change["submitted_by"] == rs.user.persona_id:
            rs.notify(
                "info", n_("This privilege change was submitted by you, so it "
                           "has to be approved by another Meta-Admin."))

        persona = self.coreproxy.get_persona(rs, privilege_change["persona_id"])
        submitter = self.coreproxy.get_persona(
            rs, privilege_change["submitted_by"])

        return self.render(rs, "show_privilege_change", {
            "persona": persona, "submitter": submitter, "admin_keys": ADMIN_KEYS,
        })

    @access("meta_admin", modi={"POST"})
    @REQUESTdata("ack")
    def decide_privilege_change(self, rs: RequestState,
                                privilege_change_id: int,
                                ack: bool) -> Response:
        """Approve or reject a privilege change."""
        if rs.has_validation_errors():
            return self.redirect(rs, 'core/show_privilege_change')
        privilege_change = rs.ambience['privilege_change']
        if privilege_change["status"] != const.PrivilegeChangeStati.pending:
            rs.notify("error", n_("Privilege change not pending."))
            return self.redirect(rs, "core/list_privilege_changes")
        if not ack:
            case_status = const.PrivilegeChangeStati.rejected
        else:
            case_status = const.PrivilegeChangeStati.approved
            if (privilege_change["is_meta_admin"] is not None
                    and privilege_change['persona_id'] == rs.user.persona_id):
                raise werkzeug.exceptions.Forbidden(
                    n_("Cannot modify own meta admin privileges."))
            if rs.user.persona_id == privilege_change["submitted_by"]:
                raise werkzeug.exceptions.Forbidden(
                    n_("Only a different admin than the submitter"
                       " may approve a privilege change."))
        code = self.coreproxy.finalize_privilege_change(
            rs, privilege_change_id, case_status)
        success = n_("Change committed.") if ack else n_("Change rejected.")
        info = n_("Password reset issued for new admin.")
        rs.notify_return_code(code, success=success, info=info)
        if not code:
            return self.show_privilege_change(rs, privilege_change_id)
        else:
            persona = self.coreproxy.get_persona(rs, privilege_change['persona_id'])
            email = persona['username']
            params = {}
            if code < 0:
                # The code is negative, the user's password needs to be changed.
                # We didn't actually issue the success message above.
                rs.notify("success", success)
                successful, cookie = self.coreproxy.make_reset_cookie(
                    rs, email, timeout=self.conf["EMAIL_PARAMETER_TIMEOUT"])
                if successful:
                    params["email"] = self.encode_parameter(
                        "core/do_password_reset_form", "email", email, persona_id=None,
                        timeout=self.conf["EMAIL_PARAMETER_TIMEOUT"])
                    params["cookie"] = cookie
            headers: Headers = {"To": {email}, "Subject": "Admin-Privilegien geändert"}
            self.do_mail(rs, "privilege_change_finalized", headers, params)
        return self.redirect(rs, "core/list_privilege_changes")

    @periodic("privilege_change_remind", period=24)
    def privilege_change_remind(self, rs: RequestState, store: CdEDBObject
                                ) -> CdEDBObject:
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
            notify = (self.conf["META_ADMIN_ADDRESS"],)
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
    @REQUESTdata("target_realm")
    def promote_user_form(self, rs: RequestState, persona_id: int,
                          target_realm: Optional[vtypes.Realm],
                          internal: bool = False) -> Response:
        """Render form.

        This has two parts. If the target realm is absent, we let the
        admin choose one. If it is present we present a mask to promote
        the user.

        The internal flag is used if the call comes from another frontend
        function to disable further redirection on validation errors.
        """
        if rs.has_validation_errors() and not internal:
            return self.redirect_show_user(rs, persona_id)
        if rs.ambience['persona']['is_archived']:
            rs.notify("error", n_("Persona is archived."))
            return self.redirect_show_user(rs, persona_id)
        merge_dicts(rs.values, rs.ambience['persona'])
        if target_realm and rs.ambience['persona']['is_{}_realm'.format(target_realm)]:
            rs.notify("warning", n_("No promotion necessary."))
            return self.redirect_show_user(rs, persona_id)
        past_events = self.pasteventproxy.list_past_events(rs)
        past_courses = {}
        if pevent_id := rs.values.get('pevent_id'):
            past_courses = self.pasteventproxy.list_past_courses(rs, pevent_id)
        return self.render(rs, "promote_user", {
            "past_events": past_events, "past_courses": past_courses,
        })

    @access("core_admin", modi={"POST"})
    @REQUESTdatadict(*CDE_TRANSITION_FIELDS)
    @REQUESTdata("target_realm", "change_note", "pevent_id", "is_orga", "is_instructor",
                 "pcourse_id")
    def promote_user(self, rs: RequestState, persona_id: int, change_note: str,
                     target_realm: vtypes.Realm, pevent_id: Optional[int],
                     is_orga: bool, is_instructor: bool,
                     pcourse_id: Optional[int], data: CdEDBObject) -> Response:
        """Add a new realm to the users ."""
        for key in tuple(k for k in data.keys() if not data[k]):
            # remove irrelevant keys, due to the possible combinations it is
            # rather lengthy to specify the exact set of them
            del data[key]
        persona = self.coreproxy.get_total_persona(rs, persona_id)
        merge_dicts(data, persona)
        # Specific fixes by target realm
        if target_realm == "cde":
            reference = {**CDE_TRANSITION_FIELDS}
            for key in ('trial_member', 'decided_search', 'bub_search'):
                if data[key] is None:
                    data[key] = False
            if data['paper_expuls'] is None:
                data['paper_expuls'] = True
            if data['donation'] is None:
                data['donation'] = decimal.Decimal("0.0")
        elif target_realm == "event":
            reference = {**EVENT_TRANSITION_FIELDS}
        else:
            reference = {}
        for key in tuple(data.keys()):
            if key not in reference and key != 'id':
                del data[key]
        # trial membership implies membership
        if data.get("trial_member"):
            data["is_member"] = True
        data['is_{}_realm'.format(target_realm)] = True
        for realm in implied_realms(target_realm):
            data['is_{}_realm'.format(realm)] = True
        data = check(rs, vtypes.Persona, data, transition=True)
        if rs.has_validation_errors():
            return self.promote_user_form(
                rs, persona_id, target_realm=target_realm, internal=True)
        if pevent_id is not None:
            # Show the form again, if past event was selected for the first time.
            if pcourse_id == -1:
                return self.promote_user_form(
                    rs, persona_id, target_realm=target_realm, internal=True)
        assert data is not None
        code = self.coreproxy.change_persona_realms(rs, data, change_note)
        rs.notify_return_code(code)
        if code > 0 and target_realm == "cde":
            if pevent_id is not None:
                self.pasteventproxy.add_participant(
                    rs, pevent_id, pcourse_id, persona_id,
                    is_instructor=is_instructor, is_orga=is_orga)
            persona = self.coreproxy.get_total_persona(rs, persona_id)
            meta_info = self.coreproxy.get_meta_info(rs)
            self.do_mail(rs, "welcome",
                         {'To': (persona['username'],),
                          'Subject': "Aufnahme in den CdE",
                          },
                         {'data': persona,
                          'fee': self.conf['MEMBERSHIP_FEE'],
                          'email': "",
                          'cookie': "",
                          'meta_info': meta_info,
                          })
        return self.redirect_show_user(rs, persona_id)

    @access("cde_admin")
    def modify_membership_form(self, rs: RequestState, persona_id: int
                               ) -> Response:
        """Render form."""
        if rs.ambience['persona']['is_archived']:
            rs.notify("error", n_("Persona is archived."))
            return self.redirect_show_user(rs, persona_id)
        persona = self.coreproxy.get_cde_user(rs, persona_id)
        return self.render(rs, "modify_membership", {
            "trial_member": persona["trial_member"]})

    @access("cde_admin", modi={"POST"})
    @REQUESTdata("is_member", "trial_member")
    def modify_membership(self, rs: RequestState, persona_id: int,
                          is_member: bool, trial_member: bool) -> Response:
        """Change association status.

        This is CdE-functionality so we require a cde_admin instead of a
        core_admin.
        """
        if trial_member and not is_member:
            rs.append_validation_error(("trial_member", ValueError(
                n_("Trial membership implies membership."))))
        if rs.has_validation_errors():
            return self.modify_membership_form(rs, persona_id)
        # We really don't want to go halfway here.
        with TransactionObserver(rs, self, "modify_membership"):
            code, revoked_permit, collateral_transaction = (
                self.cdeproxy.change_membership(
                    rs, persona_id, is_member=is_member, trial_member=trial_member))
            rs.notify_return_code(code)
            if revoked_permit:
                rs.notify("success", n_("Revoked active permit."))
            if collateral_transaction:
                transaction = self.cdeproxy.get_lastschrift_transaction(
                    rs, collateral_transaction)
                subject = ("Einzugsermächtigung zu ausstehender "
                           "Lastschrift widerrufen.")
                self.do_mail(rs, "pending_lastschrift_revoked",
                             {'To': (self.conf["MANAGEMENT_ADDRESS"],),
                              'Subject': subject},
                             {'persona_id': persona_id,
                              'payment_date': transaction['payment_date']})

        return self.redirect_show_user(rs, persona_id)

    @access("finance_admin")
    def modify_balance_form(self, rs: RequestState, persona_id: int
                            ) -> Response:
        """Serve form to manually modify a personas balance."""
        if rs.ambience['persona']['is_archived']:
            rs.notify("error", n_("Persona is archived."))
            return self.redirect_show_user(rs, persona_id)
        persona = self.coreproxy.get_cde_user(rs, persona_id)
        old_balance = persona['balance']
        trial_member = persona['trial_member']
        return self.render(
            rs, "modify_balance",
            {'old_balance': old_balance, 'trial_member': trial_member})

    @access("finance_admin", modi={"POST"})
    @REQUESTdata("new_balance", "change_note")
    def modify_balance(self, rs: RequestState, persona_id: int,
                       new_balance: vtypes.NonNegativeDecimal,
                       change_note: str) -> Response:
        """Set the new balance."""
        if rs.has_validation_errors():
            return self.modify_balance_form(rs, persona_id)
        persona = self.coreproxy.get_cde_user(rs, persona_id)
        if persona['balance'] == new_balance:
            rs.notify("info", n_("Nothing changed."))
            return self.redirect(rs, "core/modify_balance_form")
        if rs.ambience['persona']['is_archived']:
            rs.notify("error", n_("Persona is archived."))
            return self.redirect_show_user(rs, persona_id)
        code = self.coreproxy.change_persona_balance(
            rs, persona_id, new_balance,
            const.FinanceLogCodes.manual_balance_correction, change_note=change_note)
        rs.notify_return_code(code)
        return self.redirect_show_user(rs, persona_id)

    @access("cde")
    def get_foto(self, rs: RequestState, foto: str) -> Response:
        """Retrieve profile picture."""
        ret = self.coreproxy.get_foto(rs, foto)
        mimetype = magic.from_buffer(ret, mime=True)
        return self.send_file(rs, data=ret, mimetype=mimetype)

    @access("cde")
    def set_foto_form(self, rs: RequestState, persona_id: int) -> Response:
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
    @REQUESTdata("delete")
    def set_foto(self, rs: RequestState, persona_id: int,
                 foto: werkzeug.datastructures.FileStorage,
                 delete: bool) -> Response:
        """Set profile picture."""
        if rs.user.persona_id != persona_id and not self.is_admin(rs):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        foto = check_optional(rs, vtypes.ProfilePicture, foto, "foto")
        if not foto and not delete:
            rs.append_validation_error(
                ("foto", ValueError("Must not be empty.")))
        if rs.has_validation_errors():
            return self.set_foto_form(rs, persona_id)
        code = self.coreproxy.change_foto(rs, persona_id, foto=foto)
        rs.notify_return_code(code, success=n_("Foto updated."),
                                info=n_("Foto removed."))
        return self.redirect_show_user(rs, persona_id)

    @access("core_admin", modi={"POST"})
    @REQUESTdata("confirm_username")
    def invalidate_password(self, rs: RequestState, persona_id: int,
                            confirm_username: str) -> Response:
        """Delete a users current password to force them to set a new one."""
        if confirm_username != rs.ambience['persona']['username']:
            rs.append_validation_error(
                ('confirm_username',
                 ValueError(n_("Please provide the user's email address."))))
        if rs.has_validation_errors():
            return self.show_user(
                rs, persona_id, confirm_id=persona_id, internal=True,
                quote_me=False, event_id=None, ml_id=None)
        code = self.coreproxy.invalidate_password(rs, persona_id)
        rs.notify_return_code(code, success=n_("Password invalidated."))

        if not code:  # pragma: no cover
            return self.show_user(
                rs, persona_id, confirm_id=persona_id, internal=True,
                quote_me=False, event_id=None, ml_id=None)
        else:
            return self.redirect_show_user(rs, persona_id)

    @access("persona")
    def change_password_form(self, rs: RequestState) -> Response:
        """Render form."""
        return self.render(rs, "change_password")

    @access("persona", modi={"POST"})
    @REQUESTdata("old_password", "new_password", "new_password2")
    def change_password(self, rs: RequestState, old_password: str,
                        new_password: str, new_password2: str) -> Response:
        """Update your own password."""
        assert rs.user.persona_id is not None
        if rs.has_validation_errors():
            return self.change_password_form(rs)

        if new_password != new_password2:
            rs.extend_validation_errors(
                (("new_password", ValueError(n_("Passwords don’t match."))),
                 ("new_password2", ValueError(n_("Passwords don’t match.")))))
            rs.ignore_validation_errors()
            rs.notify("error", n_("Passwords don’t match."))
            return self.change_password_form(rs)

        new_password, errs = self.coreproxy.check_password_strength(
            rs, new_password, persona_id=rs.user.persona_id,
            argname="new_password")

        if errs:
            rs.extend_validation_errors(errs)
            if any(name == "new_password"
                   for name, _ in rs.retrieve_validation_errors()):
                rs.notify("error", n_("Password too weak."))
            rs.ignore_validation_errors()
            return self.change_password_form(rs)
        assert new_password is not None

        code, message = self.coreproxy.change_password(
            rs, old_password, new_password)
        rs.notify_return_code(code, success=n_("Password changed."),
                                error=message)
        if not code:
            rs.append_validation_error(
                ("old_password", ValueError(n_("Wrong password."))))
            rs.ignore_validation_errors()
            self.logger.info(
                f"Unsuccessful password change for persona {rs.user.persona_id}.")
            return self.change_password_form(rs)
        else:
            count = self.coreproxy.logout(rs, other_sessions=True, this_session=False)
            rs.notify(
                "success", n_("%(count)s session(s) terminated."), {'count': count})
            return self.redirect_show_user(rs, rs.user.persona_id)

    @access("anonymous")
    def reset_password_form(self, rs: RequestState) -> Response:
        """Render form.

        This starts the process of anonymously resetting a password.
        """
        return self.render(rs, "reset_password")

    @access("anonymous")
    @REQUESTdata("email")
    def send_password_reset_link(self, rs: RequestState, email: vtypes.Email
                                 ) -> Response:
        """Send a confirmation mail.

        To prevent an adversary from changing random passwords.
        """
        if rs.has_validation_errors():
            return self.reset_password_form(rs)
        exists = self.coreproxy.verify_existence(rs, email)
        if not exists:
            rs.append_validation_error(
                ("email", ValueError(n_("Nonexistent user."))))
            rs.ignore_validation_errors()
            return self.reset_password_form(rs)
        admin_exception = False
        try:
            success, message = self.coreproxy.make_reset_cookie(
                rs, email, self.conf["PARAMETER_TIMEOUT"])
        except PrivilegeError:
            admin_exception = True
        else:
            if not success:
                rs.notify("error", message)
            else:
                self.do_mail(
                    rs, "reset_password",
                    {'To': (email,), 'Subject': "Passwort zurücksetzen"},
                    {'email': self.encode_parameter(
                        "core/do_password_reset_form", "email", email,
                        persona_id=None,
                        timeout=self.conf["PARAMETER_TIMEOUT"]),
                        'cookie': message})
                # log message to be picked up by fail2ban
                self.logger.info(f"Sent password reset mail to {email}"
                                 f" for IP {rs.request.remote_addr}.")
                rs.notify("success", n_("Email sent."))
        if admin_exception:
            self.do_mail(
                rs, "admin_no_reset_password",
                {'To': (email,), 'Subject': "Passwort zurücksetzen"},
            )
            self.logger.info(f"Sent password reset denial mail to admin {email}"
                             f" for IP {rs.request.remote_addr}.")
            rs.notify("success", n_("Email sent."))
        return self.redirect(rs, "core/index")

    @access(*REALM_ADMINS, modi={"POST"})
    def admin_send_password_reset_link(self, rs: RequestState, persona_id: int,
                                       internal: bool = False) -> Response:
        """Generate a password reset email for an arbitrary persona.

        This is the only way to reset the password of an administrator (for
        security reasons).

        If the `internal` parameter is True, this was called internally to
        send a reset link. In that case we do not have the appropriate
        ambience dict, so we retrieve the username.
        """
        if rs.has_validation_errors():
            return self.redirect_show_user(rs, persona_id)
        if (not self.coreproxy.is_relative_admin(rs, persona_id)
                and "meta_admin" not in rs.user.roles):
            raise PrivilegeError(n_("Not a relative admin."))
        if internal:
            persona = self.coreproxy.get_persona(rs, persona_id)
            email = persona['username']
        else:
            email = rs.ambience['persona']['username']
        success, message = self.coreproxy.make_reset_cookie(
            rs, email, timeout=self.conf["EMAIL_PARAMETER_TIMEOUT"])
        if not success:
            rs.notify("error", message)
        else:
            self.do_mail(
                rs, "admin_reset_password",
                {'To': (email,), 'Subject': "Passwort zurücksetzen"},
                {'email': self.encode_parameter(
                    "core/do_password_reset_form", "email", email,
                    persona_id=None,
                    timeout=self.conf["EMAIL_PARAMETER_TIMEOUT"]),
                    'cookie': message})
            self.logger.info(f"Sent password reset mail to {email}"
                             f" for admin {rs.user.persona_id}.")
            rs.notify("success", n_("Email sent."))
        return self.redirect_show_user(rs, persona_id)

    @access("anonymous")
    @REQUESTdata("#email", "cookie")
    def do_password_reset_form(self, rs: RequestState, email: vtypes.Email,
                               cookie: str, internal: bool = False) -> Response:
        """Second form.

        Pretty similar to first form, but now we know, that the account
        owner actually wants the reset.

        The internal parameter signals that the call is from another
        frontend function and not an incoming request. This prevents
        validation from changing the target again.
        """
        if rs.has_validation_errors() and not internal:
            # Clean errors prior to displaying a new form for the first step
            rs.retrieve_validation_errors().clear()
            rs.notify("info", n_("Please try again."))
            return self.reset_password_form(rs)
        rs.values['email'] = self.encode_parameter(
            "core/do_password_reset", "email", email, persona_id=None)
        return self.render(rs, "do_password_reset")

    @access("anonymous", modi={"POST"})
    @REQUESTdata("#email", "new_password", "new_password2", "cookie")
    def do_password_reset(self, rs: RequestState, email: vtypes.Email,
                          new_password: str, new_password2: str, cookie: str
                          ) -> Response:
        """Now we can reset to a new password."""
        if rs.has_validation_errors():
            return self.reset_password_form(rs)
        if not self.coreproxy.verify_existence(rs, email, include_genesis=False):
            rs.notify("error", n_("Unknown email address."))
            return self.reset_password_form(rs)
        if new_password != new_password2:
            rs.extend_validation_errors(
                (("new_password", ValueError(n_("Passwords don’t match."))),
                 ("new_password2", ValueError(n_("Passwords don’t match."))),))
            rs.ignore_validation_errors()
            rs.notify("error", n_("Passwords don’t match."))
            return self.do_password_reset_form(rs, email=email, cookie=cookie,
                                               internal=True)
        new_password, errs = self.coreproxy.check_password_strength(
            rs, new_password, email=email, argname="new_password")

        if errs:
            rs.extend_validation_errors(errs)
            if any(name == "new_password"
                   for name, _ in rs.retrieve_validation_errors()):
                rs.notify("error", n_("Password too weak."))
            return self.do_password_reset_form(rs, email=email, cookie=cookie,
                                               internal=True)
        assert new_password is not None

        code, message = self.coreproxy.reset_password(rs, email, new_password,
                                                      cookie=cookie)
        rs.notify_return_code(code, success=n_("Password reset."),
                                error=message)
        if not code:
            return self.redirect(rs, "core/reset_password_form")
        else:
            return self.redirect(rs, "core/index")

    @access("persona")
    def change_username_form(self, rs: RequestState) -> Response:
        """Render form."""
        return self.render(rs, "change_username")

    @access("persona")
    @REQUESTdata("new_username")
    def send_username_change_link(self, rs: RequestState,
                                  new_username: vtypes.Email) -> Response:
        """First verify new name with test email."""
        if new_username == rs.user.username:
            rs.append_validation_error(
                ("new_username", ValueError(n_(
                    "Must be different from current email address."))))
        if (not rs.has_validation_errors()
                and self.coreproxy.verify_existence(rs, new_username)):
            rs.append_validation_error(
                ("new_username", ValueError(n_("Name collision."))))
        if rs.has_validation_errors():
            return self.change_username_form(rs)
        self.do_mail(rs, "change_username",
                     {'To': (new_username,),
                      'Subject': "Neue E-Mail-Adresse verifizieren"},
                     {'new_username': self.encode_parameter(
                         "core/do_username_change_form", "new_username",
                         new_username, rs.user.persona_id)})
        self.logger.info(f"Sent username change mail to {new_username}"
                         f" for {rs.user.username}.")
        rs.notify("success", "Email sent.")
        return self.redirect(rs, "core/index")

    @access("persona")
    @REQUESTdata("#new_username")
    def do_username_change_form(self, rs: RequestState, new_username: vtypes.Email
                                ) -> Response:
        """Email is now verified or we are admin."""
        if rs.has_validation_errors():
            return self.change_username_form(rs)
        rs.values['new_username'] = self.encode_parameter(
            "core/do_username_change", "new_username", new_username,
            rs.user.persona_id)
        return self.render(rs, "do_username_change", {
            'raw_email': new_username})

    @access("persona", modi={"POST"})
    @REQUESTdata("#new_username", "password")
    def do_username_change(self, rs: RequestState, new_username: vtypes.Email,
                           password: str) -> Response:
        """Now we can do the actual change."""
        if rs.has_validation_errors():
            return self.change_username_form(rs)
        assert rs.user.persona_id is not None
        code, message = self.coreproxy.change_username(
            rs, rs.user.persona_id, new_username, password)
        rs.notify_return_code(code, success=n_("Email address changed."),
                                error=message)
        if not code:
            return self.redirect(rs, "core/change_username_form")
        else:
            self.do_mail(rs, "username_change_info",
                         {'To': (rs.user.username,),
                          'Subject': "Deine E-Mail-Adresse wurde geändert"},
                         {'new_username': new_username})
            return self.redirect(rs, "core/index")

    @access(*REALM_ADMINS)
    def admin_username_change_form(self, rs: RequestState, persona_id: int
                                   ) -> Response:
        """Render form."""
        if not self.coreproxy.is_relative_admin(rs, persona_id):
            raise werkzeug.exceptions.Forbidden(n_("Not a relative admin."))
        if rs.ambience['persona']['is_archived']:
            rs.notify("error", n_("Persona is archived."))
            return self.redirect_show_user(rs, persona_id)
        data = self.coreproxy.get_persona(rs, persona_id)
        return self.render(rs, "admin_username_change", {'data': data})

    @access(*REALM_ADMINS, modi={"POST"})
    @REQUESTdata("new_username")
    def admin_username_change(self, rs: RequestState, persona_id: int,
                              new_username: vtypes.Email) -> Response:
        """Change username without verification."""
        if not self.coreproxy.is_relative_admin(rs, persona_id):
            raise werkzeug.exceptions.Forbidden(n_("Not a relative admin."))
        if rs.has_validation_errors():
            return self.admin_username_change_form(rs, persona_id)
        code, message = self.coreproxy.change_username(
            rs, persona_id, new_username, password=None)
        rs.notify_return_code(code, success=n_("Email address changed."),
                                error=message)
        if not code:
            return self.redirect(rs, "core/admin_username_change_form")
        else:
            return self.redirect_show_user(rs, persona_id)

    @access(*REALM_ADMINS, modi={"POST"})
    @REQUESTdata("activity")
    def toggle_activity(self, rs: RequestState, persona_id: int, activity: bool
                        ) -> Response:
        """Enable/disable an account."""
        if not self.coreproxy.is_relative_admin(rs, persona_id):
            raise werkzeug.exceptions.Forbidden(n_("Not a relative admin."))
        if rs.has_validation_errors():
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
        rs.notify_return_code(code)
        return self.redirect_show_user(rs, persona_id)

    @access("core_admin", "cde_admin", "event_admin")
    def list_pending_changes(self, rs: RequestState) -> Response:
        """List non-committed changelog entries."""
        pending = self.coreproxy.changelog_get_pending_changes(rs)
        return self.render(rs, "list_pending_changes", {'pending': pending})

    @periodic("pending_changelog_remind")
    def pending_changelog_remind(self, rs: RequestState, store: CdEDBObject
                                 ) -> CdEDBObject:
        """Cron job for pending changlog entries to decide.

        Send a reminder after twelve hours and then daily.
        """
        current = now()
        data = self.coreproxy.changelog_get_pending_changes(rs)
        ids = {f"{anid}/{e['generation']}" for anid, e in data.items()}
        old = set(store.get('ids', [])) & ids
        new = ids - set(old)
        remind = False
        if any(data[int(anid.split('/')[0])]['ctime']
               + datetime.timedelta(hours=12) < current
               for anid in new):
            remind = True
        if old and current.timestamp() > store.get('tstamp', 0) + 24*60*60:
            remind = True
        if remind:
            self.do_mail(
                rs, "changelog_requests_pending",
                {'To': (self.conf["MANAGEMENT_ADDRESS"],),
                 'Subject': "Offene CdEDB Accountänderungen"},
                {'count': len(data)})
            store = {
                'tstamp': current.timestamp(),
                'ids': list(ids),
            }
        return store

    @access("core_admin", "cde_admin", "event_admin")
    def inspect_change(self, rs: RequestState, persona_id: int) -> Response:
        """Look at a pending change."""
        if not self.coreproxy.is_relative_admin(rs, persona_id):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        history = self.coreproxy.changelog_get_history(rs, persona_id,
                                                       generations=None)
        pending = history[max(history)]
        if pending['code'] != const.PersonaChangeStati.pending:
            rs.notify("warning", n_("Persona has no pending change."))
            return self.list_pending_changes(rs)
        current = history[max(
            key for key in history
            if (history[key]['code']
                == const.PersonaChangeStati.committed))]
        diff = {key for key in pending if current[key] != pending[key]}
        return self.render(rs, "inspect_change", {
            'pending': pending, 'current': current, 'diff': diff})

    @access("core_admin", "cde_admin", "event_admin", modi={"POST"})
    @REQUESTdata("generation", "ack")
    def resolve_change(self, rs: RequestState, persona_id: int,
                       generation: int, ack: bool) -> Response:
        """Make decision."""
        if not self.coreproxy.is_relative_admin(rs, persona_id):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        if rs.has_validation_errors():
            return self.list_pending_changes(rs)
        code = self.coreproxy.changelog_resolve_change(rs, persona_id,
                                                       generation, ack)
        message = n_("Change committed.") if ack else n_("Change dropped.")
        rs.notify_return_code(code, success=message)
        return self.redirect(rs, "core/list_pending_changes")

    @access(*REALM_ADMINS, modi={"POST"})
    @REQUESTdata("ack_delete", "note")
    def archive_persona(self, rs: RequestState, persona_id: int,
                        ack_delete: bool, note: str) -> Response:
        """Move a persona to the attic."""
        if not self.coreproxy.is_relative_admin(rs, persona_id):
            raise werkzeug.exceptions.Forbidden(n_("Not a relative admin."))
        if not ack_delete:
            rs.append_validation_error(
                ("ack_delete", ValueError(n_("Must be checked."))))
        if rs.has_validation_errors():
            return self.show_user(
                rs, persona_id, confirm_id=persona_id, internal=True,
                quote_me=False, event_id=None, ml_id=None)

        try:
            code = self.coreproxy.archive_persona(rs, persona_id, note)
        except ArchiveError as e:
            msg = e.args[0]
            args = e.args[1] if len(e.args) > 1 else {}
            rs.notify("error", msg, args)
            code = 0
        rs.notify_return_code(code)
        return self.redirect_show_user(rs, persona_id)

    @access(*REALM_ADMINS)
    def dearchive_persona_form(self, rs: RequestState, persona_id: int) -> Response:
        """Render form."""
        if not self.coreproxy.is_relative_admin(rs, persona_id):
            raise werkzeug.exceptions.Forbidden(n_("Not a relative admin."))
        data = self.coreproxy.get_persona(rs, persona_id)
        return self.render(rs, "dearchive_user", {'data': data})

    @access(*REALM_ADMINS, modi={"POST"})
    @REQUESTdata("new_username")
    def dearchive_persona(self, rs: RequestState, persona_id: int,
                          new_username: vtypes.Email) -> Response:
        """Reinstate a persona from the attic."""
        if not self.coreproxy.is_relative_admin(rs, persona_id):
            raise werkzeug.exceptions.Forbidden(n_("Not a relative admin."))
        if new_username and self.coreproxy.verify_existence(rs, new_username):
            rs.append_validation_error(
                ("new_username",
                 ValueError(n_("User with this E-Mail exists already."))))
        if rs.has_validation_errors():
            return self.dearchive_persona_form(rs, persona_id)

        code = self.coreproxy.dearchive_persona(rs, persona_id, new_username)
        rs.notify_return_code(code)
        return self.redirect_show_user(rs, persona_id)

    @access("core_admin", modi={"POST"})
    @REQUESTdata("ack_delete")
    def purge_persona(self, rs: RequestState, persona_id: int, ack_delete: bool
                      ) -> Response:
        """Delete all identifying information for a persona."""
        if not ack_delete:
            rs.append_validation_error(
                ("ack_delete", ValueError(n_("Must be checked."))))
        if rs.has_validation_errors():
            return self.redirect_show_user(rs, persona_id)

        code = self.coreproxy.purge_persona(rs, persona_id)
        rs.notify_return_code(code)
        return self.redirect_show_user(rs, persona_id)

    @REQUESTdatadict(*ChangelogLogFilter.requestdict_fields())
    @REQUESTdata("download")
    @access("core_admin", "auditor")
    def view_changelog_meta(self, rs: RequestState, data: CdEDBObject, download: bool
                            ) -> Response:
        """View changelog activity."""
        return self.generic_view_log(
            rs, data, ChangelogLogFilter, self.coreproxy.retrieve_changelog_meta,
            download=download, template="view_changelog_meta",
        )

    @REQUESTdatadict(*CoreLogFilter.requestdict_fields())
    @REQUESTdata("download")
    @access("core_admin", "auditor")
    def view_log(self, rs: RequestState, data: CdEDBObject, download: bool) -> Response:
        """View activity."""
        return self.generic_view_log(
            rs, data, CoreLogFilter, self.coreproxy.retrieve_log,
            download=download, template="view_log",
        )

    @access("anonymous")
    def debug_email(self, rs: RequestState, token: str) -> Response:
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
        if not self.conf["CDEDB_DEV"]:  # pragma: no cover
            return self.redirect(rs, "core/index")
        filename = pathlib.Path(tempfile.gettempdir(),
                                "cdedb-mail-{}.txt".format(token))
        with open(filename, 'rb') as f:
            rawtext = f.read()
        emailtext = quopri.decodestring(rawtext).decode('utf-8')
        return self.render(rs, "debug_email", {'emailtext': emailtext})

    def get_cron_store(self, rs: RequestState, name: str) -> CdEDBObject:
        return self.coreproxy.get_cron_store(rs, name)

    def set_cron_store(self, rs: RequestState, name: str, data: CdEDBObject
                       ) -> DefaultReturnCode:
        return self.coreproxy.set_cron_store(rs, name, data)

    @access("droid_resolve")
    @REQUESTdata("username")
    def api_resolve_username(self, rs: RequestState, username: vtypes.Email
                             ) -> Response:
        """API to resolve username to that users given names and family name."""
        if rs.has_validation_errors():
            err = {'error': tuple(map(str, rs.retrieve_validation_errors()))}
            return self.send_json(rs, err)

        constraints = (
            ('username', QueryOperators.equal, username),
            ('is_event_realm', QueryOperators.equal, True),
        )
        query = Query(QueryScope.core_user, QueryScope.core_user.get_spec(),
                      ("given_names", "family_name", "is_member", "username"),
                      constraints, (('personas.id', True),))
        result = self.coreproxy.submit_resolve_api_query(rs, query)
        return self.send_json(rs, unwrap(result) if result else {})
