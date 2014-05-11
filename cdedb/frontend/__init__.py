#!/usr/bin/env python3

"""The frontend is a WSGI-application split into several components (along
the realms). The database interaction via the backends is negotiated
through :py:mod:`Pyro4` RPC calls. The bigger part of the logic will be
contained in here.

All output formatting should be handled by the :py:mod:`jinja2` templates.
"""
