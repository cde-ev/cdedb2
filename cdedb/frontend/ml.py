#!/usr/bin/env python3

"""Services for the ml realm."""

from werkzeug import Response

import cdedb.database.constants as const
from cdedb.common import RequestState, n_
from cdedb.frontend.common import REQUESTdata, access, mailinglist_guard
from cdedb.frontend.ml_base import MlBaseFrontend
from cdedb.frontend.ml_mailman import MailmanMixin
from cdedb.frontend.ml_rklists import RKListsMixin


class MlFrontend(RKListsMixin, MailmanMixin, MlBaseFrontend):
    @access("ml")
    @mailinglist_guard()
    def message_moderation_form(self, rs: RequestState, mailinglist_id: int
                                ) -> Response:
        """Render form."""
        dblist = rs.ambience['mailinglist']
        held = None
        if (self.conf["CDEDB_OFFLINE_DEPLOYMENT"] or (
                self.conf["CDEDB_DEV"] and not self.conf["CDEDB_TEST"])):
            self.logger.info("Skipping mailman query in dev/offline mode.")
        elif dblist['domain'] in {const.MailinglistDomain.testmail}:
            mailman = self.mailman_connect()
            mmlist = mailman.get_list(dblist['address'])
            held = mmlist.held
        return self.render(rs, "message_moderation", {'held': held})

    @access("ml", modi={"POST"})
    @mailinglist_guard()
    @REQUESTdata(("request_id", "int"), ("action", "str"))
    def message_moderation(self, rs: RequestState, mailinglist_id: int,
                           request_id: int, action: str) -> Response:
        """Moderate a held message."""
        if rs.has_validation_errors():
            return self.message_moderation_form(rs, mailinglist_id)
        dblist = rs.ambience['mailinglist']
        if (self.conf["CDEDB_OFFLINE_DEPLOYMENT"] or (
                self.conf["CDEDB_DEV"] and not self.conf["CDEDB_TEST"])):
            self.logger.info("Skipping mailman request in dev/offline mode.")
        elif dblist['domain'] in {const.MailinglistDomain.testmail}:
            mailman = self.mailman_connect()
            mmlist = mailman.get_list(dblist['address'])
            response = mmlist.moderate_message(request_id, action)
            # TODO notification depending on response
            rs.notify("success", n_("Message moderated."))
        return self.redirect(rs, "ml/message_moderation")
