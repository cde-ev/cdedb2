#!/usr/bin/env python3
import csv
import pathlib
import sys
import tempfile

import cdedb.database.constants as const
from cdedb.common import asciificator, make_persona_name
from cdedb.common.parse.util import TransactionType, number_to_german
from cdedb.filter import cdedbid_filter
from cdedb.frontend.cde.parse_statement import ExportFields
from cdedb.frontend.common import CustomCSVDialect
from cdedb.script import Script

s = Script(dbuser="cdb_member")
rs = s.rs()

core = s.make_core_backend()
cde = s.make_cde_backend()


if not len(sys.argv) > 1:
    sys.exit("no period given")
period = int(sys.argv[1])


with s:
    meta_data = core.get_meta_info(rs)
    lastschrift_ids = cde.list_lastschrift(rs, active=None)
    lastschrifts = cde.get_lastschrifts(rs, lastschrift_ids)
    persona_ids = {lastschrift["persona_id"] for lastschrift in lastschrifts.values()}
    personas = core.get_personas(rs, persona_ids)
    transaction_ids = cde.list_lastschrift_transactions(
        rs,
        lastschrift_ids,
        stati=[const.LastschriftTransactionStati.success],
        periods=[period],
    )
    transactions = cde.get_lastschrift_transactions(rs, transaction_ids)

    sorted_transactions = sorted(
        transactions.values(), key=lambda t: (t["payment_date"], t["id"])
    )

    data = []
    for transaction in sorted_transactions:
        lastschrift = lastschrifts[transaction["lastschrift_id"]]
        persona = personas[lastschrift["persona_id"]]
        data.append({
            "date": transaction["payment_date"],
            "amount_german": number_to_german(transaction["tally"]),
            "cdedbid": cdedbid_filter(lastschrift["persona_id"]),
            "family_name": persona.family_name,
            "given_names": persona.given_names,
            "category": TransactionType.LastschriftInitiative.category(),
            "account_nr": meta_data.lastschrift_account.display_str(),
            "reference": asciificator(
                f"{cdedbid_filter(persona.id)}, {persona.family_name},"
                f" {persona.given_names} LSI Mitgliedsbeitrag u. Spende CdE e.V."
                " z. Foerderung der Volks- u. Berufsbildung u. Studentenhilfe"
            )[:140],
            "account_holder": (
                lastschrift["account_owner"] or persona.get_name()
            ),
            "iban": lastschrift["iban"],
        })

    with tempfile.NamedTemporaryFile(delete=False) as tmp_f:
        with pathlib.Path(tmp_f.name).open("w", encoding="utf-8-sig") as csvfile:
            w = csv.DictWriter(csvfile, ExportFields.excel, dialect=CustomCSVDialect)
            w.writeheader()
            w.writerows(data)

        print(f"Wrote {len(data)} transactions to {tmp_f.name!r}.")
