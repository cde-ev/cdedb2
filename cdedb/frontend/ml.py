#!/usr/bin/env python3

"""Services for the ml realm."""

from cdedb.frontend.ml_mailman import MailmanMixin
from cdedb.frontend.ml_rklists import RKListsMixin


class MlFrontend(RKListsMixin, MailmanMixin):
    pass
