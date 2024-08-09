#!/usr/bin/env python3

"""
The `EventDroidMixin` subclasses the `EventBaseFrontend` and provides all the frontend
endpoints related to managing orga apitokens.
"""
from typing import Optional

from werkzeug import Response

import cdedb.common.validation.types as vtypes
from cdedb.common import CdEDBObject, RequestState, merge_dicts, n_
from cdedb.frontend.common import (
    REQUESTdatadict, access, check_validation as check, event_guard,
)
from cdedb.frontend.event import EventBaseFrontend
from cdedb.models.droid import OrgaToken


class EventDroidMixin(EventBaseFrontend):
    @access("event")
    @event_guard()
    def orga_token_summary(self, rs: RequestState, event_id: int,
                           new_token: Optional[str] = None) -> Response:
        """
        Show an overview of existing orga tokens.
        """
        rs.ignore_validation_errors()
        orga_token_ids = self.eventproxy.list_orga_tokens(rs, event_id)
        orga_tokens = self.eventproxy.get_orga_tokens(rs, orga_token_ids)

        return self.render(rs, "event/droid/summary", {
            'orga_tokens': orga_tokens, 'new_token': new_token,
        })

    @access("event")
    @event_guard()
    def create_orga_token_form(self, rs: RequestState, event_id: int) -> Response:
        """Display the form for creating a new orga token."""
        return self.render(rs, "event/droid/configure", {})

    @access("event", modi={"POST"})
    @event_guard()
    @REQUESTdatadict(*OrgaToken.requestdict_fields())
    def create_orga_token(self, rs: RequestState, event_id: int, data: CdEDBObject,
                          ) -> Response:
        """Create a new orga token. The new token will be displayed after a redirect."""
        data['id'] = -1
        data['event_id'] = event_id
        data = check(rs, vtypes.OrgaToken, data, creation=True)
        if rs.has_validation_errors() or not data:
            return self.create_orga_token_form(rs, event_id)

        new_id, secret = self.eventproxy.create_orga_token(rs, OrgaToken(**data))
        orga_token = self.eventproxy.get_orga_token(rs, new_id)
        new_token = orga_token.get_token_string(secret)
        rs.notify_return_code(new_id)

        return self.orga_token_summary(rs, event_id, new_token=new_token)

    @access("event")
    @event_guard()
    def change_orga_token_form(self, rs: RequestState, event_id: int,
                               orga_token_id: int) -> Response:
        """Display the form for changing an existing orga token."""
        merge_dicts(rs.values, rs.ambience['orga_token'].to_database())
        return self.render(rs, "event/droid/configure", {})

    @access("event", modi={"POST"})
    @event_guard()
    @REQUESTdatadict(*OrgaToken.requestdict_fields())
    def change_orga_token(self, rs: RequestState, event_id: int, orga_token_id: int,
                          data: CdEDBObject) -> Response:
        """Change an existing orga token."""
        data['id'] = orga_token_id
        # These are only needed for creation and are empty here.
        del data['event_id']
        del data['etime']
        data = check(rs, vtypes.OrgaToken, data)
        if rs.has_validation_errors() or not data:
            return self.change_orga_token_form(rs, event_id, orga_token_id)

        code = self.eventproxy.change_orga_token(rs, data)
        rs.notify_return_code(code)

        return self.redirect(rs, "event/orga_token_summary")

    @access("event", modi={"POST"})
    @event_guard()
    def delete_orga_token(self, rs: RequestState, event_id: int, orga_token_id: int,
                          ) -> Response:
        """Delete an existing orga token.

        Only available if the token has not been used.
        """
        blockers = self.eventproxy.delete_orga_token_blockers(rs, orga_token_id)
        orga_token_cascade: set[str] = set()
        if blockers.keys() - orga_token_cascade:
            rs.notify("error", n_("Cannot delete orga token after it has been used."))
            return self.redirect(rs, "event/orga_token_summary")

        code = self.eventproxy.delete_orga_token(rs, orga_token_id)
        rs.notify_return_code(code)

        return self.redirect(rs, "event/orga_token_summary")

    @access("event", modi={"POST"})
    @event_guard()
    def revoke_orga_token(self, rs: RequestState, event_id: int, orga_token_id: int,
                          ) -> Response:
        """Revoke an existing orga token, making it unusable."""
        code = self.eventproxy.revoke_orga_token(rs, orga_token_id)
        rs.notify_return_code(code)

        return self.redirect(rs, "event/orga_token_summary")
