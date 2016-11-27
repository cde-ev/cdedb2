#!/usr/bin/env python3
# pylint: disable=not-callable
## self.user_management['proxy'] confuses pylint

"""More common infrastructure for the frontend services.

This provides :py:class:`AbstractUserFrontend` and should technically be
a part of :py:mod:`cdedb.frontend.common`, but then we get fatal circular
dependencies.
"""

import abc

from cdedb.common import _, merge_dicts, ProxyShim, PERSONA_DEFAULTS
from cdedb.frontend.common import AbstractFrontend
from cdedb.frontend.common import check_validation as check
from cdedb.backend.core import CoreBackend

class AbstractUserFrontend(AbstractFrontend, metaclass=abc.ABCMeta):
    """Base class for all frontends which have their own user realm.

    This is basically every frontend with exception of 'core'.
    """
    #: Specification how user management works. To be filled by child classes.
    user_management = {
        "persona_getter": None, ## callable
    }

    def __init__(self, configpath):
        super().__init__(configpath)
        self.coreproxy = ProxyShim(CoreBackend(configpath))

    @abc.abstractmethod
    def finalize_session(self, rs, auxilliary=False):
        super().finalize_session(rs, auxilliary=auxilliary)

    @classmethod
    @abc.abstractmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

    ## @access("realm_admin")
    @abc.abstractmethod
    def create_user_form(self, rs):
        """Render form."""
        return self.render(rs, "create_user")

    ## @access("realm_admin", modi={"POST"})
    ## @REQUESTdatadict(...)
    @abc.abstractmethod
    def create_user(self, rs, data):
        """Create new user account."""
        merge_dicts(data, PERSONA_DEFAULTS)
        data = check(rs, "persona", data, creation=True)
        if rs.errors:
            return self.create_user_form(rs)
        new_id = self.coreproxy.create_persona(rs, data)
        self.do_mail(rs, "welcome",
                     {'To': (data['username'],),
                      'Subject': _('CdEDB account creation'),},
                     {'data': data})
        self.notify_return_code(rs, new_id, success=_("User created."))
        if new_id:
            return self.redirect_show_user(rs, new_id)
        else:
            return self.create_user_form(rs)

    ## @access("anonymous")
    ## @REQUESTdata(("secret", "str"))
    @abc.abstractmethod
    def genesis_form(self, rs, case_id, secret):
        """Render form.

        This does not use our standard method of ephemeral links as we
        cannot expect the user to react quickly after we send out the
        email containing the approval. Hence we have to store a shared
        secret and verify this.
        """
        if not secret or not self.coreproxy.genesis_check(rs, case_id, secret,
                                                          self.realm):
            rs.notify("error", _("Broken link."))
            return self.redirect(rs, "core/index")
        case = self.coreproxy.genesis_my_case(rs, case_id, secret)
        return self.render(rs, "genesis", {'case': case})

    ## @access("anonymous", modi={"POST"})
    ## @REQUESTdata(("secret", "str"))
    ## @REQUESTdatadict(...)
    @abc.abstractmethod
    def genesis(self, rs, case_id, secret, data):
        """Create new user account by anonymous."""
        if rs.errors:
            return self.genesis_form(rs, case_id, secret=secret)
        if  not self.coreproxy.genesis_check(rs, case_id, secret, self.realm):
            rs.notify("error", _("Broken link."))
            return self.redirect(rs, "core/index")
        case = self.coreproxy.genesis_my_case(rs, case_id, secret)
        for key in ("username", "given_names", "family_name"):
            data[key] = case[key]
        merge_dicts(data, PERSONA_DEFAULTS)
        if case['realm'] == "event":
            data['is_event_realm'] = True
            data['is_ml_realm'] = True
        elif case['realm'] == "ml":
            data['is_ml_realm'] = True
        data = check(rs, "persona", data, creation=True)
        if rs.errors:
            return self.genesis_form(rs, case_id, secret=secret)
        new_id = self.coreproxy.genesis(rs, case_id, secret, case['realm'],
                                        data)
        self.notify_return_code(rs, new_id, success=_("User created."))
        if new_id:
            success, message = self.coreproxy.make_reset_cookie(
                rs, data['username'])
            return self.redirect(rs, "core/do_password_reset_form", {
                'email': self.encode_parameter(
                    "core/do_password_reset_form", "email", data['username']),
                'cookie': message})
        else:
            return self.genesis_form(rs, case_id, secret=secret)
