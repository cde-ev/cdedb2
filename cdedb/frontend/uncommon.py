#!/usr/bin/env python3

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
        "proxy": None, ## callable
        "validator": None, ## str
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

    def redirect_realm(self, rs, persona_id, target, params=None):
        """Check that the persona is in the realm of this class. If
        not so create a redirect to the correct realm.

        This is intended to check for an id which is filled in
        automatically. Thus it is acceptable to raise an error upon
        impossible input (i.e. input which has been tampered) and not
        return a nice validation failure message.

        :type rs: :py:class:`cdedb.frontend.common.FrontendRequestState`
        :type persona_id: int
        :type target: str
        :rtype: :py:class:`werkzeug.wrappers.Response` or None

        """
        if not self.coreproxy.verify_ids(rs, (persona_id,)):
            raise werkzeug.exceptions.BadRequest("Nonexistant user.")
        realm = self.coreproxy.get_realm(rs, persona_id)
        if realm != self.realm:
            return self.redirect(rs, "{}/{}".format(realm, target), params)
        return None

    ## @access("user")
    ## @REQUESTdata(("confirm_id", "#int"))
    @abc.abstractmethod
    def show_user(self, rs, persona_id, confirm_id):
        """Display user details.

        This has an additional encoded parameter to make links to this
        target ephemeral. Thus it is more difficult to algorithmically
        extract user data from the web frontend."""
        if persona_id != confirm_id or rs.errors:
            rs.notify("error", "Link expired.")
            return self.redirect(rs, "core/index")
        if self.coreproxy.get_realm(rs, persona_id) != self.realm:
            return werkzeug.exceptions.NotFound()
        data = self.user_management['proxy'](self).get_data_single(rs,
                                                                   persona_id)
        data['db_privileges_ascii'] = ", ".join(
            bit.name for bit in const.PrivilegeBits
            if data['db_privileges'] & bit.value)
        return self.render(rs, "show_user", {'data': data})

    ## @access("user")
    ## @persona_dataset_guard()
    @abc.abstractmethod
    def change_user_form(self, rs, persona_id):
        """Render form."""
        data = self.user_management['proxy'](self).get_data_single(rs,
                                                                   persona_id)
        merge_dicts(rs.values, data)
        return self.render(rs, "change_user", {'username': data['username']})

    ## @access("user", {"POST"})
    ## @REQUESTdatadict(...)
    ## @persona_dataset_guard()
    @abc.abstractmethod
    def change_user(self, rs, persona_id, data):
        """Modify account details."""
        data = data or {}
        data['id'] = persona_id
        data = check(rs, self.user_management['validator'], data)
        if rs.errors:
            return self.change_user_form(rs, persona_id)
        num = self.user_management['proxy'](self).change_user(rs, data)
        self.notify_integer_success(rs, num)
        return self.redirect_show_user(rs, persona_id)

    ## @access("realm_admin")
    ## @persona_dataset_guard()
    @abc.abstractmethod
    def admin_change_user_form(self, rs, persona_id):
        """Render form."""
        data = self.user_management['proxy'](self).get_data_single(rs,
                                                                   persona_id)
        merge_dicts(rs.values, data)
        return self.render(rs, "admin_change_user",
                           {'username': data['username']})

    ## @access("realm_admin", {"POST"})
    ## @REQUESTdatadict(...)
    ## @persona_dataset_guard()
    @abc.abstractmethod
    def admin_change_user(self, rs, persona_id, data):
        """Modify account details by administrator."""
        data = data or {}
        data['id'] = persona_id
        data = check(rs, self.user_management['validator'], data)
        if rs.errors:
            return self.admin_change_user_form(rs, persona_id)
        num = self.user_management['proxy'](self).change_user(rs, data)
        self.notify_integer_success(rs, num)
        return self.redirect_show_user(rs, persona_id)

    ## @access("realm_admin")
    @abc.abstractmethod
    def create_user_form(self, rs):
        """Render form."""
        return self.render(rs, "create_user")

    ## @access("realm_admin", {"POST"})
    ## @REQUESTdatadict(...)
    @abc.abstractmethod
    def create_user(self, rs, data):
        """Create new user account."""
        data = check(rs, self.user_management['validator'], data,
                     initialization=True)
        if rs.errors:
            return self.create_user_form(rs)
        new_id = self.user_management['proxy'](self).create_user(rs, data)
        if new_id:
            rs.notify("success", "User created.")
            return self.redirect_show_user(rs, new_id)
        else:
            rs.notify("error", "Failed.")
            return self.create_user_form(rs)

    ## @access("anonymous")
    ## @REQUESTdata(("secret", "str"), ("username", "email"))
    @abc.abstractmethod
    def genesis_form(self, rs, case_id, secret, username):
        """Render form.

        This does not use our standard method of ephemeral links as we
        cannot expect the user to react quickly after we send out the
        email containing the approval. Hence we have to store a shared
        secret and verify this.
        """
        if rs.errors or not self.user_management['proxy'](self).genesis_check(
                rs, case_id, secret, username=username):
            rs.notify("error", "Broken link.")
            return self.redirect(rs, "core/index")
        return self.render(rs, "genesis")

    ## @access("anonymous", {"POST"})
    ## @REQUESTdata(("secret", "str"))
    ## @REQUESTdatadict(...)
    @abc.abstractmethod
    def genesis(self, rs, case_id, secret, data):
        """Create new user account."""
        if rs.errors or not self.user_management['proxy'](self).genesis_check(
                rs, case_id, secret, username=data['username']):
            rs.notify("error", "Broken link.")
            return self.redirect(rs, "core/index")
        data = check(rs, self.user_management['validator'], data,
                     initialization=True)
        if rs.errors:
            return self.genesis_form(rs, case_id, secret, data['username'])
        new_id = self.user_management['proxy'](self).genesis(rs, case_id,
                                                             secret, data)
        if new_id:
            rs.notify("success", "User created.")
            return self.redirect(rs, "core/do_password_reset_form", {
                'email': self.encode_parameter(
                    "core/do_password_reset_form", "email", data['username'])})
        else:
            rs.notify("error", "Failed.")
            return self.genesis_form(rs, case_id, secret, data['username'])
