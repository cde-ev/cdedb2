#!/usr/bin/env python3

"""The core backend provides services which are common for all
users/personas independent of their realm. Thus we have no user role
since the basic division is between known accounts and anonymous
accesses.
"""

from cdedb.backend.common import AbstractBackend
from cdedb.backend.common import access_decorator_generator, \
     internal_access_decorator_generator, make_RPCDaemon, run_RPCDaemon
from cdedb.common import glue, PERSONA_DATA_FIELDS_MOD, PERSONA_DATA_FIELDS
from cdedb.backend.common import affirm_validation as affirm
from cdedb.config import Config
from cdedb.database.connection import Atomizer
import cdedb.validation as validate

from passlib.hash import sha512_crypt
import uuid
import argparse
import random
import string

access = access_decorator_generator(("anonymous", "persona", "member",
                                     "core_admin", "admin"))
internal_access = internal_access_decorator_generator(
    ("anonymous", "persona", "member", "core_admin", "admin"))


class CoreBackend(AbstractBackend):
    """Access to this is probably necessary from everywhere, so we need
    ``@internal_access`` quite often. """
    realm = "core"

    def __init__(self, configpath):
        """
        :type configpath: str
        """
        super().__init__(configpath)

    @classmethod
    def extract_roles(cls, personadata):
        ret = super().extract_roles(personadata)
        if "user" in ret:
            ret.remove("user")
        return ret

    @classmethod
    def db_role(cls, role):
        return super().db_role(role)

    @classmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

    @staticmethod
    def verify_password(password, password_hash):
        """Central function, so that the actual implementation may be easily
        changed.

        :type password: str
        :type password_hash: str
        :rtype: bool
        """
        return sha512_crypt.verify(password, password_hash)

    @staticmethod
    def encrypt_password(password):
        """We currently use passlib for password protection.

        :type password: str
        :rtype: str
        """
        return sha512_crypt.encrypt(password)

    @internal_access("persona")
    def retrieve_persona_data(self, rs, ids):
        """
        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: [{str : object}]
        """
        query = "SELECT {} FROM core.personas WHERE id = ANY(%s)".format(
            ", ".join(PERSONA_DATA_FIELDS))
        ret = self.query_all(rs, query, (ids,))
        if len(ret) != len(ids):
            self.logger.warn(
                "Wrong number of data sets found ({} instead of {}).".format(
                    len(ret), len(ids)))
        return ret

    @internal_access("persona")
    def set_complete_persona_data(self, rs, data):
        """This requires that all possible keys are present. Often you may
        want to use :py:meth:`set_persona_data` instead.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str : object}
        :rtype: int
        :returns: number of changed entries
        """
        return self.set_persona_data(rs, data, keys=PERSONA_DATA_FIELDS_MOD)

    @internal_access("persona")
    def set_persona_data(self, rs, data, keys=None):
        """Update only some keys of a data set. If ``keys`` is not passed
        all keys available in ``data`` are updated.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str : object}
        :type keys: [str]
        :rtype: int
        :returns: number of changed entries
        """
        if not keys:
            keys = tuple(key for key in data if key in PERSONA_DATA_FIELDS_MOD)
        if rs.user.persona_id != data['id'] and not self.is_admin(rs):
            raise RuntimeError("Not enough privileges.")
        privileged_fields = set(('is_active', 'status', 'db_privileges'))
        if not self.is_admin(rs) and (set(keys) & privileged_fields):
            raise RuntimeError("Modifying sensitive key forbidden.")
        query = "UPDATE core.personas SET ({}) = ({}) WHERE id = %s".format(
            ", ".join(keys), ", ".join(("%s",) * len(keys)))
        num = self.query_exec(rs, query,
                              tuple(data[key] for key in keys) + (data['id'],))
        if num != 1:
            self.logger.warn(
                "Wrong number ({}) of personas updated".format(num))
        return num

    @access("anonymous")
    def login(self, rs, username, password, ip):
        """Create a new session. This invalidates all existing sessions for this
        persona. Sessions are bound to an IP-address, for bookkeeping purposes.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type username: str
        :type password: str
        :type ip: str
        :rtype: str or None
        :returns: the session-key for the new session
        """
        username = affirm("printable_ascii", username)
        password = affirm("str", password)
        ip = affirm("printable_ascii", ip)
        ## note the lower-casing for email addresses
        query = glue("SELECT id, password_hash FROM core.personas",
                     "WHERE username = lower(%s) AND is_active = True")
        data = self.query_one(rs, query, (username,))
        if not data or \
          not self.verify_password(password, data["password_hash"]):
            ## log message to be picked up by fail2ban
            self.logger.warn("CdEDB login failure from {} for {}".format(
                ip, username))
            return None
        else:
            sessionkey = str(uuid.uuid4())
            query = glue("UPDATE core.sessions SET is_active = False",
                         "WHERE (persona_id = %s OR ip = %s)",
                         "AND is_active = True")
            query2 = glue("INSERT INTO core.sessions (persona_id, ip,",
                          "sessionkey) VALUES (%s, %s, %s)")
            with rs.conn as conn:
                with conn.cursor() as cur:
                    self.execute_db_query(cur, query, (data["id"], ip))
                    self.execute_db_query(cur, query2, (data["id"], ip,
                                                        sessionkey))
                    return sessionkey

    @access("persona")
    def logout(self, rs):
        """Invalidate the current session.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :rtype: int
        :returns: number of sessions invalidated
        """
        query = glue("UPDATE core.sessions SET is_active = False,",
                     "atime = now() AT TIME ZONE 'UTC' WHERE sessionkey = %s",
                     "AND is_active = True")
        return self.query_exec(rs, query, (rs.sessionkey,))

    @access("persona")
    def change_persona(self, rs, data):
        """Change a data set. Note that you need privileges to edit someone
        elses data set.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str : object}
        :rtype: int
        :returns: number of personas changed
        """
        data = affirm("persona_data", data)
        return self.set_persona_data(rs, data)

    @access("anonymous")
    def verify_existence(self, rs, email):
        """Check wether a certain email belongs to a persona.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type email: str
        :rtype bool:
        """
        email = affirm("email", email)
        query = "SELECT COUNT(*) AS num FROM core.personas WHERE username = %s"
        data = self.query_one(rs, query, (email,))
        return bool(data['num'])

    def modify_password(self, rs, persona_id, old_password, new_password):
        """Helper for manipulationg password entries. If ``new_password`` is
        ``None``, a new password is generated automatically; in this case
        ``old_password`` may also be ``None`` (this is a password reset).

        This escalates database connection privileges in the case of a
        password reset (which is in its nature by anonymous).

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type persona_id: int
        :type old_password: str or None
        :type new_password: str or None
        :type data: {str : object}
        :rtype: (bool, str)
        :returns: The ``bool`` indicates success and the ``str`` is
          either the new password or an error message.
        """
        query = "SELECT password_hash FROM core.personas WHERE id = %s"
        data = self.query_one(rs, query, (persona_id,))
        if not data:
            raise ValueError("No persona with id {}.".format(persona_id))
        if new_password is not None and (not self.is_admin(rs) \
                                         or persona_id == rs.user.persona_id):
            if not validate.is_password_strength(new_password):
                return False, "Password too weak."
            if not self.verify_password(old_password, data['password_hash']):
                return False, "Password verification failed."
        ## escalate db privilige role in case of resetting passwords
        orig_conn = None
        if rs.user.role == "anonymous" and new_password is None:
            orig_conn = rs.conn
            rs.conn = self.connpool['cdb_persona']
        if new_password is None:
            new_password = ''.join(random.choice(
                string.ascii_letters + string.digits) for _ in range(12))
            new_password = new_password + random.choice('!@#$%^&*(){}')
        ## do not use set_persona_data since it doesn't operate on password
        ## hashes by design
        query = "UPDATE core.personas SET password_hash = %s WHERE id = %s"
        ret = self.query_exec(rs, query, (self.encrypt_password(new_password),
                                          persona_id))
        if orig_conn:
            rs.conn = orig_conn
        return ret, new_password

    @access("persona")
    def change_password(self, rs, persona_id, old_password, new_password):
        """
        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type persona_id: int
        :type old_password: str
        :type new_password: str
        :rtype: (bool, str)
        :returns: see :py:meth:`modify_password`
        """
        persona_id = affirm("int", persona_id)
        old_password = affirm("str_or_None", old_password)
        new_password = affirm("str_or_None", new_password)
        if rs.user.persona_id == persona_id or self.is_admin(rs):
            return self.modify_password(rs, persona_id, old_password,
                                        new_password)
        else:
            raise RuntimeError("Permission denied.")

    @access("anonymous")
    def reset_password(self, rs, email):
        """Perform a recovery, generating a new password (which will be sent
        to the email address). To reset the password for a privileged
        account you need to have privileges yourself.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type email: str
        :rtype: (bool, str)
        :returns: see :py:meth:`modify_password`
        """
        email = affirm("email", email)
        query = glue("SELECT id, db_privileges FROM core.personas",
                     "WHERE username = %s")
        data = self.query_one(rs, query, (email,))
        if not data:
            return False, "Nonexistant user."
        if data['db_privileges'] > 0 and not self.is_admin(rs):
            ## do not allow password reset by anonymous for privileged
            ## users, otherwise we incur a security degradation on the
            ## RPC-interface
            return False, "Privileged user."
        return self.modify_password(rs, data['id'], None, None)

    @access("persona")
    def change_username(self, rs, persona_id, new_username, password):
        """Since usernames are used for login, this needs a bit of care.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type persona_id: int
        :type new_username: str
        :type password: str
        :rtype: (bool, str)
        """
        # TODO add changelog functionality
        # if rs.user.realm == "cde":
        #     raise RuntimeError("cde realm needs special treatment")
        new_username = affirm("email", new_username)
        password = affirm("str", password)
        if self.verify_existence(rs, new_username):
            ## abort if there is allready an account with this address
            return False, "Name collision."
        with Atomizer(rs):
            query = "SELECT password_hash FROM core.personas WHERE id = %s"
            data = self.query_one(rs, query, (persona_id,))
            if (self.is_admin(rs) and persona_id != rs.user.persona_id) \
              or self.verify_password(password, data['password_hash']):
                new_data = {
                    'id' : persona_id,
                    'username' : new_username,
                }
                if self.set_persona_data(rs, new_data):
                    return True, new_username
        return False, "Failed."

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Run CdEDB Backend for core services.')
    parser.add_argument('-c', default=None, metavar='/path/to/config',
                        dest="configpath")
    args = parser.parse_args()
    core_backend = CoreBackend(args.configpath)
    conf = Config(args.configpath)
    core_server = make_RPCDaemon(core_backend, conf.CORE_SOCKET,
                                 access_log=conf.CORE_ACCESS_LOG)
    if not conf.CDEDB_DEV and conf.CORE_ACCESS_LOG:
        raise RuntimeError("Logging will disclose passwords.")
    run_RPCDaemon(core_server, conf.CORE_STATE_FILE)
