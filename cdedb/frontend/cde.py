#!/usr/bin/env python3

"""Services for the cde realm."""

import logging
from cdedb.frontend.common import REQUESTdata, \
    REQUESTdatadict, access_decorator_generator, ProxyShim, \
    encodedparam_decorator_generator, connect_proxy
from cdedb.frontend.common import check_validation as check
from cdedb.frontend.uncommon import AbstractUserFrontend

access = access_decorator_generator(
    ("anonymous", "persona", "user", "member", "searchmember", "cde_admin",
     "admin"))
encodedparam = encodedparam_decorator_generator("cde")

class CdeFrontend(AbstractUserFrontend):
    """This offers services to the members as well as facilities for managing
    the organization."""
    realm = "cde"
    logger = logging.getLogger(__name__)
    user_management = {
        "proxy" : lambda obj: obj.cdeproxy,
        "validator" : "member_data",
    }

    def __init__(self, configpath):
        super().__init__(configpath)
        self.cdeproxy = ProxyShim(connect_proxy(
            self.conf.SERVER_NAME_TEMPLATE.format("cde")))
        self.eventproxy = ProxyShim(connect_proxy(
            self.conf.SERVER_NAME_TEMPLATE.format("event")))

    def finalize_session(self, rs, sessiondata):
        return super().finalize_session(rs, sessiondata)

    @classmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

    @access("persona")
    def index(self, rs):
        return self.render(rs, "index")

    @access("user")
    @REQUESTdata("confirm_id")
    @encodedparam("confirm_id")
    def show_user(self, rs, persona_id, confirm_id=None):
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
        data = self.cdeproxy.get_data(rs, (persona_id,))[persona_id]
        participation_info = self.eventproxy.participation_info(
            rs, (persona_id,))[persona_id]
        return self.render(rs, "show_user", {
            'data' : data, 'participation_info' : participation_info})

    @access("user")
    def change_user_form(self, rs, persona_id):
        return super().change_user_form(rs, persona_id)

    @access("user", {"POST"})
    @REQUESTdatadict("display_name", "family_name", "given_names", "title",
                     "name_supplement", "telephone", "mobile",
                     "address_supplement", "address", "postal_code",
                     "location", "country", "address_supplement2", "address2",
                     "postal_code2", "location2", "country2", "weblink",
                     "specialisation", "affiliation", "timeline", "interests",
                     "free_form", "bub_search")
    def change_user(self, rs, persona_id, data=None):
        # TODO add changelog functionality
        return super().change_user(rs, persona_id, data)
