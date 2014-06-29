#!/usr/bin/env python3

"""More common infrastructure for the frontend services.

This provides :py:class:`AbstractUserFrontend` and should technically be
a part of :py:mod:`cdedb.frontend.common`, but then we get fatal circular
dependencies.
"""

from cdedb.frontend.common import AbstractFrontend, ProxyShim, connect_proxy
from cdedb.frontend.common import check_validation as check
import abc
import werkzeug

class AbstractUserFrontend(AbstractFrontend, metaclass=abc.ABCMeta):
    """Base class for all frontends which have their own user realm.

    This is basically every frontend with exception of 'core'.
    """
    #: Specification how user management works. To be filled by child classes.
    user_management = {
        "proxy" : None, # callable
        "validator" : None, # str
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
        realm = self.coreproxy.get_realms(rs, (persona_id,))[persona_id]
        if realm != self.realm:
            return self.redirect(rs, "{}/{}".format(realm, target), params)
        return None

    # @access("user")
    # @REQUESTdata("confirm_id")
    # @encodedparam("confirm_id")
    def show_user(self, rs, persona_id, confirm_id=None):
        """Display user details.

        This has an additional encoded parameter to make links to this
        target ephemeral. Thus it is more difficult to algorithmically
        extract user data from the web frontend."""
        confirm_id = check(rs, "int", confirm_id, "confirm_id")
        if persona_id != confirm_id or rs.errors:
            rs.notify("error", "Link expired.")
            return self.redirect(rs, "core/error")
        realm = self.coreproxy.get_realms(rs, (persona_id,))[persona_id]
        red = self.redirect_realm(
            rs, persona_id, "show_user", params={
                'confirm_id' : self.encode_parameter(
                    "{}/show_user".format(realm), "confirm_id", confirm_id)})
        if red:
            return red
        data = self.user_management['proxy'](self).get_data(
            rs, (persona_id,))[persona_id]
        return self.render(rs, "show_user", {'data' : data})

    # @access("user")
    def change_user_form(self, rs, persona_id):
        """Render form."""
        if persona_id != rs.user.persona_id and not self.is_admin(rs):
            return werkzeug.exceptions.Forbidden()
        if self.redirect_realm(rs, persona_id, "change_user_form"):
            return self.redirect_realm(rs, persona_id, "change_user_form")
        data = self.user_management['proxy'](self).get_data(
            rs, (persona_id,))[persona_id]
        rs.values.update(data)
        return self.render(rs, "change_user")

    # @access("user", {"POST"})
    # @REQUESTdatadict(...)
    def change_user(self, rs, persona_id, data=None):
        """Modify account details."""
        if persona_id != rs.user.persona_id and not self.is_admin(rs):
            return werkzeug.exceptions.Forbidden()
        if self.redirect_realm(rs, persona_id, "change_user_form"):
            return self.redirect_realm(rs, persona_id, "change_user_form")
        data = data or {}
        data['id'] = persona_id
        if 'username' in data:
            # changing the username is done via a special path in the core realm
            return werkzeug.exceptions.BadRequest()
        data = check(rs, self.user_management['validator'], data)
        if rs.errors:
            return self.render(rs, "change_user")
        self.user_management['proxy'](self).change_user(rs, data)
        rs.notify("success", "Change committed.")
        return self.redirect(rs, "{}/show_user".format(self.realm), params={
            'confirm_id' : self.encode_parameter(
                "{}/show_user".format(self.realm), "confirm_id", persona_id)})
