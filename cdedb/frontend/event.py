#!/usr/bin/env python3

"""Services for the event realm."""

import logging
from cdedb.frontend.common import AbstractFrontend, REQUESTdata, \
    REQUESTdatadict, access_decorator_generator, ProxyShim, \
    encodedparam_decorator_generator, connect_proxy
from cdedb.frontend.common import check_validation as check

access = access_decorator_generator(
        ("anonymous", "persona", "user", "member", "event_admin", "admin"))
encodedparam = encodedparam_decorator_generator("event")

class EventFrontend(AbstractFrontend):
    """This mainly allows the organization of events."""
    realm = "event"
    logger = logging.getLogger(__name__)

    def __init__(self, configpath):
        super().__init__(configpath)
        self.eventproxy = ProxyShim(connect_proxy(
            self.conf.SERVER_NAME_TEMPLATE.format("event")))

    @classmethod
    def finalize_session(cls, sessiondata):
        # TODO add orga info to user struct
        return super().finalize_session(sessiondata)

    @classmethod
    def build_navigation(cls, rs):
        return super().build_navigation(rs)

    @access("user")
    def mydata(self, rs):
        """Display account details."""
        if rs.user.realm != self.realm:
            return self.redirect(rs, "{}/mydata".format(rs.user.realm))
        data = self.eventproxy.get_data(rs, (rs.user.persona_id,))[0]
        return self.render(rs, "mydata", {'data' : data})

    @access("user")
    def change_data_form(self, rs):
        """Render form."""
        if rs.user.realm != self.realm:
            return self.redirect(rs, "{}/change_data_form".format(
                rs.user.realm))
        data = self.eventproxy.get_data(rs, (rs.user.persona_id,))[0]
        rs.values.update(data)
        return self.render(rs, "change_data")

    @access("user", ("POST",))
    @REQUESTdatadict("display_name", "family_name", "given_names", "title",
                     "name_supplement", "telephone", "mobile",
                     "address_supplement", "address", "postal_code", "location",
                     "country")
    def change_data(self, rs, data=None):
        """Modify account details."""
        if rs.user.realm != self.realm:
            return self.redirect(rs, "{}/change_data_form".format(
                rs.user.realm))
        data = data or {}
        data['username'] = rs.user.username
        data['id'] = rs.user.persona_id
        data = check(rs, "event_user_data", data)
        if rs.errors:
            return self.render(rs, "change_data")
        self.eventproxy.change_user(rs, data)
        rs.notify("success", "Change committed.")
        return self.redirect(rs, "event/mydata")
