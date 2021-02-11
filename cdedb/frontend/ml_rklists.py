#!/usr/bin/env python3

"""Rklists interface for the database.

This utilizes a custom software for mailinglist management.
"""
from werkzeug import Response

import cdedb.validationtypes as vtypes
from cdedb.frontend.common import REQUESTdata, RequestState, access
from cdedb.frontend.ml_base import MlBaseFrontend


class RKListsMixin(MlBaseFrontend):
    @access("droid_rklist")
    def export_overview(self, rs: RequestState) -> Response:
        """Provide listing for mailinglist software"""
        if rs.has_validation_errors():
            return self.send_json(
                rs,
                {'error': tuple(map(str, rs.retrieve_validation_errors()))})
        return self.send_json(rs, self.mlproxy.export_overview(rs))

    @access("droid_rklist")
    @REQUESTdata("address")
    def export_one(self, rs: RequestState, address: vtypes.Email) -> Response:
        """Provide specific infos for mailinglist software"""
        if rs.has_validation_errors():
            return self.send_json(
                rs,
                {'error': tuple(map(str, rs.retrieve_validation_errors()))})
        return self.send_json(rs, self.mlproxy.export_one(rs, address))

    @access("droid_rklist")
    def oldstyle_mailinglist_config_export(self, rs: RequestState) -> Response:
        """Provide listing for comptability mailinglist software"""
        if rs.has_validation_errors():
            return self.send_json(
                rs,
                {'error': tuple(map(str, rs.retrieve_validation_errors()))})
        return self.send_json(
            rs, self.mlproxy.oldstyle_mailinglist_config_export(rs))

    @access("droid_rklist")
    @REQUESTdata("address")
    def oldstyle_mailinglist_export(self, rs: RequestState,
                                    address: vtypes.Email) -> Response:
        """Provide specific infos for comptability mailinglist software"""
        if rs.has_validation_errors():
            return self.send_json(
                rs,
                {'error': tuple(map(str, rs.retrieve_validation_errors()))})
        return self.send_json(rs, self.mlproxy.oldstyle_mailinglist_export(
            rs, address))

    @access("droid_rklist")
    @REQUESTdata("address")
    def oldstyle_modlist_export(self, rs: RequestState,
                                address: vtypes.Email) -> Response:
        """Provide specific infos for comptability mailinglist software"""
        if rs.has_validation_errors():
            return self.send_json(
                rs,
                {'error': tuple(map(str, rs.retrieve_validation_errors()))})
        return self.send_json(rs, self.mlproxy.oldstyle_modlist_export(
            rs, address))

    @access("droid_rklist", modi={"POST"})
    @REQUESTdata("address", "error")
    def oldstyle_bounce(self, rs: RequestState, address: vtypes.Email,
                        error: int) -> Response:
        """Provide specific infos for comptability mailinglist software"""
        if rs.has_validation_errors():
            err = {'error': tuple(map(str, rs.retrieve_validation_errors()))}
            return self.send_json(rs, err)
        return self.send_json(rs, self.mlproxy.oldstyle_bounce(
            rs, address, error))
