#!/usr/bin/env python3

import argparse
import collections
import datetime
import decimal
import pathlib
import pprint

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.ml
from cdedb.script import Script
from cdedb.uncommon.submanshim import SubscriptionAction

def output_counters(context, prefix="", final=False):
    if context.clock is not None:
        now = datetime.datetime.now()
        delta = now - context.clock
        context.clock = now
        print(prefix + f"Processed in {delta}")
    pprint.pprint(dict(context.counters))


def make_counter(context, name, prefix='', suffix=''):
    num = context.counters[name]
    context.counters[name] += 1
    return f'{prefix}{name}{num:010}{suffix}'


def persona(context):
    rs = context.script.rs()
    data = {
        'is_cde_realm': True,
        'is_event_realm': True,
        'is_ml_realm': True,
        'is_assembly_realm': True,
        'is_member': True,
        'is_searchable': True,
        'is_active': True,
        'username': make_counter(context, 'Email', suffix='@example.cde'),
        'notes': '',
        'display_name': make_counter(context, 'Spitzname'),
        'given_names': make_counter(context, 'Vorname'),
        'family_name': make_counter(context, 'Nachname'),
        'title': '',
        'name_supplement': '',
        'gender': const.Genders.female,
        'pronouns': '',
        'pronouns_nametag': False,
        'pronouns_profile': False,
        'birthday': datetime.date(2000, 1, 1),
        'telephone': '',
        'mobile': '',
        'address_supplement': '',
        'address': make_counter(context, 'Adresse'),
        'postal_code': '01234',
        'location': make_counter(context, 'Stadt'),
        'country': '',
        'birth_name': '',
        'address_supplement2': '',
        'address2': '',
        'postal_code2': '',
        'location2': '',
        'country2': '',
        'weblink': '',
        'specialisation': '',
        'affiliation': '',
        'timeline': '',
        'interests': '',
        'free_form': '',
        'trial_member': False,
        'decided_search': True,
        'bub_search': True,
        'foto': None,
        'paper_expuls': False,
        'donation': decimal.Decimal(0),
    }
    core = context.script.make_backend('core', proxy=False)
    ret = core.create_persona(rs, data)
    query = "UPDATE core.personas SET password_hash = %s WHERE id = %s"
    hashed_secret = ("$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0"
                     "nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2"
                     "cVcK3TwSxsRPb91TLHF/si/")
    with rs.conn as conn:
        with conn.cursor() as cur:
            core.execute_db_query(cur, query, (hashed_secret, ret))
            success = cur.rowcount
    if not success:
        raise RuntimeError("Failed password reset.")
    return ret


def event(context):
    rs = context.script.rs()
    data = {
        'title': make_counter(context, 'Veranstaltung'),
        'institution': const.PastInstitutions.cde,
        'description': '',
        'shortname': make_counter(context, 'VeranstaltungKurz'),
        'is_visible': True,
        'is_course_list_visible': True,
        'is_course_state_visible': True,
        'use_additional_questionnaire': True,
        'registration_start': datetime.datetime(2000, 1, 1, 0, 0, 0),
        'is_participant_list_visible': True,
        'is_course_assignment_visible': True,
        'is_cancelled': False,
        'registration_text': make_counter(
            context, 'Veranstaltungsanmeldungstext'),
        'orga_address': make_counter(context, 'OrgaEmail',
                                     suffix='@aka.cde-ev.de'),
        'participant_info': make_counter(
            context, 'Teilnehmerinformation'),
        'orgas': [persona(context) for _ in range(1 if context.quick else 10)],
        'parts': {
            -1: {
                'tracks': {
                    -1: {'title': make_counter(context, 'Veranstaltungsschiene'),
                         'shortname': make_counter(context, 'Schiene'),
                         'num_choices': 3,
                         'min_choices': 3,
                         'sortkey': 1,
                         'course_room_field_id': None}
                },
                'title': make_counter(context, 'Veranstaltungsteil'),
                'shortname': 'first',
                'part_begin': datetime.date(2109, 8, 7),
                'part_end': datetime.date(2109, 8, 20),
                'waitlist_field_id': None,
                'camping_mat_field_id': None,
            },
            -2: {
                'tracks': {
                    -1: {'title': make_counter(context, 'Veranstaltungsschiene'),
                         'shortname': make_counter(context, 'Schiene'),
                         'num_choices': 3,
                         'min_choices': 1,
                         'sortkey': 1,
                         'course_room_field_id': None}
                },
                'title': make_counter(context, 'Veranstaltungsteil'),
                'shortname': 'second',
                'part_begin': datetime.date(2110, 8, 7),
                'part_end': datetime.date(2110, 8, 20),
                'waitlist_field_id': None,
                'camping_mat_field_id': None,
            },
        },
        'fees': {
            -1: {
                "kind": const.EventFeeType.common,
                "title": make_counter(context, 'Gebühr'),
                "notes": None,
                "amount": decimal.Decimal("234.56"),
                "condition": "part.first",
            },
            -2: {
                "kind": const.EventFeeType.common,
                "title": make_counter(context, 'Gebühr'),
                "notes": None,
                "amount": decimal.Decimal("0.00"),
                "condition": "part.second",
            },
            -3: {
                "kind": const.EventFeeType.solidary_reduction,
                "title": make_counter(context, 'Gebühr'),
                "notes": None,
                "amount": decimal.Decimal("-7.00"),
                "condition": "part.second and field.is_child",
            },
            -4: {
                "kind": const.EventFeeType.external,
                "title": make_counter(context, 'Gebühr'),
                "notes": None,
                "amount": decimal.Decimal("6.66"),
                "condition": "any_part and not is_member",
            }
        },
        'fields': {
            -1: {
                'association': const.FieldAssociations.registration,
                'field_name': make_counter(context, 'VeranstaltungsfeldIntern'),
                'title': make_counter(context, 'Veranstaltungsfeld'),
                'sortkey': 0,
                'kind': const.FieldDatatypes.str,
                'entries': None,
                'checkin': False,
            },
            -2: {
                'association': const.FieldAssociations.registration,
                'field_name': make_counter(context, 'VeranstaltungsfeldIntern'),
                'title': make_counter(context, 'Veranstaltungsfeld'),
                'sortkey': 0,
                'kind': const.FieldDatatypes.date,
                'entries': {
                    "2109-08-16": make_counter(context, 'VeranstaltungsfeldEintrag'),
                    "2110-08-16": make_counter(context, 'VeranstaltungsfeldEintrag'),
                },
                'checkin': True,
            },
            -3: {
                'association': const.FieldAssociations.registration,
                'field_name': "is_child",
                'title': make_counter(context, 'Veranstaltungsfeld'),
                'sortkey': 5,
                'kind': const.FieldDatatypes.bool,
                'entries': None,
                'checkin': False,
            },
        },
        'lodgement_groups': {
            -1: {
                'title': make_counter(context, 'Unterkunftsgruppe'),
            },
            -2: {
                'title': make_counter(context, 'Unterkunftsgruppe'),
            },
        },
    }
    event = context.script.make_backend('event', proxy=False)
    ret = event.create_event(rs, data)
    lodgement_groups = event.list_lodgement_groups(rs, ret)
    for lg in lodgement_groups:
        for _ in range(1 if context.quick else 5):
            alodgement = event.create_lodgement(rs, {
                'regular_capacity': 42,
                'event_id': ret,
                'title': make_counter(context, 'Unterkunft'),
                'camping_mat_capacity': 11,
                'notes': '',
                'group_id': lg,
            })
    tracks = event.get_event(rs, ret).tracks
    courses = {
        t: [event.create_course(rs, {'event_id': ret,
                                     'title': make_counter(
                                         context, 'Veranstaltungskurs'),
                                     'description': '',
                                     'nr': make_counter(context, 'Kursnummer'),
                                     'shortname': make_counter(context,
                                                               'Kurs'),
                                     'instructors': '',
                                     'max_size': 12,
                                     'min_size': None,
                                     'notes': '',
                                     'segments': {t},
                                     })
            for _ in range(1 if context.quick else 10)]
        for t in tracks
    }
    fields = event.get_event(rs, ret).fields
    questionnaire = {
        const.QuestionnaireUsages.additional: [
            {
                'field_id': None,
                'default_value': None,
                'info': make_counter(context, 'FragebogenText'),
                'readonly': None,
                'input_size': None,
                'title': make_counter(context, 'FragebogenÜberschrift'),
            }
        ],
        const.QuestionnaireUsages.registration: [
            {
                'field_id': None,
                'default_value': None,
                'info': make_counter(context, 'FragebogenText'),
                'readonly': None,
                'input_size': None,
                'title': make_counter(context, 'FragebogenÜberschrift'),
            }
        ],
    }
    event.set_questionnaire(rs, ret, questionnaire)
    parts = event.get_event(rs, ret).parts
    for _ in range(1 if context.quick else 100):
        event.create_registration(rs, {
            'event_id': ret,
            'persona_id': persona(context),
            'list_consent': True,
            'mixed_lodging': True,
            'notes': '',
            'parts': {
                part: {
                    'lodgement_id': alodgement,
                    'status': const.RegistrationPartStati.participant
                } for part in parts
            },
            'tracks': {
                track: {
                    'choices': courses[track][:5],
                    'course_id': None,
                    'course_instructor': None,
                } for track in tracks
            },
        })
    return ret


def assembly(context):
    rs = context.script.rs()
    assembly = context.script.make_backend('assembly', proxy=False)
    ret = assembly.create_assembly(rs, {
        'presiders': [persona(context)
                      for _ in range(1 if context.quick else 3)],
        'description': '',
        'notes': None,
        'signup_end': datetime.datetime(2100, 1, 1, 0, 0, 0),
        'title': make_counter(context, 'Mitgliederversammlung'),
        'shortname': make_counter(context, 'Versammlung'),
    })
    for _ in range(1 if context.quick else 10):
        assembly.create_ballot(rs, {
            'assembly_id': ret,
            'use_bar': True,
            'candidates': {
                -1: {'title': make_counter(context, 'Abstimmungsoption'),
                     'shortname': make_counter(context, 'OptionKurz'),},
                -2: {'title': make_counter(context, 'Abstimmungsoption'),
                     'shortname': make_counter(context, 'OptionKurz'),},
                -3: {'title': make_counter(context, 'Abstimmungsoption'),
                     'shortname': make_counter(context, 'OptionKurz'),},
            },
            'description': make_counter(context, 'Abstimmungstext'),
            'notes': None,
            'abs_quorum': 10,
            'rel_quorum': 0,
            'title': make_counter(context, 'Abstimmung'),
            'vote_begin': datetime.datetime(2222, 2, 5, 13, 22, 22, 222222,
                                            tzinfo=datetime.timezone.utc),
            'vote_end': datetime.datetime(2222, 2, 6, 13, 22, 22, 222222,
                                          tzinfo=datetime.timezone.utc),
            'vote_extension_end': datetime.datetime(2222, 2, 7, 13, 22, 22, 222222,
                                                    tzinfo=datetime.timezone.utc),
            'votes': None,
        })
    for _ in range(1 if context.quick else 100):
        secret = assembly.signup(context.script.rs(persona(context)), ret)
    return ret


def past_event(context):
    rs = context.script.rs()
    pastevent = context.script.make_backend('past_event', proxy=False)
    ret = pastevent.create_past_event(rs, {
        'title': make_counter(context, 'VergangeneVeranstaltung'),
        'shortname': make_counter(context, 'Vergangen'),
        'institution': const.PastInstitutions.cde,
        'description': '',
        'tempus': datetime.date(2000, 1, 1),
        'participant_info': None,
    })
    for _ in range(1 if context.quick else 10):
        acourse = pastevent.create_past_course(rs, {
            'pevent_id': ret,
            'nr': make_counter(context, 'VergangenerKursNr'),
            'title': make_counter(context, 'VergangenerKursTitel'),
            'description': '',
        })
        for _ in range(1 if context.quick else 10):
            pastevent.add_participant(rs, ret, acourse, persona(context),
                                      False, False)
    return ret


def mailinglist(context):
    rs = context.script.rs()
    ml = context.script.make_backend('ml', proxy=False)
    data = cdedb.models.ml.MemberOptInMailinglist(
            id=vtypes.CreationID(vtypes.ProtoID(-1)),
            local_part=vtypes.EmailLocalPart(make_counter(context, 'EmailLocalPart')),
            domain=const.MailinglistDomain.lists,
            description='',
            attachment_policy=const.AttachmentPolicy.forbid,
            convert_html=False,
            roster_visibility=const.MailinglistRosterVisibility.none,
            is_active=True,
            maxsize=None,
            additional_footer=None,
            mod_policy=const.ModerationPolicy.unmoderated,
            moderators=[persona(context)
                        for _ in range(1 if context.quick else 3)],
            whitelist=set(),
            subject_prefix=make_counter(context, 'BetreffPrefix'),
            title=make_counter(context, 'Mailingliste'),
            notes='',
    )
    ret = ml.create_mailinglist(rs, data)
    for _ in range(1 if context.quick else 10):
        ml.do_subscription_action(
            rs, SubscriptionAction.add_subscriber, mailinglist_id=ret,
            persona_id=persona(context))
    return ret


def create_everything(context):
    if context.verbose:
        context.clock = datetime.datetime.now()
        print(f"Started at {context.clock}")
        print(f" Creating personas:", end="")
    for idx in range(context.personas * context.factor):
        if context.verbose:
            print(f" {idx}", end="")
        persona(context)
    if context.verbose:
        print()
        output_counters(context, "[persona] ")
        print(f" Creating events:", end="")
    for idx in range(context.events * context.factor):
        if context.verbose:
            print(f" {idx}", end="")
        event(context)
    if context.verbose:
        print()
        output_counters(context, "[event] ")
        print(f" Creating assemblies:", end="")
    for _ in range(context.assemblies * context.factor):
        if context.verbose:
            print(f" {idx}", end="")
        assembly(context)
    if context.verbose:
        print()
        output_counters(context, "[assembly] ")
        print(f" Creating pastevents:", end="")
    for _ in range(context.pastevents * context.factor):
        past_event(context)
    if context.verbose:
        print()
        output_counters(context, "[pastevent] ")
        print(f" Creating mailinglists:", end="")
    for _ in range(context.mailinglists * context.factor):
        mailinglist(context)
    if context.verbose:
        print()
        output_counters(context, "[mailinglist] ", final=True)
        print(f"Done in {datetime.datetime.now() - context.start}")


def perform(args):
    script = Script(persona_id=1, dbuser="cdb", check_system_user=False,
                    dry_run=False)

    args.script = script
    args.counters = collections.defaultdict(lambda: 0)
    args.clock = None
    args.start = datetime.datetime.now()

    with script:
        create_everything(args)


def main():
    if pathlib.Path("/PRODUCTIONVM").is_file():
        raise RuntimeError("Refusing to touch live instance!")
    if pathlib.Path("/OFFLINEVM").is_file():
        raise RuntimeError("Refusing to touch orga instance!")

    parser = argparse.ArgumentParser(
        description=("Insert additional sample data."
                     " Especially for load testing."))

    parser.add_argument(
        "--personas", "-p", default=1, type=int)
    parser.add_argument(
        "--events", "-e", default=1, type=int)
    parser.add_argument(
        "--assemblies", "-a", default=1, type=int)
    parser.add_argument(
        "--pastevents", "-P", default=1, type=int)
    parser.add_argument(
        "--mailinglists", "-m", default=1, type=int)
    parser.add_argument(
        "--factor", "-f", default=1, type=int)
    parser.add_argument(
        "--verbose", "-v", action='store_true')
    parser.add_argument(
        "--quick", "-q", action='store_true')

    args = parser.parse_args()

    perform(args)


if __name__ == "__main__":
    main()
