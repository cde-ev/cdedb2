#!/usr/bin/env python3

"""This specifies and implements the RPC mechanism used by the backend. We
use the :py:mod:`Pyro4` module. This depends on the syntax of
:py:class:`cdedb.backend.common.AbstractBackend` for implementation (details
see there).

.. warning:: Due to the specifics of configuring :py:mod:`Pyro4` this
  mustn't be loaded by anything other in the backend than
  :py:mod:`cdedb.backend.common` (otherwise logging may be broken).
"""

import os
import Pyro4
import cgitb
import sys
import functools
import inspect
import stat
import serpent
import logging
from cdedb.common import glue, PrivilegeError
from cdedb.backend.common import do_singularization, do_batchification
from cdedb.serialization import deserialize, SERIALIZERS

_LOGGER = logging.getLogger(__name__)

def _process_function(backend, fun):
    """Wrap a function which will be accessible via RPC with authentification
    and logging.

    :type backend: :py:class:`cdedb.backend.common.AbstractBackend`
    :type fun: callable
    :rtype: callable
    """
    _LOGGER.debug("Register {} for backend {}.".format(fun, backend))
    @functools.wraps(fun)
    def new_fun(key, *args, **kwargs):
        """
        :type key: str or None
        :param key: session key
        """
        try:
            rs = backend.establish(key, fun.__name__)
            if rs:
                ## This is for frontend -> backend.
                args = deserialize(args)
                kwargs = deserialize(kwargs)
                return fun(rs, *args, **kwargs)
            else:
                raise PrivilegeError("Establishing session failed.")
        except:
            backend.logger.error(glue(
                ">>>\n>>>\n>>>\n>>> Exception for {} of {} with arguments",
                "{} and {} and {} <<<\n<<<\n<<<\n<<<").format(
                    fun, backend, key, args, kwargs))
            backend.logger.exception("FIRST AS SIMPLE TRACEBACK")
            backend.logger.error("SECOND TRY CGITB")
            backend.logger.error(cgitb.text(sys.exc_info(), context=7))
            raise
    return new_fun

class InsulationBackendServer:
    """Helper for insulating a backend for RPC. Since :py:mod:`Pyro4`
    exports whole objects (this changed in newer versions, but we ignore
    this) we create this which only has the actual RPC-methods as
    attributes and no auxillary stuff which could otherwise leak.
    """
    def __init__(self, backend):
        """
        :type backend: :py:class:`cdedb.backend.common.AbstractBackend`
        """
        funs = inspect.getmembers(backend, predicate=inspect.isroutine)
        for name, fun in funs:
            if hasattr(fun, "access_list"):
                setattr(self, name, _process_function(backend, fun))
                if hasattr(fun, "singularization_hint"):
                    hint = fun.singularization_hint
                    setattr(self, hint['singular_function_name'],
                            _process_function(backend, do_singularization(fun)))
                    setattr(backend, hint['singular_function_name'],
                            do_singularization(fun))
                if hasattr(fun, "batchification_hint"):
                    hint = fun.batchification_hint
                    setattr(self, hint['batch_function_name'],
                            _process_function(backend, do_batchification(fun)))
                    setattr(backend, hint['batch_function_name'],
                            do_batchification(fun))


def create_RPCDaemon(backend, socket_address, access_logging=True):
    """Take care of the details for publishing a backend via :py:mod:`Pyro4`.

    :type backend: :py:class:`cdedb.backend.common.AbstractBackend`
    :type socket_address: str
    :type access_logging: bool
    """
    Pyro4.config.LOGWIRE = access_logging
    Pyro4.config.DETAILED_TRACEBACK = True
    ## Use old behaviour of exposing everything (only applicable if Pyro is
    ## new enough to have this configuration option)
    if hasattr(Pyro4.config, 'REQUIRE_EXPOSE'):
        Pyro4.config.REQUIRE_EXPOSE = False
    server = InsulationBackendServer(backend)
    daemon = Pyro4.Daemon(unixsocket=socket_address)
    ## if this is not an abstract socket
    if not socket_address.startswith("\x00"):
        os.chmod(socket_address, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)
    uri = daemon.register(server)
    ns = Pyro4.locateNS()
    ns.register(backend.conf.SERVER_NAME_TEMPLATE.format(backend.realm), uri)
    _LOGGER.info("Created pyro daemon for {} at {}.".format(backend,
                                                            socket_address))
    return daemon

## pyro uses serpent as serializers and we want some additional comfort so
## we register some additional serializers, they are reversed in
## cdedb.frontend.common.ProxyShim
##
## This is for backend -> frontend.
for clazz in SERIALIZERS:
    serpent.register_class(clazz, SERIALIZERS[clazz])
