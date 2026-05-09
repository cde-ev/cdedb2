#!/usr/bin/env python3

"""Basic services for the core realm."""

import base64
import collections
import datetime
import decimal
import enum
import itertools
import operator
import pathlib
import quopri
import tempfile
from typing import Any, Optional

import segno.helpers
import werkzeug.datastructures
import werkzeug.exceptions
from werkzeug import Response

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.core as models
import cdedb.models.past_event as models_past_event
from cdedb.common import (
    CdEDBObject,
    CdEDBObjectMap,
    DefaultReturnCode,
    Realm,
    RequestState,
    User,
    get_mandatory_form_fields,
    make_persona_name,
    merge_dicts,
    now,
    pairwise,
    sanitize_filename,
    unwrap,
)
from cdedb.common.exceptions import (
    AdminPasswordResetError,
    ArchiveError,
    CryptographyError,
    IncorrectPasswordError,
    PrivilegeError,
    ValidationWarning,
)
from cdedb.common.fields import (
    PERSONA_ASSEMBLY_FIELDS,
    PERSONA_CDE_FIELDS,
    PERSONA_CORE_FIELDS,
    PERSONA_EVENT_FIELDS,
    PERSONA_ML_FIELDS,
    PERSONA_STATUS_FIELDS,
)
from cdedb.common.i18n import format_country_code, get_localized_country_codes
from cdedb.common.n_ import n_
from cdedb.common.parse.util import Accounts
from cdedb.common.query import Query, QueryOperators, QueryScope, QuerySpecEntry
from cdedb.common.query.defaults import DEFAULT_QUERIES
from cdedb.common.query.log_filter import ChangelogLogFilter, CoreLogFilter
from cdedb.common.roles import (
    ADMIN_KEYS,
    ADMIN_VIEWS_COOKIE_NAME,
    ALL_ADMIN_VIEWS,
    ALL_ADMINS,
    REALM_ADMINS,
    REALM_INHERITANCE,
    extract_roles,
    implied_realms,
)
from cdedb.common.sorting import EntitySorter, xsorted
from cdedb.common.validation.validate import (
    PERSONA_CDE_CREATION as CDE_TRANSITION_FIELDS,
    PERSONA_COMMON_FIELDS,
    PERSONA_EVENT_CREATION as EVENT_TRANSITION_FIELDS,
)
from cdedb.filter import (
    enum_entries_filter,
    markdown_parse_safe,
    money_filter,
)
from cdedb.frontend.common import (
    AbstractFrontend,
    Headers,
    REQUESTdata,
    REQUESTdatadict,
    REQUESTfile,
    TransactionObserver,
    access,
    basic_redirect,
    check_validation as check,
    inspect_validation as inspect,
    periodic,
    request_dict_extractor,
)
from cdedb.models.core import CdEPersona
from cdedb.models.ml import MailinglistGroup
from cdedb.uncommon.submanshim import SubscriptionPolicy

# Name of each realm
# TODO move to Persona dataclass?
USER_REALM_NAMES = {
    "cde": n_("CdE user / Member"),
    "event": n_("Event user"),
    "assembly": n_("Assembly user"),
    "ml": n_("Mailinglist user"),
}


class CoreBaseFrontend(AbstractFrontend):
    """Note that there is no user role since the basic distinction is between
    anonymous access and personas."""

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
                    "core/login",
                    "wants",
                    wants,
                    persona_id=rs.user.persona_id,
                    timeout=self.conf["EXTENDED_PARAMETER_TIMEOUT"],
                )
            return self.render(
                rs,
                "login",
                {'meta_info': meta_info},
                get_mandatory_form_fields(self.login),
            )

        else:
            # Redirect to wanted page, if user meanwhile logged in
            if wants:
                return basic_redirect(rs, wants)

            # genesis cases
            genesis_realms = []
            for realm in models.GenesisCase.available_realms:
                if {"core_admin", f"{realm}_admin"} & rs.user.roles:
                    genesis_realms.append(realm)
            if genesis_realms and "genesis" in rs.user.admin_views:
                data = self.coreproxy.genesis_list_cases(
                    rs, stati=(const.GenesisStati.to_review,), realms=genesis_realms
                )
                dashboard['genesis_cases'] = len(data)
            # pending changes
            if "user_review" in rs.user.admin_views:
                data = self.coreproxy.changelog_get_pending_changes(rs)
                dashboard['pending_changes'] = len(data)
            # pending privilege changes
            if "meta_admin" in rs.user.admin_views:
                stati = (const.PrivilegeChangeStati.pending,)
                data = self.coreproxy.list_privilege_changes(rs, stati=stati)
                dashboard['privilege_changes'] = len(data)
            # events organized
            orga_info = self.eventproxy.orga_info(rs, rs.user.persona_id)
            if orga_info:
                orga = []
                orga_registrations = {}
                orga_events = self.eventproxy.get_events(rs, orga_info)
                for event in orga_events.values():
                    if event.is_current_for_orga():
                        regs = self.eventproxy.list_registrations(rs, event.id)
                        orga_registrations[event.id] = len(regs)
                        orga.append(event)
                dashboard['orga'] = orga
                dashboard['orga_registrations'] = orga_registrations
                dashboard['present'] = now()
            # mailinglists moderated
            moderator_info = self.mlproxy.moderator_info(rs, rs.user.persona_id)
            if moderator_info:
                mailinglists = self.mlproxy.get_mailinglists(rs, moderator_info)
                mailman = self.get_mailman()
                moderator: dict[int, dict[str, Any]] = {}
                for ml_id, ml in mailinglists.items():
                    requests = self.mlproxy.get_subscription_states(
                        rs, ml_id, states=(const.SubscriptionState.pending,)
                    )
                    moderator[ml_id] = {
                        "id": ml.id,
                        "title": ml.title,
                        "is_active": ml.is_active,
                        "requests": len(requests),
                        "held_mails": mailman.get_held_message_count(ml),
                    }
                dashboard['moderator'] = {
                    k: v for k, v in moderator.items() if v['is_active']
                }
            # visible and open events
            if "event" in rs.user.roles:
                event_ids = self.eventproxy.list_events(
                    rs, current=True, archived=False
                )
                events = self.eventproxy.get_events(rs, event_ids.keys())
                final: dict[int, Any] = {}
                events_registration: dict[int, Optional[bool]] = {}
                events_payment_pending: dict[int, bool] = {}
                for event_id, event in events.items():
                    registration, payment_pending = (
                        self.eventproxy.get_registration_payment_info(rs, event_id)
                    )
                    if not event.is_visible_for(
                        rs.user, registration is True, privileged=False
                    ):
                        continue
                    # Skip event, if not registered and the registration begins
                    # more than 2 weeks in future
                    if (
                        not registration
                        and event.registration_start
                        and (
                            now() + datetime.timedelta(weeks=2)
                            < event.registration_start
                        )
                    ):
                        continue
                    # Skip events, that are over or are not registerable anymore
                    if (
                        event.registration_hard_limit
                        and now() > event.registration_hard_limit
                        and not registration
                    ) or now().date() > event.end:
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
                    rs, is_active=True, restrictive=True
                )
                assemblies = self.assemblyproxy.get_assemblies(rs, assembly_ids.keys())
                final = {}
                for assembly_id, assembly in assemblies.items():
                    assembly['does_attend'] = self.assemblyproxy.does_attend(
                        rs, assembly_id=assembly_id
                    )
                    if assembly['does_attend'] or assembly['signup_end'] > now():
                        final[assembly_id] = assembly
                if final:
                    dashboard['assemblies'] = final
            return self.render(
                rs, "index", {'meta_info': meta_info, 'dashboard': dashboard}
            )

    @access("core_admin")
    def meta_info_form(self, rs: RequestState) -> Response:
        """Render form."""
        info = self.coreproxy.get_meta_info(rs)
        merge_dicts(rs.values, info.as_dict())
        accounts = [
            (str(account), account.display_str())
            for account in Accounts
            if account != Accounts.Unknown
        ]
        return self.render(
            rs,
            "meta_info",
            {
                "meta_info": info,
                "hard_lockdown": self.conf["LOCKDOWN"],
                "accounts": accounts,
            },
        )

    @access("core_admin", modi={"POST"})
    @REQUESTdatadict(*models.MetaInfo.requestdict_fields(creation=None))
    def change_meta_info(self, rs: RequestState, data: CdEDBObject) -> Response:
        """Change the meta info constants."""
        data = check(rs, models.MetaInfo, data)
        if rs.has_validation_errors():  # pragma: no cover
            return self.meta_info_form(rs)
        assert data is not None
        code = self.coreproxy.set_meta_info(rs, data)
        rs.notify_return_code(code)
        return self.redirect(rs, "core/meta_info_form")

    @access("anonymous", modi={"POST"})
    @REQUESTdata("username", "password", "#wants")
    def login(
        self, rs: RequestState, username: vtypes.Email, password: str, wants: str | None
    ) -> Response:
        """Create session.

        :param wants: URL to redirect to
        """
        if rs.has_validation_errors():
            return self.index(rs)
        sessionkey = self.coreproxy.login(
            rs, username, password, rs.request.remote_addr
        )
        if not sessionkey:
            rs.notify("error", n_("Login failure."))
            rs.extend_validation_errors((
                ("username", ValueError()),
                ("password", ValueError()),
            ))
            rs.ignore_validation_errors()
            return self.index(rs)

        if wants:
            response = basic_redirect(rs, wants)
        elif "member" in rs.user.roles:
            user = self.coreproxy.get_cde_user(rs, rs.user.persona_id)
            if not user.decided_search:
                response = self.redirect(rs, "cde/consent_decision_form")
            else:
                response = self.redirect(rs, "core/index")
        else:
            response = self.redirect(rs, "core/index")
        response.set_cookie(
            "sessionkey", sessionkey, httponly=True, secure=True, samesite="Lax"
        )
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
        rs.notify("success", n_("%(count)s session(s) terminated."), {'count': count})
        # Unset persona_id so the notification is encoded correctly.
        rs.user.persona_id = None
        ret = self.redirect(rs, "core/index")
        ret.delete_cookie("sessionkey")
        return ret

    @periodic("deactivate_old_sessions", period=4 * 24)
    def deactivate_old_sessions(
        self, rs: RequestState, store: CdEDBObject
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
    def change_locale(
        self, rs: RequestState, locale: vtypes.PrintableASCII, wants: str | None
    ) -> Response:
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
                "locale", locale, expires=now() + datetime.timedelta(days=10 * 365)
            )
        else:
            rs.notify("error", n_("Unsupported locale"))
        return response

    @access("persona", modi={"POST"}, check_anti_csrf=False)
    @REQUESTdata("view_specifier", "#wants")
    def modify_active_admin_views(
        self, rs: RequestState, view_specifier: vtypes.PrintableASCII, wants: str | None
    ) -> Response:
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

        enabled_views = set(
            rs.request.cookies.get(ADMIN_VIEWS_COOKIE_NAME, "").split(',')
        )
        changed_views = set(view_specifier[1:].split(','))
        enable = view_specifier[0] == "+"
        if enable:
            enabled_views.update(changed_views)
        else:
            enabled_views -= changed_views
        response.set_cookie(
            ADMIN_VIEWS_COOKIE_NAME,
            ",".join(enabled_views & ALL_ADMIN_VIEWS),
            expires=now() + datetime.timedelta(days=10 * 365),
        )
        return response

    @access("ml", modi={"POST"}, check_anti_csrf=False)
    @REQUESTdata("md_str")
    def markdown_parse(self, rs: RequestState, md_str: str) -> Response:
        if rs.has_validation_errors():
            return Response("", mimetype='text/plain')
        html_str = markdown_parse_safe(md_str)
        return Response(html_str, mimetype='text/plain')

    @access("searchable")
    @REQUESTdata("#confirm_id")
    def download_vcard(
        self, rs: RequestState, persona_id: int, confirm_id: int
    ) -> Response:
        if persona_id != confirm_id or rs.has_validation_errors():
            return self.index(rs)

        vcard = self._create_vcard(rs, persona_id, include_foto=True)
        persona = self.coreproxy.get_persona(rs, persona_id)
        filename = sanitize_filename(persona.get_name())

        return self.send_file(
            rs, data=vcard, mimetype='text/vcard', filename=f'{filename}.vcf'
        )

    @access("searchable")
    @REQUESTdata("#confirm_id")
    def qr_vcard(self, rs: RequestState, persona_id: int, confirm_id: int) -> Response:
        if persona_id != confirm_id or rs.has_validation_errors():
            return self.index(rs)

        vcard = self._create_vcard(rs, persona_id, include_foto=False)
        return self.serve_qrcode(rs, vcard)

    def _make_vcard_data(
        self, rs: RequestState, persona: models.CdEPersona, include_foto: bool
    ) -> str:
        """Creates a string encoding the contact information as vCard 3.0.

        Only a subset of available `vCard 3.0 properties
        <https://tools.ietf.org/html/rfc2426>` is supported.

        This is a rewritten form of `segno.helpers.make_vcard_data` to suite our needs.
        """
        escape = segno.helpers._escape_vcard  # type: ignore[attr-defined]

        name = [
            persona.family_name,
            persona.given_names,
            "",
            persona.title,
            persona.name_supplement,
        ]
        data = [
            'BEGIN:VCARD',
            'VERSION:3.0',
            f'N:{";".join(escape(e or "") for e in name)}',
            f'FN:{escape(persona.get_name())}',
            f'EMAIL:{escape(persona.username)}',
        ]
        if persona.mobile:
            data.append(f'TEL;TYPE=CELL:{persona.mobile}')
        if persona.telephone:
            data.append(f'TEL;TYPE=HOME:{persona.telephone}')
        if persona.nickname:
            data.append(f'NICKNAME:{escape(persona.nickname)}')
        for sub in ["", "2"]:
            if getattr(persona, f'show_address{sub}'):
                address = [
                    getattr(persona, f'address_supplement{sub}'),
                    getattr(persona, f'address{sub}'),
                ]
            else:
                address = ["", ""]
            address += [
                getattr(persona, f'location{sub}'),
                "",
                getattr(persona, f'postal_code{sub}'),
                rs.gettext(format_country_code(getattr(persona, f'country{sub}'))),
            ]
            if any(address):
                if not sub:
                    prefix = 'ADR;TYPE=intl,home,postal,pref:;'
                else:
                    prefix = 'ADR;TYPE=intl,home,postal:;'
                data.append(prefix + ";".join(escape(e or "") for e in address))
        if persona.birthday != datetime.date.min:
            data.append(f"BDAY:{persona.birthday.strftime('%Y-%m-%d')}")
        if persona.foto and include_foto:
            mime_type = self.coreproxy.get_foto_store(rs).get_mime_type(persona.foto)
            foto_data = self.coreproxy.get_foto_store(rs).get(persona.foto)
            if mime_type and foto_data:
                data.append(
                    f'PHOTO;ENCODING=b;TYPE={mime_type.removeprefix("image/").upper()}:{base64.b64encode(foto_data).decode()}'
                )
        data.append('END:VCARD')
        data.append('')
        return '\r\n'.join(data)

    def _create_vcard(
        self, rs: RequestState, persona_id: int, include_foto: bool
    ) -> str:
        """
        Generate a vCard string for a user to be delivered to a client.

        :return: The serialized vCard (as in a vcf file)
        """
        if not {'searchable', 'cde_admin'} & rs.user.roles:
            raise werkzeug.exceptions.Forbidden(n_("No cde access to profile."))

        if "cde_admin" not in rs.user.roles and not self.coreproxy.verify_persona(
            rs, persona_id, required_roles=['searchable']
        ):
            raise werkzeug.exceptions.Forbidden(
                n_("Access to non-searchable member data.")
            )

        persona = self.coreproxy.get_cde_user(rs, persona_id)
        vcard = self._make_vcard_data(rs, persona, include_foto)
        return vcard

    @access("persona")
    def mydata(self, rs: RequestState) -> Response:
        """Convenience entry point for own data."""
        assert rs.user.persona_id is not None
        return self.redirect_show_user(rs, rs.user.persona_id)

    class AccessRealm(enum.Flag):
        """Manage realm access in show_user.

        Realms of the user the viewer may access.
        This is independent of the actual realms the user possesses.
        Additionally, each viewer is eligible to view some basic infos.
        """

        persona = 0
        ml = enum.auto()
        assembly = enum.auto()
        event = enum.auto()
        cde = enum.auto()
        all = persona | ml | assembly | event | cde

    class AccessLevel(enum.Flag):
        """Manage redaction of data in show_user."""

        # access based on special roles of the viewer
        orga = enum.auto()
        moderator = enum.auto()
        # access to status bits for meta admins
        meta = enum.auto()
        # full access, do not strip any data, for core and relative admins,
        #  and access to your own profile. Does not include admin_notes.
        _full = enum.auto()
        full = orga | moderator | meta | _full

    class AccessMode(enum.Flag):
        """Manage soft hides of data in show_user.

        Depends on the admin view of the viewer, and determines available admin views.
        """

        orga = enum.auto()
        moderator = enum.auto()
        any_admin = enum.auto()

    @access("persona")
    @REQUESTdata("#confirm_id", "quote_me", "event_id", "ml_id")
    def show_user(
        self,
        rs: RequestState,
        persona_id: int,
        confirm_id: int,
        quote_me: bool,
        event_id: vtypes.ID | None,
        ml_id: vtypes.ID | None,
        internal: bool = False,
    ) -> Response:
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
        # fmt: off
        assert rs.user.persona_id is not None
        if (persona_id != confirm_id or rs.has_validation_errors()) and not internal:
            return self.index(rs)

        is_relative_admin = self.coreproxy.is_relative_admin(rs, persona_id)
        is_relative_or_meta_admin = self.coreproxy.is_relative_admin(
            rs, persona_id, allow_meta_admin=True)

        if (rs.ambience['persona'].is_archived and not is_relative_admin):
            raise werkzeug.exceptions.Forbidden(
                n_("Only admins may view archived datasets."))

        is_relative_admin_view = self.coreproxy.is_relative_admin_view(
            rs, persona_id)
        is_relative_or_meta_admin_view = self.coreproxy.is_relative_admin_view(
            rs, persona_id, allow_meta_admin=True)

        # Check whether profile is currently searchable to viewer
        status = self.coreproxy.get_persona_status(rs, rs.ambience['persona'].id)
        is_searchable_to_you = ("searchable" in rs.user.roles
                                and status.is_member
                                and status.is_searchable)

        access_realms = self.AccessRealm(0)
        access_levels = self.AccessLevel(0)
        access_mode = self.AccessMode(0)
        REDACTED = models.CorePersona.REDACTED

        # Let users see themselves
        if persona_id == rs.user.persona_id:
            access_realms |= self.AccessRealm.all
            access_levels |= self.AccessLevel.full
        # Core admins see everything
        if ("core_admin" in rs.user.roles and "core_user" in rs.user.admin_views):
            access_realms |= self.AccessRealm.all
            access_levels |= self.AccessLevel.full
        # Meta admins see the status bits
        if ("meta_admin" in rs.user.roles and "meta_admin" in rs.user.admin_views):
            access_levels |= self.AccessLevel.meta
        # Other admins see their realm if they are relative admin
        if is_relative_admin:
            access_mode |= self.AccessMode.any_admin
            for realm in [self.AccessRealm.ml, self.AccessRealm.assembly,
                          self.AccessRealm.event, self.AccessRealm.cde]:
                if (f"{realm.name}_admin" in rs.user.roles
                        and f"{realm.name}_user" in rs.user.admin_views):
                    access_realms |= realm
                    # Relative admins can see all data
                    access_levels |= self.AccessLevel.full
        # Admins with special buttons (like viewing account requests in the nav, or
        #  links to realm-related info pages) which shall change their admin view.
        if {"core_admin", "cde_admin", "event_admin", "ml_admin"} & rs.user.roles:
            access_mode |= self.AccessMode.any_admin
        # Members see other members (modulo quota)
        if quote_me and self.AccessRealm.cde not in access_realms:
            if is_searchable_to_you:
                access_realms |= self.AccessRealm.cde
            else:
                raise werkzeug.exceptions.Forbidden(n_(
                    "Access to non-searchable member data."))
        # Orgas see their participants
        if event_id:
            is_admin = "event_admin" in rs.user.roles
            is_viewing_admin = is_admin and "event_orga" in rs.user.admin_views
            is_orgalike = event_id in rs.user.orga | rs.user.caretaker
            if is_orgalike or is_admin:
                is_participant = self.eventproxy.list_registrations(
                    rs, event_id, persona_id)
                if (is_orgalike or is_viewing_admin) and is_participant:
                    access_realms |= self.AccessRealm.event
                    access_levels |= self.AccessLevel.orga
                # Admins who are also orgas can not disable this admin view
                if is_admin and not is_orgalike and is_participant:
                    access_mode |= self.AccessMode.orga
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
                access_mode |= self.AccessMode.moderator
            relevant_stati = [s for s in const.SubscriptionState
                              if s not in {const.SubscriptionState.unsubscribed,
                                           const.SubscriptionState.none}]
            if is_moderator or ml_type.has_moderator_view(rs.user):
                subscriptions = self.mlproxy.get_subscription_states(
                    rs, ml_id, states=relevant_stati)
                if persona_id in subscriptions:
                    access_realms |= self.AccessRealm.ml
                    # the moderator access level currently does nothing, but we
                    # add it anyway to be less confusing
                    access_levels |= self.AccessLevel.moderator

        # Retrieve data
        #
        # This is the basic mechanism for restricting access, since we only
        # add attributes for which an access level is provided.
        target_roles = extract_roles(status.as_dict(), introspection_only=True)
        persona: models.CorePersona
        if self.AccessRealm.cde in access_realms and "cde" in target_roles:
            persona = self.coreproxy.get_cde_user(rs, persona_id)
        # event and assembly are independent realms, users may have both at the same time
        elif (self.AccessRealm.event in access_realms and "event" in target_roles
                and self.AccessRealm.assembly in access_realms and "assembly" in target_roles):
            persona = models.EventAssemblyPersona(**{
                **self.coreproxy.get_assembly_user(rs, persona_id).as_dict(),
                **self.coreproxy.get_event_user(rs, persona_id, event_id).as_dict(),
            })
        elif self.AccessRealm.event in access_realms and "event" in target_roles:
            persona = self.coreproxy.get_event_user(rs, persona_id, event_id)
        elif self.AccessRealm.assembly in access_realms and "assembly" in target_roles:
            persona = self.coreproxy.get_assembly_user(rs, persona_id)
        elif self.AccessRealm.ml in access_realms and "ml" in target_roles:
            persona = self.coreproxy.get_ml_user(rs, persona_id)
        elif self.AccessRealm.persona in access_realms:
            persona = self.coreproxy.get_persona(rs, persona_id)
            # The base version of the data set should only contain the name,
            # so we take care to not expose the username.
            persona.username = REDACTED
            persona.legal_given_names = REDACTED
        else:
            raise RuntimeError("Impossible")

        has_lastschrift = REDACTED
        if isinstance(persona, models.CdEPersona):
            if self.AccessLevel.full in access_levels:
                has_lastschrift = bool(self.cdeproxy.list_lastschrift(
                    rs, persona_ids=(persona_id,), active=True))
                # hide the donation property if no active lastschrift exists, to avoid confusion
                if not has_lastschrift:
                    persona.donation = REDACTED
            else:
                persona.balance = REDACTED
                persona.decided_search = REDACTED
                persona.trial_member = REDACTED
                persona.bub_search = REDACTED
                persona.paper_expuls = REDACTED
                persona.donation = REDACTED
                if not persona.show_address2:
                    # keep showing the rough location, postal code and country
                    persona.address2 = REDACTED
                    persona.address_supplement2 = REDACTED

        if self.AccessLevel.orga not in access_levels:
            # May be hidden from member search, but not from orga view.
            if not persona.show_legal_given_names:
                persona.legal_given_names = REDACTED
            if isinstance(persona, models.EventPersona):
                persona.gender = REDACTED
                persona.pronouns_nametag = REDACTED
                persona.show_legal_given_names = REDACTED
                # May be hidden from member search, but not from orga view.
                # In addition, never show the address of non-cde users.
                if not isinstance(persona, models.CdEPersona) or not persona.show_address:
                    # keep showing the rough location, postal code and country
                    persona.address = REDACTED
                    persona.address_supplement = REDACTED

        admin_bits = None
        notes = REDACTED
        if self.AccessLevel.meta in access_levels:
            # This is a bit involved to not contaminate the data dict
            # with keys which are not applicable to the requested persona
            total = self.coreproxy.get_total_persona(rs, persona_id)
            admin_bits = {bit for bit in CdEPersona.get_admin_bits() if total[bit]}
            persona.username = total['username']
            if is_relative_or_meta_admin and is_relative_or_meta_admin_view:
                # This is not shown to the persona themselves
                notes = total['notes']
        else:
            status_bits = persona.get_status_bits()
            # allow orgas to view member status
            if self.AccessLevel.orga in access_levels and "is_member" in status_bits:
                status_bits.remove("is_member")
            for field in status_bits:
                setattr(persona, field, REDACTED)

        # Determine if vcard should be visible
        show_vcard = self.AccessRealm.cde in access_realms and is_searchable_to_you

        # Add past event participation info
        past_event_participations = None
        if self.AccessRealm.cde in access_realms and {"event", "cde"} & target_roles:
            past_event_participations = self.pasteventproxy.list_persona_events(rs, persona_id)

        # Retrieve number of active sessions if the user is viewing his own profile
        active_session_count = None
        if rs.user.persona_id == persona_id:
            active_session_count = self.coreproxy.count_active_sessions(rs)

        # Check for email trouble
        email_report = None
        if (rs.user.persona_id == persona_id
                or ({"core_admin", "ml_admin"} & rs.user.roles)):
            # the username may be masked by admin views, but then we also
            # don't need the email report
            if persona.username != REDACTED:
                tmp = self.coreproxy.get_email_reports(rs, [persona_id])
                email_report = tmp.get(persona.username)

        # Check whether we should display an option for using the quota
        quoteable = (not quote_me and self.AccessRealm.cde not in access_realms
                     and is_searchable_to_you)

        meta_info = self.coreproxy.get_meta_info(rs)
        mandatory_fields = get_mandatory_form_fields(
            self.archive_persona, self.invalidate_password)

        return self.render(rs, "show_user", {
            # TODO rename in template
            'data': persona,
            'admin_bits': admin_bits,
            'meta_info': meta_info,
            'is_relative_admin_view': is_relative_admin_view,
            'quoteable': quoteable,
            'AccessMode': self.AccessMode,
            'access_mode': access_mode,
            'active_session_count': active_session_count,
            'email_report': email_report,
            'has_lastschrift': has_lastschrift,
            'notes': notes,
            'show_vcard': show_vcard,
            'past_event_participations': past_event_participations,
        }, mandatory_fields)

    # fmt: on
    @access("member")
    def my_lastschrift(self, rs: RequestState) -> Response:
        """Convenience entry point to view own lastschrift.

        This is only in the core frontend to stay consistent in the path naming scheme.
        """
        return self.redirect(
            rs, "cde/lastschrift_show", {"persona_id": rs.user.persona_id}
        )

    @access("event")
    def show_user_events(self, rs: RequestState, persona_id: vtypes.ID) -> Response:
        """Render overview which events a given user is registered for."""
        if not (
            self.coreproxy.is_relative_admin(rs, persona_id)
            or "event_admin" in rs.user.roles
            or rs.user.persona_id == persona_id
        ):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))

        registrations = self.eventproxy.list_persona_registrations(rs, persona_id)
        registration_ids: dict[int, int] = {}
        registration_parts: dict[int, dict[int, const.RegistrationPartStati]] = {}
        for event_id, reg in registrations.items():
            registration_ids[event_id] = unwrap(reg.keys())
            registration_parts[event_id] = unwrap(reg.values())
        events = self.eventproxy.get_events(rs, registrations.keys())
        return self.render(
            rs,
            "show_user_events",
            {
                'events': events,
                'registration_ids': registration_ids,
                'registration_parts': registration_parts,
            },
        )

    @access("event")
    def show_user_events_self(self, rs: RequestState) -> Response:
        """Shorthand to view event registrations for oneself."""
        return self.redirect(
            rs, "core/show_user_events", {'persona_id': rs.user.persona_id}
        )

    @access("ml")
    def show_user_mailinglists(
        self, rs: RequestState, persona_id: vtypes.ID
    ) -> Response:
        """Render overview of mailinglist data of a certain user."""
        if not (
            self.coreproxy.is_relative_admin(rs, persona_id)
            or "ml_admin" in rs.user.roles
            or rs.user.persona_id == persona_id
        ):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        if not self.coreproxy.verify_id(rs, persona_id, is_archived=False):
            # reconnoitre_ambience leads to 404 if user does not exist at all.
            rs.notify("error", n_("Persona is archived."))
            return self.redirect_show_user(rs, persona_id)

        persona = self.coreproxy.get_ml_user(rs, persona_id)
        subscriptions = self.mlproxy.get_user_subscriptions(rs, persona_id)
        mailinglists = self.mlproxy.get_mailinglists(rs, subscriptions.keys())
        addresses = self.mlproxy.get_user_subscription_addresses(rs, persona_id)
        defect_addresses = self.coreproxy.get_defect_address_reports(rs, [persona_id])

        grouped: dict[MailinglistGroup, CdEDBObjectMap]
        grouped = collections.defaultdict(dict)
        for mailinglist_id, ml in mailinglists.items():
            is_receiving = (
                addr not in defect_addresses
                if (addr := addresses.get(mailinglist_id))
                else persona.username not in defect_addresses
            )
            grouped[ml.sortkey][mailinglist_id] = {
                'title': ml.title,
                'id': mailinglist_id,
                'address': addresses.get(mailinglist_id),
                'is_active': ml.is_active,
                'is_receiving': is_receiving,
            }

        return self.render(
            rs,
            "show_user_mailinglists",
            {
                'groups': MailinglistGroup,
                'mailinglists': grouped,
                'subscriptions': subscriptions,
            },
        )

    @access("ml")
    def show_user_mailinglists_self(self, rs: RequestState) -> Response:
        """Redirect to use `self` instead of persona_id to make ambience work."""
        return self.redirect(
            rs, "core/show_user_mailinglists", {'persona_id': rs.user.persona_id}
        )

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
            total_const: list[int] = []
            tmp: list[int] = []
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
                if history[x]['code'] == stati.nacked and not already_committed:
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
        pending = {i for i in history if history[i]['code'] == stati.pending}
        # Track the omitted information whether a new value finally got
        # committed or not.
        #
        # This is necessary since we only show those data points, where the
        # data (e.g. the name) changes. This does especially not detect
        # meta-data changes (e.g. the change-status).
        eventual_status = {
            f: {
                gen: entry['code']
                for gen, entry in history.items()
                if gen not in constants[f]
            }
            for f in fields
        }
        for f in fields:
            for gen in xsorted(history):
                if gen in constants[f]:
                    anchor = max(g for g in eventual_status[f] if g < gen)
                    this_status = history[gen]['code']
                    if this_status == stati.committed:
                        eventual_status[f][anchor] = stati.committed
                    if (
                        this_status == stati.nacked
                        and eventual_status[f][anchor] != stati.committed
                    ):
                        eventual_status[f][anchor] = stati.nacked
                    if this_status == stati.pending and (
                        eventual_status[f][anchor]
                        not in {stati.committed, stati.nacked}
                    ):
                        eventual_status[f][anchor] = stati.pending
        persona_ids = {e['submitted_by'] for e in history.values()}
        persona_ids |= {e['reviewed_by'] for e in history.values() if e['reviewed_by']}
        personas = self.coreproxy.get_personas(rs, persona_ids)
        return self.render(
            rs,
            "show_history",
            {
                'entries': history,
                'constants': constants,
                'current': current,
                'pending': pending,
                'eventual_status': eventual_status,
                'personas': personas,
                'ADMIN_KEYS': ADMIN_KEYS,
                'inconsistencies': inconsistencies or [],
                'committed': committed,
            },
        )

    @access("core_admin", "meta_admin")
    @REQUESTdata("phrase", "include_archived")
    def admin_show_user(
        self, rs: RequestState, phrase: str, include_archived: bool
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
        key = "username,family_name,given_names,legal_given_names,nickname"
        spec = scope.get_spec()
        spec[key] = QuerySpecEntry("str", "")
        query = Query(
            scope=scope,
            spec=spec,
            fields_of_interest=(
                "personas.id",
                "family_name",
                "given_names",
                "nickname",
                "username",
            ),
            constraints=[(key, QueryOperators.match, t) for t in terms],
            order=(("personas.id", True),),
        )
        result = self.coreproxy.submit_general_query(rs, query)
        if len(result) == 1:
            return self.redirect_show_user(rs, result[0][query.scope.get_primary_key()])

        # Precise search didn't uniquely match, hence a fulltext search now. Results
        # will be a superset of the above, since all relevant fields are in fulltext.
        query.constraints = [('fulltext', QueryOperators.containsall, terms)]
        result = self.coreproxy.submit_general_query(rs, query)
        if len(result) == 1:
            return self.redirect_show_user(rs, result[0][query.scope.get_primary_key()])
        elif not self.is_admin(rs):
            # Shortcircuit for meta admins
            rs.notify("warning", n_("Multiple accounts found."))
            return self.index(rs)
        elif result:
            params = query.serialize_to_url()
            rs.values.update(params)
            return self.user_search(rs, is_search=True, download=None, query=query)
        else:
            rs.notify("warning", n_("No account found."))
            return self.index(rs)

    @access("persona")
    @REQUESTdata("phrase", "kind", "aux")
    def select_persona(
        self, rs: RequestState, phrase: str, kind: str, aux: Optional[vtypes.ID]
    ) -> Response:
        """Provide data for intelligent input fields.

        This searches for users by name so they can be easily selected
        without entering their numerical ids. This is for example
        intended for addition of orgas to events.

        The kind parameter specifies the purpose of the query which decides
        the privilege level required and the basic search paramaters.

        Allowed kinds:

        - ``admin_persona``: Search for users as (core|cde|complaint|meta|ml)_admin
            or auditor. Allows search by username.
        - ``admin_all_users``: Search for users as (core|complaint|ml)_admin but
            including archived users. Allows search by username.
        - ``cde_user``: Search for a cde user as cde_admin or auditor.
            Allows search by username.
        - ``past_event_user``: Search for an event user to add to a past event as
            cde_admin or auditor.
        - ``pure_assembly_user``: Search for an assembly only user as assembly_admin or
            presider. Needed for external_signup.
        - ``assembly_user``: Search for an assembly user as assembly_admin or presider or auditor.
        - ``ml_user``: Search for a mailinglist user as ml_admin or moderator
        - ``pure_ml_user``: Search for an assembly only user as ml_admin.
            Needed for the account merger. Allows seach by username.
        - ``ml_subscriber``: Search for a mailinglist user for subscription purposes.
            Needed for add_subscriber action only.
        - ``event_user``: Search an event user as event_admin or orga or auditor.
            Allows search by username.

        The aux parameter allows to supply an additional id for example
        in the case of a moderator this would be the relevant mailinglist id.

        Required aux value based on the 'kind':

        * ``ml_subscriber``: ID of the mailinglist for context.
        """
        if rs.has_validation_errors():
            return self.send_json(rs, {})

        constraints = []
        search_additions = []
        scope = QueryScope.core_user
        mailinglist = None
        len_preview = (
            self.conf["NUM_PREVIEW_PERSONAS_PRIVILEGED"]
            if {"core_admin"} & rs.user.roles
            else self.conf["NUM_PREVIEW_PERSONAS"]
        )
        if kind == "admin_persona":
            if not (
                {"core_admin", "cde_admin", "complaint_admin", "ml_admin", "meta_admin",
                 "auditor"}
                & rs.user.roles
            ):  # fmt: skip
                raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
            search_additions.append("username")
        elif kind == "admin_all_users":
            if not {"core_admin", "ml_admin", "complaint_admin"} & rs.user.roles:
                raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
            search_additions.append("username")
            scope = QueryScope.all_core_users
        elif kind == "cde_user":
            if not {"cde_admin", "auditor"} & rs.user.roles:
                raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
            search_additions.append("username")
            constraints.append(("is_cde_realm", QueryOperators.equal, True))
        elif kind == "past_event_user":
            if not {"cde_admin", "auditor"} & rs.user.roles:
                raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
            # adding archived users to past events is a common task
            scope = QueryScope.all_core_users
            constraints.append(("is_event_realm", QueryOperators.equal, True))
        elif kind == "pure_assembly_user":
            # No check by assembly, as this behaves identical for each assembly.
            if not rs.user.presider and "assembly_admin" not in rs.user.roles:
                raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
            constraints.append(("is_assembly_realm", QueryOperators.equal, True))
            constraints.append(("is_member", QueryOperators.equal, False))
        elif kind == "assembly_user":
            # No check by assembly, as this behaves identical for each assembly.
            if not (rs.user.presider or {"assembly_admin", "auditor"} & rs.user.roles):
                raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
            constraints.append(("is_assembly_realm", QueryOperators.equal, True))
        elif kind == "event_user":
            # No check by event, as this behaves identical for each event.
            # TODO How to migrate this to EventPrivileges?
            # Maybe add generic realm_roles any_orga, any_caretaker?
            if not (
                rs.user.orga
                or rs.user.caretaker
                or {"event_admin", "auditor"} & rs.user.roles
            ):
                raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
            constraints.append(("is_event_realm", QueryOperators.equal, True))
        elif kind == "ml_user":
            relevant_admin_roles = {
                "core_admin",
                "cde_admin",
                "event_admin",
                "auditor",
                "assembly_admin",
                "cdelokal_admin",
                "ml_admin",
            }
            # No check by mailinglist, as this behaves identical for each list.
            if not (rs.user.moderator or relevant_admin_roles & rs.user.roles):
                raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
            constraints.append(("is_ml_realm", QueryOperators.equal, True))
        elif kind == "pure_ml_user":
            if "ml_admin" not in rs.user.roles:
                raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
            search_additions.append("username")
            constraints.extend((
                ("is_ml_realm", QueryOperators.equal, True),
                ("is_assembly_realm", QueryOperators.equal, False),
                ("is_event_realm", QueryOperators.equal, False),
            ))
        elif kind == "ml_subscriber":
            msg = n_("Must provide id of the associated mailinglist to use this kind.")
            if aux is None:
                raise werkzeug.exceptions.BadRequest(msg)
            # In this case, the return value depends on the respective mailinglist.
            mailinglist = self.mlproxy.get_mailinglist(rs, aux)
            if not self.mlproxy.may_manage(rs, aux, allow_restricted=False):
                raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
            search_additions.append("username")
            constraints.append(("is_ml_realm", QueryOperators.equal, True))
        else:
            return self.send_json(rs, {})

        data: Optional[tuple[CdEDBObject, ...]] = None

        # Allow admins to search by (CdEDB)ID
        if ALL_ADMINS & rs.user.roles:
            anid: Optional[vtypes.ID]
            anid, errs = inspect(vtypes.CdedbID, phrase, argname="phrase")
            if not errs:
                assert anid is not None
                tmp = self.coreproxy.get_persona(rs, anid)
                if tmp:
                    data = (tmp.as_dict(),)
            else:
                anid, errs = inspect(vtypes.ID, phrase, argname="phrase")
                if not errs:
                    assert anid is not None
                    tmp = self.coreproxy.get_persona(rs, anid)
                    if tmp:
                        data = (tmp.as_dict(),)

        # Don't query, if search phrase is too short
        if not data and len(phrase) < self.conf["NUM_PREVIEW_CHARS"]:
            return self.send_json(rs, {})

        terms: tuple[str, ...] = tuple()
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
                search_constraints: list[tuple[str, QueryOperators, Any]]
                # Don't search for username by default.
                search_fields = [
                    "family_name",
                    "given_names",
                    "nickname",
                ] + search_additions
                search_key = ",".join(search_fields)
                search_constraints = [
                    (search_key, QueryOperators.match, t) for t in terms
                ]
                search_constraints.extend(constraints)
                spec = scope.get_spec()
                spec[search_key] = QuerySpecEntry("str", "")
                # Don't always select username.
                fields_of_interest = [
                    "personas.id",
                    "family_name",
                    "given_names",
                    "nickname",
                ] + search_additions
                query = Query(
                    scope,
                    spec,
                    fields_of_interest,
                    search_constraints,
                    (("personas.id", True),),
                )
                data = self.coreproxy.submit_select_persona_query(rs, query)

        # Filter result to get only users allowed to be a subscriber of a list,
        # which potentially are no subscriber yet.
        if mailinglist:
            data = self.mlproxy.filter_personas_by_policy(
                rs, mailinglist, data, SubscriptionPolicy.addable_policies()
            )

        # Strip data to contain at maximum `num_preview_personas` results
        if len(data) > len_preview:
            data = tuple(
                xsorted(data, key=lambda e: e[scope.get_primary_key()])[:len_preview]
            )

        for entry in data:
            if 'id' not in entry:
                entry['id'] = entry[scope.get_primary_key()]

        # Generate return JSON list
        ret = []
        for entry in xsorted(data, key=EntitySorter.persona):
            name = make_persona_name(entry, include_nickname=True)
            result = {
                'id': entry['id'],
                'name': name,
            }
            if 'username' in entry:
                result['email'] = entry['username']
            ret.append(result)
        return self.send_json(rs, {'personas': ret})

    def _changeable_persona_fields(
        self, rs: RequestState, user: User, restricted: bool = True
    ) -> set[str]:
        """Helper to retrieve the appropriate fields for (admin_)change_user.

        :param restricted: If True, only return fields the user may change
            themselves, i.e. remove the restricted fields.
        """
        assert user.persona_id is not None
        ret: set[str] = set()
        # some fields are of no interest here.
        hidden_fields = set(PERSONA_STATUS_FIELDS) | {"id", "username"}
        hidden_cde_fields = (
            hidden_fields
            | {
                "balance",
                "bub_search",
                "decided_search",
                "foto",
                "trial_member",
                "honorary_member",
            }
        ) - {"is_searchable"}
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
            rs, [user.persona_id], active=True
        ):
            ret.remove("donation")

        # hide the member search toggles if no cde realm
        for key in ret & {"show_legal_given_names", "show_address", "show_address2"}:
            if "cde" not in user.roles:
                ret.remove(key)

        restricted_fields = {"notes", "birthday", "is_searchable"}
        if restricted:
            ret -= restricted_fields

        return ret

    @access("persona")
    def change_user_form(self, rs: RequestState) -> Response:
        """Render form."""
        assert rs.user.persona_id is not None
        generation = self.coreproxy.changelog_get_generation(rs, rs.user.persona_id)
        data = unwrap(
            self.coreproxy.changelog_get_history(rs, rs.user.persona_id, (generation,))
        )
        if data['code'] == const.PersonaChangeStati.pending:
            rs.notify("info", n_("Change pending."))
        del data['change_note']
        shown_fields = self._changeable_persona_fields(rs, rs.user, restricted=True)

        min_donation = self.conf["MINIMAL_LASTSCHRIFT_DONATION"]
        max_donation = self.conf["MAXIMAL_LASTSCHRIFT_DONATION"]
        has_special_donation = (
            "donation" in shown_fields
            and not min_donation <= data["donation"] <= max_donation
        )

        merge_dicts(rs.values, data)
        mandatory_fields = (
            get_mandatory_form_fields(PERSONA_COMMON_FIELDS)
            | {'address', 'location'}  # we enforce this by hand in change_user
        )
        return self.render(
            rs,
            "change_user",
            {
                'username': data['username'],
                'shown_fields': shown_fields,
                'min_donation': min_donation,
                'max_donation': max_donation,
                'has_special_donation': has_special_donation,
            },
            mandatory_fields,
        )

    @access("persona", modi={"POST"})
    @REQUESTdata("generation")
    def change_user(self, rs: RequestState, generation: int) -> Response:
        """Change own data set."""
        assert rs.user.persona_id is not None
        attributes = self._changeable_persona_fields(rs, rs.user, restricted=True)
        data = request_dict_extractor(rs, attributes)
        data['id'] = rs.user.persona_id
        data = check(rs, vtypes.Persona, data, "persona")
        if not data:
            rs.ignore_validation_errors()
            return self.change_user_form(rs)
        # take special care for annual donations in combination with lastschrift
        if "donation" in data and (
            lastschrift_ids := self.cdeproxy.list_lastschrift(
                rs, [rs.user.persona_id], active=True
            )
        ):
            current = self.coreproxy.get_cde_user(rs, rs.user.persona_id)
            min_donation = self.conf["MINIMAL_LASTSCHRIFT_DONATION"]
            max_donation = self.conf["MAXIMAL_LASTSCHRIFT_DONATION"]
            # The user may specify only donations between a specific minimal and maximal
            # value. However, admins may change this to arbitrary values, so we allow
            # to surpass the check if the user didn't change the donation's amount.
            if (
                current.donation != data["donation"]
                and not min_donation <= data["donation"] <= max_donation
            ):
                rs.append_validation_error((
                    "donation",
                    ValueError(
                        n_("Lastschrift donation must be between %(min)s and %(max)s."),
                        {
                            "min": money_filter(min_donation),
                            "max": money_filter(max_donation),
                        },
                    ),
                ))
            lastschrift = self.cdeproxy.get_lastschrift(
                rs, unwrap(lastschrift_ids.keys())
            )
            # "Enforce" consent of the account holder if the user changed his donation.
            if (
                current.donation != data["donation"]
                and lastschrift["account_owner"]
                and not rs.ignore_warnings
            ):
                msg = n_(
                    "You are not the owner of the linked bank account. Make sure"
                    " the owner agreed to the change before submitting it here."
                )
                rs.append_validation_error(("donation", ValidationWarning(msg)))
        # Gender and primary address may not be unset
        if data.get('gender') == const.Genders.not_specified:
            rs.append_validation_error(('gender', ValueError(n_("Must not be empty."))))
        e = ValueError(n_("Specifying an address is mandatory."))
        for address_row in ('address', 'location'):
            if address_row in data.keys():
                if not data[address_row]:
                    rs.append_validation_error((address_row, e))
        if rs.has_validation_errors():
            return self.change_user_form(rs)
        change_note = "Normale Änderung."
        code = self.coreproxy.change_persona(
            rs, data, generation=generation, change_note=change_note
        )
        rs.notify_return_code(code)
        return self.redirect_show_user(rs, rs.user.persona_id)

    @access("core_admin")
    @REQUESTdata("download", "is_search")
    def user_search(
        self,
        rs: RequestState,
        download: Optional[str],
        is_search: bool,
        query: Optional[Query] = None,
    ) -> Response:
        """Perform search."""
        events = self.pasteventproxy.list_past_events(rs)
        choices: dict[str, dict[Any, str]] = {
            'pevent_id': collections.OrderedDict(
                xsorted(events.items(), key=operator.itemgetter(1))
            ),
            'gender': collections.OrderedDict(
                enum_entries_filter(
                    const.Genders,
                    rs.gettext if download is None else rs.default_gettext,
                )
            ),
            'country': collections.OrderedDict(get_localized_country_codes(rs)),
        }
        if query and query.scope == QueryScope.core_user:
            query.constraints.append(("is_archived", QueryOperators.equal, False))
            query.scope = QueryScope.all_core_users
        return self.generic_user_search(
            rs,
            download,
            is_search,
            QueryScope.all_core_users,
            self.coreproxy.submit_general_query,
            choices=choices,
            query=query,
        )

    @access("core_admin")
    def create_user_form(self, rs: RequestState) -> Response:
        realms = USER_REALM_NAMES.copy()
        if self.conf["CDEDB_OFFLINE_DEPLOYMENT"]:
            del realms["assembly"]
            del realms["ml"]
        return self.render(
            rs,
            "create_user",
            {'realms': realms},
            get_mandatory_form_fields(self.create_user),
        )

    @access("core_admin")
    @REQUESTdata("realm")
    def create_user(self, rs: RequestState, realm: str) -> Response:
        if realm not in USER_REALM_NAMES.keys():
            rs.append_validation_error(("realm", ValueError(n_("No valid realm."))))
        if rs.has_validation_errors():
            return self.create_user_form(rs)
        return self.redirect(rs, realm + "/create_user")

    @staticmethod
    def admin_bits(rs: RequestState) -> set[Realm]:
        """Determine realms this admin can see.

        This is somewhat involved due to realm inheritance.
        """
        ret = {"persona"}
        if "core_admin" in rs.user.roles:
            ret |= REALM_INHERITANCE.keys()
        for realm in REALM_INHERITANCE:
            if f"{realm}_admin" in rs.user.roles:
                ret |= {realm} | implied_realms(realm)
        return ret

    @access(*REALM_ADMINS)
    def admin_change_user_form(self, rs: RequestState, persona_id: int) -> Response:
        """Render form."""
        if not self.coreproxy.is_relative_admin(rs, persona_id):
            raise werkzeug.exceptions.Forbidden(n_("Not a relative admin."))
        if rs.ambience['persona'].is_archived:
            rs.notify("error", n_("Persona is archived."))
            return self.redirect_show_user(rs, persona_id)

        generation = self.coreproxy.changelog_get_generation(rs, persona_id)
        data = unwrap(
            self.coreproxy.changelog_get_history(rs, persona_id, (generation,))
        )
        del data['change_note']
        merge_dicts(rs.values, data)

        if data['code'] == const.PersonaChangeStati.pending:
            rs.notify("info", n_("Change pending."))
        status = self.coreproxy.get_persona_status(rs, rs.ambience['persona'].id)
        roles = extract_roles(status.as_dict(), introspection_only=True)
        user = User(persona_id=persona_id, roles=roles)
        shown_fields = self._changeable_persona_fields(rs, user, restricted=False)
        return self.render(
            rs,
            "admin_change_user",
            {
                'admin_bits': self.admin_bits(rs),
                'shown_fields': shown_fields,
                # We have users with an unknown birthday (this shouldn't
                # be a blocker for admins to edit those users at all) and want to
                # be able to correct wrong birthdays into missing ones.
            },
            get_mandatory_form_fields(PERSONA_COMMON_FIELDS) - {'birthday'},
        )

    @access(*REALM_ADMINS, modi={"POST"})
    @REQUESTdata("generation", "change_note")
    def admin_change_user(
        self,
        rs: RequestState,
        persona_id: int,
        generation: int,
        change_note: Optional[str],
    ) -> Response:
        """Privileged edit of data set."""
        if not self.coreproxy.is_relative_admin(rs, persona_id):
            raise werkzeug.exceptions.Forbidden(n_("Not a relative admin."))
        # Assure we don't accidently change the original.
        status = self.coreproxy.get_persona_status(rs, rs.ambience['persona'].id)
        roles = extract_roles(status.as_dict(), introspection_only=True)
        user = User(persona_id=persona_id, roles=roles)
        attributes = self._changeable_persona_fields(rs, user, restricted=False)
        data = request_dict_extractor(rs, attributes)
        data['id'] = persona_id
        data = check(rs, vtypes.Persona, data)
        # take special care for annual donations in combination with lastschrift
        if (
            data
            and "donation" in data
            and self.cdeproxy.list_lastschrift(rs, [persona_id], active=True)
        ):
            min_donation = self.conf["MINIMAL_LASTSCHRIFT_DONATION"]
            max_donation = self.conf["MAXIMAL_LASTSCHRIFT_DONATION"]
            # The user may specify only donations between a specific minimal and maximal
            # value. However, admins may change this to arbitrary values.
            if (
                not min_donation <= data["donation"] <= max_donation
                and not rs.ignore_warnings
            ):
                rs.append_validation_error((
                    "donation",
                    ValidationWarning(
                        n_(
                            "Lastschrift donation is outside of %(min)s and %(max)s."
                            " The user will not be able to change this amount by himself."
                        ),
                        {
                            "min": money_filter(min_donation),
                            "max": money_filter(max_donation),
                        },
                    ),
                ))
        if rs.has_validation_errors():
            return self.admin_change_user_form(rs, persona_id)
        assert data is not None
        code = self.coreproxy.change_persona(
            rs, data, generation=generation, change_note=change_note
        )
        rs.notify_return_code(code)
        return self.redirect_show_user(rs, persona_id)

    @access("persona")
    def view_admins(self, rs: RequestState) -> Response:
        """Render list of all admins of the users realms."""

        admin_ids = {
            # meta admins
            "meta": self.coreproxy.list_admins(rs, "meta"),
            "core": self.coreproxy.list_admins(rs, "core"),
            "complaint": self.coreproxy.list_admins(rs, "complaint"),
        }

        display_realms = rs.user.roles.intersection(REALM_INHERITANCE)
        if "cde" in display_realms:
            display_realms.add("finance")
            display_realms.add("auditor")
        if "ml" in display_realms:
            display_realms.add("cdelokal")
        for realm in display_realms:
            admin_ids[realm] = self.coreproxy.list_admins(rs, realm)

        persona_ids = set(itertools.chain.from_iterable(admin_ids.values()))
        personas = self.coreproxy.get_personas(rs, persona_ids)

        admins = {
            role: [user for user in personas.values() if user.id in set(users)]
            for role, users in admin_ids.items()
        }

        return self.render(rs, "view_admins", {"admins": admins})

    @access("core_admin", "ml_admin")
    @REQUESTdata("address", "notes")
    def email_status_overview(
        self,
        rs: RequestState,
        address: Optional[vtypes.Email] = None,
        notes: Optional[str] = None,
    ) -> Response:
        """Present overview.

        Take arguments to prefill the input mask.
        """
        if rs.has_validation_errors():
            rs.values['address'] = None
            rs.values['notes'] = None
        email_reports = self.coreproxy.get_email_reports(rs)
        persona_ids = set().union(*(e.persona_ids for e in email_reports.values()))
        personas = self.coreproxy.get_personas(rs, persona_ids)
        ml_ids = set().union(*(e.ml_ids for e in email_reports.values()))
        mls = self.mlproxy.get_mailinglists(rs, ml_ids)
        grouped_reports: dict[const.EmailStatus, dict[str, Any]] = (
            collections.defaultdict(dict)
        )
        for email, infos in email_reports.items():
            if infos.status in const.EmailStatus.notable_states():
                grouped_reports[infos.status][email] = infos
        mandatory_fields = get_mandatory_form_fields(self.set_email_status)
        return self.render(
            rs,
            "email_status_overview",
            {'grouped_reports': grouped_reports, 'personas': personas, 'mls': mls},
            mandatory_fields,
        )

    @access("core_admin", "ml_admin", modi={"POST"})
    @REQUESTdata("address", "notes", "status")
    def set_email_status(
        self,
        rs: RequestState,
        address: vtypes.Email,
        status: const.EmailStatus,
        notes: Optional[str],
    ) -> Response:
        """Insert or update the status of an email address."""
        if rs.has_validation_errors():
            return self.email_status_overview(rs)
        code = self.coreproxy.mark_email_status(rs, address, status, notes)
        rs.notify_return_code(code)
        return self.redirect(rs, "core/email_status_overview")

    @access("core_admin", "ml_admin", modi={"POST"})
    @REQUESTdata("address")
    def delete_email_status(self, rs: RequestState, address: vtypes.Email) -> Response:
        """Remove the status entry of an email address."""
        if rs.has_validation_errors():
            return self.email_status_overview(rs)
        code = self.coreproxy.remove_email_status(rs, address)
        rs.notify_return_code(code)
        return self.redirect(rs, "core/email_status_overview")

    @access("persona")
    @REQUESTdata("to")
    def contact_form(self, rs: RequestState, to: Optional[str] = None) -> Response:
        """Render form."""
        # The requestparam of "to" is only for prefilling. This automatically only
        #  works with valid recipients, so no need to test validity here.
        rs.ignore_validation_errors()
        addresses = self.conf["CONTACT_ADDRESSES"]
        return self.render(
            rs,
            "contact",
            {"addresses": addresses},
            get_mandatory_form_fields(self.contact),
        )

    @access("persona", modi={"POST"})
    @REQUESTdata("to", "anonymous", "subject", "msg")
    def contact(
        self, rs: RequestState, to: str, anonymous: str, subject: str, msg: str
    ) -> Response:
        """Send a possibly anonymous message."""
        if to is not None and to not in self.conf["CONTACT_ADDRESSES"]:
            rs.append_validation_error(("to", ValueError(n_("Invalid choice."))))
        anonymous_from = False
        if anonymous is not None:
            if anonymous == "yes":
                anonymous_from = True
            elif anonymous == "no":
                anonymous_from = False
            else:
                rs.append_validation_error((
                    "anonymous",
                    ValueError(n_("Invalid choice.")),
                ))
        if rs.has_validation_errors():
            return self.contact_form(rs)
        assert rs.user.persona_id is not None and rs.user.username is not None

        if anonymous_from:
            message, key = models.AnonymousMessageData.encrypt(
                recipient=to,
                persona_id=vtypes.ID(rs.user.persona_id),
                username=vtypes.Email(rs.user.username),
                subject=subject,
            )
            if not self.coreproxy.log_anonymous_message(rs, message):
                rs.notify("error", "Something went wrong.")
                return self.contact_form(rs)

            secret = message.format_secret(key)
            del key

            self.do_mail(
                rs,
                "contact_anonymous",
                {
                    'To': (to,),
                    'Subject': subject,
                    'From': self.conf["NOREPLY_SENDER"],
                    'Reply-To': self.conf["NOREPLY_SENDER"],
                },
                {
                    'message_text': msg,
                    'message': message,
                    'secret': secret,
                },
                suppress_subject_logging=True,
            )
        else:
            name = rs.user.persona_name()
            noreply = self.conf["NOREPLY_ADDRESS"]
            self.do_mail(
                rs,
                "contact",
                {
                    'To': (to,),
                    'Subject': subject,
                    'From': f"{name} via Kontaktformular <{noreply}>",
                    'Reply-To': rs.user.username,
                },
                {
                    'message': msg,
                    'name': name,
                },
            )
        self.do_mail(
            rs,
            "contact_receipt",
            {
                'To': (rs.user.username,),
                'Subject': "Deine Nachricht ist angekommen.",
                'From': self.conf["NOREPLY_SENDER"],
                'Reply-To': self.conf["NOREPLY_SENDER"],
            },
            {
                'message': msg,
                'subject': subject,
                'to': to,
                'anonymous': anonymous_from,
            },
            suppress_recipient_logging=anonymous_from,
        )

        rs.notify("success", n_("Message sent!"))
        return self.redirect(rs, "core/index")

    @access("persona")
    @REQUESTdata("secret")
    def contact_reply_form(
        self, rs: RequestState, secret: Optional[vtypes.Base64] = None
    ) -> Response:
        """Render the reply form. Takes a message id via GET to prefill the form."""
        rs.ignore_validation_errors()
        return self.render(
            rs,
            "contact_reply",
            mandatory_fields=get_mandatory_form_fields(self.contact_reply),
        )

    @access("persona", modi={"POST"})
    @REQUESTdata("secret", "reply_message")
    def contact_reply(
        self, rs: RequestState, secret: vtypes.Base64, reply_message: str
    ) -> Response:
        """Send a reply by retrieving and decrypting the stored metadata."""
        if rs.has_validation_errors():
            return self.render(rs, "contact_reply")
        try:
            message_id, key = models.AnonymousMessageData.parse_secret(secret)
            message = self.coreproxy.get_anonymous_message(rs, message_id)
            anonymous_message = self.coreproxy.get_anonymous_message(rs, message_id)
            message.decrypt(key)
            del secret
            del message_id
            del key
        except ValueError:
            rs.append_validation_error(("secret", ValueError(n_("Wrong format."))))
        except KeyError:
            rs.append_validation_error(("secret", KeyError(n_("Invalid secret."))))
        except CryptographyError:
            if 'message' in locals():
                # noinspection PyUnboundLocalVariable
                self.logger.error(
                    f"User {rs.user.persona_id} tried to decrypt anonymous message"
                    f" ({message.id}) with an incorrect decryption key."
                )
            rs.append_validation_error(("secret", RuntimeError(n_("Invalid secret."))))
        else:
            # Can't have validation errors in the else branch.
            rs.ignore_validation_errors()
            assert message.persona_id and message.username and message.subject
            persona = self.coreproxy.get_persona(rs, message.persona_id)
            original_subject = message.subject

            self.do_mail(
                rs,
                "contact_reply",
                {
                    'To': {persona.username, message.username},
                    'From': message.recipient,
                    'Reply-To': self.conf["NOREPLY_SENDER"],
                    'Subject': f"Re: {original_subject}",
                },
                {
                    'persona': persona,
                    'reply_message': reply_message,
                    'original_subject': original_subject,
                    'original_recipient': message.recipient,
                    'ctime': message.ctime,
                },
                suppress_recipient_logging=True,
                suppress_subject_logging=True,
            )
            del message
            del persona

            self.do_mail(
                rs,
                "contact_reply_receipt",
                {
                    'To': (anonymous_message.recipient,),
                    'From': f"{rs.user.persona_name()} via <{anonymous_message.recipient}>",
                    'Reply-To': anonymous_message.recipient,
                    'Subject': "Nachricht beantwortet.",
                },
                {
                    'reply_message': reply_message,
                    'anonymous_message': anonymous_message,
                    'original_subject': original_subject,
                },
            )
            rs.notify("success", n_("Reply sent."))
            self.coreproxy.log_contact_reply(rs, anonymous_message.recipient)
            return self.redirect(rs, "core/index")
        rs.ignore_validation_errors()
        return self.render(rs, "contact_reply")

    @access("persona")
    @REQUESTdata("secret")
    def rotate_anonymous_message(
        self, rs: RequestState, secret: vtypes.Base64
    ) -> Response:
        """Change message id and encryption key for a stored message.

        Note that this is uses GET, even though it changes state.
        """
        if rs.has_validation_errors():
            rs.notify("error", n_("Invalid secret."))
            return self.redirect(rs, "core/index")
        try:
            message_id, key = models.AnonymousMessageData.parse_secret(secret)
            message = self.coreproxy.get_anonymous_message(rs, message_id)
            message.decrypt(key)
            del secret
            del message_id
            del key
        except (ValueError, KeyError, CryptographyError):
            if 'message' in locals():
                # noinspection PyUnboundLocalVariable
                self.logger.error(
                    f"User {rs.user.persona_id} tried to rotate anonymous message"
                    f" ({message.id}) with an incorrect decryption key."
                )
            rs.notify("error", n_("Invalid secret."))
            return self.redirect(rs, "core/index")

        new_key = message.rotate()

        if self.coreproxy.rotate_anonymous_message(rs, message):
            new_secret = message.format_secret(new_key)
            original_subject = message.subject
            anonymous_message = self.coreproxy.get_anonymous_message(
                rs, message.message_id
            )
            del new_key
            del message

            self.do_mail(
                rs,
                "contact_rotate",
                {
                    'To': (anonymous_message.recipient,),
                    'Subject': "Anonyme Nachricht neu verschlüsselt",
                    'From': self.conf["NOREPLY_SENDER"],
                    'Reply-To': self.conf["NOREPLY_SENDER"],
                },
                {
                    'new_secret': new_secret,
                    'anonymous_message': anonymous_message,
                    'original_subject': original_subject,
                },
            )
            rs.notify(
                "success", n_("Encryption has been updated. New secret has been sent.")
            )
        else:
            rs.notify("error", n_("Something went wrong."))
        return self.redirect(rs, "core/index")

    @access("meta_admin")
    def change_privileges_form(self, rs: RequestState, persona_id: int) -> Response:
        """Render form."""
        if rs.ambience['persona'].is_archived:
            rs.notify("error", n_("Persona is archived."))
            return self.redirect_show_user(rs, persona_id)

        stati = (const.PrivilegeChangeStati.pending,)
        change_ids = self.coreproxy.list_privilege_changes(rs, persona_id, stati)
        if change_ids:
            rs.notify("error", n_("Resolve pending privilege change first."))
            change_id = unwrap(change_ids.keys())
            return self.redirect(
                rs, "core/show_privilege_change", {"change_id": change_id}
            )

        status = self.coreproxy.get_persona_status(rs, rs.ambience['persona'].id)
        merge_dicts(rs.values, status.as_dict())
        return self.render(
            rs,
            "change_privileges",
            {},
            get_mandatory_form_fields(self.change_privileges),
        )

    @access("meta_admin", modi={"POST"})
    @REQUESTdata(*ADMIN_KEYS, "notes")
    def change_privileges(
        self,
        rs: RequestState,
        persona_id: int,
        is_meta_admin: bool,
        is_core_admin: bool,
        is_cde_admin: bool,
        is_finance_admin: bool,
        is_event_admin: bool,
        is_ml_admin: bool,
        is_assembly_admin: bool,
        is_cdelokal_admin: bool,
        is_complaint_admin: bool,
        is_auditor: bool,
        notes: str,
    ) -> Response:
        """Grant or revoke admin bits."""
        if rs.has_validation_errors():
            return self.change_privileges_form(rs, persona_id)

        stati = (const.PrivilegeChangeStati.pending,)
        change_ids = self.coreproxy.list_privilege_changes(rs, persona_id, stati)
        if change_ids:
            rs.notify("error", n_("Resolve pending privilege change first."))
            change_id = unwrap(change_ids.keys())
            return self.redirect(
                rs, "core/show_privilege_change", {"change_id": change_id}
            )

        reason_map = {
            "is_cde_realm": rs.gettext("non-cde user"),
            "is_event_realm": rs.gettext("non-event user"),
            "is_ml_realm": rs.gettext("non-ml user"),
            "is_assembly_realm": rs.gettext("non-assembly user"),
            "is_cde_admin": rs.gettext("non-cde admin"),
        }
        persona = self.coreproxy.get_persona_status(rs, persona_id).as_dict()
        data = {
            "persona_id": persona_id,
            "notes": notes,
        }
        for admin, required in ADMIN_KEYS.items():
            if locals()[admin] != persona[admin]:
                data[admin] = locals()[admin]
            if data.get(admin):
                err = (
                    admin,
                    ValueError(
                        n_("Cannot grant this privilege to %(reason)s."),
                        {"reason": reason_map.get(required, n_("this user"))},
                    ),
                )
                if data.get(required) is False:
                    rs.append_validation_error(err)
                if not persona[required] and not data.get(required):
                    rs.append_validation_error(err)

        if "is_meta_admin" in data and data["persona_id"] == rs.user.persona_id:
            rs.append_validation_error((
                "is_meta_admin",
                ValueError(n_("Cannot modify own meta admin privileges.")),
            ))

        if rs.has_validation_errors():
            return self.change_privileges_form(rs, persona_id)

        if ADMIN_KEYS & data.keys():
            code = self.coreproxy.initialize_privilege_change(rs, data)
            rs.notify_return_code(
                code,
                success=n_(
                    "Privilege change waiting for approval by another meta admin."
                ),
            )
            if not code:
                return self.change_privileges_form(rs, persona_id)
        else:
            rs.notify("info", n_("No changes were made."))
        return self.redirect_show_user(rs, persona_id)

    @access("meta_admin")
    def list_privilege_changes(self, rs: RequestState) -> Response:
        """Show list of privilege changes pending review."""
        change_ids = self.coreproxy.list_privilege_changes(
            rs, stati=(const.PrivilegeChangeStati.pending,)
        )

        changes = self.coreproxy.get_privilege_changes(rs, change_ids)
        changes = {e["persona_id"]: e for e in changes.values()}

        personas = self.coreproxy.get_personas(rs, changes.keys())
        sorted_changes = {
            persona.id: changes[persona.id] for persona in personas.values()
        }

        return self.render(
            rs,
            "list_privilege_changes",
            {"changes": sorted_changes, "personas": personas},
        )

    @access("meta_admin")
    def show_privilege_change(self, rs: RequestState, change_id: int) -> Response:
        """Show detailed infromation about pending privilege change."""
        change = rs.ambience['privilege_change']
        if change["status"] != const.PrivilegeChangeStati.pending:
            rs.notify("info", n_("Privilege change not pending."))
        elif (
            change["is_meta_admin"] is not None
            and change["persona_id"] == rs.user.persona_id
        ):
            rs.notify(
                "info",
                n_(
                    "This privilege change is affecting your meta admin"
                    " privileges, so it has to be approved by another"
                    " meta admin."
                ),
            )
        elif change["submitted_by"] == rs.user.persona_id:
            rs.notify(
                "info",
                n_(
                    "This privilege change was submitted by you, so it "
                    "has to be approved by another meta admin."
                ),
            )

        persona_ids = {change["persona_id"], change["submitted_by"]}
        if reviewer_id := change["reviewer"]:
            persona_ids.add(reviewer_id)
        personas = self.coreproxy.get_personas(rs, persona_ids)

        return self.render(
            rs,
            "show_privilege_change",
            {
                "persona": personas[change["persona_id"]],
                "submitter": personas[change["submitted_by"]],
                "reviewer": personas[reviewer_id] if reviewer_id else None,
                "admin_keys": ADMIN_KEYS,
            },
        )

    @access("meta_admin", modi={"POST"})
    @REQUESTdata("ack")
    def decide_privilege_change(
        self, rs: RequestState, change_id: int, ack: bool
    ) -> Response:
        """Approve or reject a privilege change."""
        if rs.has_validation_errors():
            return self.redirect(rs, 'core/show_privilege_change')
        change = rs.ambience['privilege_change']
        if change["status"] != const.PrivilegeChangeStati.pending:
            rs.notify("error", n_("Privilege change not pending."))
            return self.redirect(rs, "core/list_privilege_changes")
        if not ack:
            change_status = const.PrivilegeChangeStati.rejected
        else:
            change_status = const.PrivilegeChangeStati.approved
            if (
                change["is_meta_admin"] is not None
                and change['persona_id'] == rs.user.persona_id
            ):
                raise werkzeug.exceptions.Forbidden(
                    n_("Cannot modify own meta admin privileges.")
                )
            if rs.user.persona_id == change["submitted_by"]:
                raise werkzeug.exceptions.Forbidden(
                    n_(
                        "Only a different admin than the submitter"
                        " may approve a privilege change."
                    )
                )
        code = self.coreproxy.finalize_privilege_change(rs, change_id, change_status)
        success = n_("Change committed.") if ack else n_("Change rejected.")
        info = n_("Password reset issued for new admin.")
        rs.notify_return_code(code, success=success, info=info)
        if not code:
            return self.show_privilege_change(rs, change_id)
        else:
            persona = self.coreproxy.get_persona(rs, change['persona_id'])
            params = {}
            if code < 0:
                # The code is negative, the user's password needs to be changed.
                # We didn't actually issue the success message above.
                rs.notify("success", success)
                params["reset_link"] = self._password_reset_link(
                    rs, change["persona_id"]
                )
            if change_status == const.PrivilegeChangeStati.approved:
                headers: Headers = {
                    "To": {persona.username},
                    "Subject": "Admin-Privilegien geändert",
                }
                self.do_mail(rs, "privilege_change_finalized", headers, params)
                submitter = self.coreproxy.get_persona(rs, change["submitted_by"])
                to = {"vorstand@cde-ev.de", self.conf["META_ADMIN_ADDRESS"]}
                gained_privileges = [
                    privilege
                    for privilege in ADMIN_KEYS
                    if rs.ambience['privilege_change'].get(privilege) is True
                ]
                lost_privileges = [
                    privilege
                    for privilege in ADMIN_KEYS
                    if rs.ambience['privilege_change'].get(privilege) is False
                ]
                self.do_mail(
                    rs,
                    "privilege_change_notification",
                    {'To': to, 'Subject': "Adminrolle geändert"},
                    {
                        "persona": persona,
                        "submitter": submitter,
                        "gained": gained_privileges,
                        "lost": lost_privileges,
                    },
                )
        return self.redirect(rs, "core/list_privilege_changes")

    @periodic("privilege_change_remind", period=24)
    def privilege_change_remind(
        self, rs: RequestState, store: CdEDBObject
    ) -> CdEDBObject:
        """Cron job for privilege changes to review.

        Send a reminder after four hours and then daily.
        """
        current = now()
        ids = self.coreproxy.list_privilege_changes(
            rs, stati=(const.PrivilegeChangeStati.pending,)
        )
        data = self.coreproxy.get_privilege_changes(rs, ids)
        old = set(store.get('ids', [])) & set(data)
        new = set(data) - set(old)
        remind = False
        if any(
            data[anid]['ctime'] + datetime.timedelta(hours=4) < current for anid in new
        ):
            remind = True
        if old and current.timestamp() > store.get('tstamp', 0) + 24 * 60 * 60:
            remind = True
        if remind:
            notify = (self.conf["META_ADMIN_ADDRESS"],)
            self.do_mail(
                rs,
                "privilege_change_remind",
                {
                    'To': tuple(notify),
                    'Subject': "Offene Änderungen von Admin-Privilegien",
                },
                {'count': len(data)},
            )
            store = {
                'tstamp': current.timestamp(),
                'ids': list(data),
            }
        return store

    @access("core_admin")
    @REQUESTdata("target_realm")
    def promote_user_form(
        self,
        rs: RequestState,
        persona_id: int,
        target_realm: Optional[vtypes.Realm],
        internal: bool = False,
    ) -> Response:
        """Render form.

        This has two parts. If the target realm is absent, we let the
        admin choose one. If it is present we present a mask to promote
        the user.

        The internal flag is used if the call comes from another frontend
        function to disable further redirection on validation errors.
        """
        if rs.has_validation_errors() and not internal:
            return self.redirect_show_user(rs, persona_id)
        if rs.ambience['persona'].is_archived:
            rs.notify("error", n_("Persona is archived."))
            return self.redirect_show_user(rs, persona_id)
        merge_dicts(rs.values, rs.ambience['persona'].as_dict())
        if target_realm and getattr(rs.ambience['persona'], f'is_{target_realm}_realm'):
            rs.notify("warning", n_("No promotion necessary."))
            return self.redirect_show_user(rs, persona_id)
        pevent_ids = self.pasteventproxy.list_past_events(rs)
        pevents = self.pasteventproxy.get_past_events(rs, pevent_ids)
        pcourses = {}
        if pevent_id := rs.values.get('pevent_id'):
            pcourse_ids = self.pasteventproxy.list_past_courses(rs, pevent_id)
            pcourses = self.pasteventproxy.get_past_courses(rs, pcourse_ids)
        all_pcourse_ids = self.pasteventproxy.list_past_courses(rs)
        all_pcourses = self.pasteventproxy.get_past_courses(rs, all_pcourse_ids)

        mandatory_fields = get_mandatory_form_fields(
            CDE_TRANSITION_FIELDS, self.promote_user
        )
        return self.render(
            rs,
            "promote_user",
            {
                "pevent_entries": models_past_event.PastEvent.get_entries(pevents),
                "pcourse_entries": models_past_event.PastCourse.get_entries(pcourses),
                "pcourse_entries_by_event": models_past_event.PastCourse.get_combined_entries(
                    all_pcourses
                ),
            },
            mandatory_fields,
        )

    @access("core_admin", modi={"POST"})
    @REQUESTdatadict(*CDE_TRANSITION_FIELDS)
    @REQUESTdata(
        "target_realm",
        "change_note",
        "pevent_id",
        "is_orga",
        "is_instructor",
        "pcourse_id",
        "prev_pevent_id",
    )
    def promote_user(
        self,
        rs: RequestState,
        persona_id: int,
        change_note: str,
        target_realm: vtypes.Realm,
        pevent_id: int | None,
        is_orga: bool,
        is_instructor: bool,
        prev_pevent_id: int | None,
        pcourse_id: int | None,
        data: CdEDBObject,
    ) -> Response:
        """Add a new realm to the users ."""
        for key in tuple(k for k in data.keys() if not data[k]):
            # remove irrelevant keys, due to the possible combinations it is
            # rather lengthy to specify the exact set of them
            del data[key]
        persona = self.coreproxy.get_total_persona(rs, persona_id)
        # Specific fixes by target realm
        if target_realm == "cde":
            reference = {**CDE_TRANSITION_FIELDS}
            persona.update({
                'trial_member': False,
                'honorary_member': False,
                'decided_search': False,
                'bub_search': False,
                'paper_expuls': True,
                'donation': decimal.Decimal(0),
            })
        elif target_realm == "event":
            reference = {**EVENT_TRANSITION_FIELDS}
        else:
            reference = {}
        merge_dicts(data, persona)
        for key in tuple(data.keys()):
            if key not in reference and key != 'id':
                del data[key]
        # trial membership implies membership
        if data.get("trial_member"):
            data["is_member"] = True
        data[f'is_{target_realm}_realm'] = True
        for realm in implied_realms(target_realm):
            data[f'is_{realm}_realm'] = True
        data = check(rs, vtypes.Persona, data, transition=True)
        if rs.has_validation_errors():
            return self.promote_user_form(
                rs, persona_id, target_realm=target_realm, internal=True
            )
        if pevent_id is not None and pevent_id != prev_pevent_id:
            # Show the form again, if past event changed.
            #  This is suppressed by in the js variant.
            return self.promote_user_form(
                rs, persona_id, target_realm=target_realm, internal=True
            )
        assert data is not None
        code = self.coreproxy.change_persona_realms(rs, data, change_note)
        rs.notify_return_code(code)
        if code > 0 and target_realm == "cde":
            if pevent_id:
                orga_status = const.PastOrgaKind.none
                if is_orga:
                    orga_status = const.PastOrgaKind.orga
                self.pasteventproxy.set_participant(
                    rs, pevent_id, persona_id, orga_status=orga_status
                )
            if pcourse_id:
                instructor_status = const.PastInstructorKind.none
                if is_instructor:
                    instructor_status = const.PastInstructorKind.kl
                self.pasteventproxy.set_course_assignments(
                    rs, pcourse_id, persona_id, instructor_status=instructor_status
                )
            self.send_welcome_mail(
                rs,
                self.coreproxy.get_persona(rs, persona_id),
                self.coreproxy.get_persona_status(rs, persona_id),
                is_trial_member=data.get("trial_member", False),
            )
        return self.redirect_show_user(rs, persona_id)

    @access("cde_admin")
    def modify_membership_form(self, rs: RequestState, persona_id: int) -> Response:
        """Render form."""
        if rs.ambience['persona'].is_archived:
            rs.notify("error", n_("Persona is archived."))
            return self.redirect_show_user(rs, persona_id)
        persona = self.coreproxy.get_cde_user(rs, persona_id)
        return self.render(rs, "modify_membership", {'persona': persona})

    @access("cde_admin", modi={"POST"})
    @REQUESTdata("is_member", "trial_member", "honorary_member", _omit_missing=True)
    def modify_membership(
        self,
        rs: RequestState,
        persona_id: int,
        is_member: Optional[bool] = None,
        trial_member: Optional[bool] = None,
        honorary_member: Optional[bool] = None,
    ) -> Response:
        """Change association status.

        This is CdE-functionality so we require a cde_admin instead of a
        core_admin.
        """
        if is_member is False:
            trial_member = honorary_member = False
        if trial_member or honorary_member:
            is_member = True
        rs.ignore_validation_errors()
        # We really don't want to go halfway here.
        with TransactionObserver(rs, self, "modify_membership"):
            code, revoked_permit, collateral_transaction = (
                self.cdeproxy.change_membership(
                    rs,
                    persona_id,
                    is_member=is_member,
                    trial_member=trial_member,
                    honorary_member=honorary_member,
                )
            )
            rs.notify_return_code(code)
            if revoked_permit:
                rs.notify("success", n_("Revoked active permit."))
            if collateral_transaction:
                transaction = self.cdeproxy.get_lastschrift_transaction(
                    rs, collateral_transaction
                )
                subject = "Einzugsermächtigung zu ausstehender Lastschrift widerrufen."
                self.do_mail(
                    rs,
                    "pending_lastschrift_revoked",
                    {'To': (self.conf["MANAGEMENT_ADDRESS"],), 'Subject': subject},
                    {
                        'persona_id': persona_id,
                        'payment_date': transaction['payment_date'],
                    },
                )

        return self.redirect_show_user(rs, persona_id)

    @access("finance_admin")
    def modify_balance_form(self, rs: RequestState, persona_id: int) -> Response:
        """Serve form to manually modify a personas balance."""
        if rs.ambience['persona'].is_archived:
            rs.notify("error", n_("Persona is archived."))
            return self.redirect_show_user(rs, persona_id)
        persona = self.coreproxy.get_cde_user(rs, persona_id)
        old_balance = persona.balance
        trial_member = persona.trial_member
        return self.render(
            rs,
            "modify_balance",
            {'old_balance': old_balance, 'trial_member': trial_member},
            get_mandatory_form_fields(self.modify_balance),
        )

    @access("finance_admin", modi={"POST"})
    @REQUESTdata("new_balance", "change_note")
    def modify_balance(
        self,
        rs: RequestState,
        persona_id: int,
        new_balance: vtypes.NonNegativeDecimal,
        change_note: str,
    ) -> Response:
        """Set the new balance."""
        if rs.has_validation_errors():
            return self.modify_balance_form(rs, persona_id)
        persona = self.coreproxy.get_cde_user(rs, persona_id)
        if persona.balance == new_balance:
            rs.notify("info", n_("Nothing changed."))
            return self.redirect(rs, "core/modify_balance_form")
        if rs.ambience['persona'].is_archived:
            rs.notify("error", n_("Persona is archived."))
            return self.redirect_show_user(rs, persona_id)
        code = self.coreproxy.change_persona_balance(
            rs,
            persona_id,
            new_balance,
            const.FinanceLogCodes.manual_balance_correction,
            change_note=change_note,
        )
        rs.notify_return_code(code)
        return self.redirect_show_user(rs, persona_id)

    @access("anonymous")
    def get_foto(self, rs: RequestState, foto: vtypes.Identifier) -> Response:
        """Retrieve profile picture."""
        mimetype = self.coreproxy.get_foto_store(rs).get_mime_type(foto)
        if mimetype is None:
            self.logger.warning(f"Tried to access nonexistent foto {foto!r}.")
            raise werkzeug.exceptions.NotFound(n_("File does not exist."))
        path = self.coreproxy.get_foto_store(rs).get_path(foto)
        return self.send_file(rs, path=path, mimetype=mimetype)

    @access("cde")
    def set_foto_form(self, rs: RequestState, persona_id: int) -> Response:
        """Render form."""
        if rs.user.persona_id != persona_id and not self.is_admin(rs):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        if rs.ambience['persona'].is_archived:
            rs.notify("error", n_("Persona is archived."))
            return self.redirect_show_user(rs, persona_id)
        foto = self.coreproxy.get_cde_user(rs, persona_id).foto
        return self.render(rs, "set_foto", {'foto': foto})

    @access("cde", modi={"POST"})
    @REQUESTfile("foto")
    @REQUESTdata("delete")
    def set_foto(
        self,
        rs: RequestState,
        persona_id: int,
        foto: werkzeug.datastructures.FileStorage,
        delete: bool,
    ) -> Response:
        """Set profile picture."""
        if rs.user.persona_id != persona_id and not self.is_admin(rs):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        foto = check(rs, vtypes.ProfilePicture | None, foto, "foto")
        if not foto and not delete:
            rs.append_validation_error(("foto", ValueError("Must not be empty.")))
        if rs.has_validation_errors():
            return self.set_foto_form(rs, persona_id)
        new_hash = self.coreproxy.get_foto_store(rs).store(foto) if foto else None
        code = self.coreproxy.change_foto(rs, persona_id, new_hash=new_hash)
        rs.notify_return_code(
            code, success=n_("Foto updated."), info=n_("Foto removed.")
        )
        return self.redirect_show_user(rs, persona_id)

    @periodic("forget_profile_fotos", period=96)
    def forget_fotos(self, rs: RequestState, store: CdEDBObject) -> CdEDBObject:
        """Daily delete all fotos no longer referenced."""
        self.coreproxy.get_foto_store(rs).forget(rs, self.coreproxy.get_foto_usage)
        return store

    @access("core_admin", modi={"POST"})
    @REQUESTdata("confirm_username")
    def invalidate_password(
        self, rs: RequestState, persona_id: int, confirm_username: str
    ) -> Response:
        """Delete a users current password to force them to set a new one."""
        if confirm_username != rs.ambience['persona'].username:
            rs.append_validation_error((
                'confirm_username',
                ValueError(n_("Please provide the user's email address.")),
            ))
        if rs.has_validation_errors():
            return self.show_user(
                rs,
                persona_id,
                confirm_id=persona_id,
                internal=True,
                quote_me=False,
                event_id=None,
                ml_id=None,
            )
        code = self.coreproxy.invalidate_password(rs, persona_id)
        rs.notify_return_code(code, success=n_("Password invalidated."))

        if not code:  # pragma: no cover
            return self.show_user(
                rs,
                persona_id,
                confirm_id=persona_id,
                internal=True,
                quote_me=False,
                event_id=None,
                ml_id=None,
            )
        else:
            return self.redirect_show_user(rs, persona_id)

    @access("persona")
    def change_password_form(self, rs: RequestState) -> Response:
        """Render form."""
        return self.render(
            rs, "change_password", {}, get_mandatory_form_fields(self.change_password)
        )

    @access("persona", modi={"POST"})
    @REQUESTdata("old_password", "new_password", "new_password2")
    def change_password(
        self, rs: RequestState, old_password: str, new_password: str, new_password2: str
    ) -> Response:
        """Update your own password."""
        assert rs.user.persona_id is not None
        if rs.has_validation_errors():
            return self.change_password_form(rs)

        if new_password != new_password2:
            rs.extend_validation_errors((
                ("new_password", ValueError(n_("Passwords don’t match."))),
                ("new_password2", ValueError(n_("Passwords don’t match."))),
            ))
            rs.ignore_validation_errors()
            rs.notify("error", n_("Passwords don’t match."))
            return self.change_password_form(rs)

        if errs := self.coreproxy.check_password_strength(
            rs, new_password, persona_id=rs.user.persona_id
        ):
            rs.notify("error", n_("Password too weak."))
            rs.extend_validation_errors(errs)
            rs.ignore_validation_errors()
            return self.change_password_form(rs)

        try:
            code = self.coreproxy.change_password(rs, old_password, new_password)
        except ValueError as e:
            if isinstance(e, IncorrectPasswordError):
                rs.append_validation_error((
                    "old_password",
                    ValueError(n_("Wrong password.")),
                ))
                rs.ignore_validation_errors()
            self.logger.error(
                f"Unsuccessful password change for persona {rs.user.persona_id}. {e}"
            )
            rs.notify("error", *e.args)
            return self.change_password_form(rs)

        rs.notify_return_code(code, success=n_("Password changed."))
        if not code:
            self.logger.info(
                f"Unsuccessful password change for persona {rs.user.persona_id}."
            )
            return self.change_password_form(rs)
        else:
            count = self.coreproxy.logout(rs, other_sessions=True, this_session=False)
            rs.notify(
                "success", n_("%(count)s session(s) terminated."), {'count': count}
            )
            return self.redirect_show_user(rs, rs.user.persona_id)

    @access("anonymous")
    def reset_password_form(self, rs: RequestState) -> Response:
        """Render form.

        This starts the process of anonymously resetting a password.
        """
        return self.render(
            rs,
            "reset_password",
            {},
            get_mandatory_form_fields(self.send_password_reset_link),
        )

    @access("anonymous", modi={"POST"})
    @REQUESTdata("email")
    def send_password_reset_link(
        self, rs: RequestState, email: vtypes.Email
    ) -> Response:
        """Send a confirmation mail.

        To prevent an adversary from changing random passwords.
        """
        if rs.has_validation_errors():
            return self.reset_password_form(rs)

        persona_id = self.coreproxy.resolve_username(rs, email)
        if not persona_id:
            # This leaks information on valid usernames but we live with this fact in
            #  favor of a better user experience.
            rs.append_validation_error(("email", ValueError(n_("Nonexistent user."))))
            rs.ignore_validation_errors()
            # TODO: Add fail2ban for this?
            self.logger.info(
                f"Password reset requested for unknown username {email} for IP {rs.request.remote_addr}."
            )
            return self.reset_password_form(rs)

        success_msg = n_("Email sent. Please also check your spam folder.")
        try:
            reset_link = self._password_reset_link(
                rs, persona_id, self.conf["PARAMETER_TIMEOUT"]
            )
        except AdminPasswordResetError:
            self.do_mail(
                rs,
                "admin_no_reset_password",
                {'To': (email,), 'Subject': "Passwort zurücksetzen"},
            )
            self.logger.info(
                f"Sent password reset denial mail to admin {email} for IP {rs.request.remote_addr}."
            )
            # Display success notification anyway to prevent leaking admin accounts.
            rs.notify("success", success_msg)
        else:
            self.do_mail(
                rs,
                "reset_password",
                {'To': (email,), 'Subject': "Passwort zurücksetzen"},
                {"reset_link": reset_link},
            )
            # log message to be picked up by fail2ban
            self.logger.info(
                f"Sent password reset mail to {email} for IP {rs.request.remote_addr}."
            )
            rs.notify("success", success_msg)
        return self.redirect(rs, "core/index")

    @access(*REALM_ADMINS, modi={"POST"})
    def admin_send_password_reset_link(
        self, rs: RequestState, persona_id: int
    ) -> Response:
        """Generate a password reset email for an arbitrary persona.

        This is the only way to reset the password of an administrator (for
        security reasons).
        """
        if rs.has_validation_errors():
            return self.redirect_show_user(rs, persona_id)

        try:
            reset_link = self._password_reset_link(rs, persona_id)
        except AdminPasswordResetError as e:
            raise PrivilegeError(n_("Not a relative admin.")) from e

        email = rs.ambience["persona"].username
        self.do_mail(
            rs,
            "admin_reset_password",
            {'To': [email], 'Subject': "Passwort zurücksetzen"},
            {"reset_link": reset_link},
        )
        self.logger.info(
            f"Sent password reset mail to {email} for user {persona_id} by admin {rs.user.persona_id}."
        )
        rs.notify("success", n_("Email sent."))
        return self.redirect_show_user(rs, persona_id)

    @access("anonymous")
    @REQUESTdata("persona_id", "confirm")
    def do_password_reset_form(
        self, rs: RequestState, persona_id: int, confirm: str, internal: bool = False
    ) -> Response:
        """Second form.

        Pretty similar to first form, but now we know, that the account
        owner actually wants the reset.

        The internal parameter signals that the call is from another
        frontend function and not an incoming request. This prevents
        validation from changing the target again.
        """
        if rs.has_validation_errors() and not internal:
            return self.reset_password_form(rs)
        if not self._validate_password_reset_cookie(rs, persona_id, confirm):
            return self.reset_password_form(rs)
        return self.render(
            rs,
            "do_password_reset",
            {},
            get_mandatory_form_fields(self.do_password_reset),
        )

    @access("anonymous", modi={"POST"})
    @REQUESTdata("persona_id", "confirm", "new_password", "new_password2")
    def do_password_reset(
        self,
        rs: RequestState,
        persona_id: int,
        confirm: str,
        new_password: str,
        new_password2: str,
    ) -> Response:
        """Now we can reset to a new password."""
        if rs.has_validation_errors():
            return self.do_password_reset_form(rs)  # type: ignore[call-arg]
        if not self._validate_password_reset_cookie(rs, persona_id, confirm):
            return self.reset_password_form(rs)
        if self.coreproxy.is_locked_down(rs):
            rs.notify("error", n_("Lockdown active. Try again later."))
            return self.index(rs)

        if new_password != new_password2:
            msg = n_("Passwords don’t match.")
            rs.append_validation_error(("new_password", ValueError(msg)))
            rs.append_validation_error(("new_password2", ValueError(msg)))
            rs.ignore_validation_errors()
            rs.notify("error", msg)
            return self.do_password_reset_form(rs, internal=True)  # type: ignore[call-arg]

        if errs := self.coreproxy.check_password_strength(
            rs, new_password, persona_id=persona_id
        ):
            rs.notify("error", n_("Password too weak."))
            rs.extend_validation_errors(errs)
            return self.do_password_reset_form(rs, internal=True)  # type: ignore[call-arg]

        try:
            code = self.coreproxy.reset_password(
                rs, persona_id, new_password, cookie=confirm
            )
        except ValueError as e:
            rs.notify("error", *e.args)
            return self.do_password_reset_form(rs, internal=True)  # type: ignore[call-arg]
        rs.notify_return_code(code, success=n_("Password reset."))
        if not code:
            return self.do_password_reset_form(rs, internal=True)  # type: ignore[call-arg]
        else:
            return self.redirect(rs, "core/index")

    @access("persona")
    def change_username_form(self, rs: RequestState) -> Response:
        """Render form."""
        return self.render(
            rs,
            "change_username",
            {},
            get_mandatory_form_fields(self.send_username_change_link),
        )

    @access("persona")
    @REQUESTdata("new_username")
    def send_username_change_link(
        self, rs: RequestState, new_username: vtypes.Email
    ) -> Response:
        """First verify new name with test email."""
        if new_username == rs.user.username:
            rs.append_validation_error((
                "new_username",
                ValueError(n_("Must be different from current email address.")),
            ))
        if not rs.has_validation_errors() and self.coreproxy.verify_existence(
            rs, new_username
        ):
            rs.append_validation_error((
                "new_username",
                ValueError(n_("Name collision.")),
            ))
        if rs.has_validation_errors():
            return self.change_username_form(rs)
        self.do_mail(
            rs,
            "change_username",
            {'To': (new_username,), 'Subject': "Neue E-Mail-Adresse verifizieren"},
            {
                'new_username': self.encode_parameter(
                    "core/do_username_change_form",
                    "new_username",
                    new_username,
                    rs.user.persona_id,
                )
            },
        )
        self.logger.info(
            f"Sent username change mail to {new_username} for {rs.user.username}."
        )
        rs.notify("success", "Email sent.")
        return self.redirect(rs, "core/index")

    @access("persona")
    @REQUESTdata("#new_username")
    def do_username_change_form(
        self, rs: RequestState, new_username: vtypes.Email
    ) -> Response:
        """Email is now verified or we are admin."""
        if rs.has_validation_errors():
            return self.change_username_form(rs)
        rs.values['new_username'] = self.encode_parameter(
            "core/do_username_change", "new_username", new_username, rs.user.persona_id
        )
        return self.render(
            rs,
            "do_username_change",
            {'raw_email': new_username},
            get_mandatory_form_fields(self.do_username_change),
        )

    @access("persona", modi={"POST"})
    @REQUESTdata("#new_username", "password")
    def do_username_change(
        self, rs: RequestState, new_username: vtypes.Email, password: str
    ) -> Response:
        """Now we can do the actual change."""
        if rs.has_validation_errors():
            return self.change_username_form(rs)
        assert rs.user.persona_id is not None
        code, message = self.coreproxy.change_username(
            rs, rs.user.persona_id, new_username, password
        )
        rs.notify_return_code(code, success=n_("Email address changed."), error=message)
        if not code:
            return self.redirect(rs, "core/change_username_form")
        else:
            # Warn management of possible privilege escalation
            if rs.user.roles & ALL_ADMINS:
                to = (
                    self.conf["MANAGEMENT_ADDRESS"],
                    self.conf["TROUBLESHOOTING_ADDRESS"],
                )
                self.do_mail(
                    rs,
                    "admin_username_change_info",
                    {'To': to, 'Subject': "E-Mail-Adresse von Admin wurde geändert"},
                    {'new_username': new_username, 'persona': rs.user},
                )
            self.do_mail(
                rs,
                "username_change_info",
                {
                    'To': (rs.user.username,),
                    'Subject': "Deine E-Mail-Adresse wurde geändert",
                },
                {'new_username': new_username},
            )
            return self.redirect(rs, "core/index")

    @access(*REALM_ADMINS)
    def admin_username_change_form(self, rs: RequestState, persona_id: int) -> Response:
        """Render form."""
        if not self.coreproxy.is_relative_admin(rs, persona_id):
            raise werkzeug.exceptions.Forbidden(n_("Not a relative admin."))
        if rs.ambience['persona'].is_archived:
            rs.notify("error", n_("Persona is archived."))
            return self.redirect_show_user(rs, persona_id)
        return self.render(
            rs,
            "admin_username_change",
            {'data': self.coreproxy.get_persona(rs, persona_id)},
            get_mandatory_form_fields(self.admin_username_change),
        )

    @access(*REALM_ADMINS, modi={"POST"})
    @REQUESTdata("new_username")
    def admin_username_change(
        self, rs: RequestState, persona_id: int, new_username: vtypes.Email
    ) -> Response:
        """Change username without verification."""
        if not self.coreproxy.is_relative_admin(rs, persona_id):
            raise werkzeug.exceptions.Forbidden(n_("Not a relative admin."))
        if rs.has_validation_errors():
            return self.admin_username_change_form(rs, persona_id)
        code, message = self.coreproxy.change_username(
            rs, persona_id, new_username, password=None
        )
        rs.notify_return_code(code, success=n_("Email address changed."), error=message)
        if not code:
            return self.redirect(rs, "core/admin_username_change_form")
        else:
            # Warn management of possible privilege escalation
            status = self.coreproxy.get_persona_status(rs, rs.ambience['persona'].id)
            if extract_roles(status.as_dict(), introspection_only=True) & ALL_ADMINS:
                to = (
                    self.conf["MANAGEMENT_ADDRESS"],
                    self.conf["TROUBLESHOOTING_ADDRESS"],
                )
                self.do_mail(
                    rs,
                    "admin_username_change_info",
                    {'To': to, 'Subject': "E-Mail-Adresse von Admin wurde geändert"},
                    {'new_username': new_username, 'persona': rs.ambience['persona']},
                )
            return self.redirect_show_user(rs, persona_id)

    @access(*REALM_ADMINS, modi={"POST"})
    @REQUESTdata("activity")
    def toggle_activity(
        self, rs: RequestState, persona_id: int, activity: bool
    ) -> Response:
        """Enable/disable an account."""
        if not self.coreproxy.is_relative_admin(rs, persona_id):
            raise werkzeug.exceptions.Forbidden(n_("Not a relative admin."))
        if rs.has_validation_errors():
            # Redirect for encoded parameter
            return self.redirect_show_user(rs, persona_id)
        if rs.ambience['persona'].is_archived:
            rs.notify("error", n_("Persona is archived."))
            return self.redirect_show_user(rs, persona_id)
        data = {
            'id': persona_id,
            'is_active': activity,
        }
        change_note = "Aktivierungsstatus auf {activity} geändert.".format(
            activity="aktiv" if activity else "inaktiv"
        )
        code = self.coreproxy.change_persona(
            rs, data, may_wait=False, change_note=change_note
        )
        rs.notify_return_code(code)
        return self.redirect_show_user(rs, persona_id)

    @access("core_admin", "cde_admin", "event_admin")
    def list_pending_changes(self, rs: RequestState) -> Response:
        """List non-committed changelog entries."""
        pending = self.coreproxy.changelog_get_pending_changes(rs)
        return self.render(rs, "list_pending_changes", {'pending': pending})

    @periodic("pending_changelog_remind")
    def pending_changelog_remind(
        self, rs: RequestState, store: CdEDBObject
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
        if any(
            data[int(anid.split('/')[0])]['ctime'] + datetime.timedelta(hours=12)
            < current
            for anid in new
        ):
            remind = True
        if old and current.timestamp() > store.get('tstamp', 0) + 24 * 60 * 60:
            remind = True
        if remind:
            self.do_mail(
                rs,
                "changelog_requests_pending",
                {
                    'To': (self.conf["MANAGEMENT_ADDRESS"],),
                    'Subject': "Offene CdEDB Accountänderungen",
                },
                {'count': len(data)},
            )
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
        history = self.coreproxy.changelog_get_history(rs, persona_id, generations=None)
        pending = history[max(history)]
        if pending['code'] != const.PersonaChangeStati.pending:
            rs.notify("warning", n_("Persona has no pending change."))
            return self.list_pending_changes(rs)
        pending['full_name'] = make_persona_name(pending, include_nickname=True)
        current = history[
            max(
                key
                for key in history
                if (history[key]['code'] == const.PersonaChangeStati.committed)
            )
        ]
        current['full_name'] = make_persona_name(current, include_nickname=True)
        diff = {key for key in pending if current[key] != pending[key]}
        return self.render(
            rs, "inspect_change", {'pending': pending, 'current': current, 'diff': diff}
        )

    @access("core_admin", "cde_admin", "event_admin", modi={"POST"})
    @REQUESTdata("generation", "ack")
    def resolve_change(
        self, rs: RequestState, persona_id: int, generation: int, ack: bool
    ) -> Response:
        """Make decision."""
        if not self.coreproxy.is_relative_admin(rs, persona_id):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        if rs.has_validation_errors():
            return self.list_pending_changes(rs)
        code = self.coreproxy.changelog_resolve_change(rs, persona_id, generation, ack)
        message = n_("Change committed.") if ack else n_("Change dropped.")
        rs.notify_return_code(code, success=message)
        return self.redirect(rs, "core/list_pending_changes")

    @access(*REALM_ADMINS, modi={"POST"})
    @REQUESTdata("ack_delete", "note")
    def archive_persona(
        self, rs: RequestState, persona_id: int, ack_delete: bool, note: str
    ) -> Response:
        """Move a persona to the attic."""
        if not self.coreproxy.is_relative_admin(rs, persona_id):
            raise werkzeug.exceptions.Forbidden(n_("Not a relative admin."))
        if not ack_delete:
            rs.append_validation_error((
                "ack_delete",
                ValueError(n_("Must be checked.")),
            ))
        if rs.has_validation_errors():
            return self.show_user(
                rs,
                persona_id,
                confirm_id=persona_id,
                internal=True,
                quote_me=False,
                event_id=None,
                ml_id=None,
            )

        try:
            code = self.coreproxy.archive_persona(rs, persona_id, note)
        except ArchiveError as e:
            msg = e.args[0]
            args = e.args[1] if len(e.args) > 1 else {}
            rs.notify("error", msg, args)
            rs.values['ack_delete'] = False
            return self.show_user(
                rs,
                persona_id,
                confirm_id=persona_id,
                internal=True,
                quote_me=False,
                event_id=None,
                ml_id=None,
            )
        rs.notify_return_code(code)
        return self.redirect_show_user(rs, persona_id)

    @access(*REALM_ADMINS)
    def dearchive_persona_form(self, rs: RequestState, persona_id: int) -> Response:
        """Render form."""
        if not self.coreproxy.is_relative_admin(rs, persona_id):
            raise werkzeug.exceptions.Forbidden(n_("Not a relative admin."))
        return self.render(
            rs,
            "dearchive_user",
            {'data': self.coreproxy.get_persona(rs, persona_id)},
            get_mandatory_form_fields(self.dearchive_persona),
        )

    @access(*REALM_ADMINS, modi={"POST"})
    @REQUESTdata("new_username")
    def dearchive_persona(
        self, rs: RequestState, persona_id: int, new_username: vtypes.Email
    ) -> Response:
        """Reinstate a persona from the attic."""
        if not self.coreproxy.is_relative_admin(rs, persona_id):
            raise werkzeug.exceptions.Forbidden(n_("Not a relative admin."))
        if new_username and self.coreproxy.verify_existence(rs, new_username):
            rs.append_validation_error((
                "new_username",
                ValueError(n_("User with this E-Mail exists already.")),
            ))
        if rs.has_validation_errors():
            return self.dearchive_persona_form(rs, persona_id)

        code = self.coreproxy.dearchive_persona(rs, persona_id, new_username)
        rs.notify_return_code(code)
        return self.redirect_show_user(rs, persona_id)

    @access("core_admin", modi={"POST"})
    @REQUESTdata("ack_delete")
    def purge_persona(
        self, rs: RequestState, persona_id: int, ack_delete: bool
    ) -> Response:
        """Delete all identifying information for a persona."""
        if not ack_delete:
            rs.append_validation_error((
                "ack_delete",
                ValueError(n_("Must be checked.")),
            ))
        if rs.has_validation_errors():
            return self.redirect_show_user(rs, persona_id)

        code = self.coreproxy.purge_persona(rs, persona_id)
        rs.notify_return_code(code)
        return self.redirect_show_user(rs, persona_id)

    @REQUESTdata("query_name", "scope")
    @access("persona")
    def query_by_name(
        self, rs: RequestState, query_name: str, scope: QueryScope
    ) -> Response:
        if rs.has_validation_errors():  # pragma: no cover
            rs.notify("error", str(rs.retrieve_validation_errors()))
            return self.redirect(rs, "core/index")
        queries_by_name = {sq.query_name: sq for sq in DEFAULT_QUERIES.get(scope, [])}
        if query_name not in queries_by_name:
            rs.notify(
                "error",
                n_("Unknown query name: '%(query_name)s'"),
                {"query_name": query_name},
            )
            return self.redirect(rs, scope.get_target())

        return self.redirect(
            rs,
            scope.get_target(),
            queries_by_name[query_name].serialize_to_url(),
            "query-results",
        )

    @REQUESTdatadict(*ChangelogLogFilter.requestdict_fields())
    @REQUESTdata("download")
    @access("core_admin", "auditor")
    def view_changelog_meta(
        self,
        rs: RequestState,
        data: CdEDBObject,
        download: bool,
    ) -> Response:
        """View changelog activity."""
        return self.generic_view_log(
            rs,
            data,
            ChangelogLogFilter,
            self.coreproxy.retrieve_changelog_meta,
            download=download,
            template="view_changelog_meta",
        )

    @REQUESTdatadict(*CoreLogFilter.requestdict_fields())
    @REQUESTdata("download")
    @access("core_admin", "auditor")
    def view_log(self, rs: RequestState, data: CdEDBObject, download: bool) -> Response:
        """View activity."""
        return self.generic_view_log(
            rs,
            data,
            CoreLogFilter,
            self.coreproxy.retrieve_log,
            download=download,
            template="view_log",
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
        filepath = pathlib.Path(tempfile.gettempdir(), f"cdedb-mail-{token}.txt")
        try:
            rawtext = filepath.read_bytes()
        except FileNotFoundError:
            rs.notify("error", f"File {filepath.name!r} not found.")
            return self.redirect(rs, "core/index")
        emailtext = quopri.decodestring(rawtext).decode('utf-8')
        return self.render(rs, "debug_email", {'emailtext': emailtext})

    def get_cron_store(self, rs: RequestState, name: str) -> CdEDBObject:
        return self.coreproxy.get_cron_store(rs, name)

    def set_cron_store(
        self, rs: RequestState, name: str, data: CdEDBObject
    ) -> DefaultReturnCode:
        return self.coreproxy.set_cron_store(rs, name, data)

    @access("droid_resolve")
    @REQUESTdata("username")
    def api_resolve_username(
        self, rs: RequestState, username: vtypes.Email
    ) -> Response:
        """API to resolve username to that users given names and family name."""
        if rs.has_validation_errors():
            err = {'error': tuple(map(str, rs.retrieve_validation_errors()))}
            return self.send_json(rs, err)

        constraints = (
            ('username', QueryOperators.equal, username),
            ('is_event_realm', QueryOperators.equal, True),
        )
        query = Query(
            QueryScope.core_user,
            QueryScope.core_user.get_spec(),
            ("given_names", "family_name", "is_member", "username"),
            constraints,
            (('personas.id', True),),
        )
        result = self.coreproxy.submit_resolve_api_query(rs, query)
        return self.send_json(rs, unwrap(result) if result else {})
