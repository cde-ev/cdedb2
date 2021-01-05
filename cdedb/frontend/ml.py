#!/usr/bin/env python3

"""Services for the ml realm."""

import urllib.error
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
        held = self.get_mailman().get_held_messages(rs.ambience['mailinglist'])
        return self.render(rs, "message_moderation", {'held': held})

    @access("ml", modi={"POST"})
    @mailinglist_guard()
    @REQUESTdata(("request_id", "int"), ("action", "str"))
    def message_moderation(self, rs: RequestState, mailinglist_id: int,
                           request_id: int, action: str) -> Response:
        """Moderate a held message."""
        logcode = {
            "accept": const.MlLogCodes.moderate_accept,
            "reject": const.MlLogCodes.moderate_reject,
            "discard": const.MlLogCodes.moderate_discard,
        }.get(action)
        if logcode is None:
            rs.add_validation_error(
                ("action", ValueError(n_("Invalid moderation action."))))
        if rs.has_validation_errors():
            return self.message_moderation_form(rs, mailinglist_id)
        assert logcode is not None
        dblist = rs.ambience['mailinglist']
        if (self.conf["CDEDB_OFFLINE_DEPLOYMENT"] or (
                self.conf["CDEDB_DEV"] and not self.conf["CDEDB_TEST"])):
            self.logger.info("Skipping mailman request in dev/offline mode.")
        elif dblist['domain'] in const.MailinglistDomain.mailman_domains():
            mailman = self.get_mailman()
            mmlist = mailman.get_list_safe(dblist['address'])
            if mmlist is None:
                rs.notify("error", n_("List unavailable."))
            else:
                try:
                    held = mailman.get_held_message(request_id)
                    change_note = f'{held.sender} / {held.subject}'
                    response = mmlist.moderate_message(request_id, action)
                except urllib.error.HTTPError:
                    rs.notify("error", n_("Message unavailable."))
                else:
                    if response.status // 100 == 2:
                        rs.notify("success", n_("Message moderated."))
                        self.mlproxy.log_moderation(
                            rs, logcode, mailinglist_id, change_note=change_note)
                    elif response.status // 100 == 4:
                        rs.notify("warning", n_("Message not moderated."))
                    else:
                        rs.notify("error", n_("Message not moderated."))
        return self.redirect(rs, "ml/message_moderation")
