#!/usr/bin/env python3

"""Services for the assembly realm."""

from cdedb.frontend.assembly.attachment import AssemblyAttachmentMixin
from cdedb.frontend.assembly.ballot import AssemblyBallotMixin
from cdedb.frontend.assembly.base import AssemblyBaseFrontend

__all__ = ['AssemblyFrontend']


class AssemblyFrontend(AssemblyAttachmentMixin, AssemblyBallotMixin,
                       AssemblyBaseFrontend):
    pass
