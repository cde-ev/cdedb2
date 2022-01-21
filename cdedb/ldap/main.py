import sys

from ldaptor.interfaces import IConnectedLDAPEntry
from ldaptor.protocols.ldap.ldapserver import LDAPServer
from twisted.application import service
from twisted.internet import reactor
from twisted.internet.protocol import ServerFactory
from twisted.python import log
from twisted.python.components import registerAdapter

from cdedb.ldap.sql import LDAPsqlEntry

# TODO its probably easier to implement all entries using the same class. This means
#  holding also this static entries in sql. Or specialcasing this?
ORGANIZATION = {
    "dc=cde-ev,dc=de": {
        "objectClass": ["dcObject", "organization", "top"],
        "o": ["CdE e.V."],
        "description": ["French country 2 letters iso description"],
    },
}

ORGANIZATIONAL_UNIT = {
    "ou=dua": {
        "objectClass": ["organizationalUnit"],
        "o": ["Directory User Agents"]
    },
    "ou=groups": {
        "objectClass": ["organizationalUnit"],
        "o": ["Groups"]
    },
    "ou=users": {
        "objectClass": ["organizationalUnit"],
        "o": ["Users"]
    }
}

GROUP_TYPES = {
    "ou=status": {
        "objectClass": ["organizationalUnit"],
        "o": ["Status"]
    },
    "ou=ml-subscribers": {
        "objectClass": ["organizationalUnit"],
        "o": ["Mailinglists Subscribers"]
    },
    "ou=ml-moderators": {
        "objectClass": ["organizationalUnit"],
        "o": ["Mailinglists Moderators"]
    },
    "ou=event-orgas": {
        "objectClass": ["organizationalUnit"],
        "o": ["Event Orgas"]
    },
    "ou=assembly-presiders": {
        "objectClass": ["organizationalUnit"],
        "o": ["Assembly Presiders"]
    },
}


class LDAPServerFactory(ServerFactory):
    """
    Our Factory is meant to persistently store the ldap tree
    """

    protocol = LDAPServer

    def __init__(self, root):
        self.root = root

    def buildProtocol(self, addr):
        proto = self.protocol()
        proto.debug = self.debug
        proto.factory = self
        return proto


if __name__ == "__main__":
    port = 389
    # First of all, to show logging info in stdout :
    log.startLogging(sys.stderr)
    # TODO instanicate the root dn (CdE organization dn?), the rest is done recursively
    root = ...
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
