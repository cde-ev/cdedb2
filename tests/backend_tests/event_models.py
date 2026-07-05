import datetime
import decimal

# noinspection PyUnresolvedReferences
import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.event as models
from cdedb.common import NearlyNow, nearly_now
from cdedb.common.parse.util import Accounts
from cdedb.common.query import QueryScope
from cdedb.models.event.questionnaire import make_default_questionnaire
from tests.common import BackendTest, as_users
from tests.other_tests.test_validation import NO_COMPARE, TestValidationBase

EventID = lambda x: vtypes.EventID(vtypes.ID(x))


class TestEventModels(BackendTest):
    @as_users("anton")
    def test_get_event(self) -> None:
        event_id = EventID(1)

        expectation = models.Event(
            id=event_id,
            title="Große Testakademie 2222",
            shortname="TestAka",
            institution=const.PastInstitutions.cde,
            description="Everybody come!",
            iban=Accounts.Sozialbank,
            orga_address=vtypes.Email("aka@example.cde"),
            website_url='https://www.cde-ev.de/',
            registration_start=NearlyNow.from_datetime(
                datetime.datetime(2000, 10, 30, 0, 0, 0, tzinfo=datetime.UTC)
            ),
            registration_soft_limit=NearlyNow.from_datetime(
                datetime.datetime(2200, 10, 30, 0, 0, 0, tzinfo=datetime.UTC)
            ),
            registration_hard_limit=NearlyNow.from_datetime(
                datetime.datetime(2221, 10, 30, 0, 0, 0, tzinfo=datetime.UTC)
            ),
            orgas={7},  # type: ignore[arg-type]
            registration_text=None,
            mail_text="Wir verwenden ein neues Kristallkugel-basiertes"
            " Kurszuteilungssystem; bis wir das ordentlich ans Laufen"
            " gebracht haben, müsst ihr leider etwas auf die Teilnehmerliste"
            " warten.",
            participant_info="Die Kristallkugel hat gute Dienste geleistet,"
            " nicht wahr?",
            notes="Todoliste ... just kidding ;)",
            field_definition_notes="Die Sortierung der Felder bitte nicht ändern!",
            is_locked=False,
            is_archived=False,
            is_cancelled=False,
            is_balanced=False,
            is_registration_approved=True,
            is_visible=True,
            is_course_list_visible=True,
            is_course_state_visible=False,
            is_participant_list_visible=False,
            is_course_assignment_visible=False,
            use_additional_questionnaire=False,
            notify_on_registration=const.NotifyOnRegistration.everytime,
            reimbursement_iban_field_id=None,
            lodge_field_id=vtypes.ID(3),
            parts={
                1: models.EventPart(
                    id=vtypes.ID(1),
                    event_id=event_id,
                    title="Warmup",
                    shortname=vtypes.Identifier("Wu"),
                    part_begin=datetime.date(2222, 2, 2),
                    part_end=datetime.date(2222, 2, 2),
                    waitlist_field_id=None,
                    camping_mat_field_id=vtypes.ID(4),
                    tracks=(),  # type: ignore[arg-type]
                ),
                2: models.EventPart(
                    id=vtypes.ID(2),
                    event_id=event_id,
                    title="Erste Hälfte",
                    shortname=vtypes.Identifier("1.H."),
                    part_begin=datetime.date(2222, 11, 1),
                    part_end=datetime.date(2222, 11, 11),
                    waitlist_field_id=None,
                    camping_mat_field_id=vtypes.ID(4),
                    tracks=(1, 2),  # type: ignore[arg-type]
                ),
                3: models.EventPart(
                    id=vtypes.ID(3),
                    event_id=event_id,
                    title="Zweite Hälfte",
                    shortname=vtypes.Identifier("2.H."),
                    part_begin=datetime.date(2222, 11, 11),
                    part_end=datetime.date(2222, 11, 30),
                    waitlist_field_id=None,
                    camping_mat_field_id=vtypes.ID(4),
                    tracks=(3,),  # type: ignore[arg-type]
                ),
            },
            tracks={
                1: models.CourseTrack(
                    id=vtypes.ID(1),
                    part_id=vtypes.ID(2),
                    title="Morgenkreis (Erste Hälfte)",
                    shortname="Morgenkreis",
                    num_choices=vtypes.NonNegativeInt(4),
                    min_choices=vtypes.NonNegativeInt(4),
                    sortkey=1,
                    course_room_field_id=vtypes.ID(5),
                ),
                2: models.CourseTrack(
                    id=vtypes.ID(2),
                    part_id=vtypes.ID(2),
                    title="Kaffeekränzchen (Erste Hälfte)",
                    shortname="Kaffee",
                    num_choices=vtypes.NonNegativeInt(1),
                    min_choices=vtypes.NonNegativeInt(1),
                    sortkey=2,
                    course_room_field_id=vtypes.ID(5),
                ),
                3: models.CourseTrack(
                    id=vtypes.ID(3),
                    part_id=vtypes.ID(3),
                    title="Arbeitssitzung (Zweite Hälfte)",
                    shortname="Sitzung",
                    num_choices=vtypes.NonNegativeInt(3),
                    min_choices=vtypes.NonNegativeInt(2),
                    sortkey=3,
                    course_room_field_id=vtypes.ID(5),
                ),
            },
            fields={
                1: models.RegistrationField(
                    id=vtypes.ID(1),
                    event_id=event_id,
                    field_name="brings_balls",  # type: ignore[arg-type]
                    kind=const.FieldDatatypes.bool,
                    association=const.FieldAssociations.registration,
                    title="Bringt Bälle mit",
                    sort_group=None,
                    sortkey=0,
                    description=None,
                    checkin=True,
                    entries=None,
                ),
                2: models.RegistrationField(
                    id=vtypes.ID(2),
                    event_id=event_id,
                    field_name="transportation",  # type: ignore[arg-type]
                    kind=const.FieldDatatypes.str,
                    association=const.FieldAssociations.registration,
                    title="Reist an mit",
                    sort_group=None,
                    sortkey=0,
                    description=None,
                    checkin=False,
                    entries=dict([
                        ["pedes", "by feet"],
                        ["car", "own car available"],
                        ["etc", "anything else"],
                    ]),
                ),
                3: models.RegistrationField(
                    id=vtypes.ID(3),
                    event_id=event_id,
                    field_name="lodge",  # type: ignore[arg-type]
                    kind=const.FieldDatatypes.str_multiline,
                    association=const.FieldAssociations.registration,
                    title="Zimmerwünsche",
                    sort_group=None,
                    sortkey=0,
                    description=None,
                    checkin=False,
                    entries=None,
                ),
                4: models.RegistrationField(
                    id=vtypes.ID(4),
                    event_id=event_id,
                    field_name="may_reserve",  # type: ignore[arg-type]
                    kind=const.FieldDatatypes.bool,
                    association=const.FieldAssociations.registration,
                    title="Würde auf Isomatte schlafen",
                    sort_group=None,
                    sortkey=0,
                    description=None,
                    checkin=False,
                    entries=None,
                ),
                5: models.CourseField(
                    id=vtypes.ID(5),
                    event_id=event_id,
                    field_name="room",  # type: ignore[arg-type]
                    kind=const.FieldDatatypes.str,
                    association=const.FieldAssociations.course,
                    title="Kursraum",
                    sort_group=None,
                    sortkey=0,
                    description=None,
                    entries=None,
                ),
                6: models.LodgementField(
                    id=vtypes.ID(6),
                    event_id=event_id,
                    field_name="contamination",  # type: ignore[arg-type]
                    kind=const.FieldDatatypes.str,
                    association=const.FieldAssociations.lodgement,
                    title="Verseuchung",
                    sort_group=None,
                    sortkey=0,
                    description=None,
                    entries=dict([
                        ["high", "lots of radiation"],
                        ["medium", "elevated level of radiation"],
                        ["low", "some radiation"],
                        ["none", "no radiation"],
                    ]),
                ),
                7: models.RegistrationField(
                    id=vtypes.ID(7),
                    event_id=event_id,
                    field_name="is_child",  # type: ignore[arg-type]
                    kind=const.FieldDatatypes.bool,
                    association=const.FieldAssociations.registration,
                    title="Ist U12",
                    sort_group=None,
                    sortkey=0,
                    description=None,
                    checkin=False,
                    entries=None,
                ),
                8: models.RegistrationField(
                    id=vtypes.ID(8),
                    event_id=event_id,
                    field_name="anzahl_GROSSBUCHSTABEN",  # type: ignore[arg-type]
                    kind=const.FieldDatatypes.int,
                    association=const.FieldAssociations.registration,
                    title="Anzahl Großbuchstaben",
                    sort_group=None,
                    sortkey=0,
                    description=None,
                    checkin=True,
                    entries=None,
                ),
                9: models.RegistrationField(
                    id=vtypes.ID(9),
                    event_id=event_id,
                    field_name="arrival_at",  # type: ignore[arg-type]
                    kind=const.FieldDatatypes.datetime,
                    association=const.FieldAssociations.registration,
                    title="Anreise um",
                    sort_group=None,
                    sortkey=0,
                    description=None,
                    checkin=False,
                    entries=None,
                ),
                10: models.RegistrationField(
                    id=vtypes.ID(10),
                    event_id=event_id,
                    field_name="arrival_date",  # type: ignore[arg-type]
                    kind=const.FieldDatatypes.date,
                    association=const.FieldAssociations.registration,
                    title="Anreisetag",
                    sort_group=None,
                    sortkey=0,
                    description=None,
                    checkin=False,
                    entries={
                        None: "gar nicht",
                        datetime.date.fromisoformat("2025-12-31"): "Sylvester",
                        datetime.date.fromisoformat("2026-01-01"): "Neujahr",
                    },
                ),
            },
            custom_query_filters={
                1: models.CustomQueryFilter(
                    id=vtypes.ID(1),
                    event_id=event_id,
                    scope=QueryScope.registration,
                    title="Bälle oder Kind?",
                    notes=None,
                    fields={
                        "reg_fields.xfield_brings_balls",
                        "reg_fields.xfield_is_child",
                    },
                ),
                2: models.CustomQueryFilter(
                    id=vtypes.ID(2),
                    event_id=event_id,
                    scope=QueryScope.registration,
                    title="Kind oder Bälle?",
                    notes=None,
                    fields={
                        "reg_fields.xfield_is_child",
                        "reg_fields.xfield_brings_balls",
                    },
                ),
                3: models.CustomQueryFilter(
                    id=vtypes.ID(3),
                    event_id=event_id,
                    scope=QueryScope.registration,
                    title="Alle Notizen",
                    notes=None,
                    fields={
                        "reg.notes",
                        "reg.orga_notes",
                    },
                ),
                4: models.CustomQueryFilter(
                    id=vtypes.ID(4),
                    event_id=event_id,
                    scope=QueryScope.registration,
                    title="Bad Combo!",
                    notes=None,
                    fields={
                        "reg.amount_paid",
                        "persona.birthday",
                    },
                ),
                5: models.CustomQueryFilter(
                    id=vtypes.ID(5),
                    event_id=event_id,
                    scope=QueryScope.registration,
                    title="Extrem wichtig!",
                    notes="Ups, hätte ich das Feld nicht löschen sollen?",
                    fields={
                        "reg_fields.xfield_anzahl_GROSSBUCHSTABEN",
                        "reg_fields.xfield_deleted_field",
                    },
                ),
            },
            fees={
                1: models.EventFee(
                    id=vtypes.ID(1),
                    event_id=event_id,
                    kind=const.EventFeeType.common,
                    title='Teilnahmebeitrag Warmup',
                    amount=decimal.Decimal('10.50'),
                    condition='part.Wu',  # type: ignore[arg-type]
                    notes=None,
                ),
                2: models.EventFee(
                    id=vtypes.ID(2),
                    event_id=event_id,
                    kind=const.EventFeeType.common,
                    title='Teilnahmebeitrag 1. Hälfte',
                    amount=decimal.Decimal('123.00'),
                    condition='part.1.H.',  # type: ignore[arg-type]
                    notes=None,
                ),
                3: models.EventFee(
                    id=vtypes.ID(3),
                    event_id=event_id,
                    kind=const.EventFeeType.common,
                    title='Teilnahmebeitrag 2. Hälfte',
                    amount=decimal.Decimal('450.99'),
                    condition='part.2.H.',  # type: ignore[arg-type]
                    notes=None,
                ),
                4: models.EventFee(
                    id=vtypes.ID(4),
                    event_id=event_id,
                    kind=const.EventFeeType.common,
                    title='Kinderpreis Warmup',
                    amount=decimal.Decimal('-5.00'),
                    condition='part.Wu and age.U13',  # type: ignore[arg-type]
                    notes=None,
                ),
                5: models.EventFee(
                    id=vtypes.ID(5),
                    event_id=event_id,
                    kind=const.EventFeeType.common,
                    title='Kinderpreis 1. Hälfte',
                    amount=decimal.Decimal('-12.00'),
                    condition='part.1.H. and age.U16',  # type: ignore[arg-type]
                    notes=None,
                ),
                6: models.EventFee(
                    id=vtypes.ID(6),
                    event_id=event_id,
                    kind=const.EventFeeType.common,
                    title='Kinderpreis 2. Hälfte',
                    amount=decimal.Decimal('-19.00'),
                    condition='part.2.H. and age.U18',  # type: ignore[arg-type]
                    notes=None,
                ),
                7: models.EventFee(
                    id=vtypes.ID(7),
                    event_id=event_id,
                    kind=const.EventFeeType.external,
                    title='Externenzusatzbeitrag',
                    amount=decimal.Decimal('5.00'),
                    condition='any_part and not (is_member or field.is_child)',  # type: ignore[arg-type]
                    notes=None,
                ),
                8: models.EventFee(
                    id=vtypes.ID(8),
                    event_id=event_id,
                    kind=const.EventFeeType.solidary_reduction,
                    title='Mengenrabatt',
                    amount=decimal.Decimal('-0.01'),
                    condition='all_parts',  # type: ignore[arg-type]
                    notes=None,
                ),
                9: models.EventFee(
                    id=vtypes.ID(9),
                    event_id=event_id,
                    kind=const.EventFeeType.common,
                    title='Orgarabatt',
                    amount=decimal.Decimal('-50.00'),
                    condition='part.1.H. and part.2.H. and is_orga',  # type: ignore[arg-type]
                    notes=None,
                ),
                10: models.EventFee(
                    id=vtypes.ID(10),
                    event_id=event_id,
                    kind=const.EventFeeType.instructor_refund,
                    title="KL-Erstattung",
                    notes="Individuelle Höhe",
                    amount=None,
                    condition=None,
                    amount_min=decimal.Decimal('-30.00'),
                    amount_max=decimal.Decimal('-20.00'),
                ),
            },
            part_groups={},
            track_groups={},
            checkin_helpers={vtypes.PersonaID(vtypes.ID(38))},
        )

        reality = self.event.get_event(self.key, event_id)

        self.assertEqual(expectation.parts, reality.parts)
        self.assertEqual(expectation.tracks, reality.tracks)
        self.assertEqual(expectation.fields, reality.fields)
        self.assertEqual(expectation.custom_query_filters, reality.custom_query_filters)
        self.assertEqual(expectation.fees, reality.fees)
        self.assertEqual(expectation.to_database(), reality.to_database())
        self.assertEqual(vars(expectation), vars(reality))
        self.assertEqual(expectation, reality)

        event_id = EventID(4)

        expectation = models.Event(
            id=event_id,
            title="TripelAkademie",
            shortname="triaka",
            institution=const.PastInstitutions.cde,
            iban=Accounts.Skatbank,
            orga_address=None,
            website_url=None,
            description="Ich habe gehört, du magst DoppelAkademien, also habe ich"
            " eine DoppelAkademie in Deine DoppelAkademie gepackt.",
            registration_start=nearly_now(),
            registration_soft_limit=None,
            registration_hard_limit=None,
            orgas={5},  # type: ignore[arg-type]
            registration_text=None,
            mail_text=None,
            participant_info=None,
            notes=None,
            field_definition_notes=None,
            is_locked=False,
            is_archived=False,
            is_cancelled=False,
            is_balanced=False,
            is_registration_approved=True,
            is_visible=True,
            is_course_list_visible=True,
            is_course_state_visible=False,
            is_participant_list_visible=False,
            is_course_assignment_visible=False,
            use_additional_questionnaire=False,
            notify_on_registration=const.NotifyOnRegistration.everytime,
            reimbursement_iban_field_id=None,
            lodge_field_id=None,
            parts={
                6: models.EventPart(
                    id=vtypes.ID(6),
                    event_id=event_id,
                    title="1. Hälfte Oberwesel",
                    shortname=vtypes.Identifier("O1"),
                    part_begin=datetime.date(3000, 1, 1),
                    part_end=datetime.date(3000, 2, 1),
                    waitlist_field_id=None,
                    camping_mat_field_id=None,
                    tracks=(6,),  # type: ignore[arg-type]
                ),
                7: models.EventPart(
                    id=vtypes.ID(7),
                    event_id=event_id,
                    title="1. Hälfte Windischleuba",
                    shortname=vtypes.Identifier("W1"),
                    part_begin=datetime.date(3000, 1, 1),
                    part_end=datetime.date(3000, 2, 1),
                    waitlist_field_id=None,
                    camping_mat_field_id=None,
                    tracks=(7,),  # type: ignore[arg-type]
                ),
                8: models.EventPart(
                    id=vtypes.ID(8),
                    event_id=event_id,
                    title="1. Hälfte Kaub",
                    shortname=vtypes.Identifier("K1"),
                    part_begin=datetime.date(3000, 1, 1),
                    part_end=datetime.date(3000, 2, 1),
                    waitlist_field_id=None,
                    camping_mat_field_id=None,
                    tracks=(8,),  # type: ignore[arg-type]
                ),
                9: models.EventPart(
                    id=vtypes.ID(9),
                    event_id=event_id,
                    title="2. Hälfte Oberwesel",
                    shortname=vtypes.Identifier("O2"),
                    part_begin=datetime.date(3000, 2, 1),
                    part_end=datetime.date(3000, 3, 1),
                    waitlist_field_id=None,
                    camping_mat_field_id=None,
                    tracks=(9, 10),  # type: ignore[arg-type]
                ),
                10: models.EventPart(
                    id=10,  # type: ignore[arg-type]
                    event_id=event_id,
                    title="2. Hälfte Windischleuba",
                    shortname=vtypes.Identifier("W2"),
                    part_begin=datetime.date(3000, 2, 1),
                    part_end=datetime.date(3000, 3, 1),
                    waitlist_field_id=None,
                    camping_mat_field_id=None,
                    tracks=(11, 12),  # type: ignore[arg-type]
                ),
                11: models.EventPart(
                    id=11,  # type: ignore[arg-type]
                    event_id=event_id,
                    title="2. Hälfte Kaub",
                    shortname=vtypes.Identifier("K2"),
                    part_begin=datetime.date(3000, 2, 1),
                    part_end=datetime.date(3000, 3, 1),
                    waitlist_field_id=None,
                    camping_mat_field_id=None,
                    tracks=(13, 14, 15),  # type: ignore[arg-type]
                ),
                12: models.EventPart(
                    id=12,  # type: ignore[arg-type]
                    event_id=event_id,
                    title="Silvesterfeier",
                    shortname=vtypes.Identifier("Feier"),
                    part_begin=datetime.date(2999, 12, 31),
                    part_end=datetime.date(3000, 1, 1),
                    waitlist_field_id=None,
                    camping_mat_field_id=None,
                    tracks=(),  # type: ignore[arg-type]
                ),
            },
            # parts=self.event.get_event(self.key, event_id).parts,
            tracks=self.event.get_event(self.key, event_id).tracks,
            fields={},
            custom_query_filters={},
            fees={
                17: models.EventFee(
                    id=17,  # type: ignore[arg-type]
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
                    id=vtypes.ID(1),
                    event_id=event_id,
                    title="1. Hälfte",
                    shortname="1.H.",
                    notes=None,
                    constraint_type=const.EventPartGroupType.Statistic,
                    part_ids={6, 7, 8},
                ),
                2: models.PartGroup(
                    id=vtypes.ID(2),
                    event_id=event_id,
                    title="2. Hälfte",
                    shortname="2.H.",
                    notes=None,
                    constraint_type=const.EventPartGroupType.Statistic,
                    part_ids={9, 10, 11},
                ),
                3: models.PartGroup(
                    id=vtypes.ID(3),
                    event_id=event_id,
                    title="Oberwesel",
                    shortname="OW",
                    notes=None,
                    constraint_type=const.EventPartGroupType.Statistic,
                    part_ids={6, 9},
                ),
                4: models.PartGroup(
                    id=vtypes.ID(4),
                    event_id=event_id,
                    title="Windischleuba",
                    shortname="WS",
                    notes=None,
                    constraint_type=const.EventPartGroupType.Statistic,
                    part_ids={7, 10},
                ),
                5: models.PartGroup(
                    id=vtypes.ID(5),
                    event_id=event_id,
                    title="Kaub",
                    shortname="KA",
                    notes=None,
                    constraint_type=const.EventPartGroupType.Statistic,
                    part_ids={8, 11},
                ),
                6: models.PartGroup(
                    id=vtypes.ID(6),
                    event_id=event_id,
                    title="Teilnehmer 1. Hälfte",
                    shortname="TN 1H",
                    notes=None,
                    constraint_type=const.EventPartGroupType.mutually_exclusive_participants,
                    part_ids={6, 7, 8},
                ),
                7: models.PartGroup(
                    id=vtypes.ID(7),
                    event_id=event_id,
                    title="Teilnehmer 2. Hälfte",
                    shortname="TN 2H",
                    notes=None,
                    constraint_type=const.EventPartGroupType.mutually_exclusive_participants,
                    part_ids={9, 10, 11},
                ),
                10: models.PartGroup(
                    id=10,  # type: ignore[arg-type]
                    event_id=event_id,
                    title="Mailingliste Windischleuba",
                    shortname="ML W",
                    notes=None,
                    constraint_type=const.EventPartGroupType.mailinglist_link,
                    part_ids={7, 10},
                ),
            },
            track_groups={
                1: models.SyncTrackGroup(
                    id=vtypes.ID(1),
                    event_id=event_id,
                    title="Kurs 1. Hälfte",
                    shortname="Kurs1",
                    notes=None,
                    constraint_type=const.CourseTrackGroupType.course_choice_sync,
                    sortkey=1,
                    track_ids={6, 7, 8},
                ),
                2: models.SyncTrackGroup(
                    id=vtypes.ID(2),
                    event_id=event_id,
                    title="Kurs 2. Hälfte nachmittags",
                    shortname="Kurs2n",
                    notes=None,
                    constraint_type=const.CourseTrackGroupType.course_choice_sync,
                    sortkey=4,
                    track_ids={10, 12, 14},
                ),
                3: models.SyncTrackGroup(
                    id=vtypes.ID(3),
                    event_id=event_id,
                    title="Kurs 2. Hälfte morgens",
                    shortname="Kurs2m",
                    notes=None,
                    constraint_type=const.CourseTrackGroupType.course_choice_sync,
                    sortkey=3,
                    track_ids={9, 11, 13},
                ),
                4: models.TrackGroup(
                    id=vtypes.ID(4),
                    event_id=event_id,
                    title="Kurse 1. Hälfte",
                    shortname="Kurs 1H",
                    notes=None,
                    sortkey=1,
                    constraint_type=(
                        const.CourseTrackGroupType.mutually_exclusive_courses
                    ),
                    track_ids={6, 7, 8},
                ),
                5: models.TrackGroup(
                    id=vtypes.ID(5),
                    event_id=event_id,
                    title="Kurse 2. Hälfte nachmittags",
                    shortname="Kurs 2Hn",
                    notes=None,
                    sortkey=4,
                    constraint_type=(
                        const.CourseTrackGroupType.mutually_exclusive_courses
                    ),
                    track_ids={10, 12, 14},
                ),
                6: models.TrackGroup(
                    id=vtypes.ID(6),
                    event_id=event_id,
                    title="Kurse 2. Hälfte morgens",
                    shortname="Kurs 2Hm",
                    notes=None,
                    sortkey=3,
                    constraint_type=(
                        const.CourseTrackGroupType.mutually_exclusive_courses
                    ),
                    track_ids={9, 11, 13},
                ),
            },
        )

        reality = self.event.get_event(self.key, event_id)

        # print()
        # pprint(expectation.parts)
        # print()
        # print()
        # pprint(reality.parts)

        self.assertEqual(expectation.tracks, reality.tracks)
        self.assertEqual(expectation.parts, reality.parts)
        self.assertEqual(expectation.fields, reality.fields)
        self.assertEqual(expectation.custom_query_filters, reality.custom_query_filters)
        self.assertEqual(expectation.fees, reality.fees)
        self.assertEqual(expectation.track_groups, reality.track_groups)
        self.assertEqual(expectation.part_groups, reality.part_groups)
        self.assertEqual(expectation.to_database(), expectation.to_database())
        self.assertEqual(vars(expectation), vars(reality))
        self.assertEqual(expectation, reality)

    @as_users("anton")
    def test_get_courses(self) -> None:
        course_id = vtypes.ID(1)
        event_id = EventID(1)

        expectation = models.Course(
            id=course_id,
            event_id=event_id,
            segments={
                1: models.CourseSegment(
                    id=vtypes.ID(-1),
                    course_id=course_id,
                    track_id=vtypes.ID(1),
                    is_active=True,
                ),
                3: models.CourseSegment(
                    id=vtypes.ID(-1),
                    course_id=course_id,
                    track_id=vtypes.ID(3),
                    is_active=True,
                ),
            },
            nr='α',
            title='Planetenretten für Anfänger',
            shortname='Heldentum',
            description='Wir werden die Bäume drücken.',
            instructors='ToFi & Co',
            min_size=vtypes.NonNegativeInt(2),
            max_size=vtypes.NonNegativeInt(10),
            is_visible=True,
            notes='Promotionen in Mathematik und Ethik für Teilnehmer notwendig.',
            fields=vtypes.EventAssociatedFields({'room': 'Wald'}),
        )
        reality = self.event.get_course(self.key, course_id)

        self.assertEqual(expectation.as_dict(), reality.as_dict())
        self.assertEqual(expectation, reality)

        course_ids = [1, 2]

        expectation = {
            1: expectation,
            2: models.Course(
                id=vtypes.ID(2),
                event_id=event_id,
                segments={
                    1: models.CourseSegment(
                        id=vtypes.ID(-1),
                        course_id=vtypes.ID(2),
                        track_id=vtypes.ID(1),
                        is_active=True,
                    ),
                    2: models.CourseSegment(
                        id=vtypes.ID(-1),
                        course_id=vtypes.ID(2),
                        track_id=vtypes.ID(2),
                        is_active=False,
                    ),
                    3: models.CourseSegment(
                        id=vtypes.ID(-1),
                        course_id=vtypes.ID(2),
                        track_id=vtypes.ID(3),
                        is_active=True,
                    ),
                },
                nr='β',
                title='Lustigsein für Fortgeschrittene',
                shortname='Kabarett',
                description='Inklusive Post, Backwaren und frühzeitigem Ableben.',
                instructors='Bernd Lucke',
                min_size=vtypes.NonNegativeInt(10),
                max_size=vtypes.NonNegativeInt(20),
                is_visible=True,
                notes='Kursleiter hat Sekt angefordert.',
                fields=vtypes.EventAssociatedFields({'room': 'Theater'}),
            ),
        }
        reality = self.event.get_courses(self.key, course_ids)

        self.assertEqual(
            expectation,
            reality,
        )

    @as_users("anton")
    def test_get_lodgements(self) -> None:
        lodgement_id = vtypes.ID(1)
        event_id = EventID(1)

        expectation = models.Lodgement(
            id=lodgement_id,
            event_id=event_id,
            group=models.LodgementGroup(
                id=vtypes.ID(2),
                event_id=event_id,
                title='AußenWohnGruppe',
                lodgement_ids={1},
                regular_capacity=5,
                camping_mat_capacity=1,
            ),
            group_id=vtypes.ID(2),
            title='Warme Stube',
            regular_capacity=vtypes.NonNegativeInt(5),
            camping_mat_capacity=vtypes.NonNegativeInt(1),
            notes=None,
            fields=vtypes.EventAssociatedFields({'contamination': 'high'}),
        )

        reality = self.event.new_get_lodgement(self.key, lodgement_id)

        self.assertEqual(expectation.as_dict(), reality.as_dict())
        self.assertEqual(expectation, reality)

        lodgement_ids = self.event.list_lodgements(self.key, event_id)

        expectation = {
            1: models.Lodgement(
                id=vtypes.ID(1),
                event_id=event_id,
                group=models.LodgementGroup(
                    id=vtypes.ID(2),
                    event_id=event_id,
                    title="AußenWohnGruppe",
                    lodgement_ids={1},
                    regular_capacity=5,
                    camping_mat_capacity=1,
                ),
                group_id=vtypes.ID(2),
                title='Warme Stube',
                regular_capacity=vtypes.NonNegativeInt(5),
                camping_mat_capacity=vtypes.NonNegativeInt(1),
                notes=None,
                fields=vtypes.EventAssociatedFields({'contamination': 'high'}),
            ),
            2: models.Lodgement(
                id=vtypes.ID(2),
                event_id=event_id,
                group=models.LodgementGroup(
                    id=vtypes.ID(1),
                    event_id=event_id,
                    title="Haupthaus",
                    lodgement_ids={2, 4},
                    regular_capacity=11,
                    camping_mat_capacity=2,
                ),
                group_id=vtypes.ID(1),
                title='Kalte Kammer',
                regular_capacity=vtypes.NonNegativeInt(10),
                camping_mat_capacity=vtypes.NonNegativeInt(2),
                notes='Dafür mit Frischluft.',
                fields=vtypes.EventAssociatedFields({'contamination': 'none'}),
            ),
            3: models.Lodgement(
                id=vtypes.ID(3),
                event_id=event_id,
                group=models.LodgementGroup(
                    id=vtypes.ID(3),
                    event_id=event_id,
                    title="Sonstige",
                    lodgement_ids={3},
                    regular_capacity=0,
                    camping_mat_capacity=100,
                ),
                group_id=vtypes.ID(3),
                title='Kellerverlies',
                regular_capacity=vtypes.NonNegativeInt(0),
                camping_mat_capacity=vtypes.NonNegativeInt(100),
                notes='Nur für Notfälle.',
                fields=vtypes.EventAssociatedFields({'contamination': 'low'}),
            ),
            4: models.Lodgement(
                id=vtypes.ID(4),
                event_id=event_id,
                group=models.LodgementGroup(
                    id=vtypes.ID(1),
                    event_id=event_id,
                    title="Haupthaus",
                    lodgement_ids={2, 4},
                    regular_capacity=11,
                    camping_mat_capacity=2,
                ),
                group_id=vtypes.ID(1),
                title='Einzelzelle',
                regular_capacity=vtypes.NonNegativeInt(1),
                camping_mat_capacity=vtypes.NonNegativeInt(0),
                notes=None,
                fields=vtypes.EventAssociatedFields({'contamination': 'high'}),
            ),
        }
        reality = self.event.new_get_lodgements(self.key, lodgement_ids)

        self.assertEqual(expectation, reality)

    @as_users("anton")
    def test_get_lodgement_groups(self) -> None:
        event_id = EventID(1)

        expectation = {
            1: models.LodgementGroup(
                id=vtypes.ID(1),
                event_id=event_id,
                title="Haupthaus",
                lodgement_ids={2, 4},
                regular_capacity=vtypes.NonNegativeInt(11),
                camping_mat_capacity=2,
            ),
            2: models.LodgementGroup(
                id=vtypes.ID(2),
                event_id=event_id,
                title="AußenWohnGruppe",
                lodgement_ids={1},
                regular_capacity=5,
                camping_mat_capacity=1,
            ),
            3: models.LodgementGroup(
                id=vtypes.ID(3),
                event_id=event_id,
                title="Sonstige",
                lodgement_ids={3},
                regular_capacity=0,
                camping_mat_capacity=100,
            ),
        }

        reality = self.event.get_lodgement_groups(self.key, event_id)

        self.assertEqual(
            expectation,
            reality,
        )


class TestEventValidation(BackendTest, TestValidationBase):
    @as_users("garcia")
    def test_questionnaire_validation(self) -> None:
        event = self.event.get_event(self.key, EventID(1))

        # Check that field id is required for FieldRow.
        self.do_validator_test(
            models.questionnaire.QuestionnaireFieldRow,
            [
                (
                    {
                        "kind": const.QuestionnaireUsages.additional,
                        "role": const.QuestionnaireRowRole.event_field,
                        "field_id": None,
                    },
                    None,
                    ValueError("Must not be empty. (field_id)"),
                )
            ],
            extraparams={"available_fields": event.fields},
        )
        # Check again using QuestionnaireRow, which delegates.
        self.do_validator_test(
            models.questionnaire.QuestionnaireRow,
            [
                (
                    {
                        "kind": const.QuestionnaireUsages.additional,
                        "role": const.QuestionnaireRowRole.event_field,
                        "field_id": None,
                    },
                    None,
                    ValueError("Must not be empty. (field_id)"),
                )
            ],
            extraparams={"available_fields": event.fields},
        )

        all_questionnaires = self.event.get_all_questionnaires(self.key, event.id)
        # Check required field id for full questionnaire validation.
        self.do_validator_test(
            vtypes.Questionnaire,
            [
                (
                    [
                        {
                            "role": const.QuestionnaireRowRole.event_field,
                            "field_id": None,
                        },
                    ],
                    None,
                    ValueError("Must not be empty. (field_id_0)"),
                ),
            ],
            extraparams={
                "kind": const.QuestionnaireUsages.additional,
                "all_questionnaires": all_questionnaires,
            },
        )

        self.do_validator_test(
            vtypes.Questionnaire,
            [
                # Check that course choices may not be duplicated.
                (
                    [
                        *make_default_questionnaire(event)[
                            const.QuestionnaireUsages.registration
                        ],
                        {
                            "kind": const.QuestionnaireUsages.registration,
                            "role": const.QuestionnaireRowRole.course_choices,
                        },
                    ],
                    None,
                    ValueError(
                        "Must not duplicate this role: 'CourseChoices'. (role_4)"
                    ),
                ),
                # Check that foto notice must not be missing.
                (
                    make_default_questionnaire(event)[
                        const.QuestionnaireUsages.registration
                    ][:-3],
                    None,
                    ValueError("Missing role: 'FotoNotice'. (questionnaire)"),
                ),
                # Check that fee preview may be present multiple times.
                (
                    [
                        *make_default_questionnaire(event)[
                            const.QuestionnaireUsages.registration
                        ],
                        {
                            "kind": const.QuestionnaireUsages.registration,
                            "role": const.QuestionnaireRowRole.fee_preview,
                        },
                    ],
                    NO_COMPARE,
                    None,
                ),
            ],
            extraparams={
                "kind": const.QuestionnaireUsages.registration,
                "all_questionnaires": all_questionnaires,
            },
        )
