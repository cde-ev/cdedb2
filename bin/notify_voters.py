#!/usr/bin/env python3
"""Send notifications to users who submitted an invalid vote."""

import logging
import os
import pathlib
from typing import Any

import cdedb.common.validation.types as vtypes
from cdedb.backend.assembly import AssemblyBackend
from cdedb.backend.core import CoreBackend
from cdedb.common import unwrap
from cdedb.frontend.assembly import AssemblyFrontend
from cdedb.frontend.common import Headers, cdedburl, check_validation
from cdedb.script import Script

# Setup.


def cdedblink(endpoint: str, params: dict[str, Any]) -> str:
    return cdedburl(s.rs(), endpoint, params, force_external=True)


s = Script(dbuser="cdb_admin", LOG_LEVEL=logging.WARNING)

assembly: AssemblyBackend = s.make_backend("assembly", proxy=False)
assembly_frontend: AssemblyFrontend = s.make_frontend("assembly")
core: CoreBackend = s.make_backend("core")


# Config.

ballot_id = int(os.environ.get("NOTIFY_VOTERS_BALLOT_ID", -1))
mail_subject = "Ungültige Stimme, Bitte um Korrektur"
mail_template = """Hallo!

Du hast bei der Abstimmung "{}" eine ungültige Stimme abgegeben.
Bitte besuche zeitnah die Abstimmungsseite in der Datenbank [1] und gib eine gültige Stimme ab.

Die Datenbank

[1]: {}"""


# Prepare for work.

ballot = assembly.get_ballot(s.rs(), ballot_id)
assembly_data = assembly.get_assembly(s.rs(), ballot['assembly_id'])
q = ("SELECT persona_id FROM assembly.voter_register"
     " WHERE ballot_id = %s AND has_voted = True")
p = [ballot_id]
persona_ids = [e['persona_id'] for e in assembly.query_all(s.rs(), q, p)]
ballot_link = cdedblink("assembly/show_ballot",
                        {'assembly_id': ballot['assembly_id'], 'ballot_id': ballot_id})
mail_text = mail_template.format(ballot['title'], ballot_link)
default_headers: Headers = {
    'Subject': mail_subject,
    'Reply-To': assembly_data['presider_address'],
    'Prefix': assembly_data['shortname'],
}
if not default_headers['Reply-To']:
    del default_headers['Reply-To']
mails = []
no_vote = 0
manipulated_vote = 0
valid_votes = 0
invalid_votes = 0

# Do work.
print(ballot_link)
print()
with s:
    for persona_id in persona_ids:
        # Try to retrieve the vote using the stored secret.
        # This will fail for archived assemblies.
        vote = assembly.get_vote(s.rs(persona_id), ballot_id, secret=None)
        if vote is None:
            # No vote could be retrieved. Check if there is a secret available.
            no_vote += 1
            q = ("SELECT secret IS NOT NULL AS has_secret"
                 " FROM assembly.attendees WHERE persona_id = %s")
            p = [persona_id]
            if unwrap(assembly.query_one(s.rs(), q, p)):
                # An available secret, but no retrievable vote implies manipulation.
                manipulated_vote += 1
        elif not check_validation(s.rs(), vtypes.Vote, vote, ballot=ballot):
            # Check for invalid votes and send a notification to the voter.
            persona = core.get_persona(s.rs(), persona_id)
            msg = assembly_frontend._create_mail(  # pylint: disable=protected-access
                mail_text, default_headers | {'To': (persona['username'],)},  # type: ignore[arg-type]
                attachments=None)
            mails.append(msg)
        else:
            valid_votes += 1

    # Get number of total votes and total number of invalid votes.
    q = "SELECT vote FROM assembly.votes WHERE ballot_id = %s"
    p = [ballot_id]
    data = assembly.query_all(s.rs(), q, p)
    for e in data:
        if not check_validation(s.rs(), vtypes.Vote, e['vote'], ballot=ballot):
            invalid_votes += 1

    # Present the gatherd information to the caller.
    print(f"Found {len(data)} total votes and {len(persona_ids)} voters.")
    if len(data) != len(persona_ids):
        print("This mismatch might be because this is a historical ballot.")
    if no_vote:
        print(f"Could not retrieve matching vote for {no_vote} personas.", end=" ")
        if not manipulated_vote:
            print("All of these personas have no stored secret available.")
        else:
            print(f"{manipulated_vote} of these have a stored secret available."
                  f" This is a likely indication of vote manipulation.")
    if mails:
        print(f"Matched {len(mails)} invalid votes to personas, sending notifications.")
    if valid_votes:
        print(f"Successfully matched {valid_votes} valid votes to personas.")
    if invalid_votes:
        print(f"Found {invalid_votes} total invalid votes.")

    # If necessary send the notification mails. Skip this step in dry run mode or if
    #  the ballot is not running.
    if mails and ballot['is_voting']:
        print(f"Preparing to send {len(mails)} mails.")
        if s.dry_run:
            print("Skipping sending during dry-run.")
        else:
            sent = 0
            for mail in mails:
                ret = assembly_frontend._send_mail(mail)  # pylint: disable=protected-access
                if ret:
                    path = pathlib.Path(ret)
                    if path.exists():
                        path.unlink()
                        sent += 1
            print(f"Successfully sent {sent} mails.")
        print()
