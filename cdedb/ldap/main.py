"""Entrypoint for ldaptor."""

import asyncio
import logging
import signal
import ssl

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from cdedb.config import Config, SecretsConfig
from cdedb.ldap.backend import LDAPsqlBackend
from cdedb.ldap.entry import RootEntry
from cdedb.ldap.server import LdapServer

logger = logging.getLogger(__name__)


async def main() -> None:
    conf = Config()
    secrets = SecretsConfig()

    logger.debug("Waiting for database connection ...")
    conn_params = dict(
        dbname=conf["CDB_DATABASE_NAME"],
        user="cdb_ldap",
        password=secrets["CDB_DATABASE_ROLES"]["cdb_ldap"],
        host=conf["DB_HOST"],
        port=conf["DIRECT_DB_PORT"],
    )
    conn_info = " ".join([f"{k}={v}" for k, v in conn_params.items()])
    conn_kwargs = {"row_factory": dict_row}
    pool = AsyncConnectionPool(conn_info, min_size=1, max_size=10, kwargs=conn_kwargs)
    await pool.open(wait=True)
    logger.debug("Got database connection.")
    backend = LDAPsqlBackend(pool)
    root = RootEntry(backend)

    # Create Server
    logger.info("Opening LDAP server ...")
    loop = asyncio.get_event_loop()
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    if conf["CDEDB_DEV"]:
        # This is required for Apache Directory Studio to successfully connect.
        # See https://issues.apache.org/jira/browse/DIRSTUDIO-1287
        # and https://issues.apache.org/jira/browse/DIRAPI-381.
        context.maximum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(
        certfile=conf["LDAP_PEM_PATH"], keyfile=conf["LDAP_KEY_PATH"])
    server = await loop.create_server(lambda: LdapServer(root), port=conf["LDAP_PORT"],
                                      ssl=context)
    loop.add_signal_handler(signal.SIGTERM, lambda: server.close())
    logger.warning("Startup completed")

    async with server:
        await server.serve_forever()


if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main())
