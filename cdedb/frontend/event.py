#!/usr/bin/env python3

"""Services for the event realm."""

import logging
from cdedb.frontend.common import (
    REQUESTdata, REQUESTdatadict, access_decorator_generator, ProxyShim,
    connect_proxy, check_validation as check, persona_dataset_guard)
from cdedb.frontend.uncommon import AbstractUserFrontend

access = access_decorator_generator(
    ("anonymous", "persona", "user", "member", "event_admin", "admin"))

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
            user.orga = self.eventproxy.orga_info(rs, user.persona_id)
        return user

    @classmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

    @access("persona")
    def index(self, rs):
        return self.render(rs, "index")

    @access("user")
    @REQUESTdata(("confirm_id", "#int"))
    def show_user(self, rs, persona_id, confirm_id):
        return super().show_user(rs, persona_id, confirm_id)

    @access("user")
    @persona_dataset_guard()
    def change_user_form(self, rs, persona_id):
        return super().change_user_form(rs, persona_id)

    @access("user", {"POST"})
    @REQUESTdatadict("display_name", "family_name", "given_names", "title",
                     "name_supplement", "telephone", "mobile",
                     "address_supplement", "address", "postal_code", "location",
                     "country")
    @persona_dataset_guard()
    def change_user(self, rs, persona_id, data):
        return super().change_user(rs, persona_id, data)
