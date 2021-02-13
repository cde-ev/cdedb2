#!/usr/bin/env python3
# pylint: disable=not-callable

"""More common infrastructure for the frontend services.

This provides :py:class:`AbstractUserFrontend` and should technically be
a part of :py:mod:`cdedb.frontend.common`, but then we get fatal circular
dependencies.
"""

import abc

import werkzeug

from cdedb.common import PERSONA_DEFAULTS, CdEDBObject, RequestState, merge_dicts, n_
from cdedb.frontend.common import AbstractFrontend, check_validation as check
import cdedb.validationtypes as vtypes


class AbstractUserFrontend(AbstractFrontend, metaclass=abc.ABCMeta):
    """Base class for all frontends which have their own user realm.

    This is basically every frontend with exception of 'core'.
    """

    @classmethod
    @abc.abstractmethod
    def is_admin(cls, rs: RequestState) -> bool:
        return super().is_admin(rs)

    # @access("realm_admin")
    @abc.abstractmethod
    def create_user_form(self, rs: RequestState) -> werkzeug.Response:
        """Render form."""
        return self.render(rs, "create_user")

    # @access("realm_admin", modi={"POST"})
    # @REQUESTdatadict(...)
    @abc.abstractmethod
    def create_user(self, rs: RequestState, data: CdEDBObject,
                    ignore_warnings: bool = False) -> werkzeug.Response:
        """Create new user account."""
        merge_dicts(data, PERSONA_DEFAULTS)
        data = check(rs, vtypes.Persona, data,
            creation=True, _ignore_warnings=ignore_warnings)
        if data:
            exists = self.coreproxy.verify_existence(rs, data['username'])
            if exists:
                rs.extend_validation_errors(
                    (("username",
                      ValueError("User with this E-Mail exists already.")),))
        if rs.has_validation_errors() or not data:
            return self.create_user_form(rs)
        new_id = self.coreproxy.create_persona(
            rs, data, ignore_warnings=ignore_warnings)
        if new_id:
            success, message = self.coreproxy.make_reset_cookie(rs, data[
                'username'])
            email = self.encode_parameter(
                "core/do_password_reset_form", "email", data['username'],
                persona_id=None, timeout=self.conf["EMAIL_PARAMETER_TIMEOUT"])
            meta_info = self.coreproxy.get_meta_info(rs)
            self.do_mail(rs, "welcome",
                         {'To': (data['username'],),
                          'Subject': "CdEDB Account erstellt",
                          },
                         {'data': data,
                          'fee': self.conf["MEMBERSHIP_FEE"],
                          'email': email if success else "",
                          'cookie': message if success else "",
                          'meta_info': meta_info,
                          })

            self.notify_return_code(rs, new_id, success=n_("User created."))
            return self.redirect_show_user(rs, new_id)
        else:
            return self.create_user_form(rs)
