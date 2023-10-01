import datetime
import decimal

import pytz

# noinspection PyUnresolvedReferences
import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.event as models
from cdedb.common import NearlyNow, nearly_now
from tests.common import BackendTest, as_users


class TestEventModels(BackendTest):
    @as_users("anton")
    def test_get_event(self) -> None:
        event_id = 1

        expectation = models.Event(
            id=vtypes.ProtoID(1),
            title="Große Testakademie 2222",
            shortname="TestAka",
            institution=const.PastInstitutions.cde,
            description="Everybody come!",
            registration_start=NearlyNow.from_datetime(datetime.datetime(
                2000, 10, 30, 0, 0, 0, tzinfo=pytz.utc)),
            registration_soft_limit=NearlyNow.from_datetime(datetime.datetime(
                2200, 10, 30, 0, 0, 0, tzinfo=pytz.utc)),
            registration_hard_limit=NearlyNow.from_datetime(datetime.datetime(
                2221, 10, 30, 0, 0, 0, tzinfo=pytz.utc)),
            iban="DE26370205000008068900",
            orga_address=vtypes.Email("aka@example.cde"),
            orgas={7},  # type: ignore[arg-type]
            registration_text=None,
            mail_text="Wir verwenden ein neues Kristallkugel-basiertes"
                      " Kurszuteilungssystem; bis wir das ordentlich ans Laufen"
                      " gebracht haben, müsst ihr leider etwas auf die Teilnehmerliste"
                      " warten.",
            participant_info="Die Kristallkugel hat gute Dienste geleistet, nicht wahr?",
            notes="Todoliste ... just kidding ;)",
            field_definition_notes="Die Sortierung der Felder bitte nicht ändern!",
            offline_lock=False,
            is_archived=False,
            is_cancelled=False,
            is_visible=True,
            is_course_list_visible=True,
            is_course_state_visible=False,
            is_participant_list_visible=False,
            is_course_assignment_visible=False,
            use_additional_questionnaire=False,
            lodge_field=3,  # type: ignore[arg-type]
            parts={
                1: models.EventPart(
                    id=1,  # type: ignore[arg-type]
                    event_id=vtypes.ProtoID(1),
                    title="Warmup",
                    shortname="Wu",
                    part_begin=datetime.date(2222, 2, 2),
                    part_end=datetime.date(2222, 2, 2),
                    waitlist_field=None,
                    camping_mat_field=4,  # type: ignore[arg-type]
                    tracks=(),  # type: ignore[arg-type]
                ),
                2: models.EventPart(
                    id=2,  # type: ignore[arg-type]
                    event_id=vtypes.ProtoID(1),
                    title="Erste Hälfte",
                    shortname="1.H.",
                    part_begin=datetime.date(2222, 11, 1),
                    part_end=datetime.date(2222, 11, 11),
                    waitlist_field=None,
                    camping_mat_field=4,  # type: ignore[arg-type]
                    tracks=(1, 2),  # type: ignore[arg-type]
                ),
                3: models.EventPart(
                    id=3,  # type: ignore[arg-type]
                    event_id=vtypes.ProtoID(1),
                    title="Zweite Hälfte",
                    shortname="2.H.",
                    part_begin=datetime.date(2222, 11, 11),
                    part_end=datetime.date(2222, 11, 30),
                    waitlist_field=None,
                    camping_mat_field=4,  # type: ignore[arg-type]
                    tracks=(3,),  # type: ignore[arg-type]
                ),

            },
            tracks={
                1: models.CourseTrack(
                    id=1,  # type: ignore[arg-type]
                    part_id=vtypes.ProtoID(2),
                    title="Morgenkreis (Erste Hälfte)",
                    shortname="Morgenkreis",
                    num_choices=4,
                    min_choices=4,
                    sortkey=1,
                    course_room_field=5,  # type: ignore[arg-type]
                ),
                2: models.CourseTrack(
                    id=2,  # type: ignore[arg-type]
                    part_id=vtypes.ProtoID(2),
                    title="Kaffeekränzchen (Erste Hälfte)",
                    shortname="Kaffee",
                    num_choices=1,
                    min_choices=1,
                    sortkey=2,
                    course_room_field=5,  # type: ignore[arg-type]
                ),
                3: models.CourseTrack(
                    id=3,  # type: ignore[arg-type]
                    part_id=vtypes.ProtoID(3),
                    title="Arbeitssitzung (Zweite Hälfte)",
                    shortname="Sitzung",
                    num_choices=3,
                    min_choices=2,
                    sortkey=3,
                    course_room_field=5,  # type: ignore[arg-type]
                ),
            },
            fields={
                1: models.EventField(
                    id=1,  # type: ignore[arg-type]
                    event_id=vtypes.ProtoID(1),
                    field_name="brings_balls",  # type: ignore[arg-type]
                    title="Bringt Bälle mit",
                    kind=const.FieldDatatypes.bool,
                    association=const.FieldAssociations.registration,
                    checkin=True,
                    sortkey=0,
                    entries=None,
                ),
                2: models.EventField(
                    id=2,  # type: ignore[arg-type]
                    event_id=vtypes.ProtoID(1),
                    field_name="transportation",  # type: ignore[arg-type]
                    title="Reist an mit",
                    kind=const.FieldDatatypes.str,
                    association=const.FieldAssociations.registration,
                    checkin=False,
                    sortkey=0,
                    entries=dict([
                        ["pedes", "by feet"],
                        ["car", "own car available"],
                        ["etc", "anything else"],
                    ]),
                ),
                3: models.EventField(
                    id=3,  # type: ignore[arg-type]
                    event_id=vtypes.ProtoID(1),
                    field_name="lodge",  # type: ignore[arg-type]
                    title="Zimmerwünsche",
                    kind=const.FieldDatatypes.str,
                    association=const.FieldAssociations.registration,
                    checkin=False,
                    sortkey=0,
                    entries=None,
                ),
                4: models.EventField(
                    id=4,  # type: ignore[arg-type]
                    event_id=vtypes.ProtoID(1),
                    field_name="may_reserve",  # type: ignore[arg-type]
                    title="Würde auf Isomatte schlafen",
                    kind=const.FieldDatatypes.bool,
                    association=const.FieldAssociations.registration,
                    checkin=False,
                    sortkey=0,
                    entries=None,
                ),
                5: models.EventField(
                    id=5,  # type: ignore[arg-type]
                    event_id=vtypes.ProtoID(1),
                    field_name="room",  # type: ignore[arg-type]
                    title="Kursraum",
                    kind=const.FieldDatatypes.str,
                    association=const.FieldAssociations.course,
                    checkin=False,
                    sortkey=0,
                    entries=None,
                ),
                6: models.EventField(
                    id=6,  # type: ignore[arg-type]
                    event_id=vtypes.ProtoID(1),
                    field_name="contamination",  # type: ignore[arg-type]
                    title="Verseuchung",
                    kind=const.FieldDatatypes.str,
                    association=const.FieldAssociations.lodgement,
                    checkin=False,
                    sortkey=0,
                    entries=dict([
                        ["high", "lots of radiation"],
                        ["medium", "elevated level of radiation"],
                        ["low", "some radiation"],
                        ["none", "no radiation"],
                    ]),
                ),
                7: models.EventField(
                    id=7,  # type: ignore[arg-type]
                    event_id=vtypes.ProtoID(1),
                    field_name="is_child",  # type: ignore[arg-type]
                    title="Ist U12",
                    kind=const.FieldDatatypes.bool,
                    association=const.FieldAssociations.registration,
                    checkin=False,
                    sortkey=0,
                    entries=None,
                ),
                8: models.EventField(
                    id=8,  # type: ignore[arg-type]
                    event_id=vtypes.ProtoID(1),
                    field_name="anzahl_GROSSBUCHSTABEN",  # type: ignore[arg-type]
                    title="Anzahl Großbuchstaben",
                    kind=const.FieldDatatypes.int,
                    association=const.FieldAssociations.registration,
                    checkin=True,
                    sortkey=0,
                    entries=None,
                )
            },
            fees={
                1: models.EventFee(
                    id=1,  # type: ignore[arg-type]
                    event_id=vtypes.ProtoID(1),
                    kind=const.EventFeeType.common,
                    title='Teilnahmebeitrag Warmup',
                    amount=decimal.Decimal('10.50'),
                    condition='part.Wu',  # type: ignore[arg-type]
                    notes=None,
                ),
                2: models.EventFee(
                    id=2,  # type: ignore[arg-type]
                    event_id=vtypes.ProtoID(1),
                    kind=const.EventFeeType.common,
                    title='Teilnahmebeitrag 1. Hälfte',
                    amount=decimal.Decimal('123.00'),
                    condition='part.1.H.',  # type: ignore[arg-type]
                    notes=None,
                ),
                3: models.EventFee(
                    id=3,  # type: ignore[arg-type]
                    event_id=vtypes.ProtoID(1),
                    kind=const.EventFeeType.common,
                    title='Teilnahmebeitrag 2. Hälfte',
                    amount=decimal.Decimal('450.99'),
                    condition='part.2.H.',  # type: ignore[arg-type]
                    notes=None,
                ),
                4: models.EventFee(
                    id=4,  # type: ignore[arg-type]
                    event_id=vtypes.ProtoID(1),
                    kind=const.EventFeeType.common,
                    title='Kinderpreis Warmup',
                    amount=decimal.Decimal('-5.00'),
                    condition='part.Wu and field.is_child',  # type: ignore[arg-type]
                    notes=None,
                ),
                5: models.EventFee(
                    id=5,  # type: ignore[arg-type]
                    event_id=vtypes.ProtoID(1),
                    kind=const.EventFeeType.common,
                    title='Kinderpreis 1. Hälfte',
                    amount=decimal.Decimal('-12.00'),
                    condition='part.1.H. and field.is_child',  # type: ignore[arg-type]
                    notes=None,
                ),
                6: models.EventFee(
                    id=6,  # type: ignore[arg-type]
                    event_id=vtypes.ProtoID(1),
                    kind=const.EventFeeType.common,
                    title='Kinderpreis 2. Hälfte',
                    amount=decimal.Decimal('-19.00'),
                    condition='part.2.H. and field.is_child',  # type: ignore[arg-type]
                    notes=None,
                ),
                7: models.EventFee(
                    id=7,  # type: ignore[arg-type]
                    event_id=vtypes.ProtoID(1),
                    kind=const.EventFeeType.external,
                    title='Externenzusatzbeitrag',
                    amount=decimal.Decimal('5.00'),
                    condition='any_part and not (is_member or field.is_child)',  # type: ignore[arg-type]
                    notes=None,
                ),
                8: models.EventFee(
                    id=8,  # type: ignore[arg-type]
                    event_id=vtypes.ProtoID(1),
                    kind=const.EventFeeType.solidarity,
                    title='Mengenrabatt',
                    amount=decimal.Decimal('-0.01'),
                    condition='all_parts',  # type: ignore[arg-type]
                    notes=None,
                ),
                9: models.EventFee(
                    id=9,  # type: ignore[arg-type]
                    event_id=vtypes.ProtoID(1),
                    kind=const.EventFeeType.common,
                    title='Orgarabatt',
                    amount=decimal.Decimal('-50.00'),
                    condition='part.1.H. and part.2.H. and is_orga',  # type: ignore[arg-type]
                    notes=None,
                ),
            },
            part_groups={},
            track_groups={},
        )

        reality = self.event.get_event(self.key, event_id)

        self.assertEqual(
            expectation.fields,
            reality.fields,
        )
        self.assertEqual(
            expectation.to_database(),
            reality.to_database(),
        )
        self.assertEqual(
            vars(expectation),
            vars(reality),
        )

        event_id = vtypes.ProtoID(4)

        expectation = models.Event(
            id=event_id,
            title="TripelAkademie",
            shortname="triaka",
            institution=const.PastInstitutions.cde,
            description="Ich habe gehört, du magst DoppelAkademien, also habe ich"
                        " eine DoppelAkademie in Deine DoppelAkademie gepackt.",
            registration_start=nearly_now(),
            registration_soft_limit=None,
            registration_hard_limit=None,
            iban="DE26370205000008068900",
            orga_address=None,
            orgas={5},  # type: ignore[arg-type]
            registration_text=None,
            mail_text=None,
            participant_info=None,
            notes=None,
            field_definition_notes=None,
            offline_lock=False,
            is_archived=False,
            is_cancelled=False,
            is_visible=True,
            is_course_list_visible=True,
            is_course_state_visible=False,
            is_participant_list_visible=False,
            is_course_assignment_visible=False,
            use_additional_questionnaire=False,
            lodge_field=None,
            parts={
                6: models.EventPart(
                    id=6,  # type: ignore[arg-type]
                    event_id=event_id,
                    title="1. Hälfte Oberwesel",
                    shortname="O1",
                    part_begin=datetime.date(3000, 1, 1),
                    part_end=datetime.date(3000, 2, 1),
                    waitlist_field=None,
                    camping_mat_field=None,
                    tracks=(6,),  # type: ignore[arg-type]
                ),
                7: models.EventPart(
                    id=7,  # type: ignore[arg-type]
                    event_id=event_id,
                    title="1. Hälfte Windischleuba",
                    shortname="W1",
                    part_begin=datetime.date(3000, 1, 1),
                    part_end=datetime.date(3000, 2, 1),
                    waitlist_field=None,
                    camping_mat_field=None,
                    tracks=(7,),  # type: ignore[arg-type]
                ),
                8: models.EventPart(
                    id=8,  # type: ignore[arg-type]
                    event_id=event_id,
                    title="1. Hälfte Kaub",
                    shortname="K1",
                    part_begin=datetime.date(3000, 1, 1),
                    part_end=datetime.date(3000, 2, 1),
                    waitlist_field=None,
                    camping_mat_field=None,
                    tracks=(8,),  # type: ignore[arg-type]
                ),
                9: models.EventPart(
                    id=9,  # type: ignore[arg-type]
                    event_id=event_id,
                    title="2. Hälfte Oberwesel",
                    shortname="O2",
                    part_begin=datetime.date(3000, 2, 1),
                    part_end=datetime.date(3000, 3, 1),
                    waitlist_field=None,
                    camping_mat_field=None,
                    tracks=(9, 10),  # type: ignore[arg-type]
                ),
                10: models.EventPart(
                    id=10,  # type: ignore[arg-type]
                    event_id=event_id,
                    title="2. Hälfte Windischleuba",
                    shortname="W2",
                    part_begin=datetime.date(3000, 2, 1),
                    part_end=datetime.date(3000, 3, 1),
                    waitlist_field=None,
                    camping_mat_field=None,
                    tracks=(11, 12),  # type: ignore[arg-type]
                ),
                11: models.EventPart(
                    id=11,  # type: ignore[arg-type]
                    event_id=event_id,
                    title="2. Hälfte Kaub",
                    shortname="K2",
                    part_begin=datetime.date(3000, 2, 1),
                    part_end=datetime.date(3000, 3, 1),
                    waitlist_field=None,
                    camping_mat_field=None,
                    tracks=(13, 14, 15),  # type: ignore[arg-type]
                ),
                12: models.EventPart(
                    id=12,  # type: ignore[arg-type]
                    event_id=event_id,
                    title="Silvesterfeier",
                    shortname="Feier",
                    part_begin=datetime.date(2999, 12, 31),
                    part_end=datetime.date(3000, 1, 1),
                    waitlist_field=None,
                    camping_mat_field=None,
                    tracks=(),  # type: ignore[arg-type]
                )
            },
            # parts=self.event.get_event(self.key, event_id).parts,
            tracks=self.event.get_event(self.key, event_id).tracks,
            fields={},
            fees={
                16: models.EventFee(
                    id=16,  # type: ignore[arg-type]
                    event_id=event_id,
                    kind=const.EventFeeType.common,
                    title="Unkostenbeitrag Silvesterfeier",
                    amount=decimal.Decimal("4.20"),
                    condition="part.Feier",  # type: ignore[arg-type]
                    notes=None,
                ),
            },
            part_groups={
                1: models.PartGroup(
                    id=1,  # type: ignore[arg-type]
                    event_id=event_id,
                    title="1. Hälfte",
                    shortname="1.H.",
                    notes=None,
                    constraint_type=const.EventPartGroupType.Statistic,
                    parts=(6, 7, 8),  # type: ignore[arg-type]
                ),
                2: models.PartGroup(
                    id=2,  # type: ignore[arg-type]
                    event_id=event_id,
                    title="2. Hälfte",
                    shortname="2.H.",
                    notes=None,
                    constraint_type=const.EventPartGroupType.Statistic,
                    parts=(9, 10, 11),  # type: ignore[arg-type]
                ),
                3: models.PartGroup(
                    id=3,  # type: ignore[arg-type]
                    event_id=event_id,
                    title="Oberwesel",
                    shortname="OW",
                    notes=None,
                    constraint_type=const.EventPartGroupType.Statistic,
                    parts=(6, 9),  # type: ignore[arg-type]
                ),
                4: models.PartGroup(
                    id=4,  # type: ignore[arg-type]
                    event_id=event_id,
                    title="Windischleuba",
                    shortname="WS",
                    notes=None,
                    constraint_type=const.EventPartGroupType.Statistic,
                    parts=(7, 10),  # type: ignore[arg-type]
                ),
                5: models.PartGroup(
                    id=5,  # type: ignore[arg-type]
                    event_id=event_id,
                    title="Kaub",
                    shortname="KA",
                    notes=None,
                    constraint_type=const.EventPartGroupType.Statistic,
                    parts=(8, 11),  # type: ignore[arg-type]
                ),
                6: models.PartGroup(
                    id=6,  # type: ignore[arg-type]
                    event_id=event_id,
                    title="Teilnehmer 1. Hälfte",
                    shortname="TN 1H",
                    notes=None,
                    constraint_type=const.EventPartGroupType.mutually_exclusive_participants,
                    parts=(6, 7, 8),  # type: ignore[arg-type]
                ),
                7: models.PartGroup(
                    id=7,  # type: ignore[arg-type]
                    event_id=event_id,
                    title="Teilnehmer 2. Hälfte",
                    shortname="TN 2H",
                    notes=None,
                    constraint_type=const.EventPartGroupType.mutually_exclusive_participants,
                    parts=(9, 10, 11),  # type: ignore[arg-type]
                ),
                8: models.PartGroup(
                    id=8,  # type: ignore[arg-type]
                    event_id=event_id,
                    title="Kurse 1. Hälfte",
                    shortname="Kurs 1H",
                    notes=None,
                    constraint_type=const.EventPartGroupType.mutually_exclusive_courses,
                    parts=(6, 7, 8),  # type: ignore[arg-type]
                ),
                9: models.PartGroup(
                    id=9,  # type: ignore[arg-type]
                    event_id=event_id,
                    title="Kurse 2. Hälfte",
                    shortname="Kurs 2H",
                    notes=None,
                    constraint_type=const.EventPartGroupType.mutually_exclusive_courses,
                    parts=(9, 10, 11),  # type: ignore[arg-type]
                ),
            },
            track_groups={
                1: models.SyncTrackGroup(
                    id=1,  # type: ignore[arg-type]
                    event_id=event_id,
                    title="Kurs 1. Hälfte",
                    shortname="Kurs1",
                    notes=None,
                    constraint_type=const.CourseTrackGroupType.course_choice_sync,
                    sortkey=1,
                    tracks=(6, 7, 8),  # type: ignore[arg-type]
                ),
                2: models.SyncTrackGroup(
                    id=2,  # type: ignore[arg-type]
                    event_id=event_id,
                    title="Kurs 2. Hälfte nachmittags",
                    shortname="Kurs2n",
                    notes=None,
                    constraint_type=const.CourseTrackGroupType.course_choice_sync,
                    sortkey=4,
                    tracks=(10, 12, 14),  # type: ignore[arg-type]
                ),
                3: models.SyncTrackGroup(
                    id=3,  # type: ignore[arg-type]
                    event_id=event_id,
                    title="Kurs 2. Hälfte morgens",
                    shortname="Kurs2m",
                    notes=None,
                    constraint_type=const.CourseTrackGroupType.course_choice_sync,
                    sortkey=3,
                    tracks=(9, 11, 13),  # type: ignore[arg-type]
                ),
            }
        )

        reality = self.event.get_event(self.key, event_id)

        # print()
        # pprint(expectation.parts)
        # print()
        # print()
        # pprint(reality.parts)

        self.assertEqual(expectation.tracks, reality.tracks)
        self.assertEqual(expectation.parts, reality.parts)
        self.assertEqual(expectation.track_groups, reality.track_groups)
        self.assertEqual(expectation.part_groups, reality.part_groups)
        self.assertEqual(expectation, reality)

    @as_users("anton")
    def test_get_courses(self) -> None:
        course_id = 1
        # print(self.event.new_get_course(self.key, course_id))

        expectation = models.Course(
            id=course_id,  # type: ignore[arg-type]
            event_id=1,  # type: ignore[arg-type]
            segments={1, 3},  # type: ignore[arg-type]
            active_segments={1, 3},  # type: ignore[arg-type]
            nr='α',
            title='Planetenretten für Anfänger',
            shortname='Heldentum',
            description='Wir werden die Bäume drücken.',
            instructors='ToFi & Co',
            min_size=2,
            max_size=10,
            notes='Promotionen in Mathematik und Ethik für Teilnehmer notwendig.',
            fields={'room': 'Wald'}
        )
        reality = self.event.new_get_course(self.key, course_id)

        self.assertEqual(
            expectation,
            reality,
        )

        course_ids = [1, 2]
        # print(self.event.new_get_courses(self.key, course_ids))

        expectation = {
            1: expectation,
            2: models.Course(
                id=2,  # type: ignore[arg-type]
                event_id=1,  # type: ignore[arg-type]
                segments={1, 2, 3},  # type: ignore[arg-type]
                active_segments={1, 3},  # type: ignore[arg-type]
                nr='β',
                title='Lustigsein für Fortgeschrittene',
                shortname='Kabarett',
                description='Inklusive Post, Backwaren und frühzeitigem Ableben.',
                instructors='Bernd Lucke',
                min_size=10,
                max_size=20,
                notes='Kursleiter hat Sekt angefordert.',
                fields={'room': 'Theater'}
            )
        }
        reality = self.event.new_get_courses(self.key, course_ids)

        self.assertEqual(
            expectation,
            reality,
        )

    @as_users("anton")
    def test_get_lodgements(self) -> None:
        lodgement_id = 1
        # print(self.event.new_get_lodgement(self.key, lodgement_id))

        expectation = models.Lodgement(
            id=lodgement_id,  # type: ignore[arg-type]
            event_id=1,  # type: ignore[arg-type]
            group=models.LodgementGroup(
                id=2,  # type: ignore[arg-type]
                event_id=1,  # type: ignore[arg-type]
                title='AußenWohnGruppe',
                lodgement_ids={1},
                regular_capacity=5,
                camping_mat_capacity=1,
            ),
            group_id=2,  # type: ignore[arg-type]
            title='Warme Stube',
            regular_capacity=5,
            camping_mat_capacity=1,
            notes=None,
            fields={'contamination': 'high'},
        )

        reality = self.event.new_get_lodgement(self.key, lodgement_id)

        self.assertEqual(
            vars(expectation),
            vars(reality),
        )

        event_id = 1
        lodgement_ids = self.event.list_lodgements(self.key, event_id)
        # print(self.event.new_get_lodgements(self.key, lodgement_ids))

        expectation = {
            1: models.Lodgement(
                id=1,  # type: ignore[arg-type]
                event_id=1,  # type: ignore[arg-type]
                group=models.LodgementGroup(
                    id=2,  # type: ignore[arg-type]
                    event_id=event_id,  # type: ignore[arg-type]
                    title="AußenWohnGruppe",
                    lodgement_ids={1},
                    regular_capacity=5,
                    camping_mat_capacity=1,
                ),
                group_id=2,  # type: ignore[arg-type]
                title='Warme Stube',
                regular_capacity=5,
                camping_mat_capacity=1,
                notes=None,
                fields={'contamination': 'high'}),
            2: models.Lodgement(
                id=2,  # type: ignore[arg-type]
                event_id=1,  # type: ignore[arg-type]
                group=models.LodgementGroup(
                    id=1,  # type: ignore[arg-type]
                    event_id=event_id,  # type: ignore[arg-type]
                    title="Haupthaus",
                    lodgement_ids={2, 4},
                    regular_capacity=11,
                    camping_mat_capacity=2,
                ),
                group_id=1,  # type: ignore[arg-type]
                title='Kalte Kammer',
                regular_capacity=10,
                camping_mat_capacity=2,
                notes='Dafür mit Frischluft.',
                fields={'contamination': 'none'}),
            3: models.Lodgement(
                id=3,  # type: ignore[arg-type]
                event_id=1,  # type: ignore[arg-type]
                group=models.LodgementGroup(
                    id=3,  # type: ignore[arg-type]
                    event_id=event_id,  # type: ignore[arg-type]
                    title="Sonstige",
                    lodgement_ids={3},
                    regular_capacity=0,
                    camping_mat_capacity=100,
                ),
                group_id=3,  # type: ignore[arg-type]
                title='Kellerverlies',
                regular_capacity=0,
                camping_mat_capacity=100,
                notes='Nur für Notfälle.',
                fields={'contamination': 'low'}),
            4: models.Lodgement(
                id=4,  # type: ignore[arg-type]
                event_id=1,  # type: ignore[arg-type]
                group=models.LodgementGroup(
                    id=1,  # type: ignore[arg-type]
                    event_id=event_id,  # type: ignore[arg-type]
                    title="Haupthaus",
                    lodgement_ids={2, 4},
                    regular_capacity=11,
                    camping_mat_capacity=2,
                ),
                group_id=1,  # type: ignore[arg-type]
                title='Einzelzelle',
                regular_capacity=1,
                camping_mat_capacity=0,
                notes=None,
                fields={'contamination': 'high'}),
        }

        reality = self.event.new_get_lodgements(self.key, lodgement_ids)

        self.assertEqual(
            expectation,
            reality,
        )

    @as_users("anton")
    def test_get_lodgement_groups(self) -> None:
        event_id = 1
        # print(self.event.new_get_lodgement_groups(self.key, event_id))

        expectation = {
            1: models.LodgementGroup(
                id=1,  # type: ignore[arg-type]
                event_id=event_id,  # type: ignore[arg-type]
                title="Haupthaus",
                lodgement_ids={2, 4},
                regular_capacity=11,
                camping_mat_capacity=2,
            ),
            2: models.LodgementGroup(
                id=2,  # type: ignore[arg-type]
                event_id=event_id,  # type: ignore[arg-type]
                title="AußenWohnGruppe",
                lodgement_ids={1},
                regular_capacity=5,
                camping_mat_capacity=1,
            ),
            3: models.LodgementGroup(
                id=3,  # type: ignore[arg-type]
                event_id=event_id,  # type: ignore[arg-type]
                title="Sonstige",
                lodgement_ids={3},
                regular_capacity=0,
                camping_mat_capacity=100,
            ),
        }

        reality = self.event.new_get_lodgement_groups(self.key, event_id)

        self.assertEqual(
            expectation,
            reality,
        )
