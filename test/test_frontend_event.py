#!/usr/bin/env python3

import unittest
import quopri
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
            'displayname': "Zelda",
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
