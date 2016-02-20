#!/usr/bin/env python3

import unittest
import quopri
import webtest
from test.common import as_users, USER_DICT, FrontendTest

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
        self.assertIn("Hyrule", self.response)
        self.assertEqual(
            "Zelda",
            self.response.lxml.get_element_by_id('displayname').text_content().strip())

    @as_users("anton")
    def test_adminchangeuser(self, user):
        f = self.response.forms['adminshowuserform']
        f['id_to_show'] = "DB-5-B"
        f['realm'] = "event"
        self.submit(f)
        self.traverse({'href': '/event/user/5/adminchange'})
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['birthday'] = "3.4.1933"
        self.submit(f)
        self.assertIn("Zelda", self.response)
        self.assertTitle("Emilia E. Eventis")
        self.assertIn("1933-04-03", self.response)

    @as_users("anton")
    def test_toggleactivity(self, user):
        f = self.response.forms['adminshowuserform']
        f['id_to_show'] = "DB-5-B"
        f['realm'] = "event"
        self.submit(f)
        self.assertTitle("Emilia E. Eventis")
        self.assertEqual(
            True,
            self.response.lxml.get_element_by_id('activity_checkbox').checked)
        f = self.response.forms['activitytoggleform']
        self.submit(f)
        self.assertEqual(
            False,
            self.response.lxml.get_element_by_id('activity_checkbox').checked)

    @as_users("anton")
    def test_user_search(self, user):
        self.traverse({'href': '/event/$'}, {'href': '/event/search/user/form'})
        self.assertTitle("Veranstaltungsnutzersuche")
        f = self.response.forms['usersearchform']
        f['qval_username'] = 'a@'
        for field in f.fields:
            if field.startswith('qsel_'):
                f[field].checked = True
        self.submit(f)
        self.assertTitle("\nVeranstaltungsnutzersuche -- 4 Ergebnisse gefunden\n")
        self.assertPresence("Hohle Gasse 13")

    @as_users("anton")
    def test_create_user(self, user):
        self.traverse({'href': '/event/$'}, {'href': '/event/user/create'})
        self.assertTitle("Neuen Veranstaltungsnutzer anlegen")
        data = {
            "username": 'zelda@example.cde',
            "title": "Dr.",
            "given_names": "Zelda",
            "family_name": "Zeruda-Hime",
            "name_supplement": 'von und zu',
            "display_name": 'Zelda',
            "birthday": "5.6.1987",
            "gender": "0",
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

    def test_genesis(self):
        user = USER_DICT['anton']
        self.get('/')
        self.traverse({'href': '/core/genesis/request'})
        self.assertTitle("Account anfordern")
        f = self.response.forms['genesisform']
        f['given_names'] = "Zelda"
        f['family_name'] = "Zeruda-Hime"
        f['username'] = "zelda@example.cde"
        f['notes'] = "Gimme!"
        f['realm'] = "event"
        self.submit(f)
        mail = self.fetch_mail()[0]
        link = None
        for line in mail.split('\n'):
            if line.startswith('[1] '):
                link = line[4:]
        link = quopri.decodestring(link).decode('utf-8')
        self.get(link)
        self.follow()
        self.login(user)
        self.traverse({'href': '/core/genesis/list'})
        self.assertTitle("Accountanfragen (zurzeit 1 zu begutachten)")
        f = self.response.forms['genesisapprovalform1']
        f['realm'] = "event"
        self.submit(f)
        mail = self.fetch_mail()[0]
        link = None
        for line in mail.split('\n'):
            if line.startswith('[1] '):
                link = line[4:]
        link = quopri.decodestring(link).decode('utf-8')
        self.assertTitle("Accountanfragen (zurzeit 0 zu begutachten)")
        self.logout()
        self.get(link)
        self.assertTitle("Veranstaltungsaccount anlegen")
        data = {
            "title": "Dr.",
            "name_supplement": 'von und zu',
            "display_name": 'Zelda',
            "birthday": "5.6.1987",
            "gender": "0",
            "telephone": "030456790",
            ## "mobile"
            "address": "Street 7",
            "address_supplement": "on the left",
            "postal_code": "12345",
            "location": "Lynna",
            "country": "Hyrule",
        }
        f = self.response.forms['newuserform']
        for key, value in data.items():
            f.set(key, value)
        self.submit(f)
        data["given_names"] = "Zelda",
        data["family_name"] = "Zeruda-Hime",
        self.assertTitle("Passwort zurücksetzen -- Bestätigung")
        new_password = "saFe_37pass"
        f = self.response.forms['passwordresetform']
        f['new_password'] = new_password
        self.submit(f)
        new_user = {
            'id': 9,
            'username': "zelda@example.cde",
            'password': new_password,
            'display_name': "Zelda",
            'given_names': "Zelda",
            'family_name': "Zeruda-Hime",
        }
        self.login(new_user)
        self.traverse({'href': '/core/self/show'})
        self.assertTitle("Zelda Zeruda-Hime")
        self.assertPresence("12345")

    def test_genesis_timeout(self):
        user = USER_DICT['anton']
        self.get('/')
        self.traverse({'href': '/core/genesis/request'})
        self.assertTitle("Account anfordern")
        f = self.response.forms['genesisform']
        f['given_names'] = "Zelda"
        f['family_name'] = "Zeruda-Hime"
        f['username'] = "zelda@example.cde"
        f['realm'] = "event"
        f['notes'] = "Gimme!"
        self.submit(f)
        mail = self.fetch_mail()[0]
        link = None
        for line in mail.split('\n'):
            if line.startswith('[1] '):
                link = line[4:]
        link = quopri.decodestring(link).decode('utf-8')
        self.get(link)
        self.follow()
        self.login(user)
        self.traverse({'href': '/core/genesis/list'})
        self.assertTitle("Accountanfragen (zurzeit 1 zu begutachten)")
        f = self.response.forms['genesisapprovalform1']
        f['realm'] = "event"
        self.submit(f)
        mail = self.fetch_mail()[0]
        link = None
        for line in mail.split('\n'):
            if line.startswith('[1] '):
                link = line[4:]
        link = quopri.decodestring(link).decode('utf-8')
        self.assertTitle("Accountanfragen (zurzeit 0 zu begutachten)")
        self.assertPresence("zelda@example.cde")
        f = self.response.forms['genesistimeoutform1']
        self.submit(f)
        self.assertTitle("Accountanfragen (zurzeit 0 zu begutachten)")
        self.assertNonPresence("zelda@example.cde")

    @as_users("anton")
    def test_list_past_events(self, user):
        self.traverse({'href': '/event/$'}, {'href': '/event/pastevent/list'})
        self.assertTitle("Alle abgeschlossenen Veranstaltungen")
        self.assertPresence("PfingstAkademie")

    @as_users("anton")
    def test_show_past_event_course(self, user):
        self.traverse({'href': '/event/$'}, {'href': '/event/pastevent/list'})
        self.assertTitle("Alle abgeschlossenen Veranstaltungen")
        self.assertPresence("PfingstAkademie")
        self.traverse({'href': '/event/pastevent/1/show'})
        self.assertTitle("PfingstAkademie 2014")
        self.assertPresence("Great event!")
        self.traverse({'href': '/event/pastevent/1/pastcourse/1/show'})
        self.assertTitle("Swish -- und alles ist gut (PfingstAkademie 2014)")
        self.assertPresence("Ringelpiez")

    @as_users("anton")
    def test_list_events(self, user):
        self.traverse({'href': '/event/$'}, {'href': '/event/event/list'})
        self.assertTitle("Alle DB-Veranstaltungen")
        self.assertPresence("Große Testakademie 2222")
        self.assertNonPresence("PfingstAkademie 2014")

    @as_users("anton", "berta", "emilia")
    def test_show_event_course(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'})
        self.assertTitle("Große Testakademie 2222")
        self.assertPresence("Everybody come!")
        self.assertPresence("ToFi")
        self.assertPresence("Wir werden die Bäume drücken.")
        self.traverse({'href': '/event/event/1/course/1/show'})
        self.assertTitle("Planetenretten für Anfänger (Große Testakademie 2222)")
        self.assertPresence("ToFi")
        self.assertPresence("Wir werden die Bäume drücken.")

    @as_users("anton")
    def test_change_past_event(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/pastevent/list'},
                      {'href': '/event/pastevent/1/show'},
                      {'href': '/event/pastevent/1/change'},)
        self.assertTitle("PfingstAkademie 2014 bearbeiten")
        f = self.response.forms['changeeventform']
        f['title'] = "Link Academy"
        f['organizer'] = "Privatvergnügen"
        f['description'] = "Ganz ohne Minderjährige."
        self.submit(f)
        self.assertTitle("Link Academy")
        self.assertPresence("Privatvergnügen")
        self.assertPresence("Ganz ohne Minderjährige.")

    @as_users("anton")
    def test_create_past_event(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/pastevent/create'})
        self.assertTitle("Veranstaltung anlegen")
        f = self.response.forms['createeventform']
        f['title'] = "Link Academy II"
        f['organizer'] = "Privatvergnügen"
        f['description'] = "Ganz ohne Minderjährige."
        f['tempus'] = "1.1.2000"
        self.submit(f)
        self.assertTitle("Link Academy II")
        self.assertPresence("Privatvergnügen")
        self.assertPresence("Ganz ohne Minderjährige.")

    @as_users("anton")
    def test_change_past_course(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/pastevent/list'},
                      {'href': '/event/pastevent/1/show'},
                      {'href': '/event/pastevent/1/pastcourse/1/show'},
                      {'href': '/event/pastevent/1/pastcourse/1/change'})
        self.assertTitle("Swish -- und alles ist gut (PfingstAkademie 2014) bearbeiten")
        f = self.response.forms['changecourseform']
        f['title'] = "Omph"
        f['description'] = "Loud and proud."
        self.submit(f)
        self.assertTitle("Omph (PfingstAkademie 2014)")
        self.assertPresence("Loud and proud.")

    @as_users("anton")
    def test_create_past_course(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/pastevent/list'},
                      {'href': '/event/pastevent/1/show'},
                      {'href': '/event/pastevent/1/pastcourse/create'},)
        self.assertTitle("Kurs hinzufügen (PfingstAkademie 2014)")
        f = self.response.forms['createcourseform']
        f['title'] = "Abstract Nonsense"
        f['description'] = "Lots of arrows."
        self.submit(f)
        self.assertTitle("Abstract Nonsense (PfingstAkademie 2014)")
        self.assertPresence("Lots of arrows.")

    @as_users("anton")
    def test_delete_past_course(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/pastevent/list'},
                      {'href': '/event/pastevent/1/show'},
                      {'href': '/event/pastevent/1/pastcourse/create'},)
        self.assertTitle("Kurs hinzufügen (PfingstAkademie 2014)")
        f = self.response.forms['createcourseform']
        f['title'] = "Abstract Nonsense"
        self.submit(f)
        self.assertTitle("Abstract Nonsense (PfingstAkademie 2014)")
        f = self.response.forms['deletecourseform']
        self.submit(f)
        self.assertTitle("PfingstAkademie 2014")
        self.assertNonPresence("Abstract Nonsense")

    @as_users("anton")
    def test_participant_manipulation(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/pastevent/list'},
                      {'href': '/event/pastevent/1/show'},
                      {'href': '/event/pastevent/1/pastcourse/1/show'},)
        self.assertTitle("Swish -- und alles ist gut (PfingstAkademie 2014)")
        self.assertNonPresence("Emilia")
        f = self.response.forms['addparticipantform']
        f['persona_id'] = "DB-5-B"
        f['is_orga'].checked = True
        f['is_instructor'].checked = True
        self.submit(f)
        self.assertTitle("Swish -- und alles ist gut (PfingstAkademie 2014)")
        self.assertPresence("Emilia")
        f = self.response.forms['removeparticipantform5']
        self.submit(f)
        self.assertTitle("Swish -- und alles ist gut (PfingstAkademie 2014)")
        self.assertNonPresence("Emilia")

        self.traverse({'href': '/event/$'},
                      {'href': '/event/pastevent/list'},
                      {'href': '/event/pastevent/1/show'})
        f = self.response.forms['addparticipantform']
        f['persona_id'] = "DB-5-B"
        f['is_orga'].checked = True
        self.submit(f)
        self.assertTitle("PfingstAkademie 2014")
        self.assertPresence("Emilia")
        f = self.response.forms['removeparticipantform5']
        self.submit(f)
        self.assertTitle("PfingstAkademie 2014")
        self.assertNonPresence("Emilia")

    @as_users("anton", "garcia")
    def test_change_event(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/config'},
                      {'href': '/event/event/1/change'})
        self.assertTitle("Große Testakademie 2222 bearbeiten")
        ## basic event data
        f = self.response.forms['changeeventform']
        self.assertEqual(f['registration_start'].value, "2000-10-30")
        f['title'] = "Universale Akademie"
        f['registration_start'] = "2001-10-30"
        f['notes'] = """Some

        more

        text"""
        f['use_questionnaire'].checked = True
        self.submit(f)
        self.assertTitle("Universale Akademie Details")
        self.assertNonPresence("2000-10-30")
        self.assertPresence("2001-10-30")
        ## orgas
        self.assertNonPresence("Bertålotta")
        f = self.response.forms['addorgaform']
        f['orga_id'] = "DB-2-H"
        self.submit(f)
        self.assertTitle("Universale Akademie Details")
        self.assertPresence("Bertålotta")
        f = self.response.forms['removeorgaform2']
        self.submit(f)
        self.assertTitle("Universale Akademie Details")
        self.assertNonPresence("Bertålotta")
        ## parts
        self.assertPresence("Warmup")
        self.assertNonPresence("Cooldown")
        f = self.response.forms['addpartform']
        f['part_title'] = "Cooldown"
        f['part_begin'] = "2233-4-5"
        f['part_end'] = "2233-6-7"
        f['fee'] = "23456.78"
        self.submit(f)
        self.assertTitle("Universale Akademie Details")
        self.assertPresence("Cooldown")
        self.traverse({'href': '/event/event/1/part/3/change'})
        self.assertTitle("Zweite Hälfte (Universale Akademie) bearbeiten")
        f = self.response.forms['changepartform']
        f['title'] = "Größere Hälfte"
        f['fee'] = "99.99"
        self.submit(f)
        self.assertTitle("Universale Akademie Details")
        self.assertNonPresence("Zweite Hälfte")
        self.assertPresence("Größere Hälfte")
        ## fields
        self.assertPresence("transportation")
        self.assertNonPresence("food_stuff")
        f = self.response.forms['addfieldform']
        f['field_name'] = "food_stuff"
        f['kind'] = "str"
        f['entries'] = """all;everything goes
        vegetarian;no meat
        vegan;plants only"""
        self.submit(f)
        self.assertTitle("Universale Akademie Details")
        self.assertPresence("food_stuff")
        self.traverse({'href': '/event/event/1/field/2/change'})
        self.assertTitle("\nDatenfeld transportation (Universale Akademie) bearbeiten\n")
        self.assertPresence("own car available")
        self.assertNonPresence("broom")
        f = self.response.forms['changefieldform']
        f['entries'] = """pedes;by feet
        broom;flying implements
        etc;anything else"""
        self.submit(f)
        self.assertTitle("Universale Akademie Details")
        self.assertNonPresence("own car available")
        self.assertPresence("broom")
        f = self.response.forms['removefieldform8']
        self.submit(f)
        self.assertTitle("Universale Akademie Details")
        self.assertNonPresence("food_stuff")

    @as_users("anton", "garcia")
    def test_change_minor_form(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/config'})
        self.assertTitle("Große Testakademie 2222 Details")
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
                      {'href': '/event/event/create'})
        self.assertTitle("DB-Veranstaltung anlegen")
        f = self.response.forms['createeventform']
        f['title'] = "Universale Akademie"
        f['organizer'] = "CdE"
        f['description'] = "Mit Co und Coco."
        f['shortname'] = "UnAka"
        f['registration_start'] = "2000-01-01"
        f['notes'] = "Die spinnen die Orgas."
        f['orga_ids'] = "DB-2-H, DB-7-I"
        self.submit(f)
        self.assertTitle("Universale Akademie")
        self.assertPresence("Mit Co und Coco.")
        self.traverse({'href': '/event/event/2/config'})
        self.assertPresence("Bertålotta")
        self.assertPresence("Garcia")

    @as_users("anton", "garcia")
    def test_change_course(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/course/1/change'})
        self.assertTitle("Planetenretten für Anfänger (Große Testakademie 2222) bearbeiten")
        self.assertTrue(self.response.lxml.get_element_by_id('manipulator_checkbox_1').checked)
        self.assertFalse(self.response.lxml.get_element_by_id('manipulator_checkbox_2').checked)
        self.assertTrue(self.response.lxml.get_element_by_id('manipulator_checkbox_3').checked)
        f = self.response.forms['changecourseform']
        f['title'] = "Planetenretten für Fortgeschrittene"
        f['nr'] = "ω"
        f['parts'] = ['2', '3']
        self.submit(f)
        self.assertTitle("Planetenretten für Fortgeschrittene (Große Testakademie 2222)")
        self.traverse({'href': '/event/event/1/course/1/change'})
        f = self.response.forms['changecourseform']
        self.assertEqual(f['nr'].value, "ω")
        self.assertFalse(self.response.lxml.get_element_by_id('manipulator_checkbox_1').checked)
        self.assertTrue(self.response.lxml.get_element_by_id('manipulator_checkbox_2').checked)
        self.assertTrue(self.response.lxml.get_element_by_id('manipulator_checkbox_3').checked)

    @as_users("anton")
    def test_create_course(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'})
        self.assertTitle("Große Testakademie 2222")
        self.assertPresence("Planetenretten für Anfänger")
        self.assertNonPresence("Abstract Nonsense")
        self.traverse({'href': '/event/event/1/course/create'})
        self.assertTitle("DB-Kurs hinzufügen (Große Testakademie 2222)")
        self.assertTrue(self.response.lxml.get_element_by_id('manipulator_checkbox_1').checked)
        self.assertTrue(self.response.lxml.get_element_by_id('manipulator_checkbox_2').checked)
        self.assertTrue(self.response.lxml.get_element_by_id('manipulator_checkbox_3').checked)
        f = self.response.forms['createcourseform']
        f['title'] = "Abstract Nonsense"
        f['description'] = "Lots of arrows."
        f['nr'] = "ω"
        f['shortname'] = "math"
        f['instructors'] = "Alexander Grothendieck"
        f['notes'] = "transcendental appearence"
        f['parts'] = ['1', '3']
        self.submit(f)
        self.assertTitle("Abstract Nonsense (Große Testakademie 2222)")
        self.assertPresence("Lots of arrows.")
        self.assertPresence("Alexander Grothendieck")
        self.traverse({'href': '/event/event/1/course/6/change'})
        self.assertTitle("Abstract Nonsense (Große Testakademie 2222) bearbeiten")
        self.assertTrue(self.response.lxml.get_element_by_id('manipulator_checkbox_1').checked)
        self.assertFalse(self.response.lxml.get_element_by_id('manipulator_checkbox_2').checked)
        self.assertTrue(self.response.lxml.get_element_by_id('manipulator_checkbox_3').checked)

    @as_users("berta")
    def test_register(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/register'})
        self.assertTitle("Anmeldung zur Veranstaltung Große Testakademie 2222")
        f = self.response.forms['registerform']
        f['parts'] = ['1', '3']
        f['mixed_lodging'] = 'True'
        f['foto_consent'].checked = True
        f['notes'] = "Ich freu mich schon so zu kommen\n\nyeah!\n"
        f['course_choice1_0'] = 1
        f['course_choice1_1'] = 4
        f['course_choice1_2'] = 5
        f['course_choice3_0'] = 2
        f['course_choice3_1'] = 4
        f['course_choice3_2'] = 1
        f['course_instructor3'] = 2
        self.submit(f)
        self.assertTitle("Status der Anmeldung zur Veranstaltung Große Testakademie 2222")
        mail = self.fetch_mail()[0]
        self.assertIn("461.49", mail)
        self.assertPresence("Ich freu mich schon so zu kommen")
        self.traverse({'href': '/event/event/1/registration/amend'})
        self.assertTitle("Anmeldung zur Veranstaltung Große Testakademie 2222 aktualisieren")
        self.assertPresence("Warmup")
        self.assertNonPresence("Erste Hälfte")
        self.assertPresence("Zweite Hälfte")
        f = self.response.forms['amendregistrationform']
        self.assertEqual("4", f['course_choice1_1'].value)
        self.assertEqual("1", f['course_choice3_2'].value)
        self.assertEqual("", f['course_instructor1'].value)
        self.assertEqual("2", f['course_instructor3'].value)
        self.assertPresence("Ich freu mich schon so zu kommen")
        f['notes'] = "Ich kann es kaum erwarten!"
        f['course_choice3_2'] = 5
        f['course_instructor3'] = 1
        self.submit(f)
        self.assertTitle("Status der Anmeldung zur Veranstaltung Große Testakademie 2222")
        self.assertPresence("Ich kann es kaum erwarten!")
        self.traverse({'href': '/event/event/1/registration/amend'})
        self.assertTitle("Anmeldung zur Veranstaltung Große Testakademie 2222 aktualisieren")
        f = self.response.forms['amendregistrationform']
        self.assertEqual("5", f['course_choice3_2'].value)
        self.assertEqual("1", f['course_instructor3'].value)
        self.assertPresence("Ich kann es kaum erwarten!")

    @as_users("garcia")
    def test_questionnaire(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/config'},
                      {'href': '/event/event/1/change'})
        self.assertTitle("Große Testakademie 2222 bearbeiten")
        f = self.response.forms['changeeventform']
        f['use_questionnaire'].checked = True
        self.submit(f)
        self.traverse({'href': '/event/event/1/registration/questionnaire'})
        self.assertTitle("Fragebogen zur Veranstaltung Große Testakademie 2222")
        f = self.response.forms['questionnaireform']
        self.assertEqual(False, f['brings_balls'].checked)
        f['brings_balls'].checked = True
        self.assertEqual("car", f['transportation'].value)
        f['transportation'] = "etc"
        self.assertEqual("", f['lodge'].value)
        f['lodge'] = "Bitte in ruhiger Lage.\nEcht."
        self.submit(f)
        self.traverse({'href': '/event/event/1/registration/questionnaire'})
        self.assertTitle("Fragebogen zur Veranstaltung Große Testakademie 2222")
        f = self.response.forms['questionnaireform']
        self.assertEqual(True, f['brings_balls'].checked)
        self.assertEqual("etc", f['transportation'].value)
        self.assertEqual("Bitte in ruhiger Lage.\nEcht.", f['lodge'].value)

    @as_users("garcia")
    def test_registration_query(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/registration/query'})
        self.assertTitle("Anmeldungen (Große Testakademie 2222)")
        f = self.response.forms['registrationqueryform']
        for field in f.fields:
            if field.startswith('qsel_'):
                f[field].checked = True
        f['qval_persona.family_name'] = 'e'
        f['qord_primary'] = 'reg.id'
        self.submit(f)
        self.assertTitle("\nAnmeldungen (Große Testakademie 2222) -- 2 Ergebnisse\n")
        self.assertPresence("Emilia")
        self.assertPresence("Garcia")
        self.assertEqual(
            '4',
            self.response.lxml.get_element_by_id('row_0_lodgement_id2').value)
        self.assertEqual(
            '',
            self.response.lxml.get_element_by_id('row_1_lodgement_id2').value)
        f = self.response.forms['actionform']
        f['row_0'].checked = True
        f['row_1'].checked = False
        f['column'] = 'part2.lodgement_id2'
        f['value'] = 3
        self.submit(f)
        self.assertTitle("\nAnmeldungen (Große Testakademie 2222) -- 2 Ergebnisse\n")
        self.assertEqual(
            '3',
            self.response.lxml.get_element_by_id('row_0_lodgement_id2').value)
        self.assertEqual(
            '',
            self.response.lxml.get_element_by_id('row_1_lodgement_id2').value)

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
        self.assertPresence("Planetenretten für Anfänger")
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
        self.assertEqual("2", f['part1.status'].value)
        f['part1.status'] = 1
        self.assertEqual("4", f['part2.lodgement_id'].value)
        f['part2.lodgement_id'] = 3
        self.assertEqual("2", f['part3.course_choice_1'].value)
        f['part3.course_choice_1'] = 5
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
        self.assertEqual("1", f['part1.status'].value)
        self.assertEqual("3", f['part2.lodgement_id'].value)
        self.assertEqual("5", f['part3.course_choice_1'].value)
        self.assertEqual("etc", f['fields.transportation'].value)
        self.assertEqual("Om nom nom nom", f['fields.lodge'].value)

    @as_users("garcia")
    def test_add_registration(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/registration/add'})
        self.assertTitle("Neue Anmeldung (Große Testakademie 2222)")
        f = self.response.forms['addregistrationform']
        f['user_data.persona_id'] = "DB-2-H"
        f['reg.orga_notes'] = "Du entkommst uns nicht."
        f['reg.mixed_lodging'].checked = True
        f['part1.status'] = 1
        f['part2.status'] = 3
        f['part3.status'] = 2
        f['part1.lodgement_id'] = 4
        f['part1.course_id'] = 5
        f['part1.course_choice_0'] = 5
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
        self.assertEqual("5", f['part1.course_id'].value)
        self.assertEqual("5", f['part1.course_choice_0'].value)

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
        self.submit(f)
        self.traverse({'href': '/event/event/1/lodgement/4/change'})
        self.assertTitle("Unterkunft Einzelzelle bearbeiten (Große Testakademie 2222)")
        f = self.response.forms['changelodgementform']
        self.assertEqual("3", f['capacity'].value)
        self.assertEqual("neu mit Anbau", f['notes'].value)
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
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/field/setselect'})
        self.assertTitle("Feld auswählen (Große Testakademie 2222)")
        f = self.response.forms['selectfieldform']
        f['field_id'] = 2
        self.submit(f)
        self.assertTitle("\nFeld transportation setzen (Große Testakademie 2222)\n")
        f = self.response.forms['fieldform']
        self.assertEqual("pedes", f['input2'].value)
        f['input2'] = "etc"
        self.submit(f)
        self.traverse({'href': '/event/event/1/field/setselect'})
        self.assertTitle("Feld auswählen (Große Testakademie 2222)")
        f = self.response.forms['selectfieldform']
        f['field_id'] = 2
        self.submit(f)
        self.assertTitle("\nFeld transportation setzen (Große Testakademie 2222)\n")
        f = self.response.forms['fieldform']
        self.assertEqual("etc", f['input2'].value)

        self.traverse({'href': '/event/event/1/field/setselect'})
        self.assertTitle("Feld auswählen (Große Testakademie 2222)")
        f = self.response.forms['selectfieldform']
        f['field_id'] = 3
        self.submit(f)
        self.assertTitle("\nFeld lodge setzen (Große Testakademie 2222)\n")
        f = self.response.forms['fieldform']
        self.assertEqual("", f['input4'].value)
        f['input4'] = "Test\nmit\n\nLeerzeilen"
        self.submit(f)
        self.traverse({'href': '/event/event/1/field/setselect'})
        self.assertTitle("Feld auswählen (Große Testakademie 2222)")
        f = self.response.forms['selectfieldform']
        f['field_id'] = 3
        self.submit(f)
        self.assertTitle("\nFeld lodge setzen (Große Testakademie 2222)\n")
        f = self.response.forms['fieldform']
        self.assertEqual("Test\nmit\nLeerzeilen", f['input4'].value)

    @as_users("garcia")
    def test_summary(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/summary'},)
        self.assertTitle("Teilnehmer-Übersicht Große Testakademie 2222")
        self.assertPresence("Zweite Hälfte -- 1")

    @as_users("garcia")
    def test_course_choices(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/coursechoices'},)
        self.assertTitle("Kurswahlen -- Übersicht (Große Testakademie 2222)")
        self.assertPresence("Planetenretten für Anfänger")
        self.assertIn("<td> 2 </td>", self.response.text)
        f = self.response.forms['choiceform']
        f['course_id'] = 1
        self.submit(f)
        self.assertTitle("\nKurswahlen -- Planetenretten für Anfänger (Große Testakademie 2222)\n")
        self.assertPresence("Emilia E.")

    @as_users("garcia")
    def test_downloads(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/download'},)
        self.assertTitle("Downloads zur Veranstaltung Große Testakademie 2222")
        save = self.response
        f = save.forms['coursepuzzletexform']
        self.submit(f)
        self.assertPresence('documentclass')
        self.assertPresence('Planetenretten für Anfänger')
        f = save.forms['coursepuzzlepdfform']
        self.submit(f)
        self.assertTrue(self.response.body.startswith(b"%PDF"))
        self.assertTrue(len(self.response.body) > 1000)
        f = save.forms['lodgementpuzzletexform']
        self.submit(f)
        self.assertPresence('documentclass')
        self.assertPresence('Kalte Kammer')
        f = save.forms['lodgementpuzzlepdfform']
        self.submit(f)
        self.assertTrue(self.response.body.startswith(b"%PDF"))
        self.assertTrue(len(self.response.body) > 1000)
        f = save.forms['lodgementliststexform']
        self.submit(f)
        self.assertTrue(self.response.body.startswith(b"\x1f\x8b"))
        self.assertTrue(len(self.response.body) > 1000)
        f = save.forms['lodgementlistspdfform']
        self.submit(f)
        self.assertTrue(self.response.body.startswith(b"%PDF"))
        self.assertTrue(len(self.response.body) > 1000)
        f = save.forms['courseliststexform']
        self.submit(f)
        self.assertTrue(self.response.body.startswith(b"\x1f\x8b"))
        self.assertTrue(len(self.response.body) > 1000)
        f = save.forms['courselistspdfform']
        self.submit(f)
        self.assertTrue(self.response.body.startswith(b"%PDF"))
        self.assertTrue(len(self.response.body) > 1000)
        f = save.forms['expulsform']
        self.submit(f)
        self.assertPresence('\\kurs')
        self.assertPresence('Planetenretten für Anfänger')
        f = save.forms['participantlisttexform']
        self.submit(f)
        self.assertPresence('documentclass')
        self.assertPresence('Heldentum')
        self.assertPresence('Emilia E.')
        f = save.forms['participantlistpdfform']
        self.submit(f)
        self.assertTrue(self.response.body.startswith(b"%PDF"))
        self.assertTrue(len(self.response.body) > 1000)
        f = save.forms['nametagtexform']
        self.submit(f)
        self.assertTrue(self.response.body.startswith(b"\x1f\x8b"))
        self.assertTrue(len(self.response.body) > 1000)
        with open("/tmp/output.tar.gz", 'wb') as f:
            f.write(self.response.body)
        f = save.forms['nametagpdfform']
        self.submit(f)
        self.assertTrue(self.response.body.startswith(b"%PDF"))
        self.assertTrue(len(self.response.body) > 1000)

    @as_users("garcia")
    def test_questionnaire_manipulation(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/config'},
                      {'href': '/event/event/1/change'})
        self.assertTitle("Große Testakademie 2222 bearbeiten")
        f = self.response.forms['changeeventform']
        f['use_questionnaire'].checked = True
        self.submit(f)
        self.traverse({'href': '/event/event/1/registration/questionnaire'})
        self.assertTitle("Fragebogen zur Veranstaltung Große Testakademie 2222")
        f = self.response.forms['questionnaireform']
        self.assertIn("brings_balls", f.fields)
        self.assertNotIn("may_reserve", f.fields)
        self.traverse({'href': '/event/event/1/config'},
                      {'href': '/event/event/1/questionnaire/change'},)
        self.assertTitle("Fragebogen bearbeiten (Große Testakademie 2222)")
        f = self.response.forms['changequestionnaireform']
        self.assertEqual("3", f['field_id_5'].value)
        f['field_id_5'] = 5
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
        self.assertTitle("Große Testakademie 2222 Details")
        saved = self.response
        self.traverse({'href': '/event/event/1/questionnaire/change'},)
        self.assertTitle("Fragebogen bearbeiten (Große Testakademie 2222)")
        f = self.response.forms['changequestionnaireform']
        self.assertEqual("5", f['field_id_5'].value)
        self.assertEqual("4", f['input_size_5'].value)
        self.assertEqual("", f['field_id_4'].value)
        self.assertEqual("Immernoch Überschrift", f['title_3'].value)
        self.assertEqual(True, f['readonly_1'].checked)
        self.assertEqual("mehr Text darunter\nviel mehr", f['info_0'].value)
        f = saved.forms['removequestionnairerowform1']
        self.submit(f)
        self.assertTitle("Große Testakademie 2222 Details")
        saved = self.response
        self.traverse({'href': '/event/event/1/questionnaire/change'},)
        self.assertTitle("Fragebogen bearbeiten (Große Testakademie 2222)")
        f = self.response.forms['changequestionnaireform']
        self.assertNotIn("field_id_5", f.fields)
        self.assertEqual("Unterüberschrift", f['title_0'].value)
        self.assertEqual("nur etwas Text", f['info_1'].value)
        f = saved.forms['addquestionnairerowform']
        f['row_field_id'] = 3
        f['row_title'] = "Input"
        f['row_readonly'].checked = True
        f['row_input_size'] = 4
        self.submit(f)
        self.assertTitle("Große Testakademie 2222 Details")
        self.traverse({'href': '/event/event/1/questionnaire/change'},)
        self.assertTitle("Fragebogen bearbeiten (Große Testakademie 2222)")
        f = self.response.forms['changequestionnaireform']
        self.assertIn("field_id_5", f.fields)
        self.assertEqual("3", f['field_id_5'].value)
        self.assertEqual("Input", f['title_5'].value)

    @as_users("garcia")
    def test_questionnaire_reorder(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/config'},
                      {'href': '/event/event/1/questionnaire/reorder'})
        f = self.response.forms['reorderquestionnaireform']
        f['order'] = '5,3,1,0,2,4'
        self.submit(f)
        self.assertTitle("Große Testakademie 2222 Details")
        self.traverse({'href': '/event/event/1/questionnaire/change'},)
        self.assertTitle("Fragebogen bearbeiten (Große Testakademie 2222)")
        f = self.response.forms['changequestionnaireform']
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
                      {'href': '/event/event/1/course/1/show'},
                      {'href': '/event/event/1/course/1/manage'})
        self.assertTitle("\nKursteilnehmer für Kurs Planetenretten für Anfänger verwalten (Große Testakademie 2222)\n")
        f = self.response.forms['manageattendeesform']
        f['attendees_1'] = ""
        f['attendees_3'] = "2,3"
        self.submit(f)
        self.assertTitle("Planetenretten für Anfänger (Große Testakademie 2222)")
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
        f['inhabitants_1'] = ""
        f['inhabitants_2'] = "3"
        f['inhabitants_3'] = "2,3"
        self.submit(f)
        self.assertTitle("Unterkunft Kalte Kammer (Große Testakademie 2222)")
        self.assertPresence("Emilia")
        self.assertNonPresence("Inga")

    @as_users("anton")
    def test_archive(self, user):
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/config'})
        self.assertTitle("Große Testakademie 2222 Details")
        ## prepare dates
        self.traverse({'href': '/event/event/1/change'})
        f = self.response.forms["changeeventform"]
        f['registration_soft_limit'] = "2001-10-30"
        f['registration_hard_limit'] = "2001-10-30"
        self.submit(f)
        self.assertTitle("Große Testakademie 2222 Details")
        self.traverse({'href': '/event/event/1/part/1/change'})
        f = self.response.forms["changepartform"]
        f['part_begin'] = "2003-02-02"
        f['part_end'] = "2003-02-02"
        self.submit(f)
        self.assertTitle("Große Testakademie 2222 Details")
        self.traverse({'href': '/event/event/1/part/2/change'})
        f = self.response.forms["changepartform"]
        f['part_begin'] = "2003-11-01"
        f['part_end'] = "2003-11-11"
        self.submit(f)
        self.assertTitle("Große Testakademie 2222 Details")
        self.traverse({'href': '/event/event/1/part/3/change'})
        f = self.response.forms["changepartform"]
        f['part_begin'] = "2003-11-11"
        f['part_end'] = "2003-11-30"
        self.submit(f)
        self.assertTitle("Große Testakademie 2222 Details")
        ## do it
        f = self.response.forms["archiveeventform"]
        self.submit(f)
        self.assertTitle("Große Testakademie 2222")
        self.assertIn("removeparticipantform7", self.response.forms)

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
        self.assertTitle("\nVeranstaltungen -- Logs (0--14)\n")
        f = self.response.forms['logshowform']
        f['codes'] = [10, 27, 51]
        f['event_id'] = 1
        f['start'] = 1
        f['stop'] = 10
        self.submit(f)
        self.assertTitle("\nVeranstaltungen -- Logs (1--6)\n")

        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/log'})
        self.assertTitle("\nGroße Testakademie 2222 -- Logs (0--11)\n")

    def test_past_log(self):
        ## First: generate data
        self.test_participant_manipulation()
        self.logout()
        self.test_change_past_course()
        self.logout()
        self.test_create_past_course()
        self.logout()
        self.test_change_past_event()
        self.logout()
        self.test_create_past_event()
        self.logout()

        ## Now check it
        self.login(USER_DICT['anton'])
        self.traverse({'href': '/event/$'},
                      {'href': '/pastevent/log'})
        self.assertTitle("\nAbgeschlossene Veranstaltungen -- Logs (0--8)\n")
        f = self.response.forms['logshowform']
        f['codes'] = [0, 10, 21]
        f['start'] = 1
        f['stop'] = 10
        self.submit(f)
        self.assertTitle("\nAbgeschlossene Veranstaltungen -- Logs (1--4)\n")
