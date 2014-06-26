#!/usr/bin/env python3

"""Services for the event realm."""

import logging
from cdedb.frontend.common import AbstractUserFrontend, REQUESTdata, \
    REQUESTdatadict, access_decorator_generator, ProxyShim, \
    encodedparam_decorator_generator, connect_proxy
from cdedb.frontend.common import check_validation as check

access = access_decorator_generator(
    ("anonymous", "persona", "user", "member", "event_admin", "admin"))
encodedparam = encodedparam_decorator_generator("event")

class EventFrontend(AbstractUserFrontend):
    """This mainly allows the organization of events."""
    realm = "event"
    logger = logging.getLogger(__name__)
    user_management = {
        "proxy" : lambda obj: obj.eventproxy,
        "validator" : "event_user_data",
    }

    def __init__(self, configpath):
        super().__init__(configpath)
        self.eventproxy = ProxyShim(connect_proxy(
            self.conf.SERVER_NAME_TEMPLATE.format("event")))

    def finalize_session(self, rs, sessiondata):
        user = super().finalize_session(rs, sessiondata)
        if user.persona_id:
            user.orga = self.eventproxy.orga_info(
                rs, (user.persona_id,))[user.persona_id]
        return user

    @classmethod
    def build_navigation(cls, rs):
        return super().build_navigation(rs)

    @access("user")
    def mydata(self, rs):
        return super().mydata(rs)

    @access("user")
    def change_data_form(self, rs):
        return super().change_data_form(rs)

    @access("user", {"POST"})
    @REQUESTdatadict("display_name", "family_name", "given_names", "title",
                     "name_supplement", "telephone", "mobile",
                     "address_supplement", "address", "postal_code", "location",
                     "country")
    def change_data(self, rs, data=None):
        return super().change_data(rs, data)
