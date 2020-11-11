#!/usr/bin/env python3

import json
from cdedb.script import setup, make_backend
from cdedb.common import SubscriptionActions
import cdedb.database.constants as const

# Configuration

rs = setup(persona_id=-1, dbuser="cdb_admin",
           dbpassword="9876543210abcdefghijklmnopqrst")

data_path = "/path/to/data.json"

# Execution

print("Fetching current state from database")

core = make_backend("core")
ml = make_backend("ml")

existing_lists = ml.get_mailinglists(rs(), tuple(ml.list_mailinglists(rs())))
existing_lists = {e['address']: e for e in existing_lists.values()}

persona_addresses = {}
for e in existing_lists.values():
    addresses = ml.get_subscription_addresses(
        rs(), e['id'], persona_ids=None, explicits_only=True)
    for persona_id, address in addresses.items():
        if address:
            persona_addresses[address] = persona_id
persona_id = -1
default_addresses = set()
while True:
    persona_id = core.next_persona(rs(), persona_id, is_member=False)
    if persona_id is None:
        break
    persona = core.get_persona(rs(), persona_id)
    if persona['username']:
        persona_addresses[persona['username']] = persona['id']
        default_addresses.add(persona['username'])

print("Reading data to import")

with open(data_path) as f:
    data = json.load(f)
    # format:
    # {<ml-address>: {"subs": [str],
    #                 "mods": [str],
    #                 "subscribing": str,
    #                 "posting": str}}

MOD_POLICY_MAP = {
    'open': const.ModerationPolicy.unmoderated,
    'subscriber': const.ModerationPolicy.non_subscribers,
    'moderated': const.ModerationPolicy.fully_moderated,
}

SUB_POLICY_MAP = {
    'open': const.MailinglistInteractionPolicy.opt_in,
    'moderated': const.MailinglistInteractionPolicy.moderated_opt_in,
}

for ml_address, entry in data.items():
    print("============================================================")
    if ml_address in existing_lists:
        print("Skipping existing list {}".format(ml_address))
        continue
    print("Importing list {}".format(ml_address))
    print("Checking for existence of subscriber addresses in DB")
    for sub_address in entry['subs']:
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
                'notes': None,
            }
            new_id = core.create_persona(rs(), new_persona)
            persona_addresses[sub_address] = new_id
            default_addresses.add(sub_address)
            print("Created account {} for subscriber {}".format(new_id, sub_address))
    print("Assemble infos for list creation")
    new_list = {
        'title': ml_address,
        'address': ml_address,
        'description': None,
        'sub_policy': SUB_POLICY_MAP[entry['subscribing']],
        'mod_policy': MOD_POLICY_MAP[entry['posting']],
        'attachment_policy': const.AttachmentPolicy.pdf_only,
        'audience_policy': const.AudiencePolicy.everybody,
        'subject_prefix': None,
        'maxsize': None,
        'is_active': True,
        'event_id': None,
        'registration_stati': [],
        'assembly_id': None,
        'notes': None,
    }
    print("Preparing moderators")
    moderators = []
    for mod_address in entry['mods']:
        if mod_address not in persona_addresses:
            print("Skipping moderator {} as no associated account was found".format(
                mod_address))
            continue
        moderators.append(persona_addresses[mod_address])
        print("Adding moderator {} as persona {}".format(
            mod_address, persona_addresses[mod_address]))
    new_list['moderators'] = moderators
    new_ml_id = ml.create_mailinglist(rs(), new_list)
    print("Created list {} with id {}".format(ml_address, new_ml_id))
    print("Adding subscribers to list")
    for sub_address in entry['subs']:
        persona_id = persona_addresses[sub_address]
        ml.do_subscription_action(rs(), SubscriptionActions.add_subscriber,
                                  new_ml_id, persona_id)
        if sub_address not in default_addresses:
            ml.set_subscription_address(rs(), new_ml_id, persona_id,
                                        sub_address)
            print("Adding {} with non-default address {}".format(persona_id,
                                                                 sub_address))
        else:
            print("Adding {} with default address {}".format(persona_id,
                                                             sub_address))

