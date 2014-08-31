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
        realm = self.coreproxy.get_realm(rs, persona_id)
        if realm != self.realm:
            return self.redirect(rs, "{}/{}".format(realm, target), params)
        return None

    # @access("user")
    # @REQUESTdata(("confirm_id", "#int"))
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
        return self.render(rs, "show_user", {'data' : data})

    # @access("user")
    # @persona_dataset_guard()
    def change_user_form(self, rs, persona_id):
        """Render form."""
        data = self.user_management['proxy'](self).get_data_single(rs,
                                                                   persona_id)
        rs.values.update(data)
        return self.render(rs, "change_user")

    # @access("user", {"POST"})
    # @REQUESTdatadict(...)
    # @persona_dataset_guard()
    def change_user(self, rs, persona_id, data):
        """Modify account details."""
        data = data or {}
        data['id'] = persona_id
        data = check(rs, self.user_management['validator'], data)
        if rs.errors:
            return self.render(rs, "change_user")
        num = self.user_management['proxy'](self).change_user(rs, data)
        if num:
            rs.notify("success", "Change committed.")
        else:
            rs.notify("success", "Change failed.")
        return self.redirect(rs, "{}/show_user".format(self.realm), params={
            'confirm_id' : self.encode_parameter(
                "{}/show_user".format(self.realm), "confirm_id", persona_id)})
