import sys

from ldaptor.interfaces import IConnectedLDAPEntry
from twisted.application import service
from twisted.internet import reactor
from twisted.python import log
from twisted.python.components import registerAdapter

from cdedb.ldap.backend import LDAPsqlBackend
from cdedb.ldap.entry import RootEntry
from cdedb.ldap.server import LDAPServerFactory

if __name__ == "__main__":
    port = 20389
    # First of all, to show logging info in stdout :
    log.startLogging(sys.stderr)
    backend = LDAPsqlBackend()
    root = RootEntry(backend=backend)
    # When the ldap protocol handle the ldap tree,
    # it retrieves it from the factory adapting
    # the factory to the IConnectedLDAPEntry interface
    # So we need to register an adapter for our factory
    # to match the IConnectedLDAPEntry
    # TODO what?
    registerAdapter(lambda x: x.root, LDAPServerFactory, IConnectedLDAPEntry)
    # Run it !!
    factory = LDAPServerFactory(root)
    factory.debug = True
    application = service.Application("ldaptor-server")
    myService = service.IServiceCollection(application)
    reactor.listenTCP(port, factory)
    reactor.run()
