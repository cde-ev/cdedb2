import asyncio
import sys

from twisted.internet import asyncioreactor

asyncioreactor.install(asyncio.get_event_loop())

import psycopg2.extras
from aiopg import Pool, create_pool
from ldaptor.interfaces import IConnectedLDAPEntry
from twisted.application import service
from twisted.internet.defer import Deferred, ensureDeferred
from twisted.internet.task import react
from twisted.python import log
from twisted.python.components import registerAdapter

from cdedb.config import Config, SecretsConfig
from cdedb.ldap.backend import LDAPsqlBackend
from cdedb.ldap.entry import RootEntry
from cdedb.ldap.server import LDAPServerFactory


def as_future(d):
    return d.asFuture(asyncio.get_event_loop())


def as_deferred(f):
    return Deferred.fromFuture(asyncio.ensure_future(f))


async def _main(reactor):
    conf = Config()
    secrets = SecretsConfig()
    pool: Pool = await as_deferred(create_pool(
        dbname=conf["CDB_DATABASE_NAME"],
        user="cdb_admin",
        password=secrets["CDB_DATABASE_ROLES"]["cdb_admin"],
        host=conf["DB_HOST"],
        port=conf["DB_PORT"],
        cursor_factory=psycopg2.extras.RealDictCursor
    ))
    port = 20389
    backend = LDAPsqlBackend(pool)
    root = RootEntry(backend=backend)
    registerAdapter(lambda x: x.root, LDAPServerFactory, IConnectedLDAPEntry)
    factory = LDAPServerFactory(root)
    factory.debug = True
    application = service.Application("ldaptor-server")
    myService = service.IServiceCollection(application)
    reactor.listenTCP(port, factory)
    await Deferred()


def main():
    return react(
        lambda reactor: ensureDeferred(
            _main(reactor)
        )
    )


if __name__ == '__main__':
    log.startLogging(sys.stderr)
    main()
