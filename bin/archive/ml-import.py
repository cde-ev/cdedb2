#!/usr/bin/env python3

import json
from typing import Dict

import cdedb.database.constants as const
from cdedb.common import SubscriptionAction
from cdedb.script import make_backend, setup, Script

# Configuration

# The persona_id will need to be replaced before use.
executing_admin_id = -1
rs = setup(persona_id=executing_admin_id, dbuser="cdb_admin",
           dbpassword="9876543210abcdefghijklmnopqrst")

data_path = "/path/to/data.json"

DRY_RUN = True

# Prepare backends

core = make_backend("core")
ml = make_backend("ml")

# Execution

ADDRESS_SUBSTITTIONS = {
    "*@cdelokal.schuelerakademie.de": "*@cdelokal.cde-ev.de",
    "multinational-all@cde-ev.de": "multinational-all@lists.cde-ev.de",
    "multinational@cde-ev.de": "multinational@lists.cde-ev.de",
    "cde-segeln@lists.schuelerakademie.de": "cde-segeln@lists.cde-ev.de",
    "vorstand@cde-ev.de": "vorstand@lists.cde-ev.de",
    "dsa@lists.schuelerakademie.de": "dsa@lists.cde-ev.de",
}

with Script(rs(), dry_run=DRY_RUN):
    print("Fetching current state from database")

    existing_lists = ml.get_mailinglists(rs(), tuple(ml.list_mailinglists(rs())))
    existing_lists = {e['address']: e for e in existing_lists.values()}

    persona_addresses: Dict[str, int] = {}
    semi_default_addresses = {}
    default_addresses = {}
    for e in existing_lists.values():
        addresses = ml.get_subscription_addresses(
            rs(), e['id'], persona_ids=None, explicits_only=True)
        for persona_id, address in addresses.items():
            if address:
                if persona_addresses.get(address, persona_id) != persona_id:
                    print("Non-unique persona "
                          f"({persona_addresses[address]}, {persona_id}) "
                          f"for address {address}.")
                else:
                    persona_addresses[address] = persona_id
    persona_id = -1
    while True:
        persona_id = core.next_persona(rs(), persona_id, is_member=False)
        if persona_id is None:
            break
        history = core.changelog_get_history(rs(), persona_id, None)
        this_addreses = {datum['username']
                         for datum in history.values() if datum['username']}
        for addr in this_addreses:
            if persona_addresses.get(addr, persona_id) != persona_id:
                print("Non-unique persona "
                      f"({persona_addresses[addr]}, {persona_id}) "
                      f"for address {addr}.")
            persona_addresses[addr] = persona_id
            semi_default_addresses[addr] = persona_id
        persona = core.get_persona(rs(), persona_id)
        if persona['username']:
            default_addresses[persona_id] = persona['username']

    print("Reading data to import")

    with open(data_path) as f:
        data = json.load(f)
        # format:
        # {<ml-address>: {"subs": [str],
        #                 "mods": [str],
        #                 "subscribing": str,
        #                 "prefix": str,
        #                 "posting": str}}

    MOD_POLICY_MAP = {
        'open': const.ModerationPolicy.unmoderated,
        'subscriber': const.ModerationPolicy.non_subscribers,
        'moderated': const.ModerationPolicy.fully_moderated,
    }

    SUB_POLICY_MAP = {
        'open': const.MailinglistTypes.general_opt_in,
        'moderated': const.MailinglistTypes.semi_public,
    }

    DOMAIN_MAP = {
        'lists.cde-ev.de': const.MailinglistDomain.lists,
        'aka.cde-ev.de': const.MailinglistDomain.aka,
        'cde-ev.de': const.MailinglistDomain.general,
        'cdelokal.cde-ev.de': const.MailinglistDomain.cdelokal,
    }

    for ml_address, entry in data.items():
        original_address = ml_address
        lurker_addresses = {'lurker-' + ml_address}
        ml_address = ADDRESS_SUBSTITTIONS.get(ml_address, ml_address)
        if ml_address.endswith('cdelokal.schuelerakademie.de'):
            ml_address = ml_address.replace('cdelokal.schuelerakademie.de',
                                            'cdelokal.cde-ev.de')
        lurker_addresses.add('lurker-' + ml_address)
        print("============================================================")
        if ml_address in existing_lists:
            print("Skipping existing list {}".format(ml_address))
            continue
        print("Importing list {} (originally {})".format(ml_address, original_address))
        print("Checking for existence of subscriber addresses in DB")
        for sub_address in entry['subs']:
            sub_address = sub_address.lower()
            if sub_address in lurker_addresses:
                print(f"Avoiding lurker {sub_address}")
                continue
            if sub_address not in persona_addresses:
                new_persona = {
                    'is_cde_realm': False,
                    'is_event_realm': False,
                    'is_assembly_realm': False,
                    'is_ml_realm': True,
                    'is_member': False,
                    'is_searchable': False,
                    'is_active': True,
                    'username': sub_address,
                    'display_name': sub_address,
                    'given_names': sub_address,
                    'family_name': "(Mailinglistimport)",
                    'title': None,
                    'name_supplement': None,
                    'gender': None,
                    'birthday': None,
                    'telephone': None,
                    'mobile': None,
                    'address_supplement': None,
                    'address': None,
                    'postal_code': None,
                    'location': None,
                    'country': None,
                    'birth_name': None,
                    'address_supplement2': None,
                    'address2': None,
                    'postal_code2': None,
                    'location2': None,
                    'country2': None,
                    'weblink': None,
                    'specialisation': None,
                    'affiliation': None,
                    'timeline': None,
                    'interests': None,
                    'free_form': None,
                    'trial_member': None,
                    'decided_search': None,
                    'bub_search': None,
                    'foto': None,
                    'paper_expuls': None,
                    'notes': None,
                }
                new_id = core.create_persona(rs(), new_persona)
                persona_addresses[sub_address] = new_id
                semi_default_addresses[sub_address] = new_id
                default_addresses[new_id] = sub_address
                print(f"Created account {new_id} for subscriber {sub_address}")
        print("Assemble infos for list creation")
        local_part, domain = ml_address.split('@')
        ml_type = SUB_POLICY_MAP[entry['subscribing']]
        if domain == 'cdelokal.cde-ev.de':
            ml_type = const.MailinglistTypes.cdelokal
        new_list = {
            'title': ml_address,
            'local_part': local_part,
            'domain': DOMAIN_MAP[domain],
            'description': None,
            'mod_policy': MOD_POLICY_MAP[entry['posting']],
            'attachment_policy': const.AttachmentPolicy.pdf_only,
            'ml_type': ml_type,
            'subject_prefix': entry['prefix'],
            'maxsize': 2048,
            'is_active': True,
            'notes': "Imported from ezml-mailinglist.",
            'event_id': None,
            'registration_stati': [],
            'assembly_id': None,
        }
        print("Preparing moderators")
        moderators = []
        for mod_address in entry['mods']:
            mod_address = mod_address.lower()
            if mod_address not in persona_addresses:
                print("Skipping moderator {} as no associated account was found".format(
                    mod_address))
                continue
            moderators.append(persona_addresses[mod_address])
            print("Adding moderator {} as persona {}".format(
                mod_address, persona_addresses[mod_address]))
        if not moderators:
            print("Exceptionally using admin {} as moderator".format(
                executing_admin_id))
            moderators.append(executing_admin_id)
        new_list['moderators'] = moderators
        new_ml_id = ml.create_mailinglist(rs(), new_list)
        print("Created list {} with id {}".format(ml_address, new_ml_id))
        print("Adding subscribers to list")
        subscribed = set()
        for sub_address in entry['subs']:
            sub_address = sub_address.lower()
            if sub_address in lurker_addresses:
                continue
            persona_id = persona_addresses[sub_address]
            if persona_id in subscribed:
                print(f"Omitting {persona_id} with address {sub_address}"
                      " (already subscribed)")
                continue
            ml.do_subscription_action(rs(), SubscriptionAction.add_subscriber,
                                      new_ml_id, persona_id)
            subscribed.add(persona_id)
            if sub_address not in semi_default_addresses:
                ml.set_subscription_address(rs(), new_ml_id, persona_id,
                                            sub_address)
                print(f"Adding {persona_id} with non-default address {sub_address}")
            elif sub_address != default_addresses.get(persona_id):
                print(f"Adding {persona_id} with augmented default address"
                      f" {default_addresses.get(persona_id)} (from {sub_address})")
            else:
                print(f"Adding {persona_id} with default address {sub_address}")
