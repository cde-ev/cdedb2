#!/usr/bin/env python3

"""Services for the core realm."""

import collections
import copy
import datetime
import decimal
import itertools
import operator
import pathlib
import quopri
import tempfile
from typing import Any, Collection, Dict, List, Optional, Set, Tuple, Union, cast

import magic
import qrcode
import qrcode.image.svg
import vobject
import werkzeug.exceptions
from werkzeug import Response

import cdedb.database.constants as const
import cdedb.validationtypes as vtypes
from cdedb.common import (
    ADMIN_KEYS, ADMIN_VIEWS_COOKIE_NAME, ALL_ADMIN_VIEWS, REALM_INHERITANCE,
    REALM_SPECIFIC_GENESIS_FIELDS, ArchiveError, CdEDBObject, DefaultReturnCode,
    EntitySorter, PathLike, PrivilegeError, Realm, RequestState, extract_roles,
    get_persona_fields_by_realm, implied_realms, merge_dicts, n_, now, pairwise, unwrap,
    xsorted,
)

from cdedb.config import SecretsConfig
from cdedb.database.connection import Atomizer
from cdedb.frontend.common import (
    AbstractFrontend, REQUESTdata, REQUESTdatadict, REQUESTfile, access, basic_redirect,
    calculate_db_logparams, calculate_loglinks, check_validation as check,
    check_validation_optional as check_optional, date_filter, enum_entries_filter,
    make_membership_fee_reference, periodic, querytoparams_filter,
    request_dict_extractor, request_extractor,
)
from cdedb.query import QUERY_SPECS, Query, QueryOperators, mangle_query_input
from cdedb.validation import (
    TypeMapping, _PERSONA_CDE_CREATION as CDE_TRANSITION_FIELDS,
    _PERSONA_EVENT_CREATION as EVENT_TRANSITION_FIELDS, validate_check,
)
from cdedb.validationtypes import CdedbID

# Name of each realm
USER_REALM_NAMES = {
    "cde": n_("CdE user / Member"),
    "event": n_("Event user"),
    "assembly": n_("Assembly user"),
    "ml": n_("Mailinglist user"),
}

# Name of each realm's option in the genesis form
GenesisRealmOptionName = collections.namedtuple(
    'GenesisRealmOptionName', ['realm', 'name'])
GENESIS_REALM_OPTION_NAMES = (
    GenesisRealmOptionName("event", n_("CdE event")),
    GenesisRealmOptionName("cde", n_("CdE membership")),
    GenesisRealmOptionName("assembly", n_("CdE members' assembly")),
    GenesisRealmOptionName("ml", n_("CdE mailinglist")))


class CoreFrontend(AbstractFrontend):
    """Note that there is no user role since the basic distinction is between
    anonymous access and personas. """
    realm = "core"

    @classmethod
    def is_admin(cls, rs: RequestState) -> bool:
        return super().is_admin(rs)

    @access("anonymous")
    @REQUESTdata("#wants")
    def index(self, rs: RequestState, wants: str = None) -> Response:
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
            if "core_user" in rs.user.admin_views:
                data = self.coreproxy.changelog_get_changes(
                    rs, stati=(const.MemberChangeStati.pending,))
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
                mailman = self.get_mailman()
                for mailinglist_id, mailinglist in moderator.items():
                    requests = self.mlproxy.get_subscription_states(
                        rs, mailinglist_id, states=(sub_request,))
                    held_mails = mailman.get_held_messages(mailinglist)
                    mailinglist['requests'] = len(requests)
                    mailinglist['held_mails'] = len(held_mails or [])
                dashboard['moderator'] = {k: v for k, v in moderator.items()
                                          if v['is_active']}
            # visible and open events
            if "event" in rs.user.roles:
                event_ids = self.eventproxy.list_events(
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
        return self.render(rs, "meta_info")

    @access("core_admin", modi={"POST"})
    def change_meta_info(self, rs: RequestState) -> Response:
        """Change the meta info constants."""
        info = self.coreproxy.get_meta_info(rs)
        data_params: TypeMapping = {
            key: Optional[str]  # type: ignore
            for key in info
        }
        data = request_extractor(rs, data_params)
        data = check(rs, vtypes.MetaInfo, data, keys=info.keys())
        if rs.has_validation_errors():
            return self.meta_info_form(rs)
        assert data is not None
        code = self.coreproxy.set_meta_info(rs, data)
        self.notify_return_code(rs, code)
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
        if rs.has_validation_errors():
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

    @access("member")
    @REQUESTdata("#confirm_id")
    def download_vcard(self, rs: RequestState, persona_id: int, confirm_id: int
                       ) -> Response:
        if persona_id != confirm_id or rs.has_validation_errors():
            return self.index(rs)

        vcard = self._create_vcard(rs, persona_id)
        return self.send_file(rs, data=vcard, mimetype='text/vcard',
                              filename='vcard.vcf')

    @access("member")
    @REQUESTdata("#confirm_id")
    def qr_vcard(self, rs: RequestState, persona_id: int, confirm_id: int) -> Response:
        if persona_id != confirm_id or rs.has_validation_errors():
            return self.index(rs)

        vcard = self._create_vcard(rs, persona_id)

        qr = qrcode.QRCode()
        qr.add_data(vcard)
        qr.make(fit=True)
        qr_image = qr.make_image(qrcode.image.svg.SvgPathFillImage)

        with tempfile.TemporaryDirectory() as tmp_dir:
            temppath = pathlib.Path(tmp_dir, f"vcard-{persona_id}")
            qr_image.save(str(temppath))
            with open(temppath) as f:
                data = f.read()

        return self.send_file(rs, data=data, mimetype="image/svg+xml")

    def _create_vcard(self, rs: RequestState, persona_id: int) -> str:
        """
        Generate a vCard string for a user to be delivered to a client.

        The vcard is a vcard3, following https://tools.ietf.org/html/rfc2426
        Where reasonable, we should consider the new RFC of vcard4, to increase
        compatibility, see https://tools.ietf.org/html/rfc6350

        :return: The serialized vCard (as in a vcf file)
        """
        if 'member' not in rs.user.roles:
            raise werkzeug.exceptions.Forbidden(n_("Not a member."))

        if not self.coreproxy.verify_persona(rs, persona_id, required_roles=['member']):
            raise werkzeug.exceptions.Forbidden(n_("Viewed persona is no member."))

        persona = self.coreproxy.get_cde_user(rs, persona_id)

        vcard = vobject.vCard()

        # Name
        vcard.add('N')
        vcard.n.value = vobject.vcard.Name(
            family=persona['family_name'] or '',
            given=persona['given_names'] or '',
            prefix=persona['title'] or '',
            suffix=persona['name_supplement'] or '')
        vcard.add('FN')
        vcard.fn.value = f"{persona['given_names'] or ''} {persona['family_name'] or ''}"
        vcard.add('NICKNAME')
        vcard.nickname.value = persona['display_name'] or ''

        # Address data
        if persona['address']:
            vcard.add('adr')
            # extended should be empty because of compatibility issues, see
            # https://tools.ietf.org/html/rfc6350#section-6.3.1
            vcard.adr.value = vobject.vcard.Address(
                extended='',
                street=persona['address'] or '',
                city=persona['location'] or '',
                code=persona['postal_code'] or '',
                country=persona['country'] or '')

        # Contact data
        if persona['username']:
            # see https://tools.ietf.org/html/rfc2426#section-3.3.2
            vcard.add('email')
            vcard.email.value = persona['username']
        if persona['telephone']:
            # see https://tools.ietf.org/html/rfc2426#section-3.3.1
            vcard.add(vobject.vcard.ContentLine('TEL', [('TYPE', 'home,voice')],
                                                persona['telephone']))
        if persona['mobile']:
            # see https://tools.ietf.org/html/rfc2426#section-3.3.1
            vcard.add(vobject.vcard.ContentLine('TEL', [('TYPE', 'cell,voice')],
                                                persona['mobile']))

        # Birthday
        if persona['birthday']:
            vcard.add('bday')
            # see https://tools.ietf.org/html/rfc2426#section-3.1.5
            vcard.bday.value = date_filter(persona['birthday'], formatstr="%Y-%m-%d")

        return vcard.serialize()

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
        if (rs.ambience['persona']['is_archived']
                and "core_admin" not in rs.user.roles):
            raise werkzeug.exceptions.Forbidden(
                n_("Only admins may view archived datasets."))

        is_relative_admin = self.coreproxy.is_relative_admin(rs, persona_id)
        is_relative_or_meta_admin = self.coreproxy.is_relative_admin(
            rs, persona_id, allow_meta_admin=True)

        is_relative_admin_view = self.coreproxy.is_relative_admin_view(
            rs, persona_id)
        is_relative_or_meta_admin_view = self.coreproxy.is_relative_admin_view(
            rs, persona_id, allow_meta_admin=True)

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
        # Other admins see their realm if they are relative admin
        if is_relative_admin:
            access_mode.add("relative_admin")
            for realm in ("ml", "assembly", "event", "cde"):
                if (f"{realm}_admin" in rs.user.roles
                        and f"{realm}_user" in rs.user.admin_views):
                    # Relative admins can see core data
                    access_levels.add("core")
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
        # This excludes users with relation "unsubscribed", because they are not
        # directly shown on the management sites.
        if ml_id:
            # determinate if the user is relevant admin of this mailinglist
            ml_type = self.mlproxy.get_ml_type(rs, ml_id)
            is_admin = ml_type.is_relevant_admin(rs.user)
            is_moderator = ml_id in self.mlproxy.moderator_info(
                rs, rs.user.persona_id)
            # Admins who are also moderators can not disable this admin view
            if is_admin and not is_moderator:
                access_mode.add("moderator")
            relevant_stati = [s for s in const.SubscriptionStates
                              if s != const.SubscriptionStates.unsubscribed]
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
            if "core" in access_levels and "member" in roles:
                user_lastschrift = self.cdeproxy.list_lastschrift(
                    rs, persona_ids=(persona_id,), active=True)
                data['has_lastschrift'] = len(user_lastschrift) > 0
        if is_relative_or_meta_admin and is_relative_or_meta_admin_view:
            # This is a bit involved to not contaminate the data dict
            # with keys which are not applicable to the requested persona
            total = self.coreproxy.get_total_persona(rs, persona_id)
            data['notes'] = total['notes']
            data['username'] = total['username']

        # Determinate if vcard should be visible
        data['show_vcard'] = "cde" in access_levels and "cde" in roles

        # Cull unwanted data
        if (not ('is_cde_realm' in data and data['is_cde_realm'])
                 and 'foto' in data):
            del data['foto']
        # relative admins, core admins and the user himself got "core"
        if "core" not in access_levels:
            masks = ["balance", "decided_search", "trial_member", "bub_search",
                     "is_searchable", "paper_expuls"]
            if "meta" not in access_levels:
                masks.extend([
                    "is_active", "is_meta_admin", "is_core_admin",
                    "is_cde_admin", "is_event_admin", "is_ml_admin",
                    "is_assembly_admin", "is_cde_realm", "is_event_realm",
                    "is_ml_realm", "is_assembly_realm", "is_archived",
                    "notes"])
            if "orga" not in access_levels:
                masks.extend(["is_member", "gender"])
            for key in masks:
                if key in data:
                    del data[key]

        # Add past event participation info
        past_events = None
        if "cde" in access_levels and {"event", "cde"} & roles:
            past_events = self.pasteventproxy.participation_info(rs, persona_id)

        # Check whether we should display an option for using the quota
        quoteable = (not quote_me
                     and "cde" not in access_levels
                     and "searchable" in rs.user.roles
                     and rs.ambience['persona']['is_searchable'])

        meta_info = self.coreproxy.get_meta_info(rs)
        reference = make_membership_fee_reference(data)

        return self.render(rs, "show_user", {
            'data': data, 'past_events': past_events, 'meta_info': meta_info,
            'is_relative_admin': is_relative_admin_view, 'reference': reference,
            'quoteable': quoteable, 'access_mode': access_mode,
        })

    @access("core_admin", "cde_admin", "event_admin", "ml_admin",
            "assembly_admin")
    def show_history(self, rs: RequestState, persona_id: int) -> Response:
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
            'personas': personas})

    @access("core_admin")
    @REQUESTdata("phrase")
    def admin_show_user(self, rs: RequestState, phrase: str) -> Response:
        """Allow admins to view any user data set.

        The search phrase may be anything: a numeric id (wellformed with
        check digit or without) or a string matching the data set.
        """
        if rs.has_validation_errors():
            return self.index(rs)
        anid, errs = validate_check(vtypes.CdedbID, phrase, argname="phrase")
        if not errs:
            assert anid is not None
            if self.coreproxy.verify_id(rs, anid, is_archived=None):
                return self.redirect_show_user(rs, anid)
        anid, errs = validate_check(vtypes.ID, phrase, argname="phrase")
        if not errs:
            assert anid is not None
            if self.coreproxy.verify_id(rs, anid, is_archived=None):
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

        - ``admin_persona``: Search for users as core_admin
        - ``cde_user``: Search for a cde user as cde_admin.
        - ``past_event_user``: Search for an event user to add to a past
          event as cde_admin
        - ``pure_assembly_user``: Search for an assembly only user as
          assembly_admin or presider. Needed for external_signup.
        - ``assembly_user``: Search for an assembly user as assembly_admin or presider
        - ``ml_user``: Search for a mailinglist user as ml_admin or moderator
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

        spec_additions: Dict[str, str] = {}
        search_additions = []
        mailinglist = None
        num_preview_personas = (self.conf["NUM_PREVIEW_PERSONAS_CORE_ADMIN"]
                                if {"core_admin"} & rs.user.roles
                                else self.conf["NUM_PREVIEW_PERSONAS"])
        if kind == "admin_persona":
            if not {"core_admin", "cde_admin"} & rs.user.roles:
                raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        elif kind == "cde_user":
            if "cde_admin" not in rs.user.roles:
                raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
            search_additions.append(
                ("is_cde_realm", QueryOperators.equal, True))
        elif kind == "past_event_user":
            if "cde_admin" not in rs.user.roles:
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
            if not rs.user.presider and "assembly_admin" not in rs.user.roles:
                raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
            search_additions.append(
                ("is_assembly_realm", QueryOperators.equal, True))
        elif kind == "event_user":
            # No check by event, as this behaves identical for each event.
            if not rs.user.orga and "event_admin" not in rs.user.roles:
                raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
            search_additions.append(
                ("is_event_realm", QueryOperators.equal, True))
        elif kind == "ml_user":
            relevant_admin_roles = {"core_admin", "cde_admin", "event_admin",
                                    "assembly_admin", "cdelokal_admin", "ml_admin"}
            # No check by mailinglist, as this behaves identical for each list.
            if not rs.user.moderator and not relevant_admin_roles & rs.user.roles:
                raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
            search_additions.append(
                ("is_ml_realm", QueryOperators.equal, True))
        elif kind == "ml_subscriber":
            if aux is None:
                raise werkzeug.exceptions.BadRequest(n_(
                    "Must provide id of the associated mailinglist to use this kind."))
            # In this case, the return value depends on the respective mailinglist.
            mailinglist = self.mlproxy.get_mailinglist(rs, aux)
            if not self.mlproxy.may_manage(rs, aux, privileged=True):
                raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
            search_additions.append(
                ("is_ml_realm", QueryOperators.equal, True))
        else:
            return self.send_json(rs, {})

        data: Optional[Tuple[CdEDBObject, ...]] = None

        # Core admins are allowed to search by raw ID or CDEDB-ID
        if "core_admin" in rs.user.roles:
            anid: Optional[vtypes.ID]
            anid, errs = validate_check(
                vtypes.CdedbID, phrase, argname="phrase")
            if not errs:
                assert anid is not None
                tmp = self.coreproxy.get_personas(rs, (anid,))
                if tmp:
                    data = (unwrap(tmp),)
            else:
                anid, errs = validate_check(
                    vtypes.ID, phrase, argname="phrase")
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
                _, errs = validate_check(vtypes.NonRegex, t, argname="phrase")
                if errs:
                    valid = False
            if not valid:
                data = tuple()
            else:
                search: List[Tuple[str, QueryOperators, Any]]
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

        # Filter result to get only users allowed to be a subscriber of a list,
        # which potentially are no subscriber yet.
        if mailinglist:
            pol = const.MailinglistInteractionPolicy
            allowed_pols = {pol.opt_out, pol.opt_in, pol.moderated_opt_in,
                            pol.invitation_only}
            data = self.mlproxy.filter_personas_by_policy(
                rs, mailinglist, data, allowed_pols)

        # Strip data to contain at maximum `num_preview_personas` results
        if len(data) > num_preview_personas:
            data = tuple(xsorted(
                data, key=lambda e: e['id'])[:num_preview_personas])

        def name(x: CdEDBObject) -> str:
            return f"{x['given_names']} {x['family_name']}"

        # Check if name occurs multiple times to add email address in this case
        counter: Dict[str, int] = collections.defaultdict(lambda: 0)
        for entry in data:
            counter[name(entry)] += 1

        # Generate return JSON list
        ret = []
        for entry in xsorted(data, key=EntitySorter.persona):
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
                '@' in t and len(t) > self.conf["NUM_PREVIEW_CHARS"]
                and entry['username'] and t in entry['username']
                for t in terms)
            if counter[name(entry)] > 1 or searched_email or \
                    self.coreproxy.is_relative_admin(rs, entry['id']):
                result['email'] = entry['username']
            ret.append(result)
        return self.send_json(rs, {'personas': ret})

    @access("persona")
    def change_user_form(self, rs: RequestState) -> Response:
        """Render form."""
        assert rs.user.persona_id is not None
        generation = self.coreproxy.changelog_get_generation(
            rs, rs.user.persona_id)
        data = unwrap(self.coreproxy.changelog_get_history(
            rs, rs.user.persona_id, (generation,)))
        if data['code'] == const.MemberChangeStati.pending:
            rs.notify("info", n_("Change pending."))
        del data['change_note']
        merge_dicts(rs.values, data)
        shown_fields = get_persona_fields_by_realm(rs.user.roles,
                                                   restricted=True)
        return self.render(rs, "change_user", {
            'username': data['username'],
            'shown_fields': shown_fields,
        })

    @access("persona", modi={"POST"})
    @REQUESTdata("generation", "ignore_warnings")
    def change_user(self, rs: RequestState, generation: int,
                    ignore_warnings: bool = False) -> Response:
        """Change own data set."""
        assert rs.user.persona_id is not None
        attributes = get_persona_fields_by_realm(rs.user.roles, restricted=True)
        data = request_dict_extractor(rs, attributes)
        data['id'] = rs.user.persona_id
        data = check(rs, vtypes.Persona, data, "persona",
                     _ignore_warnings=ignore_warnings)
        if rs.has_validation_errors():
            return self.change_user_form(rs)
        assert data is not None
        change_note = "Normale Änderung."
        code = self.coreproxy.change_persona(
            rs, data, generation=generation, change_note=change_note,
            ignore_warnings=ignore_warnings)
        self.notify_return_code(rs, code)
        return self.redirect_show_user(rs, rs.user.persona_id)

    @access("core_admin")
    @REQUESTdata("download", "is_search")
    def user_search(self, rs: RequestState, download: Optional[str],
                    is_search: bool, query: Query = None) -> Response:
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
            query = check(rs, vtypes.Query, query, "query")
        elif is_search:
            # mangle the input, so we can prefill the form
            query_input = mangle_query_input(rs, spec)
            query = check(rs, vtypes.QueryInput,
                query_input, "query", spec=spec, allow_empty=False)
        events = self.pasteventproxy.list_past_events(rs)
        choices = {
            'pevent_id': collections.OrderedDict(
                xsorted(events.items(), key=operator.itemgetter(0)))}
        choices_lists = {k: list(v.items()) for k, v in choices.items()}
        default_queries = self.conf["DEFAULT_QUERIES"]['qview_core_user']
        params = {
            'spec': spec, 'choices': choices, 'choices_lists': choices_lists,
            'default_queries': default_queries, 'query': query}
        # Tricky logic: In case of no validation errors we perform a query
        if not rs.has_validation_errors() and is_search and query:
            query.scope = "qview_core_user"
            result = self.coreproxy.submit_general_query(rs, query)
            params['result'] = result
            if download:
                return self.send_query_download(
                    rs, result, fields=query.fields_of_interest, kind=download,
                    filename="user_search_result", substitutions=choices)
        else:
            rs.values['is_search'] = is_search = False
        return self.render(rs, "user_search", params)

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

    @access("core_admin")
    @REQUESTdata("download", "is_search")
    def archived_user_search(self, rs: RequestState, download: Optional[str],
                             is_search: bool) -> Response:
        """Perform search.

        Archived users are somewhat special since they are not visible
        otherwise.
        """
        spec = copy.deepcopy(QUERY_SPECS['qview_archived_persona'])
        # mangle the input, so we can prefill the form
        query_input = mangle_query_input(rs, spec)
        query: Optional[Query] = None
        if is_search:
            query = check(rs, vtypes.QueryInput,
                query_input, "query", spec=spec, allow_empty=False)
        events = self.pasteventproxy.list_past_events(rs)
        choices = {
            'pevent_id': collections.OrderedDict(
                xsorted(events.items(), key=operator.itemgetter(0))),
            'gender': collections.OrderedDict(
                enum_entries_filter(const.Genders, rs.gettext))
        }
        choices_lists = {k: list(v.items()) for k, v in choices.items()}
        default_queries = self.conf["DEFAULT_QUERIES"]['qview_archived_persona']
        params = {
            'spec': spec, 'choices': choices, 'choices_lists': choices_lists,
            'default_queries': default_queries, 'query': query}
        # Tricky logic: In case of no validation errors we perform a query
        if not rs.has_validation_errors() and is_search and query:
            query.scope = "qview_archived_persona"
            result = self.coreproxy.submit_general_query(rs, query)
            params['result'] = result
            if download:
                return self.send_query_download(
                    rs, result, fields=query.fields_of_interest, kind=download,
                    filename="archived_user_search_result",
                    substitutions=choices)
        else:
            rs.values['is_search'] = is_search = False
        return self.render(rs, "archived_user_search", params)

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

    @access("core_admin", "cde_admin", "event_admin", "ml_admin",
            "assembly_admin")
    def admin_change_user_form(self, rs: RequestState, persona_id: int
                               ) -> Response:
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
        if data['code'] == const.MemberChangeStati.pending:
            rs.notify("info", n_("Change pending."))
        shown_fields = get_persona_fields_by_realm(
            extract_roles(rs.ambience['persona']), restricted=False)
        return self.render(rs, "admin_change_user", {
            'admin_bits': self.admin_bits(rs),
            'shown_fields': shown_fields,
        })

    @access("core_admin", "cde_admin", "event_admin", "ml_admin",
            "assembly_admin", modi={"POST"})
    @REQUESTdata("generation", "change_note", "ignore_warnings")
    def admin_change_user(self, rs: RequestState, persona_id: int,
                          generation: int, change_note: Optional[str],
                          ignore_warnings: Optional[bool] = False) -> Response:
        """Privileged edit of data set."""
        if not self.coreproxy.is_relative_admin(rs, persona_id):
            raise werkzeug.exceptions.Forbidden(n_("Not a relative admin."))
        # Assure we don't accidently change the original.
        roles = extract_roles(rs.ambience['persona'])
        attributes = get_persona_fields_by_realm(roles, restricted=False)
        data = request_dict_extractor(rs, attributes)
        data['id'] = persona_id
        data = check(rs, vtypes.Persona, data, _ignore_warnings=ignore_warnings)
        if rs.has_validation_errors():
            return self.admin_change_user_form(rs, persona_id)
        assert data is not None
        code = self.coreproxy.change_persona(
            rs, data, generation=generation, change_note=change_note,
            ignore_warnings=bool(ignore_warnings))
        self.notify_return_code(rs, code)
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
    @REQUESTdata("is_meta_admin", "is_core_admin", "is_cde_admin",
                 "is_finance_admin", "is_event_admin", "is_ml_admin",
                 "is_assembly_admin", "is_cdelokal_admin", "notes")
    def change_privileges(self, rs: RequestState, persona_id: int,
                          is_meta_admin: bool, is_core_admin: bool,
                          is_cde_admin: bool, is_finance_admin: bool,
                          is_event_admin: bool, is_ml_admin: bool,
                          is_assembly_admin: bool, is_cdelokal_admin: bool,
                          notes: str) -> Response:
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

        persona = self.coreproxy.get_persona(rs, persona_id)

        data = {
            "persona_id": persona_id,
            "notes": notes,
        }

        for key in ADMIN_KEYS:
            if locals()[key] != persona[key]:
                data[key] = locals()[key]

        # see also cdedb.frontend.templates.core.change_privileges
        # and initialize_privilege_change in cdedb.backend.core

        errors = []

        if (any(k in data for k in
                ["is_meta_admin", "is_core_admin", "is_cde_admin",
                 "is_cdelokal_admin"])
                and not rs.ambience['persona']['is_cde_realm']):
            errors.append(n_(
                "Cannot grant meta, core, CdE or CdElokal admin privileges"
                " to non CdE users."))

        if data.get('is_finance_admin'):
            if (data.get('is_cde_admin') is False
                    or (not rs.ambience['persona']['is_cde_admin']
                        and not data.get('is_cde_admin'))):
                errors.append(n_(
                    "Cannot grant finance admin privileges to non CdE admins."))

        if (any(k in data for k in ["is_ml_admin", "is_cdelokal_admin"])
                and not rs.ambience['persona']['is_ml_realm']):
            errors.append(n_(
                "Cannot grant mailinglist or CdElokal admin privileges"
                " to non mailinglist users."))

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

        if ADMIN_KEYS & data.keys():
            code = self.coreproxy.initialize_privilege_change(rs, data)
            self.notify_return_code(
                rs, code, success=n_("Privilege change waiting for approval by "
                                     "another Meta-Admin."))
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

        return self.render(rs, "show_privilege_change",
                           {"persona": persona, "submitter": submitter})

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
        self.notify_return_code(rs, code, success=success, info=info)
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
            headers = {"To": {email}, "Subject": "Admin-Privilegien geändert"}
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
        if (target_realm
                and rs.ambience['persona']['is_{}_realm'.format(target_realm)]):
            rs.notify("warning", n_("No promotion necessary."))
            return self.redirect_show_user(rs, persona_id)
        return self.render(rs, "promote_user")

    @access("core_admin", modi={"POST"})
    @REQUESTdatadict(
        "title", "name_supplement", "birthday", "gender", "free_form",
        "telephone", "mobile", "address", "address_supplement", "postal_code",
        "location", "country", "trial_member")
    @REQUESTdata("target_realm")
    def promote_user(self, rs: RequestState, persona_id: int,
                     target_realm: vtypes.Realm, data: CdEDBObject) -> Response:
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
            if data['paper_expuls'] is None:
                data['paper_expuls'] = True
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
        data = check(rs, vtypes.Persona, data, transition=True)
        if rs.has_validation_errors():
            return self.promote_user_form(  # type: ignore
                rs, persona_id, internal=True)
        assert data is not None
        code = self.coreproxy.change_persona_realms(rs, data)
        self.notify_return_code(rs, code)
        if code > 0 and target_realm == "cde":
            meta_info = self.coreproxy.get_meta_info(rs)
            self.do_mail(rs, "welcome",
                         {'To': (persona['username'],),
                          'Subject': "Aufnahme in den CdE",
                          },
                         {'data': persona,
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
        return self.render(rs, "modify_membership")

    @access("cde_admin", modi={"POST"})
    @REQUESTdata("is_member")
    def modify_membership(self, rs: RequestState, persona_id: int,
                          is_member: bool) -> Response:
        """Change association status.

        This is CdE-functionality so we require a cde_admin instead of a
        core_admin.
        """
        if rs.has_validation_errors():
            return self.modify_membership_form(rs, persona_id)
        # We really don't want to go halfway here.
        with Atomizer(rs):
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
                    transaction_ids = (
                        self.cdeproxy.list_lastschrift_transactions(
                            rs, lastschrift_ids=active_permits,
                            stati=(const.LastschriftTransactionStati.issued,)))
                    if transaction_ids:
                        subject = ("Einzugsermächtigung zu ausstehender "
                                   "Lastschrift widerrufen.")
                        self.do_mail(rs, "pending_lastschrift_revoked",
                                     {'To': (self.conf["MANAGEMENT_ADDRESS"],),
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
    @REQUESTdata("new_balance", "trial_member", "change_note")
    def modify_balance(self, rs: RequestState, persona_id: int,
                       new_balance: vtypes.NonNegativeDecimal, trial_member: bool,
                       change_note: str) -> Response:
        """Set the new balance."""
        if rs.has_validation_errors():
            return self.modify_balance_form(rs, persona_id)
        persona = self.coreproxy.get_cde_user(rs, persona_id)
        if (persona['balance'] == new_balance
                and persona['trial_member'] == trial_member):
            rs.notify("warning", n_("Nothing changed."))
            return self.redirect(rs, "core/modify_balance_form")
        if rs.ambience['persona']['is_archived']:
            rs.notify("error", n_("Persona is archived."))
            return self.redirect_show_user(rs, persona_id)
        if rs.has_validation_errors():
            return self.modify_balance_form(rs, persona_id)
        code = self.coreproxy.change_persona_balance(
            rs, persona_id, new_balance,
            const.FinanceLogCodes.manual_balance_correction,
            change_note=change_note, trial_member=trial_member)
        self.notify_return_code(rs, code)
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
                 foto: werkzeug.FileStorage, delete: bool) -> Response:
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
        self.notify_return_code(rs, code, success=n_("Foto updated."),
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
        self.notify_return_code(rs, code, success=n_("Password invalidated."))

        if not code:
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
        self.notify_return_code(rs, code, success=n_("Password changed."),
                                error=message)
        if not code:
            rs.append_validation_error(
                ("old_password", ValueError(n_("Wrong password."))))
            rs.ignore_validation_errors()
            self.logger.info(
                "Unsuccessful password change for persona {}.".format(
                    rs.user.persona_id))
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
                msg = "Sent password reset mail to {} for IP {}."
                self.logger.info(msg.format(email, rs.request.remote_addr))
                rs.notify("success", n_("Email sent."))
        if admin_exception:
            self.do_mail(
                rs, "admin_no_reset_password",
                {'To': (email,), 'Subject': "Passwort zurücksetzen"})
            msg = "Sent password reset denial mail to admin {} for IP {}."
            self.logger.info(msg.format(email, rs.request.remote_addr))
            rs.notify("success", n_("Email sent."))
        return self.redirect(rs, "core/index")

    @access("core_admin", "meta_admin", "cde_admin", "event_admin", "ml_admin",
            "assembly_admin", modi={"POST"})
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
            msg = "Sent password reset mail to {} for admin {}."
            self.logger.info(msg.format(email, rs.user.persona_id))
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
        if new_password != new_password2:
            rs.extend_validation_errors(
                (("new_password", ValueError(n_("Passwords don’t match."))),
                 ("new_password2", ValueError(n_("Passwords don’t match."))),))
            rs.ignore_validation_errors()
            rs.notify("error", n_("Passwords don’t match."))
            return self.change_password_form(rs)
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
        self.notify_return_code(rs, code, success=n_("Password reset."),
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
        self.logger.info("Sent username change mail to {} for {}.".format(
            new_username, rs.user.username))
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

    @access("core_admin", "cde_admin", "event_admin", "ml_admin",
            "assembly_admin", modi={"POST"})
    @REQUESTdata("new_username")
    def admin_username_change(self, rs: RequestState, persona_id: int,
                              new_username: Optional[vtypes.Email]) -> Response:
        """Change username without verification."""
        if not self.coreproxy.is_relative_admin(rs, persona_id):
            raise werkzeug.exceptions.Forbidden(n_("Not a relative admin."))
        if rs.has_validation_errors():
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
        self.notify_return_code(rs, code)
        return self.redirect_show_user(rs, persona_id)

    @access("anonymous")
    def genesis_request_form(self, rs: RequestState) -> Response:
        """Render form."""
        allowed_genders = set(x for x in const.Genders
                              if x != const.Genders.not_specified)
        realm_options = [(option.realm, rs.gettext(option.name))
                         for option in GENESIS_REALM_OPTION_NAMES
                         if option.realm in REALM_SPECIFIC_GENESIS_FIELDS]
        meta_info = self.coreproxy.get_meta_info(rs)
        return self.render(rs, "genesis_request", {
            'max_rationale': self.conf["MAX_RATIONALE"],
            'allowed_genders': allowed_genders,
            'REALM_SPECIFIC_GENESIS_FIELDS': REALM_SPECIFIC_GENESIS_FIELDS,
            'realm_options': realm_options,
            'meta_info': meta_info,
        })

    @access("anonymous", modi={"POST"})
    @REQUESTdatadict(
        "notes", "realm", "username", "given_names", "family_name", "gender",
        "birthday", "telephone", "mobile", "address_supplement", "address",
        "postal_code", "location", "country", "birth_name")
    @REQUESTfile("attachment")
    @REQUESTdata("attachment_hash", "attachment_filename", "ignore_warnings")
    def genesis_request(self, rs: RequestState, data: CdEDBObject,
                        attachment: Optional[werkzeug.FileStorage],
                        attachment_hash: Optional[str],
                        attachment_filename: str = None,
                        ignore_warnings: bool = False) -> Response:
        """Voice the desire to become a persona.

        This initiates the genesis process.
        """
        attachment_data = None
        if attachment:
            attachment_filename = attachment.filename
            attachment_data = check(
                rs, vtypes.PDFFile, attachment, 'attachment')
        attachment_base_path = self.conf["STORAGE_DIR"] / 'genesis_attachment'
        if attachment_data:
            myhash = self.coreproxy.genesis_set_attachment(rs, attachment_data)
            data['attachment'] = myhash
            rs.values['attachment_hash'] = myhash
            rs.values['attachment_filename'] = attachment_filename
        elif attachment_hash:
            attachment_stored = self.coreproxy.genesis_check_attachment(
                rs, attachment_hash)
            if not attachment_stored:
                data['attachment'] = None
                e = ("attachment", ValueError(n_(
                    "It seems like you took too long and "
                    "your previous upload was deleted.")))
                rs.append_validation_error(e)
            else:
                data['attachment'] = attachment_hash
        data = check(rs, vtypes.GenesisCase, data, creation=True,
                     _ignore_warnings=ignore_warnings)
        if rs.has_validation_errors():
            return self.genesis_request_form(rs)
        assert data is not None
        if len(data['notes']) > self.conf["MAX_RATIONALE"]:
            rs.append_validation_error(
                ("notes", ValueError(n_("Rationale too long."))))
        # We dont actually want gender == not_specified as a valid option if it
        # is required for the requested realm)
        if 'gender' in REALM_SPECIFIC_GENESIS_FIELDS.get(data['realm'], {}):
            if data['gender'] == const.Genders.not_specified:
                rs.append_validation_error(
                    ("gender", ValueError(n_(
                        "Must specify gender for %(realm)s realm."),
                        {"realm": data["realm"]})))
        if rs.has_validation_errors():
            return self.genesis_request_form(rs)
        if self.coreproxy.verify_existence(rs, data['username']):
            existing_id = self.coreproxy.genesis_case_by_email(
                rs, data['username'])
            if existing_id:
                # TODO this case is kind of a hack since it throws
                # away the information entered by the user, but in
                # theory this should not happen too often (reality
                # notwithstanding)
                rs.notify("info", n_("Confirmation email has been resent."))
                case_id = existing_id
            else:
                rs.notify("error",
                          n_("Email address already in DB. Reset password."))
                return self.redirect(rs, "core/index")
        else:
            new_id = self.coreproxy.genesis_request(
                rs, data, ignore_warnings=ignore_warnings)
            if not new_id:
                rs.notify("error", n_("Failed."))
                return self.genesis_request_form(rs)
            case_id = new_id

        # Send verification mail for new case or resend for old case.
        self.do_mail(rs, "genesis_verify",
                     {
                         'To': (data['username'],),
                         'Subject': "Accountanfrage verifizieren",
                     },
                     {
                         'genesis_case_id': self.encode_parameter(
                             "core/genesis_verify", "genesis_case_id",
                             str(case_id), persona_id=None),
                         'given_names': data['given_names'],
                         'family_name': data['family_name'],
                     })
        rs.notify(
            "success",
            n_("Email sent. Please follow the link contained in the email."))
        return self.redirect(rs, "core/index")

    @access("anonymous")
    @REQUESTdata("#genesis_case_id")
    def genesis_verify(self, rs: RequestState, genesis_case_id: int
                       ) -> Response:
        """Verify the email address entered in :py:meth:`genesis_request`.

        This is not a POST since the link is shared via email.
        """
        if rs.has_validation_errors():
            return self.genesis_request_form(rs)
        code, realm = self.coreproxy.genesis_verify(rs, genesis_case_id)
        self.notify_return_code(
            rs, code,
            error=n_("Verification failed. Please contact the administrators."),
            success=n_("Email verified. Wait for moderation. "
                       "You will be notified by mail."),
            info=n_("This account request was already verified.")
        )
        if not code:
            return self.redirect(rs, "core/genesis_request_form")
        return self.redirect(rs, "core/index")

    @periodic("genesis_remind")
    def genesis_remind(self, rs: RequestState, store: CdEDBObject
                       ) -> CdEDBObject:
        """Cron job for genesis cases to review.

        Send a reminder after four hours and then daily.
        """
        current = now()
        data = self.coreproxy.genesis_list_cases(
            rs, stati=(const.GenesisStati.to_review,))
        old = set(store.get('ids', [])) & set(data)
        new = set(data) - set(old)
        remind = False
        if any(data[anid]['ctime'] + datetime.timedelta(hours=4) < current
               for anid in new):
            remind = True
        if old and current.timestamp() > store.get('tstamp', 0) + 24*60*60:
            remind = True
        if remind:
            stati = (const.GenesisStati.to_review,)
            cde_count = len(self.coreproxy.genesis_list_cases(
                rs, stati=stati, realms=["cde"]))
            event_count = len(self.coreproxy.genesis_list_cases(
                rs, stati=stati, realms=["event"]))
            ml_count = len(self.coreproxy.genesis_list_cases(
                rs, stati=stati, realms=["ml"]))
            assembly_count = len(self.coreproxy.genesis_list_cases(
                rs, stati=stati, realms=["assembly"]))
            notify = {self.conf["MANAGEMENT_ADDRESS"]}
            if cde_count:
                notify |= {self.conf["CDE_ADMIN_ADDRESS"]}
            if event_count:
                notify |= {self.conf["EVENT_ADMIN_ADDRESS"]}
            if ml_count:
                notify |= {self.conf["ML_ADMIN_ADDRESS"]}
            if assembly_count:
                notify |= {self.conf["ASSEMBLY_ADMIN_ADDRESS"]}
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
    def genesis_forget(self, rs: RequestState, store: CdEDBObject
                       ) -> CdEDBObject:
        """Cron job for deleting unconfirmed or rejected genesis cases.

        This allows the username to be used once more.
        """
        stati = (const.GenesisStati.unconfirmed, const.GenesisStati.rejected)
        cases = self.coreproxy.genesis_list_cases(
            rs, stati=stati)

        delete = tuple(case["id"] for case in cases.values() if
                       case["ctime"] < now() - self.conf["PARAMETER_TIMEOUT"])

        count = 0
        for genesis_case_id in delete:
            count += self.coreproxy.delete_genesis_case(rs, genesis_case_id)

        genesis_attachment_path: pathlib.Path = (
                self.conf["STORAGE_DIR"] / "genesis_attachment")

        attachment_count = self.coreproxy.genesis_forget_attachments(rs)

        if count or attachment_count:
            msg = "genesis_forget: Deleted {} genesis cases and {} attachments"
            self.logger.info(msg.format(count, attachment_count))

        return store

    @access("core_admin", *("{}_admin".format(realm)
                            for realm, fields in
                            REALM_SPECIFIC_GENESIS_FIELDS.items()
                            if "attachment" in fields))
    def genesis_get_attachment(self, rs: RequestState, attachment: str
                               ) -> Response:
        """Retrieve attachment for genesis case."""
        path = self.conf["STORAGE_DIR"] / 'genesis_attachment' / attachment
        mimetype = magic.from_file(str(path), mime=True)
        return self.send_file(rs, path=path, mimetype=mimetype)

    @access("core_admin", *("{}_admin".format(realm)
                            for realm in REALM_SPECIFIC_GENESIS_FIELDS))
    def genesis_list_cases(self, rs: RequestState) -> Response:
        """Compile a list of genesis cases to review."""
        realms = [realm for realm in REALM_SPECIFIC_GENESIS_FIELDS.keys()
                  if {"{}_admin".format(realm), 'core_admin'} & rs.user.roles]
        data = self.coreproxy.genesis_list_cases(
            rs, stati=(const.GenesisStati.to_review,), realms=realms)
        cases = self.coreproxy.genesis_get_cases(rs, set(data))
        cases_by_realm = {
            realm: {k: v for k, v in cases.items() if v['realm'] == realm}
            for realm in realms}
        return self.render(rs, "genesis_list_cases", {
            'cases_by_realm': cases_by_realm})

    @access("core_admin", *("{}_admin".format(realm)
                            for realm in REALM_SPECIFIC_GENESIS_FIELDS))
    def genesis_show_case(self, rs: RequestState, genesis_case_id: int
                          ) -> Response:
        """View a specific case."""
        case = rs.ambience['genesis_case']
        if (not self.is_admin(rs)
                and "{}_admin".format(case['realm']) not in rs.user.roles):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        reviewer = None
        if case['reviewer']:
            reviewer = self.coreproxy.get_persona(rs, case['reviewer'])
        return self.render(rs, "genesis_show_case", {'reviewer': reviewer})

    @access("core_admin", *("{}_admin".format(realm)
                            for realm in REALM_SPECIFIC_GENESIS_FIELDS))
    def genesis_modify_form(self, rs: RequestState, genesis_case_id: int
                            ) -> Response:
        """Edit a specific case it."""
        case = rs.ambience['genesis_case']
        if (not self.is_admin(rs)
                and "{}_admin".format(case['realm']) not in rs.user.roles):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        if case['case_status'] != const.GenesisStati.to_review:
            rs.notify("error", n_("Case not to review."))
            return self.genesis_list_cases(rs)
        merge_dicts(rs.values, case)
        realm_options = [option
                         for option in GENESIS_REALM_OPTION_NAMES
                         if option.realm in REALM_SPECIFIC_GENESIS_FIELDS]
        return self.render(rs, "genesis_modify_form", {
            'REALM_SPECIFIC_GENESIS_FIELDS': REALM_SPECIFIC_GENESIS_FIELDS,
            'realm_options': realm_options})

    @access("core_admin", *("{}_admin".format(realm)
                            for realm in REALM_SPECIFIC_GENESIS_FIELDS),
            modi={"POST"})
    @REQUESTdatadict(
        "notes", "realm", "username", "given_names", "family_name", "gender",
        "birthday", "telephone", "mobile", "address_supplement", "address",
        "postal_code", "location", "country", "birth_name")
    @REQUESTdata("ignore_warnings")
    def genesis_modify(self, rs: RequestState, genesis_case_id: int,
                       data: CdEDBObject, ignore_warnings: bool = False
                       ) -> Response:
        """Edit a case to fix potential issues before creation."""
        data['id'] = genesis_case_id
        data = check(
            rs, vtypes.GenesisCase, data, _ignore_warnings=ignore_warnings)
        if rs.has_validation_errors():
            return self.genesis_modify_form(rs, genesis_case_id)
        assert data is not None
        case = rs.ambience['genesis_case']
        if (not self.is_admin(rs)
                and "{}_admin".format(case['realm']) not in rs.user.roles):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        if case['case_status'] != const.GenesisStati.to_review:
            rs.notify("error", n_("Case not to review."))
            return self.genesis_list_cases(rs)
        code = self.coreproxy.genesis_modify_case(
            rs, data, ignore_warnings=ignore_warnings)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "core/genesis_show_case")

    @access("core_admin", *("{}_admin".format(realm)
                            for realm in REALM_SPECIFIC_GENESIS_FIELDS),
            modi={"POST"})
    @REQUESTdata("case_status")
    def genesis_decide(self, rs: RequestState, genesis_case_id: int,
                       case_status: const.GenesisStati) -> Response:
        """Approve or decline a genensis case.

        This either creates a new account or declines account creation.
        """
        if rs.has_validation_errors():
            return self.genesis_list_cases(rs)
        case = rs.ambience['genesis_case']
        if (not self.is_admin(rs)
                and "{}_admin".format(case['realm']) not in rs.user.roles):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        if case['case_status'] != const.GenesisStati.to_review:
            rs.notify("error", n_("Case not to review."))
            return self.genesis_list_cases(rs)
        data = {
            'id': genesis_case_id,
            'case_status': case_status,
            'reviewer': rs.user.persona_id,
            'realm': case['realm'],
        }
        with Atomizer(rs):
            code = self.coreproxy.genesis_modify_case(rs, data)
            success = bool(code)
            if success and data['case_status'] == const.GenesisStati.approved:
                success = bool(self.coreproxy.genesis(rs, genesis_case_id))
        if not success:
            rs.notify("error", n_("Failed."))
            return self.genesis_list_cases(rs)
        if case_status == const.GenesisStati.approved:
            success, cookie = self.coreproxy.make_reset_cookie(
                rs, case['username'],
                timeout=self.conf["EMAIL_PARAMETER_TIMEOUT"])
            self.do_mail(
                rs, "genesis_approved",
                {'To': (case['username'],),
                 'Subject': "CdEDB-Account erstellt",
                 },
                {
                    'email': self.encode_parameter(
                        "core/do_password_reset_form", "email",
                        case['username'], persona_id=None,
                        timeout=self.conf["EMAIL_PARAMETER_TIMEOUT"]),
                    'cookie': cookie,
                 })
            rs.notify("success", n_("Case approved."))
        else:
            self.do_mail(
                rs, "genesis_declined",
                {'To': (case['username'],),
                 'Subject': "CdEDB Accountanfrage abgelehnt"},
                {})
            rs.notify("info", n_("Case rejected."))
        return self.redirect(rs, "core/genesis_list_cases")

    @access("core_admin")
    def list_pending_changes(self, rs: RequestState) -> Response:
        """List non-committed changelog entries."""
        pending = self.coreproxy.changelog_get_changes(
            rs, stati=(const.MemberChangeStati.pending,))
        return self.render(rs, "list_pending_changes", {'pending': pending})

    @periodic("pending_changelog_remind")
    def pending_changelog_remind(self, rs: RequestState, store: CdEDBObject
                                 ) -> CdEDBObject:
        """Cron job for pending changlog entries to decide.

        Send a reminder after twelve hours and then daily.
        """
        current = now()
        data = self.coreproxy.changelog_get_changes(
            rs, stati=(const.MemberChangeStati.pending,))
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

    @access("core_admin")
    def inspect_change(self, rs: RequestState, persona_id: int) -> Response:
        """Look at a pending change."""
        history = self.coreproxy.changelog_get_history(rs, persona_id,
                                                       generations=None)
        pending = history[max(history)]
        if pending['code'] != const.MemberChangeStati.pending:
            rs.notify("warning", n_("Persona has no pending change."))
            return self.list_pending_changes(rs)
        current = history[max(
            key for key in history
            if (history[key]['code']
                == const.MemberChangeStati.committed))]
        diff = {key for key in pending if current[key] != pending[key]}
        return self.render(rs, "inspect_change", {
            'pending': pending, 'current': current, 'diff': diff})

    @access("core_admin", modi={"POST"})
    @REQUESTdata("generation", "ack")
    def resolve_change(self, rs: RequestState, persona_id: int,
                       generation: int, ack: bool) -> Response:
        """Make decision."""
        if rs.has_validation_errors():
            return self.list_pending_changes(rs)
        code = self.coreproxy.changelog_resolve_change(rs, persona_id,
                                                       generation, ack)
        message = n_("Change committed.") if ack else n_("Change dropped.")
        self.notify_return_code(rs, code, success=message)
        return self.redirect(rs, "core/list_pending_changes")

    @access("core_admin", "cde_admin", modi={"POST"})
    @REQUESTdata("ack_delete", "note")
    def archive_persona(self, rs: RequestState, persona_id: int,
                        ack_delete: bool, note: str) -> Response:
        """Move a persona to the attic."""
        if not ack_delete:
            rs.append_validation_error(
                ("ack_delete", ValueError(n_("Must be checked."))))
        if not note:
            rs.notify("error", n_("Must supply archival note."))
        if rs.has_validation_errors():
            return self.show_user(
                rs, persona_id, confirm_id=persona_id, internal=True,
                quote_me=False, event_id=None, ml_id=None)

        try:
            code = self.coreproxy.archive_persona(rs, persona_id, note)
        except ArchiveError as e:
            rs.notify("error", e.args[0])
            code = 0
        self.notify_return_code(rs, code)
        return self.redirect_show_user(rs, persona_id)

    @access("core_admin", "cde_admin", modi={"POST"})
    def dearchive_persona(self, rs: RequestState, persona_id: int) -> Response:
        """Reinstate a persona from the attic."""
        if rs.has_validation_errors():
            return self.redirect_show_user(rs, persona_id)

        code = self.coreproxy.dearchive_persona(rs, persona_id)
        self.notify_return_code(rs, code)
        return self.redirect_show_user(rs, persona_id)

    @access("core_admin", "cde_admin", modi={"POST"})
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
        self.notify_return_code(rs, code)
        return self.redirect_show_user(rs, persona_id)

    @access("core_admin")
    @REQUESTdata("stati", "submitted_by", "reviewed_by", "persona_id",
                 "change_note", "offset", "length", "time_start", "time_stop")
    def view_changelog_meta(self, rs: RequestState,
                            stati: Collection[const.MemberChangeStati],
                            offset: Optional[int],
                            length: Optional[vtypes.PositiveInt],
                            persona_id: Optional[CdedbID],
                            submitted_by: Optional[CdedbID],
                            change_note: Optional[str],
                            time_start: Optional[datetime.datetime],
                            time_stop: Optional[datetime.datetime],
                            reviewed_by: Optional[CdedbID]) -> Response:
        """View changelog activity."""
        length = length or self.conf["DEFAULT_LOG_LENGTH"]
        # length is the requested length, _length the theoretically
        # shown length for an infinite amount of log entries.
        _offset, _length = calculate_db_logparams(offset, length)

        # no validation since the input stays valid, even if some options
        # are lost
        rs.ignore_validation_errors()
        total, log = self.coreproxy.retrieve_changelog_meta(
            rs, stati, _offset, _length, persona_id=persona_id,
            submitted_by=submitted_by, change_note=change_note,
            time_start=time_start, time_stop=time_stop, reviewed_by=reviewed_by)
        persona_ids = (
                {entry['submitted_by'] for entry in log if
                 entry['submitted_by']}
                | {entry['reviewed_by'] for entry in log if
                   entry['reviewed_by']}
                | {entry['persona_id'] for entry in log if entry['persona_id']})
        personas = self.coreproxy.get_personas(rs, persona_ids)
        loglinks = calculate_loglinks(rs, total, offset, length)
        return self.render(rs, "view_changelog_meta", {
            'log': log, 'total': total, 'length': _length,
            'personas': personas, 'loglinks': loglinks})

    @access("core_admin")
    @REQUESTdata("codes", "persona_id", "submitted_by", "change_note", "offset",
                 "length", "time_start", "time_stop")
    def view_log(self, rs: RequestState, codes: Collection[const.CoreLogCodes],
                 offset: Optional[int], length: Optional[vtypes.PositiveInt],
                 persona_id: Optional[CdedbID], submitted_by: Optional[CdedbID],
                 change_note: Optional[str],
                 time_start: Optional[datetime.datetime],
                 time_stop: Optional[datetime.datetime]) -> Response:
        """View activity."""
        length = length or self.conf["DEFAULT_LOG_LENGTH"]
        # length is the requested length, _length the theoretically
        # shown length for an infinite amount of log entries.
        _offset, _length = calculate_db_logparams(offset, length)

        # no validation since the input stays valid, even if some options
        # are lost
        rs.ignore_validation_errors()
        total, log = self.coreproxy.retrieve_log(
            rs, codes, _offset, _length, persona_id=persona_id,
            submitted_by=submitted_by, change_note=change_note,
            time_start=time_start, time_stop=time_stop)
        persona_ids = (
                {entry['submitted_by'] for entry in log if
                 entry['submitted_by']}
                | {entry['persona_id'] for entry in log if entry['persona_id']})
        personas = self.coreproxy.get_personas(rs, persona_ids)
        loglinks = calculate_loglinks(rs, total, offset, length)
        return self.render(rs, "view_log", {
            'log': log, 'total': total, 'length': _length,
            'personas': personas, 'loglinks': loglinks})

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
        if not self.conf["CDEDB_DEV"]:
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

        spec = {
            "id": "id",
            "username": "str",
            "is_event_realm": "bool",
        }
        constraints = (
            ('username', QueryOperators.equal, username),
            ('is_event_realm', QueryOperators.equal, True),
        )
        query = Query("qview_persona", spec,
                      ("given_names", "family_name", "is_member", "username"),
                      constraints, (('id', True),))
        result = self.coreproxy.submit_resolve_api_query(rs, query)
        return self.send_json(rs, unwrap(result) if result else {})
