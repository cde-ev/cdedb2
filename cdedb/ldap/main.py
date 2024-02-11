"""Entrypoint for ldaptor."""

import asyncio
import logging
import os
import signal
import socket
import ssl

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from cdedb.config import Config, SecretsConfig
from cdedb.ldap.backend import LDAPsqlBackend
from cdedb.ldap.entry import RootEntry
from cdedb.ldap.server import LdapHander

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
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    if conf["CDEDB_DEV"]:
        # This is required for Apache Directory Studio to successfully connect.
        # See https://issues.apache.org/jira/browse/DIRSTUDIO-1287
        # and https://issues.apache.org/jira/browse/DIRAPI-381.
        context.maximum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(
        certfile=conf["LDAP_PEM_PATH"], keyfile=conf["LDAP_KEY_PATH"])

    # Systemd socket activation
    if "LISTEN_FDS" in os.environ:
        logging.debug("Detected socket activation")
        # Systemd passes fds from SD_LISTEN_FDS_START...SD_LISTEN_FDS_START+LISTEN_FDS,
        # SD_LISTEN_FDS_START is always 3, and we only expect one fd to be passed to us.
        # Set family and type to -1 which instructs Python to detect them from the passed fd.
        sock = socket.fromfd(3, family=-1, type=-1)
        port = None
    else:
        sock = None
        port = conf["LDAP_PORT"]

    server = await asyncio.start_server(LdapHander(root).connection_callback, port=port, sock=sock, ssl=context)
    for s in server.sockets:
        logging.info(f"Listening on {s!r}")

    def shutdown(server):
        logger.info("Shutting down")
        server.close()

    server.get_loop().add_signal_handler(signal.SIGTERM, lambda: shutdown(server))
    server.get_loop().add_signal_handler(signal.SIGINT, lambda: shutdown(server))
    logger.warning("Startup completed")

    async with server:
        try:
            await server.serve_forever()
        except asyncio.CancelledError:
            logger.info("Server shut down")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
