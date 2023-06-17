import datetime
import decimal

import cdedb.database.constants as const
from cdedb.backend.core import CoreBackend
from cdedb.common import CdEDBObject, unwrap
from cdedb.script import Script

s = Script(dbuser="cdb")

core: CoreBackend = s.make_backend("core", proxy=False)

affected_count = 351
error_time = datetime.datetime.fromisoformat("2023-04-12 10:28:35+02:00")
persona_balances = {}

def get_clean_history(persona_id: int, old_generation: int) -> CdEDBObject:
    generation_data = unwrap(
        core.changelog_get_history(s.rs(), persona_id, [old_generation]))

    generation_data['persona_id'] = persona_id

    del generation_data['id']
    generation_data['submitted_by'] = s.persona_id
    generation_data['reviewed_by'] = None
    generation_data['ctime'] = None
    generation_data['change_note'] = None
    generation_data['automated_change'] = True
    generation_data['code'] = const.MemberChangeStati.committed

    generation_data['ctime'] = error_time
    generation_data['change_note'] = "Restguthaben von Nicht-Mitglied entfernt."
    generation_data['generation'] += 1

    return generation_data

with s:
    # 1.a Find those users where nothing has changed since the error. (337 users)
    q = """
        SELECT p.id, generation
        FROM core.personas AS p
            JOIN core.changelog AS cl ON p.id = cl.persona_id
            JOIN (
                SELECT persona_id, MAX(generation) AS max_gen
                FROM core.changelog
                GROUP BY persona_id
            ) AS clmax ON p.id = clmax.persona_id
        WHERE p.balance != cl.balance AND cl.generation = clmax.max_gen
    """
    p = ()
    data = core.query_all(s.rs(), q, p)
    easy_affected = len(data)

    print(f"Fixing {easy_affected} easy personas, by appending changelog entries.")

    # 1.b Insert fake changelog entry associated with the update
    for d in data:
        persona_id = d['id']
        generation_data = get_clean_history(persona_id, d['generation'])

        persona_balances[persona_id] = generation_data['balance']
        generation_data['balance'] = decimal.Decimal("0.00")

        core.sql_insert(s.rs(), "core.changelog", generation_data)

    # 1.c Add skipped transactions from the finance log to changelog and persona
    # (17 users (subset of 337))
    q = """
        SELECT fl.ctime AS fl_ctime, fl.persona_id, fl.submitted_by, fl.transaction_date, fl.delta, clmax.max_gen, cl2.ctime AS max_gen_ctime 
        FROM cde.finance_log fl
            LEFT JOIN core.changelog cl ON fl.persona_id = cl.persona_id AND fl.ctime = cl.ctime
            JOIN (
                SELECT persona_id, MAX(generation) AS max_gen
                FROM core.changelog
                GROUP BY persona_id
            ) AS clmax ON fl.persona_id = clmax.persona_id
            JOIN core.changelog cl2 ON fl.persona_id = cl2.persona_id AND clmax.max_gen = cl2.generation
        WHERE fl.code = %s AND cl.persona_id IS NULL AND fl.ctime > %s;
    """
    p = (
        const.FinanceLogCodes.increase_balance,
        datetime.datetime.fromisoformat("2023-01-01"),
    )
    data = core.query_all(s.rs(), q, p)

    print(f"Fixing changelog for {len(data)} missing transactions, by appending"
          f" skipped transactions.")

    note_template = ("Guthabenänderung um {amount} auf {new_balance} "
                     "(Überwiesen am {date})")

    for d in data:
        if d['max_gen_ctime'] > d['fl_ctime']:
            raise RuntimeError
        generation_data = get_clean_history(d['persona_id'], d['max_gen'])
        generation_data['balance'] = d['delta']

        generation_data['submitted_by'] = d['submitted_by']
        generation_data['ctime'] = d['fl_ctime']
        generation_data['change_note'] = note_template.format(
            amount=d['delta'], new_balance=d['delta'], date=d['transaction_date'])

        core.sql_insert(s.rs(), "core.changelog", generation_data)

    # 2.a Find those users where there were changes since the error. (14 users)
    # It is hard to determine these algorithmically.
    affected_changed = [9138, 14454, 16451, 16705, 17473, 21530, 21792, 23831, 25122,
                        25262, 25761, 25769, 26625, 29722]
    if not affected_count == len(affected_changed) + easy_affected:
        raise RuntimeError("More accounts have broken.")

    print(f"Fixing {len(affected_changed)} complicated personas.")

    # 2.b Increase changelog generation by one for each entry after the error
    q = """
        ALTER TABLE core.changelog DROP CONSTRAINT changelog_persona_id_generation_key;
    """
    core.query_exec(s.rs(), q, ())

    q = """
        UPDATE core.changelog SET generation = generation + 1
        WHERE persona_id = ANY(%s) AND ctime >= %s;
    """
    p = (affected_changed, error_time)
    rowcount = core.query_exec(s.rs(), q, p)
    print(f"Moved {rowcount} changelog entries.")

    q = """
        ALTER TABLE core.changelog ADD UNIQUE (persona_id, generation);
    """
    core.query_exec(s.rs(), q, ())

    # 2.c Determine number of missing changelog entry
    q = """
        SELECT persona_id, MAX(generation) AS before_gen
        FROM core.changelog
        WHERE persona_id = ANY(%s) AND ctime < %s
        GROUP BY persona_id
    """
    params = (affected_changed, error_time,)
    data = core.query_all(s.rs(), q, params)

    print(f"Inserting {len(data)} new changelog entries.")

    # 2.d Insert fake changelog entry associated with the update
    for d in data:
        persona_id = d['persona_id']
        generation_data = get_clean_history(persona_id, d['before_gen'])
        persona_balances[persona_id] = generation_data['balance']
        generation_data['balance'] = decimal.Decimal("0.00")
        core.sql_insert(s.rs(), "core.changelog", generation_data)

    from pprint import pprint
    pprint(persona_balances)
