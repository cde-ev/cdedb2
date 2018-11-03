#!/usr/bin/env python3
# pylint: disable=not-callable
## self.user_management['proxy'] confuses pylint

"""More common infrastructure for the frontend services.

This provides :py:class:`AbstractUserFrontend` and should technically be
a part of :py:mod:`cdedb.frontend.common`, but then we get fatal circular
dependencies.
"""

import abc

from cdedb.common import n_, merge_dicts, ProxyShim, PERSONA_DEFAULTS
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
    def finalize_session(self, rs, connpool, auxilliary=False):
        super().finalize_session(rs, connpool, auxilliary=auxilliary)

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
                      'Subject': n_('CdEDB account creation'), },
                     {'data': data})
        self.notify_return_code(rs, new_id, success=n_("User created."))
        if new_id:
            return self.redirect_show_user(rs, new_id)
        else:
            return self.create_user_form(rs)
