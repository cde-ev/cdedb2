#!/usr/bin/env python3

"""Rklists interface for the database.

This utilizes a custom software for mailinglist management.
"""

from cdedb.frontend.ml_base import MlBaseFrontend


class RKListsMixin(MlBaseFrontend):
    @access("ml_script")
    def export_overview(self, rs):
        """Provide listing for mailinglist software"""
        if rs.has_validation_errors():
            return self.send_json(
                rs,
                {'error': tuple(map(str, rs.retrieve_validation_errors()))})
        return self.send_json(rs, self.mlproxy.export_overview(rs))

    @access("ml_script")
    @REQUESTdata(("address", "email"))
    def export_one(self, rs, address):
        """Provide specific infos for mailinglist software"""
        if rs.has_validation_errors():
            return self.send_json(
                rs,
                {'error': tuple(map(str, rs.retrieve_validation_errors()))})
        return self.send_json(rs, self.mlproxy.export_one(rs, address))

    @access("ml_script")
    def oldstyle_mailinglist_config_export(self, rs):
        """Provide listing for comptability mailinglist software"""
        if rs.has_validation_errors():
            return self.send_json(
                rs,
                {'error': tuple(map(str, rs.retrieve_validation_errors()))})
        return self.send_json(
            rs, self.mlproxy.oldstyle_mailinglist_config_export(rs))

    @access("ml_script")
    @REQUESTdata(("address", "email"))
    def oldstyle_mailinglist_export(self, rs, address):
        """Provide specific infos for comptability mailinglist software"""
        if rs.has_validation_errors():
            return self.send_json(
                rs,
                {'error': tuple(map(str, rs.retrieve_validation_errors()))})
        return self.send_json(rs, self.mlproxy.oldstyle_mailinglist_export(
            rs, address))

    @access("ml_script")
    @REQUESTdata(("address", "email"))
    def oldstyle_modlist_export(self, rs, address):
        """Provide specific infos for comptability mailinglist software"""
        if rs.has_validation_errors():
            return self.send_json(
                rs,
                {'error': tuple(map(str, rs.retrieve_validation_errors()))})
        return self.send_json(rs, self.mlproxy.oldstyle_modlist_export(
            rs, address))

    @access("ml_script", modi={"POST"}, check_anti_csrf=False)
    @REQUESTdata(("address", "email"), ("error", "int"))
    def oldstyle_bounce(self, rs, address, error):
        """Provide specific infos for comptability mailinglist software"""
        if rs.has_validation_errors():
            return self.send_json(
                rs,
                {'error': tuple(map(str, rs.retrieve_validation_errors()))})
        return self.send_json(rs, self.mlproxy.oldstyle_bounce(rs, address,
                                                               error))
