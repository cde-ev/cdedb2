#!/usr/bin/env python3

import json
import unittest
import quopri
import webtest
from test.common import as_users, USER_DICT, FrontendTest, nearly_now

from cdedb.query import QueryOperators

class TestEventFrontend(FrontendTest):
    @as_users("anton", "berta", "emilia")
    def test_index(self, user):
        self.traverse({'href': '/event/'})

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

    @as_users("anton")
    def test_adminchangeuser(self, user):
        self.admin_view_profile('emilia')
        self.traverse({'href': '/core/persona/5/adminchange'})
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['birthday'] = "3.4.1933"
        self.assertNotIn('free_form', f.fields)
        self.submit(f)
        self.assertPresence("Zelda")
        self.assertTitle("Emilia E. Eventis")
        self.assertPresence("03.04.1933")

    @as_users("anton")
    def test_toggleactivity(self, user):
        self.admin_view_profile('emilia')
        self.assertEqual(
            True,
            self.response.lxml.get_element_by_id('activity_checkbox').get('data-checked') == 'True')
        f = self.response.forms['activitytoggleform']
        self.submit(f)
        self.assertEqual(
            False,
            self.response.lxml.get_element_by_id('activity_checkbox').get('data-checked') == 'True')

    @as_users("anton")
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
        self.assertPresence("Ergebnis [4]")
        self.assertPresence("Hohle Gasse 13")

    @as_users("anton")
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

    @as_users("anton", "garcia")
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
        f['orga_id'] = "DB-2-H"
        self.submit(f)
        self.assertTitle("Universale Akademie")
        self.assertPresence("Bertålotta")
        f = self.response.forms['removeorgaform2']
        self.submit(f)
        self.assertTitle("Universale Akademie")
        self.assertNonPresence("Bertålotta")

    @as_users("anton", "garcia")
    def test_part_summary_trivial(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/part/summary'})
        self.assertTitle("Große Testakademie 2222 Teile konfigurieren")
        f = self.response.forms['partsummaryform']
        self.assertEqual("Warmup", f['title_1'].value)

    @as_users("anton")
    def test_part_summary_complex(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/list'},
                      {'href': '/event/event/create'})
        f = self.response.forms['createeventform']
        f['title'] = "Universale Akademie"
        f['institution'] = 1
        f['description'] = "Mit Co und Coco."
        f['shortname'] = "UnAka"
        f['event_begin'] = "2345-01-01"
        f['event_end'] = "2345-6-7"
        f['registration_start'] = "2000-01-01 00:00:00+0000"
        f['notes'] = "Die spinnen die Orgas."
        f['orga_ids'] = "DB-2-H, DB-7-I"
        self.submit(f)
        self.assertTitle("Universale Akademie")
        ## Here we go
        self.traverse({'href': '/event/event/2/part/summary'})
        self.assertTitle("Universale Akademie Teile konfigurieren")
        f = self.response.forms['partsummaryform']
        self.assertNotIn('title_5', f.fields)
        f['create_-1'].checked = True
        f['title_-1'] = "Cooldown"
        f['part_begin_-1'] = "2233-4-5"
        f['part_end_-1'] = "2233-6-7"
        f['fee_-1'] = "23456.78"
        f['track_create_-1_-1'].checked = True
        f['track_-1_-1'] = "Chillout"
        self.submit(f)
        self.assertTitle("Universale Akademie Teile konfigurieren")
        f = self.response.forms['partsummaryform']
        self.assertEqual("Cooldown", f['title_5'].value)
        self.assertEqual("Chillout", f['track_5_4'].value)
        f['title_5'] = "Größere Hälfte"
        f['fee_5'] = "99.99"
        self.submit(f)
        ## and now for tracks
        self.assertTitle("Universale Akademie Teile konfigurieren")
        f = self.response.forms['partsummaryform']
        self.assertNotIn('track_5_5', f.fields)
        f['track_5_-1'] = "Spätschicht"
        f['track_create_5_-1'].checked = True
        self.submit(f)
        f = self.response.forms['partsummaryform']
        self.assertEqual("Spätschicht", f['track_5_5'].value)
        f['track_5_5'] = "Nachtschicht"
        self.submit(f)
        f = self.response.forms['partsummaryform']
        self.assertEqual("Nachtschicht", f['track_5_5'].value)
        f['track_delete_5_5'].checked = True
        self.submit(f)
        self.assertTitle("Universale Akademie Teile konfigurieren")
        f = self.response.forms['partsummaryform']
        self.assertNotIn('track_5_5', f.fields)
        ## finally deletion
        self.assertTitle("Universale Akademie Teile konfigurieren")
        f = self.response.forms['partsummaryform']
        self.assertEqual("Größere Hälfte", f['title_5'].value)
        f['delete_5'].checked = True
        self.submit(f)
        self.assertTitle("Universale Akademie Teile konfigurieren")
        f = self.response.forms['partsummaryform']
        self.assertNotIn('title_5', f.fields)

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
        f['association_-1'] = "1"
        f['kind_-1'] = "str"
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

    @as_users("anton")
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
        f['orga_ids'] = "DB-2-H, DB-7-I"
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
        self.assertTitle("Heldentum (Große Testakademie 2222) bearbeiten")
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
    def test_create_course(self, user):
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
        self.assertPresence("transcendental appearence")
        self.assertPresence("Alexander Grothendieck")
        self.traverse({'href': '/event/event/1/course/6/change'})
        self.assertTitle("math (Große Testakademie 2222) bearbeiten")
        f = self.response.forms['changecourseform']
        self.assertEqual("1", f.get('segments', index=0).value)
        self.assertEqual(None, f.get('segments', index=1).value)
        self.assertEqual("3", f.get('segments', index=2).value)

    @as_users("berta")
    def test_register(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/register'})
        self.assertTitle("Anmeldung für Große Testakademie 2222")
        f = self.response.forms['registerform']
        f['parts'] = ['1', '3']
        f['mixed_lodging'] = 'True'
        f['foto_consent'].checked = True
        f['notes'] = "Ich freu mich schon so zu kommen\n\nyeah!\n"
        f['course_choice3_0'] = 2
        f['course_choice3_1'] = 4
        f['course_choice3_2'] = 1
        self.assertNotIn('5', tuple(o for o, _, _ in f['course_choice3_2'].options))
        f['course_instructor3'] = 2
        self.submit(f)
        self.assertTitle("Deine Anmeldung (Große Testakademie 2222)")
        mail = self.fetch_mail()[0]
        self.assertIn("461.49", mail)
        self.assertPresence("Ich freu mich schon so zu kommen")
        self.traverse({'href': '/event/event/1/registration/amend'})
        self.assertTitle("Anmeldung für Große Testakademie 2222 ändern")
        self.assertNonPresence("Morgenkreis")
        self.assertNonPresence("Kaffeekränzchen")
        self.assertPresence("Arbeitssitzung")
        f = self.response.forms['amendregistrationform']
        self.assertEqual("1", f['course_choice3_2'].value)
        self.assertEqual("2", f['course_instructor3'].value)
        self.assertPresence("Ich freu mich schon so zu kommen")
        f['notes'] = "Ich kann es kaum erwarten!"
        f['course_choice3_1'] = 1
        f['course_choice3_2'] = 4
        f['course_instructor3'] = 1
        self.submit(f)
        self.assertTitle("Deine Anmeldung (Große Testakademie 2222)")
        self.assertPresence("Ich kann es kaum erwarten!")
        self.traverse({'href': '/event/event/1/registration/amend'})
        self.assertTitle("Anmeldung für Große Testakademie 2222 ändern")
        f = self.response.forms['amendregistrationform']
        self.assertEqual("4", f['course_choice3_2'].value)
        self.assertEqual("1", f['course_instructor3'].value)
        self.assertPresence("Ich kann es kaum erwarten!")

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
        f['fee_data'] = """01.04.2018;570.99;DB-1-J;Admin;Anton
01.04.2018;461.49;DB-5-B;Eventis;Emilia
01.04.2018;570.99;DB-11-G;K;Kalif
77.04.2018;0.0;DB-666-X;Y;Z;stuff
"""
        self.submit(f, check_notification=False)
        f = self.response.forms['batchfeesform']
        f['fee_data'] = """01.04.2018;573.99;DB-1-J;Admin;Anton
04.01.2018;461.49;DB-5-B;Eventis;Emilia
"""
        self.submit(f, check_notification=False)
        f = self.response.forms['batchfeesform']
        f['force'].checked = True
        self.submit(f)
        self.traverse({'href': '/event/event/1/show'},
                      {'href': '/event/event/1/registration/query'},
                      {'description': 'Alle Anmeldungen'},
                      {'href': '/event/event/1/registration/1/show'})
        self.assertTitle("Anmeldung von Anton Armin A. Administrator (Große Testakademie 2222)")
        self.assertPresence("bezahlt am 01.04.2018")
        self.traverse({'href': '/event/event/1/show'},
                      {'href': '/event/event/1/registration/query'},
                      {'description': 'Alle Anmeldungen'},
                      {'href': '/event/event/1/registration/2/show'})
        self.assertTitle("Anmeldung von Emilia E. Eventis (Große Testakademie 2222)")
        self.assertPresence("bezahlt am 04.01.2018")

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
        self.assertTitle("\nAnmeldung von Emilia E. Eventis bearbeiten\n(Große Testakademie 2222)\n")
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
        f['persona.persona_id'] = "DB-2-H"
        f['reg.orga_notes'] = "Du entkommst uns nicht."
        f['reg.mixed_lodging'].checked = True
        f['part1.status'] = 1
        f['part2.status'] = 3
        f['part3.status'] = 2
        f['part1.lodgement_id'] = 4
        f['track1.course_id'] = 5
        f['track1.course_choice_0'] = 5
        self.submit(f)
        self.assertTitle("\nAnmeldung von Bertålotta Beispiel (Große Testakademie 2222)\n")
        self.assertPresence("Du entkommst uns nicht.")
        self.traverse({'href': '/event/event/1/registration/5/change'})
        f = self.response.forms['changeregistrationform']
        self.assertEqual("Du entkommst uns nicht.", f['reg.orga_notes'].value)
        self.assertEqual(True, f['reg.mixed_lodging'].checked)
        self.assertEqual("1", f['part1.status'].value)
        self.assertEqual("3", f['part2.status'].value)
        self.assertEqual("2", f['part3.status'].value)
        self.assertEqual("4", f['part1.lodgement_id'].value)
        self.assertEqual("5", f['track1.course_id'].value)
        self.assertEqual("5", f['track1.course_choice_0'].value)

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
        self.assertTitle("Unterkunftsübersicht (Große Testakademie 2222)")
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
        self.assertTitle("Unterkunftsübersicht (Große Testakademie 2222)")
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
        self.assertTitle("Feld auswählen (Große Testakademie 2222)")
        self.assertNonPresence("Inga")
        f = self.response.forms['selectfieldform']
        f['field_id'] = 2
        self.submit(f)
        self.assertTitle("Feld transportation setzen (Große Testakademie 2222)")
        f = self.response.forms['fieldform']
        self.assertEqual("pedes", f['input2'].value)
        f['input2'] = "etc"
        self.submit(f)
        self.traverse({'href': '/event/event/1/field/setselect'})
        self.assertTitle("Feld auswählen (Große Testakademie 2222)")
        f = self.response.forms['selectfieldform']
        f['field_id'] = 2
        self.submit(f)
        self.assertTitle("Feld transportation setzen (Große Testakademie 2222)")
        f = self.response.forms['fieldform']
        self.assertEqual("etc", f['input2'].value)
        # Value of Inga should not have changed
        self.assertEqual("etc", f['input4'].value)

        self.traverse({'href': '/event/event/1/registration/query'},
                      {'href': '/event/event/1/field/setselect'})
        self.assertTitle("Feld auswählen (Große Testakademie 2222)")
        f = self.response.forms['selectfieldform']
        f['field_id'] = 3
        self.submit(f)
        self.assertTitle("Feld lodge setzen\n    (Große Testakademie 2222)")
        f = self.response.forms['fieldform']
        self.assertEqual("", f['input4'].value)
        f['input4'] = "Test\nmit\n\nLeerzeilen"
        self.submit(f)
        self.traverse({'href': '/event/event/1/registration/query'},
                      {'href': '/event/event/1/field/setselect'})
        self.assertTitle("Feld auswählen (Große Testakademie 2222)")
        f = self.response.forms['selectfieldform']
        f['field_id'] = 3
        self.submit(f)
        self.assertTitle("Feld lodge setzen\n    (Große Testakademie 2222)")
        f = self.response.forms['fieldform']
        self.assertEqual("Test\nmit\n\nLeerzeilen", f['input4'].value)

    @as_users("garcia")
    def test_stats(self, user):
        ## first check stats
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/stats'},)
        self.assertTitle("Teilnehmer-Übersicht Große Testakademie 2222")
        self.assertNonPresence("Inga Iota")
        ## second create some verifiable output
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/registration/query'})
        self.assertTitle("Anmeldungen (Große Testakademie 2222)")
        self.traverse({'description': 'Alle Anmeldungen'},
                      {'href': '/event/event/1/registration/4/show'},
                      {'href': '/event/event/1/registration/4/change'})
        self.assertTitle("\nAnmeldung von Inga Iota bearbeiten\n(Große Testakademie 2222)\n")
        f = self.response.forms['changeregistrationform']
        self.assertEqual("1", f['track3.course_id'].value)
        f['track3.course_id'] = 5
        self.submit(f)
        ## third check change
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/stats'},)
        self.assertTitle("Teilnehmer-Übersicht Große Testakademie 2222")
        self.assertPresence("Inga Iota")

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
        self.submit(f)
        self.assertNonPresence("Anton Armin")
        self.assertPresence("Emilia")
        self.assertPresence("Garcia")
        self.assertPresence("Inga")
        f = self.response.forms['choicefilterform']
        f['course_id'] = 4
        f['position'] = 4
        self.submit(f)
        self.assertNonPresence("Anton Armin")
        self.assertNonPresence("Emilia")
        self.assertPresence("Garcia")
        self.assertPresence("Inga")
        f = self.response.forms['choicefilterform']
        f['course_id'] = 4
        f['position'] = 4
        f['track_id'] = 3
        self.submit(f)
        self.assertNonPresence("Anton Armin")
        self.assertNonPresence("Emilia")
        self.assertNonPresence("Garcia")
        self.assertPresence("Inga")
        f = self.response.forms['choicefilterform']
        f['course_id'] = ''
        f['position'] = ''
        f['track_id'] = ''
        self.submit(f)
        f = self.response.forms['choiceactionform']
        f['registration_ids'] = [1, 2]
        f['track_ids'] = [3]
        f['action'] = 1
        self.submit(f)
        f = self.response.forms['choicefilterform']
        f['course_id'] = 1
        f['position'] = 6
        f['track_id'] = 3
        self.submit(f)
        self.assertPresence("Anton Armin")
        self.assertNonPresence("Emilia")
        self.assertNonPresence("Garcia")
        self.assertPresence("Inga")
        f = self.response.forms['choicefilterform']
        f['course_id'] = 4
        f['position'] = 6
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
        f['track_ids'] = [2, 3]
        f['action'] = 4
        f['course_id'] = 5
        self.submit(f)
        f = self.response.forms['choicefilterform']
        f['course_id'] = 5
        f['position'] = 6
        self.submit(f)
        self.assertNonPresence("Anton Armin")
        self.assertNonPresence("Emilia")
        self.assertPresence("Garcia")
        self.assertNonPresence("Inga")

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
        f['track_ids'] = [1,2, 3]
        f['action'] = 5
        self.submit(f)

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
        self.response = save.click(href='/event/event/1/download/participantlist\\?runs=0')
        self.assertPresence('documentclass')
        self.assertPresence('Heldentum')
        self.assertPresence('Emilia E.')
        self.response = save.click(href='/event/event/1/download/participantlist\\?runs=2')
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
        self.assertTitle("Fragebogen-Konfiguration (Große Testakademie 2222)")
        f = self.response.forms['questionnairesummaryform']
        self.assertEqual("3", f['field_id_5'].value)
        self.assertEqual("3", f['input_size_5'].value)
        f['input_size_5'] = 4
        self.assertEqual("2", f['field_id_4'].value)
        f['field_id_4'] = ""
        self.assertEqual("Weitere Überschrift", f['title_3'].value)
        f['title_3'] = "Immernoch Überschrift"
        self.assertEqual(False, f['readonly_1'].checked)
        f['readonly_1'].checked = True
        self.assertEqual("mit Text darunter", f['info_0'].value)
        f['info_0'] = "mehr Text darunter\nviel mehr"
        self.submit(f)
        self.assertTitle("Fragebogen-Konfiguration (Große Testakademie 2222)")
        f = self.response.forms['questionnairesummaryform']
        self.assertEqual("3", f['field_id_5'].value)
        self.assertEqual("4", f['input_size_5'].value)
        self.assertEqual("", f['field_id_4'].value)
        self.assertEqual("Immernoch Überschrift", f['title_3'].value)
        self.assertEqual(True, f['readonly_1'].checked)
        self.assertEqual("mehr Text darunter\nviel mehr", f['info_0'].value)
        f['delete_1'].checked = True
        self.submit(f)
        self.assertTitle("Fragebogen-Konfiguration (Große Testakademie 2222)")
        f = self.response.forms['questionnairesummaryform']
        self.assertNotIn("field_id_5", f.fields)
        self.assertEqual("Unterüberschrift", f['title_0'].value)
        self.assertEqual("nur etwas Text", f['info_1'].value)
        f['create_-1'].checked = True
        f['field_id_-1'] = 3
        f['title_-1'] = "Input"
        f['readonly_-1'].checked = True
        f['input_size_-1'] = 4
        self.submit(f)
        self.assertTitle("Fragebogen-Konfiguration (Große Testakademie 2222)")
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
        self.assertTitle("Fragebogen-Konfiguration (Große Testakademie 2222)")
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
        self.assertTitle("Große Testakademie 2222 Teile konfigurieren")
        ## do it
        self.traverse({'href': '/event/event/1/show'})
        f = self.response.forms["archiveeventform"]
        f['ack_archive'].checked = True
        self.submit(f)
        self.assertTitle("Große Testakademie 2222")
        self.assertIn("removeparticipantform7", self.response.forms)

    @as_users("anton")
    def test_one_track_no_courses(self, user):
        # First, create a new event
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/list'},
                      {'href': '/event/event/create'})
        self.assertTitle("Veranstaltung anlegen")
        f = self.response.forms['createeventform']
        f['title'] = "Universale Akademie"
        f['institution'] = 1
        f['shortname'] = "UnAka"
        f['event_begin'] = "2345-01-01"
        f['event_end'] = "2345-6-7"
        f['registration_start'] = "2000-01-01 00:00:00+0000"
        f['orga_ids'] = "DB-2-H"
        self.submit(f)

        # Check if course list is present (though we have no course track)
        self.assertNonPresence('/event/event/2/course/list', div="sidebar")
        self.assertNonPresence('/event/event/2/course/stats', div="sidebar")
        self.assertNonPresence('/event/event/2/course/choices', div="sidebar")

        # Add course track
        self.traverse({'href': '/event/event/2/part/summary'})
        f = self.response.forms['partsummaryform']
        f['title_4'] = "Partywoche"
        f['track_create_4_-1'].checked = True
        f['track_4_-1'] = "Chillout"
        self.submit(f)

        # Add registration
        self.traverse({'href': '/event/event/2/registration/query'},
                      {'href': '/event/event/2/registration/add'})
        self.assertNonPresence('Partywoche')  # We have only one part, thus it should not be named
        self.assertNonPresence('Chillout')  # We have only one track, thus it should not be named
        f = self.response.forms['addregistrationform']
        f['persona.persona_id'] = "DB-2-H"
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
        self.test_create_course()
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
        self.assertTitle("Log: Veranstaltungen [0–17]")
        f = self.response.forms['logshowform']
        f['codes'] = [10, 27, 51]
        f['event_id'] = 1
        f['start'] = 1
        f['stop'] = 10
        self.submit(f)
        self.assertTitle("Log: Veranstaltungen [1–4]")

        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/log'})
        self.assertTitle("Log: Große Testakademie 2222 [0–13]")
