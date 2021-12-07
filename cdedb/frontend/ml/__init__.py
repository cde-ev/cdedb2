#!/usr/bin/env python3

"""Services for the ml realm."""

import email.parser
import urllib.error
from typing import Collection, Mapping

from werkzeug import Response

import cdedb.database.constants as const
from cdedb.common import RequestState, n_
from cdedb.frontend.common import REQUESTdata, access, mailinglist_guard
from cdedb.frontend.ml.base import MlBaseFrontend
from cdedb.frontend.ml.mailman import MlMailmanMixin

__all__ = ['MlFrontend']


class MlFrontend(MlMailmanMixin, MlBaseFrontend):
    @access("ml")
    @mailinglist_guard()
    def message_moderation_form(self, rs: RequestState, mailinglist_id: int
                                ) -> Response:
        """Render form."""
        held = self.get_mailman().get_held_messages(rs.ambience['mailinglist'])
        return self.render(rs, "message_moderation", {'held': held})

    _moderate_action_logcodes: Mapping[str, const.MlLogCodes] = {
        "whitelist": const.MlLogCodes.moderate_accept,
        "accept": const.MlLogCodes.moderate_accept,
        "reject": const.MlLogCodes.moderate_reject,
        "discard": const.MlLogCodes.moderate_discard,
    }

    def _moderate_messages(self, rs: RequestState, request_ids: Collection[int],
                           action: str) -> Response:
        """Helper to take care of the communication with mailman."""
        dblist = rs.ambience['mailinglist']
        if (self.conf["CDEDB_OFFLINE_DEPLOYMENT"] or (
                self.conf["CDEDB_DEV"] and not self.conf["CDEDB_TEST"])):
            self.logger.info("Skipping mailman request in dev/offline mode.")
            rs.notify('info', n_("Skipping mailman request in dev/offline mode."))
        else:
            mailman = self.get_mailman()
            mmlist = mailman.get_list_safe(dblist['address'])
            if mmlist is None:
                rs.notify("error", n_("List unavailable."))
                return self.redirect(rs, "ml/message_moderation")
            success = warning = error = 0
            for request_id in request_ids:
                try:
                    held = mmlist.get_held_message(request_id)
                    sender, subject, msg = held.sender, held.subject, held.msg
                    # This destroys the information we just queried.
                    response = mmlist.moderate_message(request_id, action)
                except urllib.error.HTTPError:
                    rs.notify("error", n_("Message unavailable."))
                else:
                    if response.status_code // 100 == 2:
                        success += 1
                        headers = email.parser.HeaderParser().parsestr(msg)
                        change_note = (
                            f'{sender} / {subject} / '
                            f'Spam score: {headers.get("X-Spam-Score", "—")}')
                        self.mlproxy.log_moderation(
                            rs, self._moderate_action_logcodes[action],
                            dblist['id'], change_note=change_note)
                    elif response.status_code // 100 == 4:
                        warning += 1
                    else:
                        error += 1
            if success:
                rs.notify("success", n_("%(count)s messages moderated."),
                          {"count": success})
            if warning:
                rs.notify("warning", n_("%(count)s messages not moderated."),
                          {"count": warning})
            if error:
                rs.notify("error", n_("%(count)s messages not moderated."),
                          {"count": error})

        return self.redirect(rs, "ml/message_moderation")

    @access("ml", modi={"POST"})
    @mailinglist_guard()
    @REQUESTdata("request_ids", "action")
    def message_moderation_multi(self, rs: RequestState, mailinglist_id: int,
                                 request_ids: Collection[int], action: str) -> Response:
        """Moderate multiple held messages at once.

        Valid actions are: accept and discard.
        """
        if action not in {"accept", "discard"}:
            rs.append_validation_error(
                ("action", ValueError(n_("Invalid moderation action."))))
        if rs.has_validation_errors():
            return self.message_moderation_form(rs, mailinglist_id)
        return self._moderate_messages(rs, request_ids, action)

    @access("ml", modi={"POST"})
    @mailinglist_guard()
    @REQUESTdata("request_id", "action", "sender")
    def message_moderation(self, rs: RequestState, mailinglist_id: int, request_id: int,
                           action: str, sender: str) -> Response:
        """Moderate a held message.

        Valid actions are: whitelist, accept, reject, discard
        """
        if action not in self._moderate_action_logcodes:
            rs.append_validation_error(
                ("action", ValueError(n_("Invalid moderation action."))))
        if rs.has_validation_errors():
            return self.message_moderation_form(rs, mailinglist_id)
        dblist = rs.ambience['mailinglist']

        # Add to whitelist if requested
        if action == "whitelist":
            self.mlproxy.add_whitelist_entry(rs, dblist['id'], sender)
            action = "accept"

        return self._moderate_messages(rs, [request_id], action)
