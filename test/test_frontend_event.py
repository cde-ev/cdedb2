#!/usr/bin/env python3
import csv
import json
import datetime
import unittest
import webtest
from test.common import as_users, USER_DICT, FrontendTest, nearly_now

from cdedb.query import QueryOperators
from cdedb.common import now
from cdedb.database.constants import FieldDatatypes, FieldAssociations

class TestEventFrontend(FrontendTest):
    @as_users("emilia")
    def test_index(self, user):
        self.traverse({'href': '/event/'})
        self.assertPresence("Große Testakademie 2222")
        self.assertNonPresence("PfingstAkademie 2014")
        self.assertNonPresence("CdE-Party 2050")

    @as_users("anton", "berta")
    def test_index_orga(self, user):
        self.traverse({'href': '/event/'})
        self.assertPresence("CdE-Party 2050")

    @as_users("emilia")
    def test_showuser(self, user):
        self.traverse({'href': '/core/self/show'})
        self.assertTitle("{} {}".format(user['given_names'],
                                        user['family_name']))

    @as_users("emilia")
    def test_changeuser(self, user):
        self.traverse({'href': '/core/self/show'}, {'href': '/core/self/change'})
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['location'] = "Hyrule"
        self.submit(f)
        self.assertPresence("Hyrule")
        self.assertEqual(
            "Zelda",
            self.response.lxml.get_element_by_id('displayname').text_content().strip())

    @as_users("anton", "ferdinand")
    def test_adminchangeuser(self, user):
        self.realm_admin_view_profile('emilia', 'event')
        self.traverse({'href': '/core/persona/5/adminchange'})
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['birthday'] = "3.4.1933"
        self.assertNotIn('free_form', f.fields)
        self.submit(f)
        self.assertPresence("Zelda")
        self.assertTitle("Emilia E. Eventis")
        self.assertPresence("03.04.1933")

    @as_users("anton", "ferdinand")
    def test_toggleactivity(self, user):
        self.realm_admin_view_profile('emilia', 'event')
        self.assertEqual(
            True,
            self.response.lxml.get_element_by_id('activity_checkbox').get('data-checked') == 'True')
        f = self.response.forms['activitytoggleform']
        self.submit(f)
        self.assertEqual(
            False,
            self.response.lxml.get_element_by_id('activity_checkbox').get('data-checked') == 'True')

    @as_users("anton", "ferdinand")
    def test_user_search(self, user):
        self.traverse({'href': '/event/$'}, {'href': '/event/search/user'})
        self.assertTitle("Veranstaltungsnutzersuche")
        f = self.response.forms['queryform']
        f['qop_username'] = QueryOperators.similar.value
        f['qval_username'] = 'a@'
        for field in f.fields:
            if field and field.startswith('qsel_'):
                f[field].checked = True
        self.submit(f)
        self.assertTitle("Veranstaltungsnutzersuche")
        self.assertPresence("Ergebnis [1]")
        self.assertPresence("Hohle Gasse 13")

    @as_users("anton", "ferdinand")
    def test_create_user(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/search/user'},
                      {'href': '/event/user/create'})
        self.assertTitle("Neuen Veranstaltungsnutzer anlegen")
        data = {
            "username": 'zelda@example.cde',
            "title": "Dr.",
            "given_names": "Zelda",
            "family_name": "Zeruda-Hime",
            "name_supplement": 'von und zu',
            "display_name": 'Zelda',
            "birthday": "5.6.1987",
            "gender": "1",
            "telephone": "030456790",
            ## "mobile"
            "address": "Street 7",
            "address_supplement": "on the left",
            "postal_code": "12345",
            "location": "Lynna",
            "country": "Hyrule",
            "notes": "some talk",
        }
        f = self.response.forms['newuserform']
        for key, value in data.items():
            f.set(key, value)
        self.submit(f)
        self.assertTitle("Zelda Zeruda-Hime")
        self.assertPresence("12345")

    @as_users("anton")
    def test_list_events(self, user):
        self.traverse({'href': '/event/$'}, {'href': '/event/event/list'})
        self.assertTitle("Veranstaltungen verwalten")
        self.assertPresence("Große Testakademie 2222")
        self.assertPresence("CdE-Party 2050")
        self.assertNonPresence("PfingstAkademie 2014")

    @as_users("anton", "berta", "emilia")
    def test_show_event(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'})
        self.assertTitle("Große Testakademie 2222")
        self.assertPresence("Everybody come!")
        # TODO

    @as_users("anton", "berta", "emilia")
    def test_course_list(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/course/list'})
        self.assertTitle("Kursliste Große Testakademie 2222")
        self.assertNonPresence("Everybody come!")
        self.assertPresence("ToFi")
        self.assertPresence("Wir werden die Bäume drücken.")

    @as_users("anton", "garcia", "ferdinand")
    def test_change_event(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/change'})
        self.assertTitle("Große Testakademie 2222 – Konfiguration")
        ## basic event data
        f = self.response.forms['changeeventform']
        self.assertEqual(f['registration_start'].value, "2000-10-30T01:00:00")
        f['title'] = "Universale Akademie"
        f['registration_start'] = "2001-10-30 00:00:00"
        f['notes'] = """Some

        more

        text"""
        f['use_questionnaire'].checked = True
        self.submit(f)
        self.assertTitle("Universale Akademie")
        self.assertNonPresence("30.10.2000")
        self.assertPresence("30.10.2001")
        ## orgas
        self.assertNonPresence("Bertålotta")
        f = self.response.forms['addorgaform']
        f['orga_id'] = "DB-2-7"
        self.submit(f)
        self.assertTitle("Universale Akademie")
        self.assertPresence("Bertålotta")
        f = self.response.forms['removeorgaform2']
        self.submit(f)
        self.assertTitle("Universale Akademie")
        self.assertNonPresence("Bertålotta")

    @as_users("garcia")
    def test_orga_rate_limit(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'})
        for i in range(7):
            self.assertTitle("Große Testakademie 2222")
            self.assertNonPresence("Bertålotta")
            f = self.response.forms['addorgaform']
            f['orga_id'] = "DB-2-7"
            if i == 6:
                break
            self.submit(f)
            self.assertTitle("Große Testakademie 2222")
            self.assertPresence("Bertålotta")
            f = self.response.forms['removeorgaform2']
            self.submit(f)
            self.assertTitle("Große Testakademie 2222")
            self.assertNonPresence("Bertålotta")
        f = self.response.forms['addorgaform']
        f['orga_id'] = "DB-2-7"
        self.submit(f, check_notification=False)
        self.assertTitle("Große Testakademie 2222")
        self.assertNonPresence("Bertålotta")
        self.assertIn("alert alert-danger", self.response.text)

    def test_event_visibility(self):
        # Add a course track, a course and move the registration start to one
        # week in the future.
        self.login(USER_DICT['anton'])
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/2/show'},
                      {'href': '/event/event/2/part/summary'})
        f = self.response.forms['partsummaryform']
        f['track_title_4_-1'] = "Spätschicht"
        f['track_shortname_4_-1'] = "Spät"
        f['track_create_4_-1'].checked = True
        self.submit(f)
        self.traverse({'href': '/event/event/2/course/stats'},
                      {'href': '/event/event/2/course/create'})
        f = self.response.forms['createcourseform']
        f['title'] = "Chillout mit Musik"
        f['nr'] = "1"
        f['shortname'] = "music"
        f['instructors'] = "Giorgio Moroder"
        self.submit(f)
        self.traverse({'href': '/event/event/2/change'})
        f = self.response.forms['changeeventform']
        f['registration_start'] =\
            (now() + datetime.timedelta(days=7)).isoformat()
        self.submit(f)

        # Check visibility for orga
        self.traverse({'href': '/event/event/2/course/list'})
        self.assertPresence("Chillout mit Musik")
        # Check for inexistence of links to event, invisible event page, but
        # visible course page
        self.logout()
        self.login(USER_DICT['emilia'])
        self.assertNotIn('/event/event/2/show', self.response.text)
        self.traverse({'href': '/event/$'})
        self.assertNotIn('/event/event/2/show', self.response.text)
        self.get('/event/event/2/course/list')
        self.assertPresence("Chillout mit Musik")
        self.assertNotIn('/event/event/2/show', self.response.text)
        self.get('/event/event/2/show', status=403)

        # Now, the other way round: visible event without visible course list
        self.get('/')
        self.logout()
        self.login(USER_DICT['anton'])
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/2/show'},
                      {'href': '/event/event/2/change'})
        f = self.response.forms['changeeventform']
        f['is_course_list_visible'] = False
        f['is_visible'] = True
        self.submit(f)
        self.traverse({'href': '/event/event/2/course/list'})
        self.assertPresence("Chillout mit Musik")
        self.logout()

        self.login(USER_DICT['emilia'])
        self.traverse({'href': '/event/event/2/show'})
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/2/show'})
        self.assertPresence("Let's have a party!")
        self.assertNotIn('/event/event/2/course/list', self.response.text)
        self.get('/event/event/2/course/list')
        self.follow()
        self.assertPresence("Die Kursliste ist noch nicht öffentlich",
                            'notifications')

    @as_users("anton", "garcia")
    def test_part_summary_trivial(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/part/summary'})
        self.assertTitle("Veranstaltungsteile konfigurieren (Große Testakademie 2222)")
        f = self.response.forms['partsummaryform']
        self.assertEqual("Warmup", f['title_1'].value)

    @as_users("anton")
    def test_part_summary_complex(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/2/show'},
                      {'href': '/event/event/2/part/summary'})
        self.assertTitle("Veranstaltungsteile konfigurieren (CdE-Party 2050)")
        f = self.response.forms['partsummaryform']
        self.assertNotIn('title_5', f.fields)
        f['create_-1'].checked = True
        f['title_-1'] = "Cooldown"
        f['shortname_-1'] = "cd"
        f['part_begin_-1'] = "2233-4-5"
        f['part_end_-1'] = "2233-6-7"
        f['fee_-1'] = "23456.78"
        f['track_create_-1_-1'].checked = True
        f['track_title_-1_-1'] = "Chillout Training"
        f['track_shortname_-1_-1'] = "Chillout"
        f['track_num_choices_-1_-1'] = "1"
        f['track_sortkey_-1_-1'] = "1"
        self.submit(f)
        self.assertTitle("Veranstaltungsteile konfigurieren (CdE-Party 2050)")
        f = self.response.forms['partsummaryform']
        self.assertEqual("Cooldown", f['title_5'].value)
        self.assertEqual("cd", f['shortname_5'].value)
        self.assertEqual("Chillout Training", f['track_title_5_4'].value)
        f['title_5'] = "Größere Hälfte"
        f['fee_5'] = "99.99"
        self.submit(f)
        ## and now for tracks
        self.assertTitle("Veranstaltungsteile konfigurieren (CdE-Party 2050)")
        f = self.response.forms['partsummaryform']
        self.assertNotIn('track_5_5', f.fields)
        f['track_title_5_-1'] = "Spätschicht"
        f['track_shortname_5_-1'] = "Spät"
        f['track_num_choices_5_-1'] = "3"
        f['track_sortkey_5_-1'] = "1"
        f['track_create_5_-1'].checked = True
        self.submit(f)
        f = self.response.forms['partsummaryform']
        self.assertEqual("Spätschicht", f['track_title_5_5'].value)
        f['track_title_5_5'] = "Nachtschicht"
        f['track_shortname_5_5'] = "Nacht"
        self.submit(f)
        f = self.response.forms['partsummaryform']
        self.assertEqual("Nachtschicht", f['track_title_5_5'].value)
        self.assertEqual("Nacht", f['track_shortname_5_5'].value)
        f['track_delete_5_5'].checked = True
        self.submit(f)
        self.assertTitle("Veranstaltungsteile konfigurieren (CdE-Party 2050)")
        f = self.response.forms['partsummaryform']
        self.assertNotIn('track_title_5_5', f.fields)
        ## finally deletion
        self.assertTitle("Veranstaltungsteile konfigurieren (CdE-Party 2050)")
        f = self.response.forms['partsummaryform']
        self.assertEqual("Größere Hälfte", f['title_5'].value)
        f['delete_5'].checked = True
        self.submit(f)
        self.assertTitle("Veranstaltungsteile konfigurieren (CdE-Party 2050)")
        f = self.response.forms['partsummaryform']
        self.assertNotIn('title_5', f.fields)

    @as_users("garcia")
    def test_aposteriori_change_num_choices(self, user):
        # Increase number of course choices of track 2 ("Kaffekränzchen")
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/part/summary'})
        f = self.response.forms['partsummaryform']
        f['track_num_choices_2_2'] = "2"
        self.submit(f)

        # Change course choices as Orga
        self.traverse({'href': '/event/event/1/registration/query'},
                      {'description': 'Alle Anmeldungen'},
                      {'href': '/event/event/1/registration/3/show'},
                      {'href': '/event/event/1/registration/3/change'})
        f = self.response.forms['changeregistrationform']
        self.assertEqual('', f['track2.course_choice_1'].value)
        f['track2.course_choice_0'] = 3
        self.submit(f)
        self.traverse({'href': '/event/event/1/registration/3/change'})
        f = self.response.forms['changeregistrationform']
        self.assertEqual('', f['track2.course_choice_1'].value)

        # Amend registration with new choice and check via course_choices
        self.traverse({'href': '/event/event/1/registration/status'},
                      {'href': '/event/event/1/registration/amend'})
        f = self.response.forms['amendregistrationform']
        self.assertEqual('3', f['course_choice2_0'].value)
        # Check preconditions for second part
        self.assertIsNotNone(f.get('course_choice1_3', default=None))
        f['course_choice2_1'] = 4
        self.submit(f)
        self.traverse({'href': '/event/event/1/course/choices'})
        f = self.response.forms['choicefilterform']
        f['track_id'] = 2
        f['course_id'] = 4
        f['position'] = 1
        self.submit(f)
        self.assertPresence("Garcia")

        # Reduce number of course choices of track 1 ("Morgenkreis")
        self.traverse({'href': '/event/event/1/part/summary'})
        f = self.response.forms['partsummaryform']
        f['track_num_choices_2_1'] = "3"
        self.submit(f)

        # Check registration as Orga
        self.traverse({'href': '/event/event/1/registration/query'},
                      {'description': 'Alle Anmeldungen'},
                      {'href': '/event/event/1/registration/3/show'})
        self.assertPresence('3. Wahl')
        self.assertNonPresence('4. Wahl')
        self.assertNonPresence('ε. Backup')

        # Amend registration
        self.traverse({'href': '/event/event/1/registration/status'})
        self.assertNonPresence('4. Wahl')
        self.assertNonPresence('ε. Backup')
        self.traverse({'href': '/event/event/1/registration/amend'})
        f = self.response.forms['amendregistrationform']
        self.assertEqual('1', f['course_choice1_2'].value)
        self.assertIsNone(f.get('course_choice1_3', default=None))
        f['course_choice1_0'] = 2
        f['course_choice1_1'] = 4
        self.submit(f)

        # Change registration as orga
        self.traverse({'href': '/event/event/1/registration/query'},
                      {'description': 'Alle Anmeldungen'},
                      {'href': '/event/event/1/registration/3/show'},
                      {'href': '/event/event/1/registration/3/change'})
        f = self.response.forms['changeregistrationform']
        self.assertIsNone(f.get('track1.course_choice_3', default=None))
        self.assertEqual('4', f['track1.course_choice_1'].value)
        self.assertEqual('1', f['track1.course_choice_2'].value)
        f['track1.course_choice_2'] = ''
        self.submit(f)
        self.assertNonPresence('Heldentum')

    @as_users("anton", "garcia")
    def test_change_event_fields(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/field/summary'})
        ## fields
        f = self.response.forms['fieldsummaryform']
        self.assertEqual('transportation', f['field_name_2'].value)
        self.assertNotIn('field_name_10', f.fields)
        f['create_-1'].checked = True
        f['field_name_-1'] = "food_stuff"
        f['association_-1'] = FieldAssociations.registration.value
        f['kind_-1'] = FieldDatatypes.str.value
        f['entries_-1'] = """all;everything goes
        vegetarian;no meat
        vegan;plants only"""
        self.submit(f)
        self.assertTitle("Datenfelder konfigurieren (Große Testakademie 2222)")
        f = self.response.forms['fieldsummaryform']
        self.assertEqual('food_stuff', f['field_name_7'].value)
        self.assertEqual("""pedes;by feet
car;own car available
etc;anything else""", f['entries_2'].value)
        f['entries_2'] = """pedes;by feet
        broom;flying implements
        etc;anything else"""
        self.submit(f)
        self.assertTitle("Datenfelder konfigurieren (Große Testakademie 2222)")
        f = self.response.forms['fieldsummaryform']
        self.assertEqual("""pedes;by feet
broom;flying implements
etc;anything else""", f['entries_2'].value)
        f['delete_7'].checked = True
        self.submit(f)
        self.assertTitle("Datenfelder konfigurieren (Große Testakademie 2222)")
        f = self.response.forms['fieldsummaryform']
        self.assertNotIn('field_name_7', f.fields)

    @as_users("anton")
    def test_event_fields_unique_name(self, user):
        self.get("/event/event/1/field/summary")
        f = self.response.forms['fieldsummaryform']
        f['delete_1'].checked = True
        f['create_-1'].checked = True
        f['field_name_-1'] = f['field_name_1'].value
        f['association_-1'] = FieldAssociations.registration.value
        f['kind_-1'] = FieldDatatypes.str.value
        self.submit(f, check_notification=False)
        self.assertPresence("Feldname nicht eindeutig.")
        f = self.response.forms['fieldsummaryform']
        self.assertIn('field_name_1', f.fields)
        self.assertNotIn('field_name_7', f.fields)

        f = self.response.forms['fieldsummaryform']
        # If the form would be valid in the first turn, we would need the
        # following (hacky) code to add the fields, which are normally added by
        # Javascript.
        # for field in (webtest.forms.Checkbox(f, 'input', 'create_-2', 100,
        #                                      value='True'),
        #               webtest.forms.Text(f, 'input', 'field_name_-2', 101),
        #               webtest.forms.Text(f, 'input', 'association_-2', 102),
        #               webtest.forms.Text(f, 'input', 'kind_-2', 103)):
        #     f.fields.setdefault(field.name, []).append(field)
        #     f.field_order.append((field.name, field))

        f['create_-1'].checked = True
        f['field_name_-1'] = "food_stuff"
        f['association_-1'] = FieldAssociations.registration.value
        f['kind_-1'] = FieldDatatypes.str.value
        f['create_-2'].checked = True
        f['field_name_-2'] = "food_stuff"
        f['association_-2'] = FieldAssociations.registration.value
        f['kind_-2'] = FieldDatatypes.str.value
        self.submit(f, check_notification=False)
        self.assertPresence("Feldname nicht eindeutig.")

    @as_users("anton")
    def test_event_fields_datatype(self, user):
        self.get("/event/event/1/field/summary")
        f = self.response.forms['fieldsummaryform']
        f['create_-1'].checked = True
        f['field_name_-1'] = "invalid"
        f['association_-1'] = FieldAssociations.registration.value
        f['kind_-1'].force_value("invalid")
        self.submit(f, check_notification=False)
        self.assertTitle("Datenfelder konfigurieren (Große Testakademie 2222)")
        self.assertPresence("Validierung fehlgeschlagen.", div="notifications")
        self.assertPresence("Ungültige Eingabe für eine Ganzzahl.")
        f['create_-1'].checked = True
        f['field_name_-1'] = "invalid"
        f['association_-1'] = FieldAssociations.registration.value
        f['kind_-1'].force_value(sum(x for x in FieldDatatypes))
        self.submit(f, check_notification=False)
        self.assertTitle("Datenfelder konfigurieren (Große Testakademie 2222)")
        self.assertPresence("Validierung fehlgeschlagen.", div="notifications")
        self.assertPresence("Ungültige Eingabe für Enumeration <enum 'FieldDatatypes'>.")

    @as_users("anton")
    def test_event_fields_change_datatype(self, user):
        # First, remove the "lodge" field from the questionaire and the event's,
        # so it can be deleted
        self.get("/event/event/1/questionnaire/summary")
        f = self.response.forms['questionnairesummaryform']
        f['delete_5'].checked = True
        self.submit(f)
        self.get("/event/event/1/change")
        f = self.response.forms['changeeventform']
        f['lodge_field'] = ''
        self.submit(f)

        # Change datatype of "transportation" field to datetime and delete
        # options, delete and recreate "lodge" field with int type.
        self.get("/event/event/1/field/summary")
        f = self.response.forms['fieldsummaryform']
        f['kind_2'] = FieldDatatypes.datetime.value
        f['entries_2'] = ""
        f['delete_3'].checked = True
        self.submit(f)
        f = self.response.forms['fieldsummaryform']
        f['create_-1'].checked = True
        f['field_name_-1'] = "lodge"
        f['association_-1'] = FieldAssociations.registration.value
        f['kind_-1'] = FieldDatatypes.int.value
        self.submit(f)

        # No page of the orga area should be broken by this
        self.traverse({'href': '/event/event/1/course/choices'},
                      {'href': '/event/event/1/stats'},
                      {'href': '/event/event/1/course/stats'},
                      {'href': '/event/event/1/checkin'},
                      {'href': '/event/event/1/registration/query'},
                      {'description': 'Alle Anmeldungen'})
        f = self.response.forms['queryform']
        f['qsel_reg_fields.xfield_lodge'].checked = True
        f['qsel_reg_fields.xfield_transportation'].checked = True
        self.submit(f)
        f = self.response.forms['queryform']
        f['qop_reg_fields.xfield_transportation'] = QueryOperators.empty.value
        self.submit(f)
        self.traverse({'href': '/event/event/1/registration/1/show'},
                      {'href': '/event/event/1/registration/1/change'})

    @as_users("anton")
    def test_event_fields_boolean(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/field/summary'})
        f = self.response.forms['fieldsummaryform']
        f['create_-1'].checked = True
        f['field_name_-1'] = "notevil"
        f['association_-1'] = FieldAssociations.registration.value
        f['kind_-1'] = FieldDatatypes.bool.value
        f['entries_-1'] = """True;definitely
        False;no way!"""
        self.submit(f)
        self.assertTitle("Datenfelder konfigurieren (Große Testakademie 2222)")
        self.traverse({'href': '/event/event/1/show'},
                      {'href': '/event/event/1/change'})
        f = self.response.forms['changeeventform']
        f['use_questionnaire'].checked = True
        self.submit(f)
        self.traverse({'href': '/event/event/1/questionnaire/summary'})
        f = self.response.forms['questionnairesummaryform']
        f['create_-1'].checked = True
        f['title_-1'] = "foobar"
        f['info_-1'] = "blaster master"
        f['field_id_-1'] = "7"
        self.submit(f)
        self.traverse({'href': '/event/event/1/registration/questionnaire'})
        f = self.response.forms['questionnaireform']
        f['notevil'] = "True"
        self.submit(f)

    @as_users("anton")
    def test_event_fields_date(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/field/summary'})
        f = self.response.forms['fieldsummaryform']
        f['create_-1'].checked = True
        f['field_name_-1'] = "notevil"
        f['association_-1'] = FieldAssociations.registration.value
        f['kind_-1'] = FieldDatatypes.date.value
        f['entries_-1'] = """2018-01-01;new year
        2018-10-03;party!
        2018-04-01;April fools"""
        self.submit(f)
        self.assertTitle("Datenfelder konfigurieren (Große Testakademie 2222)")
        self.traverse({'href': '/event/event/1/show'},
                      {'href': '/event/event/1/change'})
        f = self.response.forms['changeeventform']
        f['use_questionnaire'].checked = True
        self.submit(f)
        self.traverse({'href': '/event/event/1/questionnaire/summary'})
        f = self.response.forms['questionnairesummaryform']
        f['create_-1'].checked = True
        f['title_-1'] = "foobar"
        f['info_-1'] = "blaster master"
        f['field_id_-1'] = "7"
        self.submit(f)
        self.traverse({'href': '/event/event/1/registration/questionnaire'})
        f = self.response.forms['questionnaireform']
        f['notevil'] = "2018-10-03"
        self.submit(f)

    @as_users("garcia")
    def test_event_fields_query(self, user):
        self.get("/event/event/1/field/summary")
        f = self.response.forms['fieldsummaryform']
        f['create_-1'].checked = True
        f['field_name_-1'] = "CapitalLetters"
        f['association_-1'] = FieldAssociations.registration.value
        f['kind_-1'] = FieldDatatypes.str.value
        self.submit(f)
        self.get("/event/event/1/field/setselect")
        f = self.response.forms['selectfieldform']
        f['field_id'] = 7
        self.submit(f)
        f = self.response.forms['fieldform']
        f['input1'] = "Example Text"
        f['input2'] = ""
        f['input3'] = "Other Text"
        self.submit(f)
        self.assertTitle("Anmeldungen (Große Testakademie 2222)")
        f = self.response.forms['queryform']
        f['qsel_reg_fields.xfield_CapitalLetters'].checked = True
        f['qop_reg_fields.xfield_CapitalLetters'] = 2  # 2: is not empty
        self.submit(f)
        self.assertPresence("Anton Armin A.")
        self.assertPresence("Garcia G.")
        #self.assertPresence("Other Text")

    @as_users("anton", "garcia")
    def test_change_minor_form(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'})
        self.assertTitle("Große Testakademie 2222")
        f = self.response.forms['changeminorformform']
        with open("/tmp/cdedb-store/testfiles/form.pdf", 'rb') as datafile:
            data = datafile.read()
        f['minor_form'] = webtest.Upload("form.pdf", data, "application/octet-stream")
        self.submit(f)
        self.traverse({'href': '/event/event/1/minorform'})
        with open("/tmp/cdedb-store/testfiles/form.pdf", 'rb') as f:
            self.assertEqual(f.read(), self.response.body)

    @as_users("anton", "garcia")
    def test_set_event_logo(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'})
        self.assertTitle("Große Testakademie 2222")
        f = self.response.forms['seteventlogoform']
        with open("/tmp/cdedb-store/testfiles/picture.jpg", 'rb') as datafile:
            data = datafile.read()
        f['event_logo'] = webtest.Upload("picture.jpg", data, "application/octet-stream")
        self.submit(f)
        self.get('/event/event/1/logo')
        with open("/tmp/cdedb-store/testfiles/picture.jpg", 'rb') as f:
            self.assertEqual(f.read(), self.response.body)
        # Remove the logo again
        self.get("/event/event/1/show")
        self.assertTitle("Große Testakademie 2222")
        self.assertNonPresence("Kein Logo.")
        f = self.response.forms['removeeventlogoform']
        self.submit(f)
        self.assertTitle("Große Testakademie 2222")
        self.assertPresence("Kein Logo.")

    @as_users("anton", "garcia")
    def test_set_course_logo(self, user):
        self.get("/event/event/1/course/1/show")
        self.assertTitle("Kurs Heldentum (Große Testakademie 2222)")
        self.assertPresence("Kein Logo.")
        f = self.response.forms['setcourselogoform']
        with open("/tmp/cdedb-store/testfiles/picture.jpg", 'rb') as datafile:
            data = datafile.read()
        f['course_logo'] = webtest.Upload("picture.jpg", data,
                                         "application/octet-stream")
        self.submit(f)
        self.assertTitle("Kurs Heldentum (Große Testakademie 2222)")
        self.assertNonPresence("Kein Logo.")
        self.get('/event/event/1/course/1/logo')
        with open("/tmp/cdedb-store/testfiles/picture.jpg", 'rb') as f:
            self.assertEqual(f.read(), self.response.body)
        # Remove the logo again
        self.get("/event/event/1/course/1/show")
        self.assertTitle("Kurs Heldentum (Große Testakademie 2222)")
        self.assertNonPresence("Kein Logo.")
        f = self.response.forms['removecourselogoform']
        self.submit(f)
        self.assertTitle("Kurs Heldentum (Große Testakademie 2222)")
        self.assertPresence("Kein Logo.")


    @as_users("anton", "ferdinand")
    def test_create_event(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/list'},
                      {'href': '/event/event/create'})
        self.assertTitle("Veranstaltung anlegen")
        f = self.response.forms['createeventform']
        f['title'] = "Universale Akademie"
        f['institution'] = 1
        f['description'] = "Mit Co und Coco."
        f['shortname'] = "UnAka"
        f['event_begin'] = "2345-01-01"
        f['event_end'] = "2345-6-7"
        f['registration_start'] = "2000-01-01 00:00:00+0000"
        f['notes'] = "Die spinnen die Orgas."
        f['orga_ids'] = "DB-2-7, DB-7-8"
        self.submit(f)
        self.assertTitle("Universale Akademie")
        self.assertPresence("Mit Co und Coco.")
        self.assertPresence("Bertålotta")
        self.assertPresence("Garcia")

    @as_users("anton", "garcia")
    def test_change_course(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/course/list'},
                      {'href': '/event/event/1/course/1/change'})
        self.assertTitle("Heldentum bearbeiten (Große Testakademie 2222)")
        f = self.response.forms['changecourseform']
        self.assertEqual("1", f.get('segments', index=0).value)
        self.assertEqual(None, f.get('segments', index=1).value)
        self.assertEqual("3", f.get('segments', index=2).value)
        self.assertEqual("1", f.get('active_segments', index=0).value)
        self.assertEqual(None, f.get('active_segments', index=1).value)
        self.assertEqual("3", f.get('active_segments', index=2).value)
        self.assertEqual("10", f['max_size'].value)
        self.assertEqual("3", f['min_size'].value)
        self.assertEqual("Wald", f['fields.room'].value)
        f['shortname'] = "Helden"
        f['nr'] = "ω"
        f['max_size'] = "21"
        f['segments'] = ['2', '3']
        f['active_segments'] = ['2']
        f['fields.room'] = "Canyon"
        self.submit(f)
        self.assertTitle("Kurs Helden (Große Testakademie 2222)")
        self.traverse({'href': '/event/event/1/course/1/change'})
        f = self.response.forms['changecourseform']
        self.assertEqual(f['nr'].value, "ω")
        self.assertEqual(None, f.get('segments', index=0).value)
        self.assertEqual("2", f.get('segments', index=1).value)
        self.assertEqual("3", f.get('segments', index=2).value)
        self.assertEqual(None, f.get('active_segments', index=0).value)
        self.assertEqual("2", f.get('active_segments', index=1).value)
        self.assertEqual(None, f.get('active_segments', index=2).value)
        self.assertEqual("21", f['max_size'].value)
        self.assertEqual("Canyon", f['fields.room'].value)

    @as_users("anton")
    def test_create_delete_course(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/course/list'})
        self.assertTitle("Kursliste Große Testakademie 2222")
        self.assertPresence("Planetenretten für Anfänger")
        self.assertNonPresence("Abstract Nonsense")
        self.traverse({'href': '/event/event/1/course/stats'},
                      {'href': '/event/event/1/course/create'})
        self.assertTitle("Kurs hinzufügen (Große Testakademie 2222)")
        f = self.response.forms['createcourseform']
        self.assertEqual("1", f.get('segments', index=0).value)
        self.assertEqual("2", f.get('segments', index=1).value)
        self.assertEqual("3", f.get('segments', index=2).value)
        f['title'] = "Abstract Nonsense"
        f['nr'] = "ω"
        f['shortname'] = "math"
        f['instructors'] = "Alexander Grothendieck"
        f['notes'] = "transcendental appearence"
        f['segments'] = ['1', '3']
        self.submit(f)
        self.assertTitle("Kurs math (Große Testakademie 2222)")
        self.assertNonPresence("Kursfelder gesetzt.", div="notifications")
        self.assertPresence("transcendental appearence")
        self.assertPresence("Alexander Grothendieck")
        self.traverse({'href': '/event/event/1/course/6/change'})
        self.assertTitle("math bearbeiten (Große Testakademie 2222)")
        f = self.response.forms['changecourseform']
        self.assertEqual("1", f.get('segments', index=0).value)
        self.assertEqual(None, f.get('segments', index=1).value)
        self.assertEqual("3", f.get('segments', index=2).value)
        self.traverse({'href': '/event/event/1/course/6/show'})
        f = self.response.forms['deletecourseform']
        f['ack_delete'].checked = True
        self.submit(f)
        self.assertTitle("Kurse verwalten (Große Testakademie 2222)")
        self.assertNonPresence("Abstract Nonsense")

    @as_users("anton")
    def test_create_course_with_fields(self, user):
        self.get("/event/event/1/course/create")
        self.assertTitle("Kurs hinzufügen (Große Testakademie 2222)")
        f = self.response.forms['createcourseform']
        f['title'] = "Abstract Nonsense"
        f['nr'] = "ω"
        f['shortname'] = "math"
        f['fields.room'] = "Outside"
        self.submit(f)
        self.assertTitle("Kurs math (Große Testakademie 2222)")
        self.assertPresence("Outside")

    @as_users("berta")
    def test_register(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/register'})
        self.assertTitle("Anmeldung für Große Testakademie 2222")
        f = self.response.forms['registerform']
        f['parts'] = ['1', '3']
        f['mixed_lodging'] = 'True'
        f['notes'] = "Ich freu mich schon so zu kommen\n\nyeah!\n"
        f['course_choice3_0'] = 2
        f['course_choice3_1'] = 4
        self.assertNotIn('5', tuple(
            o for o, _, _ in f['course_choice3_1'].options))
        f['course_instructor3'] = 2
        self.submit(f)
        self.assertTitle("Deine Anmeldung (Große Testakademie 2222)")
        mail = self.fetch_mail()[0]
        text = mail.get_body().get_content()
        self.assertIn("461.49", text)
        self.assertPresence("Ich freu mich schon so zu kommen")
        self.traverse({'href': '/event/event/1/registration/amend'})
        self.assertTitle("Anmeldung für Große Testakademie 2222 ändern")
        self.assertNonPresence("Morgenkreis")
        self.assertNonPresence("Kaffeekränzchen")
        self.assertPresence("Arbeitssitzung")
        f = self.response.forms['amendregistrationform']
        self.assertEqual("4", f['course_choice3_1'].value)
        self.assertEqual("2", f['course_instructor3'].value)
        self.assertPresence("Ich freu mich schon so zu kommen")
        f['notes'] = "Ich kann es kaum erwarten!"
        f['course_choice3_0'] = 4
        f['course_choice3_1'] = 1
        f['course_instructor3'] = 1
        self.submit(f)
        self.assertTitle("Deine Anmeldung (Große Testakademie 2222)")
        self.assertPresence("Ich kann es kaum erwarten!")
        self.traverse({'href': '/event/event/1/registration/amend'})
        self.assertTitle("Anmeldung für Große Testakademie 2222 ändern")
        f = self.response.forms['amendregistrationform']
        self.assertEqual("4", f['course_choice3_0'].value)
        self.assertEqual("1", f['course_instructor3'].value)
        self.assertPresence("Ich kann es kaum erwarten!")

    def test_register_no_registraion_end(self):
        # Remove registration end (soft and hard) from Große Testakademie 2222
        self.login(USER_DICT['garcia'])
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/change'})
        self.assertTitle("Große Testakademie 2222 – Konfiguration")
        f = self.response.forms['changeeventform']
        f['registration_soft_limit'] = ""
        f['registration_hard_limit'] = ""
        self.submit(f)
        self.logout()

        # Berta tries registering and amending registraions. We do less checks
        # than in test_register()
        # (the login checks the dashboard for Exceptions, by the way)
        self.login(USER_DICT['berta'])
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/register'})
        self.assertTitle("Anmeldung für Große Testakademie 2222")
        f = self.response.forms['registerform']
        f['notes'] = "Ich freu mich schon so zu kommen\n\nyeah!\n"
        f['parts'] = ['1']
        f['mixed_lodging'] = 'True'
        self.submit(f)
        self.assertTitle("Deine Anmeldung (Große Testakademie 2222)")
        mail = self.fetch_mail()[0]
        text = mail.get_body().get_content()
        self.assertIn("10.50", text)
        self.traverse({'href': '/event/event/1/registration/amend'})
        self.assertTitle("Anmeldung für Große Testakademie 2222 ändern")
        f = self.response.forms['amendregistrationform']
        self.assertPresence("Ich freu mich schon so zu kommen")
        self.submit(f)
        self.assertTitle("Deine Anmeldung (Große Testakademie 2222)")

    @as_users("garcia")
    def test_questionnaire(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/change'})
        self.assertTitle("Große Testakademie 2222 – Konfiguration")
        f = self.response.forms['changeeventform']
        f['use_questionnaire'].checked = True
        self.submit(f)
        self.traverse({'href': '/event/event/1/registration/questionnaire'})
        self.assertTitle("Fragebogen (Große Testakademie 2222)")
        f = self.response.forms['questionnaireform']
        self.assertEqual(False, f['brings_balls'].checked)
        f['brings_balls'].checked = True
        self.assertEqual("car", f['transportation'].value)
        f['transportation'] = "etc"
        self.assertEqual("", f['lodge'].value)
        f['lodge'] = "Bitte in ruhiger Lage.\nEcht."
        self.submit(f)
        self.traverse({'href': '/event/event/1/registration/questionnaire'})
        self.assertTitle("Fragebogen (Große Testakademie 2222)")
        f = self.response.forms['questionnaireform']
        self.assertEqual(True, f['brings_balls'].checked)
        self.assertEqual("etc", f['transportation'].value)
        self.assertEqual("Bitte in ruhiger Lage.\nEcht.", f['lodge'].value)

    @as_users("garcia")
    def test_batch_fee(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/batchfee'})
        self.assertTitle("Überweisungen eintragen (Große Testakademie 2222)")
        f = self.response.forms['batchfeesform']
        f['fee_data'] ="""
570.99;DB-1-9;Admin;Anton;01.04.18
461.49;DB-5-1;Eventis;Emilia;01.04.18
570.99;DB-11-6;K;Kalif;01.04.18
0.0;DB-666-1;Y;Z;77.04.18;stuff
"""
        self.submit(f, check_notification=False)
        self.assertPresence("Kein Account mit ID 666 gefunden.")
        f = self.response.forms['batchfeesform']
        f['fee_data'] = """
573.99;DB-1-9;Admin;Anton;01.04.18
461.49;DB-5-1;Eventis;Emilia;04.01.18
"""
        self.submit(f, check_notification=False)
        f = self.response.forms['batchfeesform']
        f['force'].checked = True
        self.submit(f, check_notification=False)
        # submit again because of checksum
        f = self.response.forms['batchfeesform']
        self.submit(f)
        self.traverse({'href': '/event/event/1/show'},
                      {'href': '/event/event/1/registration/query'})
        self.traverse({'description': 'Alle Anmeldungen'},
                      {'href': '/event/event/1/registration/1/show'})
        self.assertTitle("Anmeldung von Anton Armin A. Administrator (Große Testakademie 2222)")
        self.assertPresence("Bezahlt am 01.04.2018")
        self.traverse({'href': '/event/event/1/show'},
                      {'href': '/event/event/1/registration/query'},
                      {'description': 'Alle Anmeldungen'},
                      {'href': '/event/event/1/registration/2/show'})
        self.assertTitle("Anmeldung von Emilia E. Eventis (Große Testakademie 2222)")
        self.assertPresence("Bezahlt am 04.01.2018")

    @as_users("garcia")
    def test_registration_query(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/registration/query'})
        self.assertTitle("Anmeldungen (Große Testakademie 2222)")
        f = self.response.forms['queryform']
        for field in f.fields:
            if field and field.startswith('qsel_'):
                f[field].checked = True
        f['qop_persona.family_name'] = QueryOperators.similar.value
        f['qval_persona.family_name'] = 'e'
        f['qord_primary'] = 'reg.id'
        self.submit(f)
        self.assertTitle("\nAnmeldungen (Große Testakademie 2222)")
        self.assertPresence("Ergebnis [2]")
        self.assertPresence("Emilia")
        self.assertPresence("Garcia")
        self.assertEqual(
            self.response.lxml.xpath('//*[@id="query-result"]//tr[1]/td[@data-col="lodgement_id2"]')[0].text.strip(),
            "Einzelzelle")
        self.assertEqual(
            self.response.lxml.xpath('//*[@id="query-result"]//tr[2]/td[@data-col="lodgement_id2"]')[0].text.strip(),
            "")

    @as_users("garcia")
    def test_multiedit(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/registration/query'},
                      {'description': 'Alle Anmeldungen'})
        self.assertTitle("Anmeldungen (Große Testakademie 2222)")
        self.assertNotEqual(self.response.lxml.xpath('//table[@id="query-result"]/tbody/tr[@data-id="2"]'), [])
        # Fake JS link redirection
        self.get("/event/event/1/registration/multiedit?reg_ids=2,3")
        self.assertTitle("Anmeldungen bearbeiten (Große Testakademie 2222)")
        f = self.response.forms['changeregistrationform']
        self.assertEqual(False, f['enable_part2.status'].checked)
        self.assertEqual(True, f['enable_part3.status'].checked)
        self.assertEqual("2", f['part3.status'].value)
        f['part3.status'] = 5
        self.assertEqual(False, f['enable_fields.transportation'].checked)
        self.assertEqual(True, f['enable_fields.may_reserve'].checked)
        f['enable_fields.transportation'].checked = True
        f['fields.transportation'] = "pedes"
        self.submit(f)
        self.traverse({'description': 'Alle Anmeldungen'},
                      {'href': '/event/event/1/registration/2/show'},
                      {'href': '/event/event/1/registration/2/change'})
        f = self.response.forms['changeregistrationform']
        self.assertEqual("4", f['part2.status'].value)
        self.assertEqual("5", f['part3.status'].value)
        self.assertEqual("pedes", f['fields.transportation'].value)
        self.traverse({'href': '/event/event/1/registration/query'},
                      {'description': 'Alle Anmeldungen'},
                      {'href': '/event/event/1/registration/3/show'},
                      {'href': '/event/event/1/registration/3/change'})
        f = self.response.forms['changeregistrationform']
        self.assertEqual("2", f['part2.status'].value)
        self.assertEqual("5", f['part3.status'].value)
        self.assertEqual("pedes", f['fields.transportation'].value)

    @as_users("garcia")
    def test_show_registration(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/registration/query'})
        self.assertTitle("Anmeldungen (Große Testakademie 2222)")
        self.traverse({'description': 'Alle Anmeldungen'},
                      {'href': '/event/event/1/registration/2/show'})
        self.assertTitle("\nAnmeldung von Emilia E. Eventis (Große Testakademie 2222)\n")
        self.assertPresence("56767 Wolkenkuckuksheim")
        self.assertPresence("Einzelzelle")
        self.assertPresence("α. Heldentum")
        self.assertPresence("Extrawünsche: Meerblick, Weckdienst")

    @as_users("garcia")
    def test_change_registration(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/registration/query'})
        self.assertTitle("Anmeldungen (Große Testakademie 2222)")
        self.traverse({'description': 'Alle Anmeldungen'},
                      {'href': '/event/event/1/registration/2/show'},
                      {'href': '/event/event/1/registration/2/change'})
        self.assertTitle("Anmeldung von Emilia E. Eventis bearbeiten (Große Testakademie 2222)")
        f = self.response.forms['changeregistrationform']
        self.assertEqual("Unbedingt in die Einzelzelle.", f['reg.orga_notes'].value)
        f['reg.orga_notes'] = "Wir wllen mal nicht so sein."
        self.assertEqual(True, f['reg.mixed_lodging'].checked)
        f['reg.mixed_lodging'].checked = False
        self.assertEqual("3", f['part1.status'].value)
        f['part1.status'] = 2
        self.assertEqual("4", f['part2.lodgement_id'].value)
        f['part2.lodgement_id'] = 3
        self.assertEqual("2", f['track3.course_choice_1'].value)
        f['track3.course_choice_1'] = 5
        self.assertEqual("pedes", f['fields.transportation'].value)
        f['fields.transportation'] = "etc"
        self.assertEqual("", f['fields.lodge'].value)
        f['fields.lodge'] = "Om nom nom nom"
        self.submit(f)
        self.assertTitle("\nAnmeldung von Emilia E. Eventis (Große Testakademie 2222)\n")
        self.assertPresence("Om nom nom nom")
        self.traverse({'href': '/event/event/1/registration/2/change'})
        f = self.response.forms['changeregistrationform']
        self.assertEqual("Wir wllen mal nicht so sein.", f['reg.orga_notes'].value)
        self.assertEqual(False, f['reg.mixed_lodging'].checked)
        self.assertEqual("2", f['part1.status'].value)
        self.assertEqual("3", f['part2.lodgement_id'].value)
        self.assertEqual("5", f['track3.course_choice_1'].value)
        self.assertEqual("etc", f['fields.transportation'].value)
        self.assertEqual("Om nom nom nom", f['fields.lodge'].value)

    @as_users("garcia")
    def test_add_registration(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/registration/query'},
                      {'href': '/event/event/1/registration/add'})
        self.assertTitle("Neue Anmeldung (Große Testakademie 2222)")
        f = self.response.forms['addregistrationform']
        f['persona.persona_id'] = "DB-2-7"
        f['reg.orga_notes'] = "Du entkommst uns nicht."
        f['reg.mixed_lodging'].checked = False
        f['part1.status'] = 1
        f['part2.status'] = 3
        f['part3.status'] = -1
        f['part1.lodgement_id'] = 4
        f['track1.course_id'] = 5
        f['track1.course_choice_0'] = 5
        self.submit(f)
        self.assertTitle("\nAnmeldung von Bertålotta Beispiel (Große Testakademie 2222)\n")
        self.assertPresence("Du entkommst uns nicht.")
        self.traverse({'href': '/event/event/1/registration/5/change'})
        f = self.response.forms['changeregistrationform']
        self.assertEqual("Du entkommst uns nicht.", f['reg.orga_notes'].value)
        self.assertEqual(False, f['reg.mixed_lodging'].checked)
        self.assertEqual("1", f['part1.status'].value)
        self.assertEqual("3", f['part2.status'].value)
        self.assertEqual("-1", f['part3.status'].value)
        self.assertEqual("4", f['part1.lodgement_id'].value)
        self.assertEqual("5", f['track1.course_id'].value)
        self.assertEqual("5", f['track1.course_choice_0'].value)
        
    @as_users("garcia")
    def test_add_illegal_registration(self, user):
        self.get("/event/event/1/registration/add")
        self.assertTitle("Neue Anmeldung (Große Testakademie 2222)")
        f = self.response.forms["addregistrationform"]
        f["persona.persona_id"] = "DB-2-7"
        f["part1.status"] = 1
        f["track1.course_choice_0"] = 5
        f["track1.course_choice_1"] = 5
        self.submit(f, check_notification=False)
        self.assertTitle("Neue Anmeldung (Große Testakademie 2222)")
        self.assertPresence("Bitte verschiedene Kurse wählen.")
        f = self.response.forms["addregistrationform"]
        f["track1.course_choice_1"] = 4
        self.submit(f)
        self.assertTitle("\nAnmeldung von Bertålotta Beispiel (Große Testakademie 2222)\n")
        self.assertEqual("5", f['track1.course_choice_0'].value)
        self.assertEqual("4", f['track1.course_choice_1'].value)

    @as_users("anton")
    def test_add_empty_registration(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/2/show'},
                      {'href': '/event/event/2/registration/query'},
                      {'href': '/event/event/2/registration/add'})
        f = self.response.forms['addregistrationform']
        f['persona.persona_id'] = "DB-5-1"
        f['reg.parental_agreement'].checked = True
        f['part4.status'] = -1
        self.submit(f)
        self.assertTitle("Anmeldung von Emilia E. Eventis (CdE-Party 2050)")
        self.traverse({'href': '/event/event/2/registration/5/change'})
        f = self.response.forms['changeregistrationform']
        self.assertEqual(True, f['reg.parental_agreement'].checked)

    @as_users("garcia")
    def test_delete_registration(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/registration/query'},
                      {'description': 'Alle Anmeldungen'})
        self.assertPresence("Anton Armin A.")
        self.traverse({'href': '/event/event/1/registration/1/show'})
        self.assertTitle("Anmeldung von Anton Armin A. Administrator (Große Testakademie 2222)")
        f = self.response.forms['deleteregistrationform']
        f['ack_delete'].checked = True
        self.submit(f)
        self.traverse({'href': '/event/event/1/registration/query'},
                      {'description': 'Alle Anmeldungen'})
        self.assertNonPresence("Anton Armin A.")

    @as_users("garcia")
    def test_lodgements(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/lodgement/overview'})
        self.assertTitle("Unterkünfte (Große Testakademie 2222)")
        self.assertPresence("Kalte Kammer")
        self.traverse({'href': '/event/event/1/lodgement/4/show'})
        self.assertTitle("Unterkunft Einzelzelle (Große Testakademie 2222)")
        self.assertPresence("Emilia")
        self.traverse({'href': '/event/event/1/lodgement/4/change'})
        self.assertTitle("Unterkunft Einzelzelle bearbeiten (Große Testakademie 2222)")
        f = self.response.forms['changelodgementform']
        self.assertEqual("1", f['capacity'].value)
        f['capacity'] = 3
        self.assertEqual("", f['notes'].value)
        f['notes'] = "neu mit Anbau"
        self.assertEqual("high", f['fields.contamination'].value)
        f['fields.contamination'] = "medium"
        self.submit(f)
        self.traverse({'href': '/event/event/1/lodgement/4/change'})
        self.assertTitle("Unterkunft Einzelzelle bearbeiten (Große Testakademie 2222)")
        f = self.response.forms['changelodgementform']
        self.assertEqual("3", f['capacity'].value)
        self.assertEqual("neu mit Anbau", f['notes'].value)
        self.assertEqual("medium", f['fields.contamination'].value)
        self.traverse({'href': '/event/event/1/lodgement/overview'})
        self.traverse({'href': '/event/event/1/lodgement/3/show'})
        self.assertTitle("Unterkunft Kellerverlies (Große Testakademie 2222)")
        f = self.response.forms['deletelodgementform']
        self.submit(f)
        self.assertTitle("Unterkünfte (Große Testakademie 2222)")
        self.assertNonPresence("Kellerverlies")
        self.traverse({'href': '/event/event/1/lodgement/create'})
        f = self.response.forms['createlodgementform']
        f['moniker'] = "Zelte"
        f['capacity'] = 0
        f['reserve'] = 20
        f['notes'] = "oder gleich unter dem Sternenhimmel?"
        self.submit(f)
        self.assertTitle("Unterkunft Zelte (Große Testakademie 2222)")
        self.traverse({'href': '/event/event/1/lodgement/5/change'})
        self.assertTitle("Unterkunft Zelte bearbeiten (Große Testakademie 2222)")
        f = self.response.forms['changelodgementform']
        self.assertEqual('20', f['reserve'].value)
        self.assertEqual("oder gleich unter dem Sternenhimmel?", f['notes'].value)

    @as_users("garcia")
    def test_field_set(self, user):
        self.get('/event/event/1/field/setselect?reg_ids=1,2')
        self.assertTitle("Datenfeld auswählen (Große Testakademie 2222)")
        self.assertNonPresence("Inga")
        f = self.response.forms['selectfieldform']
        f['field_id'] = 2
        self.submit(f)
        self.assertTitle("Datenfeld transportation setzen (Große Testakademie 2222)")
        f = self.response.forms['fieldform']
        self.assertEqual("pedes", f['input2'].value)
        f['input2'] = "etc"
        self.submit(f)
        self.traverse({'href': '/event/event/1/field/setselect'})
        self.assertTitle("Datenfeld auswählen (Große Testakademie 2222)")
        f = self.response.forms['selectfieldform']
        f['field_id'] = 2
        self.submit(f)
        self.assertTitle("Datenfeld transportation setzen (Große Testakademie 2222)")
        f = self.response.forms['fieldform']
        self.assertEqual("etc", f['input2'].value)
        # Value of Inga should not have changed
        self.assertEqual("etc", f['input4'].value)

        self.traverse({'href': '/event/event/1/registration/query'},
                      {'href': '/event/event/1/field/setselect'})
        self.assertTitle("Datenfeld auswählen (Große Testakademie 2222)")
        f = self.response.forms['selectfieldform']
        f['field_id'] = 3
        self.submit(f)
        self.assertTitle("Datenfeld lodge setzen (Große Testakademie 2222)")
        f = self.response.forms['fieldform']
        self.assertEqual("", f['input4'].value)
        f['input4'] = "Test\nmit\n\nLeerzeilen"
        self.submit(f)
        self.traverse({'href': '/event/event/1/registration/query'},
                      {'href': '/event/event/1/field/setselect'})
        self.assertTitle("Datenfeld auswählen (Große Testakademie 2222)")
        f = self.response.forms['selectfieldform']
        f['field_id'] = 3
        self.submit(f)
        self.assertTitle("Datenfeld lodge setzen (Große Testakademie 2222)")
        f = self.response.forms['fieldform']
        self.assertEqual("Test\nmit\n\nLeerzeilen", f['input4'].value)

    @as_users("garcia")
    def test_stats(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/stats'},)
        self.assertTitle("Statistik (Große Testakademie 2222)")

    @as_users("garcia")
    def test_course_stats(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/course/stats'},)
        self.assertTitle("Kurse verwalten (Große Testakademie 2222)")
        self.assertPresence("Heldentum")
        self.assertPresence("1")
        self.assertPresence("δ")

    @as_users("garcia")
    def test_course_choices(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/course/choices'},)
        self.assertTitle("Kurswahlen (Große Testakademie 2222)")
        self.assertPresence("Morgenkreis", div="course_choice_table")
        self.assertPresence("Morgenkreis", div="assignment-options")
        self.assertPresence("Heldentum")
        self.assertPresence("Anton Armin")
        self.assertPresence("Emilia")
        self.assertPresence("Garcia")
        self.assertPresence("Inga")
        f = self.response.forms['choicefilterform']
        f['track_id'] = 3
        self.submit(f)
        self.assertPresence("Anton Armin")
        self.assertPresence("Emilia")
        self.assertPresence("Garcia")
        self.assertPresence("Inga")
        f = self.response.forms['choicefilterform']
        f['track_id'] = 1
        self.submit(f)
        self.assertNonPresence("Anton Armin")
        self.assertNonPresence("Emilia")
        self.assertPresence("Garcia")
        self.assertNonPresence("Inga")
        f = self.response.forms['choicefilterform']
        f['track_id'] = ''
        f['course_id'] = 2
        f['position'] = -7
        self.submit(f)
        self.assertNonPresence("Anton Armin")
        self.assertPresence("Emilia")
        self.assertPresence("Garcia")
        self.assertPresence("Inga")
        f = self.response.forms['choicefilterform']
        f['course_id'] = 4
        f['position'] = 0
        self.submit(f)
        self.assertNonPresence("Inga")
        self.assertNonPresence("Anton Armin")
        self.assertPresence("Garcia")
        self.assertPresence("Emilia")
        f = self.response.forms['choicefilterform']
        f['course_id'] = 4
        f['position'] = 0
        f['track_id'] = 3
        self.submit(f)
        self.assertNonPresence("Anton Armin")
        self.assertNonPresence("Inga")
        self.assertNonPresence("Garcia")
        self.assertPresence("Emilia")
        f = self.response.forms['choicefilterform']
        f['course_id'] = ''
        f['position'] = ''
        f['track_id'] = ''
        self.submit(f)
        f = self.response.forms['choiceactionform']
        f['registration_ids'] = [1, 2]
        f['assign_track_ids'] = [3]
        f['assign_action'] = 0
        self.submit(f)
        f = self.response.forms['choicefilterform']
        f['course_id'] = 1
        f['position'] = -6
        f['track_id'] = 3
        self.submit(f)
        self.assertPresence("Anton Armin")
        self.assertPresence("Inga")
        self.assertNonPresence("Garcia")
        self.assertNonPresence("Emilia")
        f = self.response.forms['choicefilterform']
        f['course_id'] = 4
        f['position'] = -6
        f['track_id'] = 3
        self.submit(f)
        self.assertNonPresence("Anton Armin")
        self.assertPresence("Emilia")
        self.assertNonPresence("Garcia")
        self.assertNonPresence("Inga")
        f = self.response.forms['choicefilterform']
        f['course_id'] = ''
        f['position'] = ''
        f['track_id'] = ''
        self.submit(f)
        f = self.response.forms['choiceactionform']
        f['registration_ids'] = [3]
        f['assign_track_ids'] = [2, 3]
        f['assign_action'] = -4
        f['assign_course_id'] = 5
        self.submit(f)
        f = self.response.forms['choicefilterform']
        f['course_id'] = 5
        f['position'] = -6
        self.submit(f)
        self.assertNonPresence("Anton Armin")
        self.assertNonPresence("Emilia")
        self.assertPresence("Garcia")
        self.assertNonPresence("Inga")

        # Test filtering for unassigned participants
        f = self.response.forms['choicefilterform']
        f['course_id'] = ''
        f['track_id'] = ''
        f['position'] = -6
        self.submit(f)
        self.assertNonPresence("Inga")
        self.assertPresence("Garcia")
        f = self.response.forms['choicefilterform']
        f['track_id'] = 2
        self.submit(f)
        self.assertNonPresence("Garcia")
        self.assertNonPresence("Emilia")

        # Test including all open registrations
        f = self.response.forms['choicefilterform']
        f['include_active'].checked = True
        self.submit(f)
        self.assertPresence("Emilia")

    @as_users("garcia")
    def test_automatic_assignment(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/course/choices'},)
        self.assertTitle("Kurswahlen (Große Testakademie 2222)")
        self.assertPresence("Heldentum")
        self.assertPresence("Anton Armin")
        self.assertPresence("Emilia")
        self.assertPresence("Garcia")
        self.assertPresence("Inga")
        f = self.response.forms['choiceactionform']
        f['registration_ids'] = [1, 2, 3, 4]
        f['assign_track_ids'] = [1, 2, 3]
        f['assign_action'] = -5
        self.submit(f)

    @as_users("garcia")
    def test_assignment_checks(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/course/choices'},
                      {'href': '/event/event/1/course/checks'},)
        self.assertTitle("Kurseinteilungsprüfung (Große Testakademie 2222)")
        self.assertPresence("Ausfallende Kurse mit Teilnehmern")
        self.assertPresence("Kabarett", 'problem_cancelled_with_p')
        self.assertPresence("Teilnehmer ohne Kurs")
        self.assertPresence("Anton", 'problem_no_course')

        # Assigning Garcia to "Backup" in "Kaffekränzchen" fixes 'cancelled'
        # problem, but raises 'unchosen' problem
        self.get('/event/event/1/registration/3/change')
        f = self.response.forms['changeregistrationform']
        f['track2.course_id'] = "5"
        self.submit(f)
        # Assign Garcia and Anton to their 1. choice to fix 'no_course' issues;
        # accidentally, also assign emilia (instructor) to 1. choice ;-)
        self.get('/event/event/1/course/choices')
        f = self.response.forms['choiceactionform']
        f['registration_ids'] = [1, 2, 3]
        f['assign_track_ids'] = [1, 3]
        f['assign_action'] = 0
        self.submit(f)

        self.traverse({'href': '/event/event/1/course/checks'})
        self.assertPresence("Teilnehmer in einem ungewählten Kurs")
        self.assertPresence("Garcia", 'problem_unchosen')
        self.assertPresence("Kursleiter im falschen Kurs")
        self.assertPresence("Emilia", 'problem_instructor_wrong_course')
        self.assertPresence("α", 'problem_instructor_wrong_course')
        self.assertPresence("δ", 'problem_instructor_wrong_course')


    @as_users("garcia")
    def test_downloads(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/download'},)
        self.assertTitle("Downloads zur Veranstaltung Große Testakademie 2222")
        save = self.response
        self.response = save.click(href='/event/event/1/download/coursepuzzle\\?runs=0')
        self.assertPresence('documentclass')
        self.assertPresence('Planetenretten für Anfänger')
        self.response = save.click(href='/event/event/1/download/coursepuzzle\\?runs=2')
        self.assertTrue(self.response.body.startswith(b"%PDF"))
        self.assertTrue(len(self.response.body) > 1000)
        self.response = save.click(href='/event/event/1/download/lodgementpuzzle\\?runs=0')
        self.assertPresence('documentclass')
        self.assertPresence('Kalte Kammer')
        self.response = save.click(href='/event/event/1/download/lodgementpuzzle\\?runs=2')
        self.assertTrue(self.response.body.startswith(b"%PDF"))
        self.assertTrue(len(self.response.body) > 1000)
        self.response = save.click(href='/event/event/1/download/lodgementlists\\?runs=0')
        self.assertTrue(self.response.body.startswith(b"\x1f\x8b"))
        self.assertTrue(len(self.response.body) > 1000)
        self.response = save.click(href='/event/event/1/download/lodgementlists\\?runs=2')
        self.assertTrue(self.response.body.startswith(b"%PDF"))
        self.assertTrue(len(self.response.body) > 1000)
        self.response = save.click(href='/event/event/1/download/courselists\\?runs=0')
        self.assertTrue(self.response.body.startswith(b"\x1f\x8b"))
        self.assertTrue(len(self.response.body) > 1000)
        self.response = save.click(href='/event/event/1/download/courselists\\?runs=2')
        self.assertTrue(self.response.body.startswith(b"%PDF"))
        self.assertTrue(len(self.response.body) > 1000)
        self.response = save.click(href='/event/event/1/download/expuls')
        self.assertPresence('\\kurs')
        self.assertPresence('Planetenretten für Anfänger')
        self.response = save.click(href='/event/event/1/download/participantlist\\?runs=0',
                                   index=0)
        self.assertPresence('documentclass')
        self.assertPresence('Heldentum')
        self.assertPresence('Emilia E.')
        self.assertNonPresence('Garcia G.')
        self.response = save.click(href='/event/event/1/download/participantlist\\?runs=0&orgas_only=True',
                                   index=0)
        self.assertPresence('documentclass')
        self.assertPresence('Heldentum')
        self.assertPresence('Emilia E.')
        self.assertPresence('Garcia G.')
        self.response = save.click(href='/event/event/1/download/participantlist\\?runs=2',
                                   index=0)
        self.assertTrue(self.response.body.startswith(b"%PDF"))
        self.assertTrue(len(self.response.body) > 1000)
        self.response = save.click(href='/event/event/1/download/nametag\\?runs=0')
        self.assertTrue(self.response.body.startswith(b"\x1f\x8b"))
        self.assertTrue(len(self.response.body) > 1000)
        with open("/tmp/output.tar.gz", 'wb') as f:
            f.write(self.response.body)
        self.response = save.click(href='/event/event/1/download/nametag\\?runs=2')
        self.assertTrue(self.response.body.startswith(b"%PDF"))
        self.assertTrue(len(self.response.body) > 1000)

    @as_users("garcia")
    def test_download_export(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/download'},)
        self.assertTitle("Downloads zur Veranstaltung Große Testakademie 2222")
        self.traverse({'href': '/event/event/1/download/export$'})
        with open("/tmp/cdedb-store/testfiles/event_export.json") as datafile:
            expectation = json.load(datafile)
        result = json.loads(self.response.text)
        expectation['timestamp'] = result['timestamp'] # nearly_now() won't do
        self.assertEqual(expectation, result)

    @as_users("garcia")
    def test_download_csv(self, user):
        class dialect(csv.Dialect):
            delimiter = ';'
            quotechar = '"'
            doublequote = False
            escapechar = '\\'
            lineterminator = '\n'
            quoting = csv.QUOTE_MINIMAL

        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/download'},)
        save = self.response
        self.response = save.click(href='/event/event/1/download/csv_registrations')

        result = list(csv.DictReader(self.response.text.split('\n'),
                                     dialect=dialect))
        self.assertIn('2222-01-01', tuple(row['persona.birthday']
                                          for row in result))
        self.assertIn('high', tuple(row['part3.lodgement.fields.contamination']
                                    for row in result))
        self.assertIn('5', tuple(row['part2.status']
                                 for row in result))
        self.response = save.click(href='/event/event/1/download/csv_courses')

        result = list(csv.DictReader(self.response.text.split('\n'),
                                     dialect=dialect))
        self.assertIn('ToFi & Co', tuple(row['instructors'] for row in result))
        self.assertIn('cancelled', tuple(row['track2'] for row in result))
        self.assertIn('Seminarraum 42', tuple(row['fields.room']
                                              for row in result))
        self.response = save.click(href='/event/event/1/download/csv_lodgements')

        result = list(csv.DictReader(self.response.text.split('\n'),
                                     dialect=dialect))
        self.assertIn('100', tuple(row['reserve'] for row in result))
        self.assertIn('low', tuple(row['fields.contamination']
                                   for row in result))

    @as_users("garcia")
    def test_questionnaire_manipulation(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/change'})
        self.assertTitle("Große Testakademie 2222 – Konfiguration")
        f = self.response.forms['changeeventform']
        f['use_questionnaire'].checked = True
        self.submit(f)
        self.traverse({'href': '/event/event/1/registration/questionnaire'})
        self.assertTitle("Fragebogen (Große Testakademie 2222)")
        f = self.response.forms['questionnaireform']
        self.assertIn("brings_balls", f.fields)
        self.assertNotIn("may_reserve", f.fields)
        self.traverse({'href': '/event/event/1/questionnaire/summary'})
        self.assertTitle("Fragebogen konfigurieren (Große Testakademie 2222)")
        f = self.response.forms['questionnairesummaryform']
        self.assertEqual("3", f['field_id_5'].value)
        self.assertEqual("3", f['input_size_5'].value)
        f['input_size_5'] = 3
        self.assertEqual("2", f['field_id_4'].value)
        f['field_id_4'] = ""
        self.assertEqual("Weitere Überschrift", f['title_3'].value)
        f['title_3'] = "Immernoch Überschrift"
        self.assertEqual(False, f['readonly_1'].checked)
        f['readonly_1'].checked = True
        self.assertEqual("mit Text darunter", f['info_0'].value)
        f['info_0'] = "mehr Text darunter\nviel mehr"
        self.submit(f)
        self.assertTitle("Fragebogen konfigurieren (Große Testakademie 2222)")
        f = self.response.forms['questionnairesummaryform']
        self.assertEqual("3", f['field_id_5'].value)
        self.assertEqual("3", f['input_size_5'].value)
        self.assertEqual("", f['field_id_4'].value)
        self.assertEqual("Immernoch Überschrift", f['title_3'].value)
        self.assertEqual(True, f['readonly_1'].checked)
        self.assertEqual("mehr Text darunter\nviel mehr", f['info_0'].value)
        f['delete_1'].checked = True
        self.submit(f)
        self.assertTitle("Fragebogen konfigurieren (Große Testakademie 2222)")
        f = self.response.forms['questionnairesummaryform']
        self.assertNotIn("field_id_5", f.fields)
        self.assertEqual("Unterüberschrift", f['title_0'].value)
        self.assertEqual("nur etwas Text", f['info_1'].value)
        f['create_-1'].checked = True
        f['field_id_-1'] = 3
        f['title_-1'] = "Input"
        f['readonly_-1'].checked = True
        f['input_size_-1'] = 2
        self.submit(f)
        self.assertTitle("Fragebogen konfigurieren (Große Testakademie 2222)")
        f = self.response.forms['questionnairesummaryform']
        self.assertIn("field_id_5", f.fields)
        self.assertEqual("3", f['field_id_5'].value)
        self.assertEqual("Input", f['title_5'].value)

    @as_users("garcia")
    def test_questionnaire_reorder(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/questionnaire/summary'},
                      {'href': '/event/event/1/questionnaire/reorder'})
        f = self.response.forms['reorderquestionnaireform']
        f['order'] = '5,3,1,0,2,4'
        self.submit(f)
        self.assertTitle("Fragebogen konfigurieren (Große Testakademie 2222)")
        f = self.response.forms['questionnairesummaryform']
        self.assertEqual("3", f['field_id_0'].value)
        self.assertEqual("2", f['field_id_5'].value)
        self.assertEqual("1", f['field_id_2'].value)
        self.assertEqual("", f['field_id_3'].value)

    @as_users("garcia")
    def test_checkin(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/checkin'})
        self.assertTitle("Checkin (Große Testakademie 2222)")
        f = self.response.forms['checkinform2']
        self.submit(f)
        self.assertTitle("Checkin (Große Testakademie 2222)")
        self.assertNotIn('checkinform2', self.response.forms)

    @as_users("garcia")
    def test_checkin_concurrent_modification(self, user):
        """Test the special measures of the 'Edit' button at the Checkin page,
        that ensure that the checkin state is not overriden by the
        change_registration form"""
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/checkin'})
        f = self.response.forms['checkinform2']
        self.traverse({'href': '/event/event/1/registration/2/change'})
        f2 = self.response.forms['changeregistrationform']
        f2['part2.lodgement_id'] = 3
        self.submit(f)
        self.submit(f2)
        # Check that the change to lodgement was committed ...
        self.assertPresence("Kellerverlies")
        # ... but the checkin is still valid
        self.assertPresence("eingecheckt:")


    @as_users("garcia")
    def test_manage_attendees(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/course/list'},
                      {'href': '/event/event/1/course/1/show'})
        self.assertTitle("Kurs Heldentum (Große Testakademie 2222)")
        self.traverse({'href': '/event/event/1/course/1/manage'})
        self.assertTitle("\nKursteilnehmer für Kurs Planetenretten für Anfänger verwalten (Große Testakademie 2222)\n")
        f = self.response.forms['manageattendeesform']
        f['new_1'] = "3"
        f['delete_3_4'] = True
        self.submit(f)
        self.assertTitle("Kurs Heldentum (Große Testakademie 2222)")
        self.assertPresence("Garcia G.")
        self.assertNonPresence("Inga")

    @as_users("garcia")
    def test_manage_inhabitants(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/lodgement/overview'},
                      {'href': '/event/event/1/lodgement/2/show'})
        self.assertTitle("Unterkunft Kalte Kammer (Große Testakademie 2222)")
        self.assertPresence("Inga")
        self.assertNonPresence("Emilia")
        self.traverse({'href': '/event/event/1/lodgement/2/manage'})
        self.assertTitle("\nBewohner der Unterkunft Kalte Kammer verwalten (Große Testakademie 2222)\n")
        f = self.response.forms['manageinhabitantsform']
        f['new_1'] = ""
        f['delete_1_3'] = True
        f['new_2'] = ""
        f['new_3'].force_value(2)
        f['delete_3_4'] = True
        self.submit(f)
        self.assertTitle("Unterkunft Kalte Kammer (Große Testakademie 2222)")
        self.assertPresence("Emilia")
        self.assertPresence("Garcia")
        self.assertNonPresence("Inga")

    @as_users("anton", "garcia")
    def test_lock_event(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'})
        self.assertTitle("Große Testakademie 2222")
        self.assertPresence("Die Veranstaltung ist nicht gesperrt.")
        f = self.response.forms["lockform"]
        self.submit(f)
        self.assertTitle("Große Testakademie 2222")
        self.assertPresence("Die Veranstaltung ist zur Offline-Nutzung gesperrt.")

    @as_users("anton")
    def test_unlock_event(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'})
        self.assertTitle("Große Testakademie 2222")
        f = self.response.forms["lockform"]
        self.submit(f)
        self.traverse({'href': '/event/event/1/show'},
                      {'href': '/event/event/1/download'},)
        self.assertTitle("Downloads zur Veranstaltung Große Testakademie 2222")
        saved = self.response
        data = saved.click(href='/event/event/1/download/export$').body
        data = data.replace(b"Gro\\u00dfe Testakademie 2222",
                            b"Mittelgro\\u00dfe Testakademie 2222")
        self.response = saved
        self.traverse({'href': '/event/event/1/show'})
        self.assertTitle("Große Testakademie 2222")
        self.assertPresence("Die Veranstaltung ist zur Offline-Nutzung gesperrt.")
        f = self.response.forms['unlockform']
        f['json'] = webtest.Upload("event_export.json", data,
                                   "application/octet-stream")
        self.submit(f)
        self.assertTitle("Mittelgroße Testakademie 2222")
        self.assertPresence("Die Veranstaltung ist nicht gesperrt.")

    @as_users("anton")
    def test_archive(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'})
        self.assertTitle("Große Testakademie 2222")
        ## prepare dates
        self.traverse({'href': '/event/event/1/change'})
        f = self.response.forms["changeeventform"]
        f['registration_soft_limit'] = "2001-10-30 00:00:00+0000"
        f['registration_hard_limit'] = "2001-10-30 00:00:00+0000"
        self.submit(f)
        self.assertTitle("Große Testakademie 2222")
        self.traverse({'href': '/event/event/1/part/summary'})
        f = self.response.forms["partsummaryform"]
        f['part_begin_1'] = "2003-02-02"
        f['part_end_1'] = "2003-02-02"
        f['part_begin_2'] = "2003-11-01"
        f['part_end_2'] = "2003-11-11"
        f['part_begin_3'] = "2003-11-11"
        f['part_end_3'] = "2003-11-30"
        self.submit(f)
        self.assertTitle("Veranstaltungsteile konfigurieren (Große Testakademie 2222)")
        ## do it
        self.traverse({'href': '/event/event/1/show'})
        f = self.response.forms["archiveeventform"]
        f['ack_archive'].checked = True
        self.submit(f)
        self.assertTitle("Große Testakademie 2222")
        self.traverse({'href': '/cde/$'},
                      {'href': '/cde/past/event/list'})
        self.assertPresence("Große Testakademie 2222 (Warmup)")

    @as_users("anton")
    def test_one_track_no_courses(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/2/show'})
        # Check if course list is present (though we have no course track)
        self.assertNonPresence('/event/event/2/course/list', div="sidebar")
        self.assertNonPresence('/event/event/2/course/stats', div="sidebar")
        self.assertNonPresence('/event/event/2/course/choices', div="sidebar")

        # Add course track
        self.traverse({'href': '/event/event/2/part/summary'})
        f = self.response.forms['partsummaryform']
        f['track_create_4_-1'].checked = True
        f['track_title_4_-1'] = "Chillout Training"
        f['track_shortname_4_-1'] = "Chill"
        f['track_num_choices_4_-1'] = "1"
        f['track_sortkey_4_-1'] = "1"
        self.submit(f)

        # Add registration
        self.traverse({'href': '/event/event/2/registration/query'},
                      {'href': '/event/event/2/registration/add'})
        self.assertNonPresence('Partywoche')  # We have only one part, thus it should not be named
        self.assertNonPresence('Chillout')  # We have only one track, thus it should not be named
        f = self.response.forms['addregistrationform']
        f['persona.persona_id'] = "DB-2-7"
        f['part4.status'] = 1
        self.submit(f)
        self.assertNonPresence('Partywoche')
        self.assertNonPresence('Chillout')
        self.traverse({'href': '/event/event/2/registration/5/change'})
        self.assertNonPresence('Partywoche')
        self.assertNonPresence('Chillout')
        self.get("/event/event/2/registration/multiedit?reg_ids=5")
        self.assertNonPresence('Partywoche')
        self.assertNonPresence('Chillout')

        # Check course related pages for errors
        self.traverse({'href': '/event/event/2/course/list'})
        self.assertNonPresence('Partywoche')
        self.assertNonPresence('Chillout')
        self.traverse({'href': '/event/event/2/course/stats'})
        self.assertNonPresence('Partywoche')
        self.assertNonPresence('Chillout')
        self.traverse({'href': '/event/event/2/course/choices'})
        self.assertNonPresence('Partywoche')
        self.assertNonPresence('Chillout')

    def test_log(self):
        ## First: generate data
        self.test_register()
        self.logout()
        self.test_create_delete_course()
        self.logout()
        self.test_lodgements()
        self.logout()
        self.test_create_event()
        self.logout()
        self.test_manage_attendees()
        self.logout()

        ## Now check it
        self.login(USER_DICT['anton'])
        self.traverse({'href': '/event/$'},
                      {'href': '/event/log'})
        self.assertTitle("Veranstaltungen-Log [0–10]")
        f = self.response.forms['logshowform']
        f['codes'] = [10, 27, 51]
        f['event_id'] = 1
        f['start'] = 1
        f['stop'] = 10
        self.submit(f)
        self.assertTitle("Veranstaltungen-Log [1–2]")

        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/log'})
        self.assertTitle("Große Testakademie 2222: Log [0–6]")
