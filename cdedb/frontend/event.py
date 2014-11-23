#!/usr/bin/env python3

"""Services for the event realm."""

import logging
from cdedb.frontend.common import (
    REQUESTdata, REQUESTdatadict, access, ProxyShim, connect_proxy,
    check_validation as check, persona_dataset_guard)
from cdedb.frontend.uncommon import AbstractUserFrontend

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
        ret = super().finalize_session(rs, sessiondata)
        if ret.is_persona:
            ret.orga = self.eventproxy.orga_info(rs, ret.persona_id)
        return ret

    @classmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

    @access("persona")
    def index(self, rs):
        return self.render(rs, "index")

    @access("event_user")
    @REQUESTdata(("confirm_id", "#int"))
    def show_user(self, rs, persona_id, confirm_id):
        return super().show_user(rs, persona_id, confirm_id)

    @access("event_user")
    @persona_dataset_guard()
    def change_user_form(self, rs, persona_id):
        return super().change_user_form(rs, persona_id)

    @access("event_user", {"POST"})
    @REQUESTdatadict(
        "display_name", "family_name", "given_names", "title",
        "name_supplement", "telephone", "mobile", "address_supplement",
        "address", "postal_code", "location", "country")
    @persona_dataset_guard()
    def change_user(self, rs, persona_id, data):
        return super().change_user(rs, persona_id, data)

    @access("event_admin")
    @persona_dataset_guard()
    def admin_change_user_form(self, rs, persona_id):
        """Render form."""
        return super().admin_change_user_form(rs, persona_id)

    @access("event_admin", {"POST"})
    @REQUESTdatadict(
        "title", "given_names", "family_name", "name_supplement",
        "display_name", "birthday", "gender", "telephone", "mobile",
        "address", "address_supplement", "postal_code", "location",
        "country", "notes")
    @persona_dataset_guard()
    def admin_change_user(self, rs, persona_id, data):
        return super().admin_change_user(rs, persona_id, data)
