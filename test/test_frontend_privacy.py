#!/usr/bin/env python3

from test.common import as_users, USER_DICT, FrontendTest

# TODO beef up Berta, Emilia, Janis, Kalif to fill all of their available fields
# TODO how to tread "Mitgliedschaft"?


class TestPrivacyFrontend(FrontendTest):

    ALL_FIELDS = {
        "Name", "Geburstname", "Geburtsdatum", "Geschlecht", "CdEDB-ID",
        "Account aktiv", "Bereiche", "Admin-Privilegien", "Admin-Notizen",
        "Guthaben", "Sichtbarkeit", "E-Mail", "Telefon", #missing: "Mitgliedschaft"
        "Mobiltelefon", "WWW", "Adresse", "Zweitadresse", "Fachgebiet",
        "Schule, Uni, …", "Jahrgang, Matrikel, …", "Interessen", "Sonstiges",
        "Verg. Veranstaltungen"
    }

    def _profile_base_view(self, inspected):
        expected = {"Name", "CdEDB-ID", "E-Mail"}
        for field in expected:
            self.assertPresence(field)
        return expected

    def _profile_relative_admin_view(self, inspected):
        expected = {
            "Account aktiv", "Bereiche", "Admin-Privilegien", "Admin-Notizen"
        }
        for field in expected:
            self.assertPresence(field)
        # actual username should be displayed
        self.assertPresence(inspected['username'])
        checked = self._profile_base_view(inspected)
        return expected | checked

    def _profile_ml_admin_view(self, inspected):
        expected = set()
        checked = self._profile_relative_admin_view(inspected)
        return expected | checked

    def _profile_assembly_admin_view(self, inspected):
        expected = set()
        checked = self._profile_relative_admin_view(inspected)
        return expected | checked

    def _profile_event_admin_view(self, inspected):
        expected = {
            "Geburtsdatum", "Geschlecht", "Telefon", "Mobiltelefon", "Adresse"
        }
        for field in expected:
            self.assertPresence(field)
        checked = self._profile_relative_admin_view(inspected)
        return expected | checked

    def _profile_meta_admin_view(self, inspected):
        expected = {"Bereiche", "Admin-Privilegien"}
        for field in expected:
            self.assertPresence(field)
        # actual username must not be displayed
        self.assertNonPresence(inspected['username'])
        checked = self._profile_base_view(inspected)
        return expected | checked

    def _profile_member_view(self, inspected):
        expected = {
            "Geburtsname", "Geburtsdatum", "Telefon", "Mobiltelefon", "WWW",
            "Adresse", "Zweitadresse", "Fachgebiet", "Schule, Uni, …",
            "Jahrgang, Matrikel, …", "Interessen", "Sonstiges", "Verg. Veranstaltungen"
        }
        for field in expected:
            self.assertPresence(field)
        # actual username should be displayed
        self.assertPresence(inspected['username'])
        checked = self._profile_base_view(inspected)
        return expected | checked

    def _profile_orga_view(self, inspected):
        expected = {
            "Geburtsdatum", "Geschlecht", "Telefon", "Mobiltelefon", "Adresse"
        }
        for field in expected:
            self.assertPresence(field)
        # actual username should be displayed
        self.assertPresence(inspected['username'])
        checked = self._profile_base_view(inspected)
        return expected | checked

    def _profile_moderator_view(self, inspected):
        expected = set()
        # actual username should be displayed
        self.assertPresence(inspected['username'])
        checked = self._profile_base_view(inspected)
        return expected | checked

    def _disable_searchability(self, user):
        ''' To avoid gaining more viewing rights through being a member '''
        self.logout()
        self.login(USER_DICT['anton'])
        self.admin_view_profile(user)
        self.traverse({'description': 'Bearbeiten'})
        f = self.response.forms['changedataform']
        f['is_searchable'].checked = False
        self.submit(f)
        self.logout()

    def test_profile_base_information(self):
        # non-searchable user views normal account
        case1 = {
            'viewer': USER_DICT['charly'],
            'inspected': USER_DICT['anton'],
        }
        # normal user views non-searchable account
        case2 = {
            'viewer': USER_DICT['inga'],
            'inspected': USER_DICT['charly'],
        }
        # normal user views non-member account
        case3 = {
            'viewer': USER_DICT['inga'],
            'inspected': USER_DICT['daniel'],
        }
        # normal user views inactive account
        case4 = {
            'viewer': USER_DICT['inga'],
            'inspected': USER_DICT['olaf'],
        }

        for case in [case1, case2, case3, case4]:
            self.login(case['viewer'])
            self.get(case['inspected']['url'])
            found = self._profile_base_view(case['inspected'])
            # The username must not be visible, although "Email" occurs as field
            self.assertNonPresence(case['inspected']['username'])
            for field in self.ALL_FIELDS - found:
                self.assertNonPresence(field)
            self.logout()

    @as_users("nina")
    def test_profile_as_ml_admin(self, user):
        # on ml only users, ml admins get full view
        inspected = USER_DICT['janis']
        self.get(inspected['url'])
        found = self._profile_ml_admin_view(inspected)
        for field in self.ALL_FIELDS - found:
            self.assertNonPresence(field)

        # on other users, they get no special view ...
        inspected = USER_DICT['berta']
        self.get(inspected['url'])
        found = self._profile_base_view(inspected)
        # The username must not be visible, although "Email" occurs as field
        self.assertNonPresence(inspected['username'])
        for field in self.ALL_FIELDS - found:
            self.assertNonPresence(field)

        # TODO should this also be functional if the inspected user is moderator
        #  and not subscriber of that mailinglist?
        # ... unless they see them as mailinglist associated
        inspected = USER_DICT['berta']
        self.get(inspected['url'] + "&ml_id=51")
        found = self._profile_base_view(inspected)
        # The username should be visible, although "Email" occurs as field
        self.assertPresence(inspected['username'])
        for field in self.ALL_FIELDS - found:
            self.assertNonPresence(field)

    @as_users("werner")
    def test_profile_as_assembly_admin(self, user):
        self._disable_searchability('werner')

        # on (assembly and ml) only users, assembly admins get full view
        self.login(user)
        inspected = USER_DICT['kalif']
        self.get(inspected['url'])
        found = self._profile_assembly_admin_view(inspected)
        for field in self.ALL_FIELDS - found:
            self.assertNonPresence(field)

        # on other users, they get no special view
        inspected = USER_DICT['berta']
        self.get(inspected['url'])
        found = self._profile_base_view(inspected)
        # The username must not be visible, although "Email" occurs as field
        self.assertNonPresence(inspected['username'])
        for field in self.ALL_FIELDS - found:
            self.assertNonPresence(field)

    @as_users("annika")
    def test_profile_as_event_admin(self, user):
        self._disable_searchability('annika')

        # on event but not cde users, event admins get full view
        self.login(user)
        inspected = USER_DICT['emilia']
        self.get(inspected['url'])
        found = self._profile_event_admin_view(inspected)
        for field in self.ALL_FIELDS - found:
            self.assertNonPresence(field)

        # on other users, they get no special view ...
        inspected = USER_DICT['berta']
        self.get(inspected['url'])
        found = self._profile_base_view(inspected)
        # The username must not be visible, although "Email" occurs as field
        self.assertNonPresence(inspected['username'])
        for field in self.ALL_FIELDS - found:
            self.assertNonPresence(field)

        # TODO should this also be functional if the inspected user is orga
        #  and not registered for that event?
        # ... unless they see them as event associated
        # TODO replace inga with berta
        inspected = USER_DICT['inga']
        self.get(inspected['url'] + "&event_id=1")
        found = self._profile_event_admin_view(inspected)
        for field in self.ALL_FIELDS - found:
            self.assertNonPresence(field)

    @as_users("martin")
    def test_profile_as_meta_admin(self, user):
        # meta admins get the same view for every user
        inspected = USER_DICT['berta']
        self.get(inspected['url'])
        found = self._profile_meta_admin_view(inspected)
        # The username must not be visible, although "Email" occurs as field
        self.assertNonPresence(inspected['username'])
        for field in self.ALL_FIELDS - found:
            self.assertNonPresence(field)

    @as_users("inga")
    def test_profile_as_member(self, user):
        inspected = USER_DICT['berta']
        self.get(inspected['url'])

        # members got first an un-quoted view on a profile, showing the basics
        found = self._profile_base_view(inspected)
        # The username must not be visible, although "Email" occurs as field
        self.assertNonPresence(inspected['username'])
        for field in self.ALL_FIELDS - found:
            self.assertNonPresence(field)

        # they can decide to got an quoted closer look on a profile
        self.traverse({'description': 'Gesamtes Profil anzeigen'})
        found = self._profile_member_view(inspected)
        for field in self.ALL_FIELDS - found:
            self.assertNonPresence(field)

    @as_users("garcia")
    def test_profile_as_orga(self, user):
        # TODO should this also be true for "Mit-Orgas"?
        # orgas get a closer view on users associated to their event
        # TODO replace inga with berta
        inspected = USER_DICT['inga']
        self.get(inspected['url'] + "&event_id=1")
        found = self._profile_orga_view(inspected)
        for field in self.ALL_FIELDS - found:
            self.assertNonPresence(field)

        # otherwise, they have no special privileges ...
        # TODO replace inga with berta
        inspected = USER_DICT['inga']
        self.get(inspected['url'])
        found = self._profile_base_view(inspected)
        # The username must not be visible, although "Email" occurs as field
        self.assertNonPresence(inspected['username'])
        for field in self.ALL_FIELDS - found:
            self.assertNonPresence(field)

        # ... especially also for (event but not cde) users
        # (in contrast to event admins)
        inspected = USER_DICT['emilia']
        self.get(inspected['url'])
        found = self._profile_base_view(inspected)
        # The username must not be visible, although "Email" occurs as field
        self.assertNonPresence(inspected['username'])
        for field in self.ALL_FIELDS - found:
            self.assertNonPresence(field)

    @as_users("janis")
    def test_profile_as_moderator(self, user):
        # moderators get a closer view on users associated to their mailinglist
        inspected = USER_DICT['berta']
        self.get(inspected['url'] + "&ml_id=2")
        found = self._profile_moderator_view(inspected)
        for field in self.ALL_FIELDS - found:
            self.assertNonPresence(field)

        # otherwise, they have no special privileges ...
        inspected = USER_DICT['berta']
        self.get(inspected['url'])
        found = self._profile_base_view(inspected)
        # The username must not be visible, although "Email" occurs as field
        self.assertNonPresence(inspected['username'])
        for field in self.ALL_FIELDS - found:
            self.assertNonPresence(field)

        # ... especially also for ml only users (in contrast to ml admins)
        # TODO this is actual not possible caused by our sample-data
        # inspected = USER_DICT['emilia']
        # self.get(inspected['url'])
        # found = self._profile_base_view(inspected)
        # # The username must not be visible, although "Email" occurs as field
        # self.assertNonPresence(inspected['username'])
        # for field in self.ALL_FIELDS - found:
        #     self.assertNonPresence(field)

    @as_users("annika", "berta", "farin", "martin", "nina", "olaf", "vera",
              "werner")
    def test_user_search(self, user):
        # users who should have access to the specific user search
        core = [
            USER_DICT['farin'], USER_DICT['vera']
        ]
        archive = [
            USER_DICT['farin'], USER_DICT['vera']
        ]
        # TODO replace vera with new core only admin
        # TODO replace olaf with new cde only admin
        cde = [
            USER_DICT['farin'], USER_DICT['olaf'], USER_DICT['vera']
        ]
        event = [
            USER_DICT['farin'], USER_DICT['annika']
        ]
        ml = [
            USER_DICT['farin'], USER_DICT['nina']
        ]
        assembly = [
            USER_DICT['farin'], USER_DICT['werner']
        ]

        # some preparation
        # re-activate olaf, so he can login
        if user == USER_DICT['olaf']:
            self.login(USER_DICT['anton'])
            self.admin_view_profile('olaf')
            f = self.response.forms['activitytoggleform']
            self.submit(f)
            self.logout()
            self.login(USER_DICT['olaf'])

        if user in core:
            self.get('/core/search/user')
            self.assertTitle("Allgemeine Nutzerverwaltung")
        else:
            self.get('/core/search/user', status="403 FORBIDDEN")
            self.assertTitle("403: Forbidden")

        if user in archive:
            self.get('/core/search/archiveduser')
            self.assertTitle("Archivsuche")
        else:
            self.get('/core/search/archiveduser', status="403 FORBIDDEN")
            self.assertTitle("403: Forbidden")

        if user in cde:
            self.get('/cde/search/user')
            self.assertTitle("CdE-Nutzerverwaltung")
        else:
            self.get('/cde/search/user', status="403 FORBIDDEN")
            self.assertTitle("403: Forbidden")

        if user in event:
            self.get('/event/search/user')
            self.assertTitle("Veranstaltungs-Nutzerverwaltung")
        else:
            self.get('/event/search/user', status="403 FORBIDDEN")
            self.assertTitle("403: Forbidden")

        if user in ml:
            self.get('/ml/search/user')
            self.assertTitle("Mailinglisten-Nutzerverwaltung")
        else:
            self.get('/ml/search/user', status="403 FORBIDDEN")
            self.assertTitle("403: Forbidden")

        if user in assembly:
            self.get('/assembly/search/user')
            self.assertTitle("Versammlungs-Nutzerverwaltung")
        else:
            self.get('/assembly/search/user', status="403 FORBIDDEN")
            self.assertTitle("403: Forbidden")
