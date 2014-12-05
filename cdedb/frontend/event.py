#!/usr/bin/env python3

"""Services for the event realm."""

import logging
from cdedb.frontend.common import (
    REQUESTdata, REQUESTdatadict, access, ProxyShim, connect_proxy,
    check_validation as check, persona_dataset_guard)
from cdedb.frontend.uncommon import AbstractUserFrontend
from cdedb.query import QUERY_SPECS, QueryOperators, mangle_query_input
import cdedb.database.constants as const

class EventFrontend(AbstractUserFrontend):
    """This mainly allows the organization of events."""
    realm = "event"
    logger = logging.getLogger(__name__)
    user_management = {
        "proxy": lambda obj: obj.eventproxy,
        "validator": "event_user_data",
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
        """Render start page."""
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

    @access("event_admin")
    def create_user_form(self, rs):
        """Render form."""
        return super().create_user_form(rs)

    @access("event_admin", {"POST"})
    @REQUESTdatadict(
        "title", "given_names", "family_name", "name_supplement",
        "display_name", "birthday", "gender", "telephone", "mobile",
        "address", "address_supplement", "postal_code", "location",
        "country", "notes", "username")
    def create_user(self, rs, data):
        """Create new user account."""
        data.update({
            'status': const.PersonaStati.event_user,
            'is_active': True,
            'cloud_account': False,
        })
        return super().create_user(rs, data)

    @access("anonymous")
    @REQUESTdata(("secret", "str"), ("username", "email"))
    def genesis_form(self, rs, case_id, secret, username):
        """Render form."""
        return super().genesis_form(rs, case_id, secret, username)

    @access("anonymous", {"POST"})
    @REQUESTdata(("secret", "str"))
    @REQUESTdatadict(
        "title", "given_names", "family_name", "name_supplement",
        "display_name", "birthday", "gender", "telephone", "mobile",
        "address", "address_supplement", "postal_code", "location",
        "country", "username")
    def genesis(self, rs, case_id, secret, data):
        """Create new user account."""
        data.update({
            'status': const.PersonaStati.event_user,
            'is_active': True,
            'cloud_account': False,
            'notes': '',
        })
        return super().genesis(rs, case_id, secret, data)

    @access("event_admin")
    def user_search_form(self, rs):
        """Render form."""
        spec = QUERY_SPECS['qview_event_user']
        ## mangle the input, so we can prefill the form
        mangle_query_input(rs, spec)
        events = self.eventproxy.list_events(rs)
        choices = {'event_id': events,
                   'gender': self.enum_choice(rs, const.Genders)}
        default_queries = self.conf.DEFAULT_QUERIES['qview_event_user']
        return self.render(rs, "user_search", {
            'spec': spec, 'choices': choices, 'queryops': QueryOperators,
            'default_queries': default_queries,})

    @access("event_admin")
    @REQUESTdata(("CSV", "bool"))
    def user_search(self, rs, CSV):
        """Perform search."""
        spec = QUERY_SPECS['qview_event_user']
        query = check(rs, "query_input", mangle_query_input(rs, spec), "query",
                      spec=spec, allow_empty=False)
        if rs.errors:
            return self.user_search_form(rs)
        query.scope = "qview_event_user"
        result = self.eventproxy.submit_general_query(rs, query)
        params = {'result': result, 'query': query}
        if CSV:
            data = self.fill_template(rs, 'web', 'csv_search_result', params)
            return self.send_file(rs, data=data)
        else:
            return self.render(rs, "user_search_result", params)
