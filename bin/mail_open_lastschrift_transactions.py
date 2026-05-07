#!/usr/bin/env python3

import cdedb.database.constants as const
from cdedb.script import Script

s = Script(dbuser="cdb_admin")

core_backend = s.make_core_backend()
cde_backend = s.make_cde_backend()
cde_frontend = s.make_cde_frontend()

mail_text = """Hallo {given_names}!

Am 17.01. hast du eine Mail von uns erhalten, die dich
über den bevorstehenden Lastschrifteinzug informiert hat.
Leider hat sich dort ein Fehler in die Gläubiger-ID
eingeschlichen.

Die korrekte (neue) Gläubiger-Identifikationsnummer ist:
    {glaeubiger_id}
Die bisherige Gläubiger-Identifikationsnummer war:
    {original_glaeubiger_id}

Für dich ändert sich hierdurch nichts.

Viele Grüße
die CdE-Mitgliederverwaltung
"""

with s:
    transaction_ids = cde_backend.list_lastschrift_transactions(
        s.rs(), stati=[const.LastschriftTransactionStati.issued]
    )
    transactions = cde_backend.get_lastschrift_transactions(s.rs(), transaction_ids)
    lastschrifts = cde_backend.get_lastschrifts(
        s.rs(), [t["lastschrift_id"] for t in transactions.values()]
    )
    personas = core_backend.get_core_users(
        s.rs(), [l["persona_id"] for l in lastschrifts.values()]
    )
    for i, persona in enumerate(personas.values()):
        print(f"Notifying {persona.given_names}... ", end="", flush=True)
        msg = cde_frontend._create_mail(
            mail_text.format(
                given_names=persona.given_names,
                glaeubiger_id=s.config["SEPA_GLAEUBIGERID"],
                original_glaeubiger_id=s.config["SEPA_ORIGINAL_GLAEUBIGERID"],
            ),
            {
                "To": [persona.username],
                "Reply-To": s.config["FINANCE_ADMIN_ADDRESS"],
                "Subject": "Korrektur Gläubiger-ID Lastschritinitiative",
            },
            attachments=None,
            defect_addresses={},
        )

        if not s.dry_run:
            cde_frontend._send_mail(msg)
            print("sent")
        else:
            print("omitted (dry run)")

        if i == 0:
            print()
            print("Example message:")
            print(msg)
            print()

    if not s.dry_run:
        print(f"Sent {len(personas)} notifications.")
    else:
        print(f"Would have sent {len(personas)} notifications.")
