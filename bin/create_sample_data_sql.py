import argparse
import json
from itertools import chain
from typing import Any, Callable, Dict, List, Set, Tuple, Type

from typing_extensions import TypedDict

from cdedb.backend.common import PsycoJson
from cdedb.backend.core import CoreBackend
from cdedb.common import RequestState, CdEDBObject
from cdedb.script import setup


class AuxData(TypedDict):
    rs: RequestState
    core: Type[CoreBackend]
    PsycoJson: Type[PsycoJson]
    seq_id_tables: List[str]
    cyclic_references: Dict[str, Tuple[str, ...]]
    constant_replacements: CdEDBObject
    entry_replacements: Dict[str, Dict[str, Callable[..., Any]]]
    xss_field_excludes: Set[str]
    xss_table_excludes: Set[str]


def prepare_aux(data: CdEDBObject) -> AuxData:
    # Note that we do not care about the actual backend but rather about
    # the methds inherited from `AbstractBackend`.
    rs_maker = setup(1, "nobody", "nobody", dbname="nobody")
    rs = rs_maker()
    core = CoreBackend  # No need to instantiate, we only use statics.

    # Extract some data about the databse tables using the database connection.

    # The following is a list of tables to that do NOT have sequential ids:
    non_seq_id_tables = [
        "cde.org_period",
        "cde.expuls_period",
    ]

    seq_id_tables = [t for t in data if t not in non_seq_id_tables]
    # Prepare some constants for special casing.

    # This maps full table names to a list of column names in that table that
    # require special care, because they contain cycliy references.
    # They will be removed from the initial INSERT and UPDATEd later.
    cyclic_references: Dict[str, Tuple[str, ...]] = {
        "event.events": ("lodge_field", "course_room_field", "camping_mat_field"),
    }

    # This contains a list of replacements performed on the resulting SQL
    # code at the very end. Note that this is the only way to actually insert
    # SQL-syntax. We use it to alway produce a current timestamp, because a
    # fixed timestamp from the start of a test suite won't do.
    constant_replacements = {
        "'---now---'": "now()",
    }

    # For every table we may map one of it's columns to a function which
    # dynamically generates data to insert.
    # The function will get the entire row as a argument.
    entry_replacements = {
        "core.personas":
            {
                "fulltext": core.create_fulltext,
            },
    }

    # For xss checking insert a payload into all string fields except excluded ones.
    xss_field_excludes = {
        "username", "password_hash", "birthday", "telephone", "mobile", "balance",
        "ctime", "atime", "dtime", "foto", "amount", "iban", "granted_at", "revoked_at",
        "issued_at", "processed_at", "tally", "total", "delta", "shortname", "tempus",
        "registration_start", "registration_soft_limit", "registration_hard_limit",
        "nonmember_surcharge", "part_begin", "part_end", "fee", "field_name",
        "amount_paid", "amount_owed", "payment", "presider_address", "signup_end",
        "vote_begin", "vote_end", "vote_extension_end", "secret", "vote", "salt",
        "hash", "filename", "file_hash", "address", "local_part", "new_balance",
        "modifier_name",
    }
    xss_table_excludes = {
        "cde.org_period", "cde.expuls_period",
    }

    return AuxData(
        rs=rs, core=core,
        PsycoJson=PsycoJson,
        seq_id_tables=seq_id_tables,
        cyclic_references=cyclic_references,
        constant_replacements=constant_replacements,
        entry_replacements=entry_replacements,
        xss_field_excludes=xss_field_excludes,
        xss_table_excludes=xss_table_excludes,
    )


def format_inserts(table_name, table_data, keys, params, aux):
    ret = []
    # Create len(data) many row placeholders for len(keys) many values.
    value_list = ",\n".join(("({})".format(", ".join(("%s",) * len(keys))),)
                            * len(table_data))
    query = "INSERT INTO {table} ({keys}) VALUES {value_list};".format(
        table=table_name, keys=", ".join(keys), value_list=value_list)
    # noinspection PyProtectedMember
    params = tuple(aux["core"]._sanitize_db_input(p) for p in params)

    # This is a bit hacky, but it gives us access to a psycopg2.cursor
    # object so we can let psycopg2 take care of the heavy lifting
    # regarding correctly inserting the parameters into the SQL query.
    with aux["rs"].conn as conn:
        with conn.cursor() as cur:
            ret.append(cur.mogrify(query, params).decode("utf8"))
    return ret


def build_commands(data: CdEDBObject, aux: AuxData, xss: str) -> List[str]:
    commands: List[str] = []

    # Start off by resetting the sequential ids to 1.
    commands.extend("ALTER SEQUENCE IF EXISTS {}_id_seq RESTART WITH 1;"
                    .format(table) for table in aux["seq_id_tables"])

    # Prepare insert statements for the tables in the source file.
    for table, table_data in data.items():
        # Skip tables that have no data.
        if not table_data:
            continue

        # The following is similar to `cdedb.AbstractBackend.sql_insert_many
        # But we fill missing keys with None isntead of giving an error.
        key_set = set(chain.from_iterable(e.keys() for e in table_data))
        for k in aux["entry_replacements"].get(table, {}).keys():
            key_set.add(k)

        # Remove fileds causing cyclic references. These will be handled later.
        key_set -= set(aux["cyclic_references"].get(table, {}))

        # Convert the keys to a tuple to ensure consistent ordering.
        keys = tuple(key_set)
        # FIXME more precise type
        params: List[Any] = []
        for entry in table_data:
            for k in keys:
                if k not in entry:
                    entry[k] = None
                if isinstance(entry[k], dict):
                    entry[k] = aux["PsycoJson"](entry[k])
                elif isinstance(entry[k], str) and xss:
                    if (table not in aux["xss_table_excludes"]
                            and k not in aux['xss_field_excludes']):
                        entry[k] = entry[k] + xss
            for k, f in aux["entry_replacements"].get(table, {}).items():
                entry[k] = f(entry)
            params.extend(entry[k] for k in keys)

        commands.extend(format_inserts(table, table_data, keys, params, aux))

    # Now we update the tables to fix the cyclic references we skipped earlier.
    for table, refs in aux["cyclic_references"].items():
        for entry in data[table]:
            for ref in refs:
                if entry.get(ref):
                    query = "UPDATE {} SET {} = %s WHERE id = %s;".format(
                        table, ref)
                    params = (entry[ref], entry["id"])
                    with aux["rs"].conn as conn:
                        with conn.cursor() as cur:
                            commands.append(
                                cur.mogrify(query, params).decode("utf8"))

    # Insert the ldap infos
    # This is adapted from
    # servers/slapd/back-sql/rdbms_depend/pgsql/testdb_metadata.sql
    # in the openldap sources.
    #
    # Currently this just provides a minimal viable example to test the ldap
    # sql integration. This is just a static data set kind of independent
    # from the rest of the DB.
    LDAP_TABLES = {
        'ldap_oc_mappings': [
            {
                'id': 1,
                'name': 'organization',
                'keytbl': 'ldap_organizations',
                'keycol': 'id',
                'create_proc': "SELECT 'TODO'",
                'delete_proc': "SELECT 'TODO'",
                'expect_return': 0,
            },
            {
                'id': 2,
                'name': 'inetOrgPerson',
                'keytbl': 'core.personas',
                'keycol': 'id',
                'create_proc': "SELECT 'TODO'",
                'delete_proc': "SELECT 'TODO'",
                'expect_return': 0,
            },
        ],
        'ldap_organizations': [
            {
                'id': 1,
                'dn': 'dc=cde-ev,dc=de',
                'oc_map_id': 1,
                'parent': 0
            },
            {
                'id': 2,
                'dn': 'ou=users,dc=cde-ev,dc=de',
                'oc_map_id': 1,
                'parent': 1
            },
            {
                'id': 3,
                'dn': 'ou=groups,dc=cde-ev,dc=de',
                'oc_map_id': 1,
                'parent': 1
            },
        ],
        'ldap_attr_mappings': [
            {
                'id': 1,
                'oc_map_id': 2,
                'name': 'cn',
                'sel_expr': 'personas.username',
                'from_tbls': 'core.personas',
                'join_where': None,
                'add_proc': "SELECT 'TODO'",
                'delete_proc': "SELECT 'TODO'",
                'param_order': 3,
                'expect_return': 0,
            },
            {
                'id': 2,
                'oc_map_id': 2,
                'name': 'givenName',
                'sel_expr': 'personas.given_names',
                'from_tbls': 'core.personas',
                'join_where': None,
                'add_proc': 'UPDATE core.personas SET given_names=? WHERE username=?',
                'delete_proc': "SELECT 'TODO'",
                'param_order': 3,
                'expect_return': 0,
            },
            {
                'id': 3,
                'oc_map_id': 2,
                'name': 'sn',
                'sel_expr': 'personas.family_name',
                'from_tbls': 'core.personas',
                'join_where': None,
                'add_proc': 'UPDATE core.personas SET family_name=? WHERE username=?',
                'delete_proc': "SELECT 'TODO'",
                'param_order': 3,
                'expect_return': 0,
            },
            {
                'id': 4,
                'oc_map_id': 2,
                'name': 'userPassword',
                'sel_expr': 'personas.password_hash',
                'from_tbls': 'core.personas',
                'join_where': None,
                'add_proc': "SELECT 'TODO'",
                'delete_proc': "SELECT 'TODO'",
                'param_order': 3,
                'expect_return': 0,
            },
            {
                'id': 5,
                'oc_map_id': 2,
                'name': 'o',
                'sel_expr': 'ldap_organizations.moniker',
                'from_tbls': 'ldap_organizations',
                'join_where': None,
                'add_proc': "SELECT 'TODO'",
                'delete_proc': "SELECT 'TODO'",
                'param_order': 3,
                'expect_return': 0,
            },
        ],
        'ldap_entry_objclasses': [
            {
                'entry_id': 1,
                'oc_name': 'dcObject',
            },
        ],
    }

    for table, table_data in LDAP_TABLES.items():
        keys = tuple(set(chain.from_iterable(e.keys() for e in table_data)))
        params = [entry[key] for entry in table_data for key in keys]
        commands.extend(format_inserts(table, table_data, keys, params, aux))

    # Here we set all sequential ids to start with 1001, so that
    # ids are consistent when running the test suite.
    commands.extend("SELECT setval('{}_id_seq', 1000);".format(table)
                    for table in aux["seq_id_tables"])

    # Lastly we do some string replacements to cheat in SQL-syntax like `now()`:
    ret = []
    for cmd in commands:
        for k, v in aux["constant_replacements"].items():
            cmd = cmd.replace(k, v)
        ret.append(cmd)

    return ret


def main() -> None:
    # Import filelocations from commandline.
    parser = argparse.ArgumentParser(
        description="Generate an SQL-file to insert sample data from a "
                    "JSON-file.")
    parser.add_argument(
        "-i", "--infile",
        default="/cdedb2/tests/ancillary_files/sample_data.json")
    parser.add_argument(
        "-o", "--outfile", default="/tmp/sample_data.sql")
    parser.add_argument("-x", "--xss", default="")
    args = parser.parse_args()

    with open(args.infile) as f:
        data = json.load(f)

    assert isinstance(data, dict)
    aux = prepare_aux(data)
    commands = build_commands(data, aux, args.xss)

    with open(args.outfile, "w") as f:
        for cmd in commands:
            print(cmd, file=f)


if __name__ == '__main__':
    main()
