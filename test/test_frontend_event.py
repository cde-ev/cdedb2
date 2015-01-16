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
        self.traverse({'href': '/mydata'})
        self.assertTitle("{} {}".format(user['given_names'],
                                        user['family_name']))

    @as_users("emilia")
    def test_changeuser(self, user):
        self.traverse({'href': '/mydata'}, {'href': '/event/changeuser', 'index': 0})
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['location'] = "Hyrule"
        self.submit(f)
        self.assertIn("Hyrule", self.response)
        self.assertEqual(
            "Zelda",
            self.response.lxml.get_element_by_id('displayname').text_content())

    @as_users("anton")
    def test_adminchangeuser(self, user):
        f = self.response.forms['adminshowuserform']
        f['id_to_show'] = 5
        self.submit(f)
        self.traverse({'href': '/event/adminchangeuser', 'index': 0})
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
        f['id_to_show'] = 5
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
        self.traverse({'description': '^Veranstaltungen$'}, {'href': '/usersearch'})
        self.assertTitle("Veranstaltungsnutzersuche")
        f = self.response.forms['usersearchform']
        f['qval_username'] = 'a@'
        f['qsel_user_data.persona_id'].checked = True
        f['qsel_address'].checked = True
        self.submit(f)
        self.assertTitle("Veranstaltungsnutzersuche -- 1 Ergebnis gefunden")
        self.assertIn("Hohle Gasse 13", self.response.text)

    @as_users("anton")
    def test_create_user(self, user):
        self.traverse({'description': '^Veranstaltungen$'}, {'href': '/createuser'})
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
        self.assertIn("12345", self.response.text)

    def test_genesis(self):
        user = USER_DICT['anton']
        self.get('/')
        self.traverse({'href': '/genesisrequest'})
        self.assertTitle("Account anfordern")
        f = self.response.forms['genesisform']
        f['full_name'] = "Zelda"
        f['username'] = "zelda@example.cde"
        f['rationale'] = "Gimme!"
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
        self.traverse({'href': '/genesislistcases'})
        self.assertTitle("Accountanfragen (zurzeit 1 zu begutachten)")
        f = self.response.forms['genesisapprovalform1']
        f['persona_status'] = 20
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
        }
        f = self.response.forms['newuserform']
        for key, value in data.items():
            f.set(key, value)
        self.submit(f)
        self.assertTitle("Passwort zurücksetzen")
        f = self.response.forms['passwordresetform']
        self.submit(f)
        mail = self.fetch_mail()[0]
        for line in mail.split('\n'):
            if line.startswith('zur'):
                words = line.split(' ')
                break
        index = words.index('nun')
        new_password = quopri.decodestring(words[index + 1])
        new_user = {
            'id': 9,
            'username': "zelda@example.cde",
            'password': new_password,
            'display_name': "Zelda",
            'given_names': "Zelda",
            'family_name': "Zeruda-Hime",
        }
        self.login(new_user)
        self.traverse({'href': '/mydata'})
        self.assertTitle("Zelda Zeruda-Hime")
        self.assertIn("12345", self.response.text)

    def test_genesis_timeout(self):
        user = USER_DICT['anton']
        self.get('/')
        self.traverse({'href': '/genesisrequest'})
        self.assertTitle("Account anfordern")
        f = self.response.forms['genesisform']
        f['full_name'] = "Zelda"
        f['username'] = "zelda@example.cde"
        f['rationale'] = "Gimme!"
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
        self.traverse({'href': '/genesislistcases'})
        self.assertTitle("Accountanfragen (zurzeit 1 zu begutachten)")
        f = self.response.forms['genesisapprovalform1']
        f['persona_status'] = 20
        self.submit(f)
        mail = self.fetch_mail()[0]
        link = None
        for line in mail.split('\n'):
            if line.startswith('[1] '):
                link = line[4:]
        link = quopri.decodestring(link).decode('utf-8')
        self.assertTitle("Accountanfragen (zurzeit 0 zu begutachten)")
        self.assertIn("zelda@example.cde", self.response.text)
        f = self.response.forms['genesistimeoutform1']
        self.submit(f)
        self.assertTitle("Accountanfragen (zurzeit 0 zu begutachten)")
        self.assertNotIn("zelda@example.cde", self.response.text)

    @as_users("anton")
    def test_list_past_events(self, user):
        self.traverse({'description': '^Veranstaltungen$'}, {'href': '/listpastevents'})
        self.assertTitle("Alle abgeschlossenen Veranstaltungen")
        self.assertIn("PfingstAkademie", self.response.text)

    @as_users("anton")
    def test_show_past_event_course(self, user):
        self.traverse({'description': '^Veranstaltungen$'}, {'href': '/listpastevents'})
        self.assertTitle("Alle abgeschlossenen Veranstaltungen")
        self.assertIn("PfingstAkademie", self.response.text)
        self.traverse({'href': '/showpastevent/1'})
        self.assertTitle("PfingstAkademie 2014")
        self.assertIn("Great event!", self.response.text)
        self.traverse({'href': '/showpastcourse/1/1'})
        self.assertTitle("Swish -- und alles ist gut (PfingstAkademie 2014)")
        self.assertIn("Ringelpiez", self.response.text)

    @as_users("anton")
    def test_list_events(self, user):
        self.traverse({'description': '^Veranstaltungen$'}, {'href': '/listevents'})
        self.assertTitle("Alle DB-Veranstaltungen")
        self.assertIn("Große Testakademie 2222", self.response.text)
        self.assertNotIn("PfingstAkademie 2014", self.response.text)

    @as_users("anton", "berta", "emilia")
    def test_show_event_course(self, user):
        self.traverse({'description': '^Veranstaltungen$'},
                      {'href': '/showevent/1'})
        self.assertTitle("Große Testakademie 2222")
        self.assertIn("Everybody come!", self.response.text)
        self.assertIn("ToFi", self.response.text)
        self.assertIn("Wir werden die Bäume drücken.", self.response.text)
        self.traverse({'href': '/showcourse/1/1'})
        self.assertTitle("Planetenretten für Anfänger (Große Testakademie 2222)")
        self.assertIn("ToFi", self.response.text)
        self.assertIn("Wir werden die Bäume drücken.", self.response.text)

    @as_users("anton")
    def test_change_past_event(self, user):
        self.traverse({'description': '^Veranstaltungen$'},
                      {'href': '/listpastevents'},
                      {'href': '/showpastevent/1'},
                      {'href': '/changepastevent/1'},)
        self.assertTitle("PfingstAkademie 2014 bearbeiten")
        f = self.response.forms['changeeventform']
        f['title'] = "Link Academy"
        f['organizer'] = "Privatvergnügen"
        f['description'] = "Ganz ohne Minderjährige."
        self.submit(f)
        self.assertTitle("Link Academy")
        self.assertIn("Privatvergnügen", self.response.text)
        self.assertIn("Ganz ohne Minderjährige.", self.response.text)

    @as_users("anton")
    def test_create_past_event(self, user):
        self.traverse({'description': '^Veranstaltungen$'},
                      {'href': '/createpastevent'})
        self.assertTitle("Veranstaltung anlegen")
        f = self.response.forms['createeventform']
        f['title'] = "Link Academy"
        f['organizer'] = "Privatvergnügen"
        f['description'] = "Ganz ohne Minderjährige."
        self.submit(f)
        self.assertTitle("Link Academy")
        self.assertIn("Privatvergnügen", self.response.text)
        self.assertIn("Ganz ohne Minderjährige.", self.response.text)

    @as_users("anton")
    def test_change_past_course(self, user):
        self.traverse({'description': '^Veranstaltungen$'},
                      {'href': '/listpastevents'},
                      {'href': '/showpastevent/1'},
                      {'href': '/showpastcourse/1/1'},
                      {'href': '/changepastcourse/1/1'})
        self.assertTitle("Swish -- und alles ist gut (PfingstAkademie 2014) bearbeiten")
        f = self.response.forms['changecourseform']
        f['title'] = "Omph"
        f['description'] = "Loud and proud."
        self.submit(f)
        self.assertTitle("Omph (PfingstAkademie 2014)")
        self.assertIn("Loud and proud.", self.response.text)

    @as_users("anton")
    def test_create_past_course(self, user):
        self.traverse({'description': '^Veranstaltungen$'},
                      {'href': '/listpastevents'},
                      {'href': '/showpastevent/1'},
                      {'href': '/createpastcourse/1'},)
        self.assertTitle("Kurs hinzufügen (PfingstAkademie 2014)")
        f = self.response.forms['createcourseform']
        f['title'] = "Abstract Nonsense"
        f['description'] = "Lots of arrows."
        self.submit(f)
        self.assertTitle("Abstract Nonsense (PfingstAkademie 2014)")
        self.assertIn("Lots of arrows.", self.response.text)

    @as_users("anton")
    def test_delete_past_course(self, user):
        self.traverse({'description': '^Veranstaltungen$'},
                      {'href': '/listpastevents'},
                      {'href': '/showpastevent/1'},
                      {'href': '/createpastcourse/1'},)
        self.assertTitle("Kurs hinzufügen (PfingstAkademie 2014)")
        f = self.response.forms['createcourseform']
        f['title'] = "Abstract Nonsense"
        self.submit(f)
        self.assertTitle("Abstract Nonsense (PfingstAkademie 2014)")
        f = self.response.forms['deletecourseform']
        self.submit(f)
        self.assertTitle("PfingstAkademie 2014")
        self.assertNotIn("Abstract Nonsense", self.response.text)

    @as_users("anton")
    def test_participant_manipulation(self, user):
        self.traverse({'description': '^Veranstaltungen$'},
                      {'href': '/listpastevents'},
                      {'href': '/showpastevent/1'},
                      {'href': '/showpastcourse/1/1'},)
        self.assertTitle("Swish -- und alles ist gut (PfingstAkademie 2014)")
        self.assertNotIn("Emilia", self.response.text)
        f = self.response.forms['addparticipantform']
        f['persona_id'] = "DB-5-F"
        f['is_orga'].checked = True
        f['is_instructor'].checked = True
        self.submit(f)
        self.assertTitle("Swish -- und alles ist gut (PfingstAkademie 2014)")
        self.assertIn("Emilia", self.response.text)
        f = self.response.forms['removeparticipantform5']
        self.submit(f)
        self.assertTitle("Swish -- und alles ist gut (PfingstAkademie 2014)")
        self.assertNotIn("Emilia", self.response.text)

        self.traverse({'description': '^Veranstaltungen$'},
                      {'href': '/listpastevents'},
                      {'href': '/showpastevent/1'})
        f = self.response.forms['addparticipantform']
        f['persona_id'] = "DB-5-F"
        f['is_orga'].checked = True
        self.submit(f)
        self.assertTitle("PfingstAkademie 2014")
        self.assertIn("Emilia", self.response.text)
        f = self.response.forms['removeparticipantform5']
        self.submit(f)
        self.assertTitle("PfingstAkademie 2014")
        self.assertNotIn("Emilia", self.response.text)

    @as_users("anton", "garcia")
    def test_change_event(self, user):
        self.traverse({'description': '^Veranstaltungen$'},
                      {'href': '/showevent/1'},
                      {'href': '/changeevent/1', 'index': 0})
        self.assertTitle("Große Testakademie 2222 bearbeiten")
        ## basic event data
        self.assertIn("2000-10-30", self.response.text)
        self.assertNotIn("2001-10-30", self.response.text)
        f = self.response.forms['changeeventform']
        f['title'] = "Universale Akademie"
        f['registration_start'] = "2001-10-30"
        f['notes'] = """Some

        more

        text"""
        f['use_questionnaire'].checked = True
        self.submit(f)
        self.assertTitle("Universale Akademie bearbeiten")
        self.assertNotIn("2000-10-30", self.response.text)
        self.assertIn("2001-10-30", self.response.text)
        ## orgas
        self.assertNotIn("Bertålotta", self.response.text)
        f = self.response.forms['addorgaform']
        f['orga_id'] = "DB-2-C"
        self.submit(f)
        self.assertTitle("Universale Akademie bearbeiten")
        self.assertIn("Bertålotta", self.response.text)
        f = self.response.forms['removeorgaform2']
        self.submit(f)
        self.assertTitle("Universale Akademie bearbeiten")
        self.assertNotIn("Bertålotta", self.response.text)
        ## parts
        self.assertIn("Warmup", self.response.text)
        self.assertNotIn("Cooldown", self.response.text)
        f = self.response.forms['addpartform']
        f['part_title'] = "Cooldown"
        f['part_begin'] = "2233-4-5"
        f['part_end'] = "2233-6-7"
        f['fee'] = "23456.78"
        self.submit(f)
        self.assertTitle("Universale Akademie bearbeiten")
        self.assertIn("Cooldown", self.response.text)
        self.traverse({'href': '/changepart/1/3'})
        self.assertTitle("Zweite Hälfte (Universale Akademie) bearbeiten")
        f = self.response.forms['changepartform']
        f['title'] = "Größere Hälfte"
        f['fee'] = "99.99"
        self.submit(f)
        self.assertTitle("Universale Akademie bearbeiten")
        self.assertNotIn("Zweite Hälfte", self.response.text)
        self.assertIn("Größere Hälfte", self.response.text)
        ## fields
        self.assertIn("transportation", self.response.text)
        self.assertNotIn("food_stuff", self.response.text)
        f = self.response.forms['addfieldform']
        f['field_name'] = "food_stuff"
        f['kind'] = "str"
        f['entries'] = """all;everything goes
        vegetarian;no meat
        vegan;plants only"""
        self.submit(f)
        self.assertTitle("Universale Akademie bearbeiten")
        self.assertIn("food_stuff", self.response.text)
        self.traverse({'href': '/changefield/1/2'})
        self.assertTitle("Datenfeld transportation (Universale Akademie) bearbeiten")
        self.assertIn("own car available", self.response.text)
        self.assertNotIn("broom", self.response.text)
        f = self.response.forms['changefieldform']
        f['entries'] = """pedes;by feet
        broom;flying implements
        etc;anything else"""
        self.submit(f)
        self.assertTitle("Universale Akademie bearbeiten")
        self.assertNotIn("own car available", self.response.text)
        self.assertIn("broom", self.response.text)
        f = self.response.forms['removefieldform3']
        self.submit(f)
        self.assertTitle("Universale Akademie bearbeiten")
        self.assertNotIn("food_stuff", self.response.text)

    @as_users("anton", "garcia")
    def test_change_minor_form(self, user):
        self.traverse({'description': '^Veranstaltungen$'},
                      {'href': '/showevent/1'},
                      {'href': '/changeevent/1', 'index': 0})
        self.assertTitle("Große Testakademie 2222 bearbeiten")
        f = self.response.forms['changeminorformform']
        f['minor_form'] = webtest.Upload("/tmp/cdedb-store/testfiles/form.pdf")
        self.submit(f)
        self.traverse({'href': '/getminorform/1'})
        with open("/tmp/cdedb-store/testfiles/form.pdf", 'rb') as f:
            self.assertEqual(f.read(), self.response.body)

    @as_users("anton")
    def test_create_event(self, user):
        self.traverse({'description': '^Veranstaltungen$'},
                      {'href': '/createevent'})
        self.assertTitle("DB-Veranstaltung anlegen")
        f = self.response.forms['createeventform']
        f['title'] = "Universale Akademie"
        f['organizer'] = "CdE"
        f['description'] = "Mit Co und Coco."
        f['shortname'] = "UnAka"
        f['registration_start'] = "2000-01-01"
        f['notes'] = "Die spinnen die Orgas."
        f['orga_ids'] = "DB-2-C, DB-7-H"
        self.submit(f)
        self.assertTitle("Universale Akademie")
        self.assertIn("Mit Co und Coco.", self.response.text)
        self.traverse({'href': '/changeevent', 'index': 0})
        self.assertIn("Bertålotta", self.response.text)
        self.assertIn("Garcia", self.response.text)

    @as_users("anton", "garcia")
    def test_change_course(self, user):
        self.traverse({'description': '^Veranstaltungen$'},
                      {'href': '/showevent/1'},
                      {'href': '/changecourse/1/1'})
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
        self.traverse({'href': '/changecourse/1/1'})
        self.assertIn("ω", self.response.text)
        self.assertFalse(self.response.lxml.get_element_by_id('manipulator_checkbox_1').checked)
        self.assertTrue(self.response.lxml.get_element_by_id('manipulator_checkbox_2').checked)
        self.assertTrue(self.response.lxml.get_element_by_id('manipulator_checkbox_3').checked)

    @as_users("anton")
    def test_create_course(self, user):
        self.traverse({'description': '^Veranstaltungen$'},
                      {'href': '/showevent/1'})
        self.assertTitle("Große Testakademie 2222")
        self.assertIn("Planetenretten für Anfänger", self.response.text)
        self.assertNotIn("Abstract Nonsense", self.response.text)
        self.traverse({'href': '/createcourse/1', 'index': 0})
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
        self.assertIn("Lots of arrows.", self.response.text)
        self.assertIn("Alexander Grothendieck", self.response.text)
        self.traverse({'href': '/changecourse', 'index': 0})
        self.assertTrue(self.response.lxml.get_element_by_id('manipulator_checkbox_1').checked)
        self.assertFalse(self.response.lxml.get_element_by_id('manipulator_checkbox_2').checked)
        self.assertTrue(self.response.lxml.get_element_by_id('manipulator_checkbox_3').checked)
