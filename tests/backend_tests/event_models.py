import datetime
import decimal

import pytz

# noinspection PyUnresolvedReferences
import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.event as models
from cdedb.common import NearlyNow
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
                1: models.EventPart(  # type: ignore[dict-item]
                    id=1,  # type: ignore[arg-type]
                    title="Warmup",
                    shortname="Wu",
                    part_begin=datetime.date(2222, 2, 2),
                    part_end=datetime.date(2222, 2, 2),
                    waitlist_field=None,
                    camping_mat_field=4,  # type: ignore[arg-type]
                ),
                2: models.EventPart(  # type: ignore[dict-item]
                    id=2,  # type: ignore[arg-type]
                    title="Erste Hälfte",
                    shortname="1.H.",
                    part_begin=datetime.date(2222, 11, 1),
                    part_end=datetime.date(2222, 11, 11),
                    waitlist_field=None,
                    camping_mat_field=4,  # type: ignore[arg-type]
                ),
                3: models.EventPart(  # type: ignore[dict-item]
                    id=3,  # type: ignore[arg-type]
                    title="Zweite Hälfte",
                    shortname="2.H.",
                    part_begin=datetime.date(2222, 11, 11),
                    part_end=datetime.date(2222, 11, 30),
                    waitlist_field=None,
                    camping_mat_field=4,  # type: ignore[arg-type]
                ),

            },
            tracks={
                1: models.CourseTrack(  # type: ignore[dict-item]
                    id=1,  # type: ignore[arg-type]
                    part_id=2,  # type: ignore[arg-type]
                    title="Morgenkreis (Erste Hälfte)",
                    shortname="Morgenkreis",
                    num_choices=4,
                    min_choices=4,
                    sortkey=1,
                    course_room_field=5,  # type: ignore[arg-type]
                ),
                2: models.CourseTrack(  # type: ignore[dict-item]
                    id=2,  # type: ignore[arg-type]
                    part_id=2,  # type: ignore[arg-type]
                    title="Kaffeekränzchen (Erste Hälfte)",
                    shortname="Kaffee",
                    num_choices=1,
                    min_choices=1,
                    sortkey=2,
                    course_room_field=5,  # type: ignore[arg-type]
                ),
                3: models.CourseTrack(  # type: ignore[dict-item]
                    id=3,  # type: ignore[arg-type]
                    part_id=3,  # type: ignore[arg-type]
                    title="Arbeitssitzung (Zweite Hälfte)",
                    shortname="Sitzung",
                    num_choices=3,
                    min_choices=2,
                    sortkey=3,
                    course_room_field=5,  # type: ignore[arg-type]
                ),
            },
            fields={
                1: models.EventField(  # type: ignore[dict-item]
                    id=1,  # type: ignore[arg-type]
                    field_name="brings_balls",  # type: ignore[arg-type]
                    title="Bringt Bälle mit",
                    kind=const.FieldDatatypes.bool,
                    association=const.FieldAssociations.registration,
                    checkin=True,
                    sortkey=0,
                    entries=None,
                ),
                2: models.EventField(  # type: ignore[dict-item]
                    id=2,  # type: ignore[arg-type]
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
                3: models.EventField(  # type: ignore[dict-item]
                    id=3,  # type: ignore[arg-type]
                    field_name="lodge",  # type: ignore[arg-type]
                    title="Zimmerwünsche",
                    kind=const.FieldDatatypes.str,
                    association=const.FieldAssociations.registration,
                    checkin=False,
                    sortkey=0,
                    entries=None,
                ),
                4: models.EventField(  # type: ignore[dict-item]
                    id=4,  # type: ignore[arg-type]
                    field_name="may_reserve",  # type: ignore[arg-type]
                    title="Würde auf Isomatte schlafen",
                    kind=const.FieldDatatypes.bool,
                    association=const.FieldAssociations.registration,
                    checkin=False,
                    sortkey=0,
                    entries=None,
                ),
                5: models.EventField(  # type: ignore[dict-item]
                    id=5,  # type: ignore[arg-type]
                    field_name="room",  # type: ignore[arg-type]
                    title="Kursraum",
                    kind=const.FieldDatatypes.str,
                    association=const.FieldAssociations.course,
                    checkin=False,
                    sortkey=0,
                    entries=None,
                ),
                6: models.EventField(  # type: ignore[dict-item]
                    id=6,  # type: ignore[arg-type]
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
                7: models.EventField(  # type: ignore[dict-item]
                    id=7,  # type: ignore[arg-type]
                    field_name="is_child",  # type: ignore[arg-type]
                    title="Ist U12",
                    kind=const.FieldDatatypes.bool,
                    association=const.FieldAssociations.registration,
                    checkin=False,
                    sortkey=0,
                    entries=None,
                ),
                8: models.EventField(  # type: ignore[dict-item]
                    id=8,  # type: ignore[arg-type]
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
                1: models.EventFee(  # type: ignore[dict-item]
                    id=1,  # type: ignore[arg-type]
                    kind=const.EventFeeType.common,
                    title='Teilnahmebeitrag Warmup',
                    amount=decimal.Decimal('10.50'),
                    condition='part.Wu',  # type: ignore[arg-type]
                    notes=None,
                ),
                2: models.EventFee(  # type: ignore[dict-item]
                    id=2,  # type: ignore[arg-type]
                    kind=const.EventFeeType.common,
                    title='Teilnahmebeitrag 1. Hälfte',
                    amount=decimal.Decimal('123.00'),
                    condition='part.1.H.',  # type: ignore[arg-type]
                    notes=None,
                ),
                3: models.EventFee(  # type: ignore[dict-item]
                    id=3,  # type: ignore[arg-type]
                    kind=const.EventFeeType.common,
                    title='Teilnahmebeitrag 2. Hälfte',
                    amount=decimal.Decimal('450.99'),
                    condition='part.2.H.',  # type: ignore[arg-type]
                    notes=None,
                ),
                4: models.EventFee(  # type: ignore[dict-item]
                    id=4,  # type: ignore[arg-type]
                    kind=const.EventFeeType.common,
                    title='Kinderpreis Warmup',
                    amount=decimal.Decimal('-5.00'),
                    condition='part.Wu and field.is_child',  # type: ignore[arg-type]
                    notes=None,
                ),
                5: models.EventFee(  # type: ignore[dict-item]
                    id=5,  # type: ignore[arg-type]
                    kind=const.EventFeeType.common,
                    title='Kinderpreis 1. Hälfte',
                    amount=decimal.Decimal('-12.00'),
                    condition='part.1.H. and field.is_child',  # type: ignore[arg-type]
                    notes=None,
                ),
                6: models.EventFee(  # type: ignore[dict-item]
                    id=6,  # type: ignore[arg-type]
                    kind=const.EventFeeType.common,
                    title='Kinderpreis 2. Hälfte',
                    amount=decimal.Decimal('-19.00'),
                    condition='part.2.H. and field.is_child',  # type: ignore[arg-type]
                    notes=None,
                ),
                7: models.EventFee(  # type: ignore[dict-item]
                    id=7,  # type: ignore[arg-type]
                    kind=const.EventFeeType.external,
                    title='Externenzusatzbeitrag',
                    amount=decimal.Decimal('5.00'),
                    condition='any_part and not (is_member or field.is_child)',  # type: ignore[arg-type]
                    notes=None,
                ),
                8: models.EventFee(  # type: ignore[dict-item]
                    id=8,  # type: ignore[arg-type]
                    kind=const.EventFeeType.solidarity,
                    title='Mengenrabatt',
                    amount=decimal.Decimal('-0.01'),
                    condition='all_parts',  # type: ignore[arg-type]
                    notes=None,
                ),
                9: models.EventFee(  # type: ignore[dict-item]
                    id=9,  # type: ignore[arg-type]
                    kind=const.EventFeeType.common,
                    title='Orgarabatt',
                    amount=decimal.Decimal('-50.00'),
                    condition='part.1.H. and part.2.H. and is_orga',  # type: ignore[arg-type]
                    notes=None,
                ),
            },
        )

        reality = self.event.new_get_event(self.key, event_id)

        self.assertEqual(
            expectation.fields,
            reality.fields,
        )
        self.assertEqual(
            expectation.to_database(),
            reality.to_database(),
        )
        self.assertEqual(
            expectation,
            reality,
        )
