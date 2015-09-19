#!/usr/bin/env python3
# pylint: disable=not-callable
## self.user_management['proxy'] confuses pylint

"""More common infrastructure for the frontend services.

This provides :py:class:`AbstractUserFrontend` and should technically be
a part of :py:mod:`cdedb.frontend.common`, but then we get fatal circular
dependencies.
"""

from cdedb.common import merge_dicts
from cdedb.frontend.common import AbstractFrontend, ProxyShim, connect_proxy
from cdedb.frontend.common import check_validation as check
import cdedb.database.constants as const
import abc
import werkzeug

class AbstractUserFrontend(AbstractFrontend, metaclass=abc.ABCMeta):
    """Base class for all frontends which have their own user realm.

    This is basically every frontend with exception of 'core'.
    """
    #: Specification how user management works. To be filled by child classes.
    user_management = {
        "persona_getter": None, ## callable
    }

    def __init__(self, configpath):
        super().__init__(configpath)
        self.coreproxy = ProxyShim(connect_proxy(
            self.conf.SERVER_NAME_TEMPLATE.format("core")))

    @abc.abstractmethod
    def finalize_session(self, rs, sessiondata):
        return super().finalize_session(rs, sessiondata)

    @classmethod
    @abc.abstractmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

    ## @access("user")
    ## @REQUESTdata(("confirm_id", "#int"))
    @abc.abstractmethod
    def show_user(self, rs, persona_id, confirm_id):
        """Display user details.

        This has an additional encoded parameter to make links to this
        target ephemeral. Thus it is more difficult to algorithmically
        extract user data from the web frontend.
        """
        if persona_id != confirm_id or rs.errors:
            rs.notify("error", "Link expired.")
            return self.redirect(rs, "core/index")
        data = self.user_management['persona_getter'](self)(rs, persona_id)
        return self.render(rs, "show_user", {'data': data})

    ## @access("realm_admin")
    @abc.abstractmethod
    def admin_change_user_form(self, rs, persona_id):
        """Render form."""
        data = self.user_management['persona_getter'](self)(rs, persona_id)
        merge_dicts(rs.values, data)
        return self.render(rs, "admin_change_user",
                           {'username': data['username']})

    ## @access("realm_admin", modi={"POST"})
    ## @REQUESTdatadict(...)
    @abc.abstractmethod
    def admin_change_user(self, rs, persona_id, data):
        """Modify account details by administrator."""
        data = data or {}
        data['id'] = persona_id
        data = check(rs, "persona", data)
        if rs.errors:
            return self.admin_change_user_form(rs, persona_id)
        code = self.coreproxy.change_persona(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect_show_user(rs, persona_id)

    ## @access("realm_admin")
    @abc.abstractmethod
    def create_user_form(self, rs):
        """Render form."""
        return self.render(rs, "create_user")

    ## @access("realm_admin", modi={"POST"})
    ## @REQUESTdatadict(...)
    @abc.abstractmethod
    def create_user(self, rs, data):
        """Create new user account."""
        defaults = {
            'is_cde_realm': False,
            'is_event_realm': False,
            'is_ml_realm': False,
            'is_assembly_realm': False,
            'is_member': False,
            'is_searchable': False,
            'is_active': True,
            'cloud_account': False,
            'title': None,
            'name_supplement': None,
            'gender': None,
            'birthday': None,
            'telephone': None,
            'mobile': None,
            'address_supplement': None,
            'address': None,
            'postal_code': None,
            'location': None,
            'country': None,
            'birth_name': None,
            'address_supplement2': None,
            'address2': None,
            'postal_code2': None,
            'location2': None,
            'country2': None,
            'weblink': None,
            'specialisation': None,
            'affiliation': None,
            'timeline': None,
            'interests': None,
            'free_form': None,
            'trial_member': None,
            'decided_search': None,
            'bub_search': None,
            'foto': None,
        }
        merge_dicts(data, defaults)
        data = check(rs, "persona", data, creation=True)
        if rs.errors:
            return self.create_user_form(rs)
        new_id = self.coreproxy.create_persona(rs, data)
        self.notify_return_code(rs, new_id, success="User created.")
        if new_id:
            return self.redirect_show_user(rs, new_id)
        else:
            return self.create_user_form(rs)

    ## @access("anonymous")
    ## @REQUESTdata(("secret", "str"))
    @abc.abstractmethod
    def genesis_form(self, rs, case_id, secret):
        """Render form.

        This does not use our standard method of ephemeral links as we
        cannot expect the user to react quickly after we send out the
        email containing the approval. Hence we have to store a shared
        secret and verify this.
        """
        if rs.errors or not self.coreproxy.genesis_check(rs, case_id, secret,
                                                         self.realm):
            rs.notify("error", "Broken link.")
            return self.redirect(rs, "core/index")
        case = self.coreproxy.genesis_my_case(rs, case_id, secret)
        return self.render(rs, "genesis", {'case': case})

    ## @access("anonymous", modi={"POST"})
    ## @REQUESTdata(("secret", "str"))
    ## @REQUESTdatadict(...)
    @abc.abstractmethod
    def genesis(self, rs, case_id, secret, data):
        """Create new user account by anonymous."""
        if rs.errors:
            # FIXME this doesn't display errors
            return self.genesis_form(rs, case_id, secret=secret)
        if  not self.coreproxy.genesis_check(rs, case_id, secret, self.realm):
            rs.notify("error", "Broken link.")
            return self.redirect(rs, "core/index")
        case = self.coreproxy.genesis_my_case(rs, case_id, secret)
        for key in ("username", "given_names", "family_name"):
            data[key] = case[key]
        defaults = {
            'is_cde_realm': False,
            'is_event_realm': False,
            'is_ml_realm': False,
            'is_assembly_realm': False,
            'is_member': False,
            'is_searchable': False,
            'is_active': True,
            'cloud_account': False,
            'title': None,
            'name_supplement': None,
            'gender': None,
            'birthday': None,
            'telephone': None,
            'mobile': None,
            'address_supplement': None,
            'address': None,
            'postal_code': None,
            'location': None,
            'country': None,
            'birth_name': None,
            'address_supplement2': None,
            'address2': None,
            'postal_code2': None,
            'location2': None,
            'country2': None,
            'weblink': None,
            'specialisation': None,
            'affiliation': None,
            'timeline': None,
            'interests': None,
            'free_form': None,
            'trial_member': None,
            'decided_search': None,
            'bub_search': None,
            'foto': None,
        }
        merge_dicts(data, defaults)
        if case['realm'] == "event":
            data['is_event_realm'] = True
            data['is_ml_realm'] = True
        elif case['realm'] == "ml":
            data['is_ml_realm'] = True
        data = check(rs, "persona", data, creation=True)
        if rs.errors:
            return self.genesis_form(rs, case_id, secret=secret)
        new_id = self.coreproxy.genesis(rs, case_id, secret, case['realm'],
                                        data)
        self.notify_return_code(rs, new_id, success="User created.")
        if new_id:
            success, message = self.coreproxy.make_reset_cookie(
                rs, data['username'])
            return self.redirect(rs, "core/do_password_reset_form", {
                'email': self.encode_parameter(
                    "core/do_password_reset_form", "email", data['username']),
                'cookie': message})
        else:
            return self.genesis_form(rs, case_id, secret=secret)
