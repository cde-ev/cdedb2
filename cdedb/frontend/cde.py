#!/usr/bin/env python3

"""Services for the cde realm."""

import logging
from cdedb.frontend.common import AbstractFrontend, REQUESTdata, \
    REQUESTdatadict, access_decorator_generator, ProxyShim, \
    encodedparam_decorator_generator, connect_proxy
from cdedb.frontend.common import check_validation as check

access = access_decorator_generator(
        ("anonymous", "persona", "user", "member", "searchmember",
        "cde_admin", "admin"))
encodedparam = encodedparam_decorator_generator("cde")

class CdeFrontend(AbstractFrontend):
    """This offers services to the members as well as facilities for managing
    the organization."""
    realm = "cde"
    logger = logging.getLogger(__name__)

    def __init__(self, configpath):
        super().__init__(configpath)
        self.cdeproxy = ProxyShim(connect_proxy(
            self.conf.SERVER_NAME_TEMPLATE.format("cde")))

    @classmethod
    def finalize_session(cls, sessiondata):
        return super().finalize_session(sessiondata)

    @classmethod
    def build_navigation(cls, rs):
        return super().build_navigation(rs)

    @access("user")
    def mydata(self, rs):
        """Display account details."""
        if rs.user.realm != self.realm:
            return self.redirect(rs, "{}/mydata".format(rs.user.realm))
        data = self.cdeproxy.get_data(rs, (rs.user.persona_id,))[0]
        return self.render(rs, "mydata", {'data' : data})

    @access("user")
    def change_data_form(self, rs):
        """Render form."""
        if rs.user.realm != self.realm:
            return self.redirect(rs, "{}/change_data_form".format(
                rs.user.realm))
        data = self.cdeproxy.get_data(rs, (rs.user.persona_id,))[0]
        rs.values.update(data)
        return self.render(rs, "change_data")

    @access("user", ("POST",))
    @REQUESTdatadict("display_name", "family_name", "given_names", "title",
                     "name_supplement", "telephone", "mobile",
                     "address_supplement", "address", "postal_code",
                     "location", "country", "address_supplement2", "address2",
                     "postal_code2", "location2", "country2", "weblink",
                     "specialisation", "affiliation", "timeline", "interests",
                     "free_form")
    def change_data(self, rs, data=None):
        """Modify account details."""
        # TODO add changelog functionality
        if rs.user.realm != self.realm:
            return self.redirect(rs, "{}/change_data_form".format(
                rs.user.realm))
        data = data or {}
        data['username'] = rs.user.username
        data['id'] = rs.user.persona_id
        data = check(rs, "member_data", data)
        if rs.errors:
            return self.render(rs, "change_data")
        self.cdeproxy.change_member(rs, data)
        rs.notify("success", "Change committed.")
        return self.redirect(rs, "cde/mydata")
