* [33m13802cdf[m[33m ([m[1;36mHEAD -> [m[1;32marchitecture/mailinglists[m[33m)[m ml/nackend: Make set_subscription(s) internal
[31m|[m *   [33m08934451[m[33m ([m[1;35mrefs/stash[m[33m)[m WIP on architecture/mailinglists: 6be812f4 ml: Shift subscription management functions to backend
[31m|[m [31m|[m[33m\[m  
[31m|[m[31m/[m [33m/[m  
[31m|[m * [33m633a1280[m index on architecture/mailinglists: 6be812f4 ml: Shift subscription management functions to backend
[31m|[m[31m/[m  
* [33m6be812f4[m[33m ([m[1;31morigin/architecture/mailinglists[m[33m)[m ml: Shift subscription management functions to backend
* [33m02e1ebc9[m ml: improve the usage of may_subscribe
* [33m044fd0e3[m ml: Multiple fixes
* [33mbca4487f[m backend: create helpers in event and assembly backends to check mailinglist eligibility.
* [33ma99dea71[m ml: fix sample data for tests
* [33m79f9a8fc[m ml/backend: Introduce new may_manage function
* [33m4bc305dd[m ml: Shift logic to change own subscription state to backend
* [33mee6da900[m ml: Drop SubscriptiionPolicy.privileged_transition()
* [33md5eaea45[m ml/backend: Overhaul may_subscribe function
* [33m60b212bc[m ml: Renamne SS.subscription_requested to SS.pending
* [33mb3e5939b[m ml/frontend: Implement modification of own subscription state
* [33m377c5d9e[m ml: Drop gateway
* [33m5d59d05a[m ml: fix privilege checks
* [33m123a999d[m ml: fix two minor bugs
* [33mb03fdaf5[m frontend: adapt to changes in the ml backend interface. no functional changes.
* [33m2c602ad6[m ml: use new subscription request resolutions in the frontend.
* [33m043b17a6[m frontend/ml: minor fixes and improvements
* [33meec61a80[m ml: new backend method to gather all known email addresses for the user.
* [33md2f32a3e[m test: fix sample data to include implicit subscribers.
* [33m88aef5cf[m ml: fix singularization
* [33mc4544c60[m test: make old backend tests work
* [33m84c613aa[m database: allow deleting subscriptions for non-admins
* [33m604721f1[m ml: fix mailinglist deletion blockers after db schema change
* [33mf7f791f4[m ml: rework parameters of low level backend functions.
* [33m0a9da0af[m const: introduce resolution states for subscription requests.
* [33m72be5353[m ml: improve pivilege validation and documentation in the backend.
* [33mfdd13abd[m ml: fix import in frontend
* [33mcb1763c9[m ml: add logging and fix and test a bug
* [33md73068ee[m frontend: remove check states.
* [33m04b789bd[m frontend: fix backend parameters and add cron endpoint.
* [33m7c85e551[m frontend: redo mailinglist management. Introduce new more detailed page for managing overrides and whitelists.
* [33m6b4f5aed[m frontend: fix show_mailinglist endpoint.
* [33m215770c8[m frontend: fix ml index
* [33m8bb97ddb[m core: fix dashboard moderator overview
* [33m0bce52aa[m test: add new backend tests
* [33m2bcb275c[m backend: refactor subscription and address handling in the backend.
* [33me8f1f57a[m validation: add validator for id_pair
* [33m77bcca14[m const: add new SubscriptionStates Enum.
* [33mc48b0183[m sql: reshape ml.subscription_states table. We only save a subscription state. Subscription addresses are now kept in a separate table.
* [33m16d4ecdc[m backend: extend singularize decorator with optional parameter to allow singularizing functions with non-dict return values.
[33m|[m * [33m47226a5a[m[33m ([m[1;31morigin/master[m[33m, [m[1;31morigin/HEAD[m[33m)[m event: make registration_text optional at creation.
[33m|[m * [33m7f65dc4a[m event: hide course choices for tracks that don't allow choices.
[33m|[m * [33m43321a52[m event: add option for freetext on registration page.
[33m|[m * [33maaa6df3d[m assembly: validate params before using them in SQL.
[33m|[m * [33m09ae41bd[m[33m ([m[1;32mmaster[m[33m)[m test: Fix log tests
[33m|[m * [33m2d2df3e4[m auto-build: Add a diagnostic output to the failure path.
[33m|[m *   [33m61ad5639[m Merge remote-tracking branch 'origin/stable'
[33m|[m [35m|[m[36m\[m  
[33m|[m [35m|[m * [33m4a87f382[m[33m ([m[1;31morigin/stable[m[33m)[m cde-frontend: Fix lastschrift snafu.
[33m|[m * [36m|[m [33md3f9e416[m event: add button to create default orga-/participant-mailinglist to show_event.
[33m|[m * [36m|[m [33m4a1beb7a[m cde: improve sepa filename and notification email.
[33m|[m * [36m|[m [33m56c37b70[m template: fix JavaScript bug.
[33m|[m[33m/[m [36m/[m  
* [36m|[m [33mf9ac23e1[m buttonstyle: replace folder-close icons of "delete" buttons with trash icons
[36m|[m [36m|[m * [33m7f5b9b95[m[33m ([m[1;31morigin/feature/mdext[m[33m, [m[1;32mfeature/mdext[m[33m)[m doc: Improve markdown documentation
[36m|[m [36m|[m * [33m97faf4f1[m test: Adjust tests to markdown changes
[36m|[m [36m|[m * [33mf611fecb[m doc: Add markdown/bleach specification
[36m|[m [36m|[m * [33mf148e743[m markdown: Add more syntax elements
[36m|[m [36m|[m [1;31m|[m * [33m47eccb55[m[33m ([m[1;32mbackup[m[33m)[m common: extend singularize decorator to allow usage with non-dict return values.
[36m|[m [36m|[m [1;31m|[m * [33m9a79e126[m ml: improve address test and fix bugs.
[36m|[m [36m|[m [1;31m|[m * [33m2aa4169a[m ml: enable backend to handle subscription addresses.
[36m|[m [36m|[m [1;31m|[m * [33m1ff4a016[m ml: finish backend handlers for subscriptions (logging still missing.)
[36m|[m [36m|[m [1;31m|[m * [33m05f73cd3[m ml: fix critical bug
[36m|[m [36m|[m [1;31m|[m * [33me8cae844[m ml: add additional helpers
[36m|[m [36m|[m [1;31m|[m * [33m5a70000a[m frontend: fix const.SS to SS
[36m|[m [36m|[m [1;31m|[m * [33m9111f8a8[m frontend: fix paths.py
[36m|[m [36m|[m [1;31m|[m * [33m98162e0c[m ml: add remove_subscriptions function
[36m|[m [36m|[m [1;31m|[m * [33me46c229e[m ml: some backend and test changes
[36m|[m [36m|[m [1;31m|[m * [33m73d91d4d[m ml: fix managment.tmpl and request function
[36m|[m [36m|[m [1;31m|[m * [33m671e9ff0[m ml: fix sample data
[36m|[m [36m|[m [1;31m|[m * [33m27045bf4[m ml: Remove check_states and friends
[36m|[m [36m|[m [1;31m|[m * [33m34b26bc4[m ml: fix SubscriptionState usage in frontend.
[36m|[m [36m|[m [1;31m|[m * [33mef6fb50f[m core: adapt index page to change in ml backend.
[36m|[m [36m|[m [1;31m|[m * [33m79977252[m ml/frontend: fix some frontend endpoints
[36m|[m [36m|[m [1;31m|[m * [33m1f600d7a[m ml: add separate table for subscription addresses.
[36m|[m [36m|[m [1;31m|[m * [33md7448328[m ml: provide backend helpers for determining ml visibility and subscribability
[36m|[m [36m|[m [1;31m|[m * [33me5962223[m ml: Fix ml/index frontend
[36m|[m [36m|[m [1;31m|[m * [33mcfae3ea4[m ml: rename parameter
[36m|[m [36m|[m [1;31m|[m * [33mf28c94df[m ml: fix more stuff.
[36m|[m [36m|[m [1;31m|[m * [33m08d20217[m ml: fix bugs
[36m|[m [36m|[m [1;31m|[m * [33mcf86892c[m ml: continue backend work
[36m|[m [36m|[m [1;31m|[m * [33m90a99a39[m test: add test for new functionality
[36m|[m [36m|[m [1;31m|[m * [33mb8d392d7[m wip: ml: start refactoring the ml backend.
[36m|[m [36m|[m [1;31m|[m * [33m5bcdae23[m database: adapt subscription_states table. remove subscription_requests table.
[36m|[m [36m|[m [1;31m|[m * [33mdda1744c[m database: add new enum SubscriptionStates to define the relationship between a user and a mailinglist.
[36m|[m [36m|[m [1;31m|[m * [33ma7d01954[m ml: implement first draft for MailinglistTypes.
[36m|[m [36m|[m [1;31m|[m * [33m272b4be2[m assembly: hide add attachment button for non-Admins
[36m|[m [36m|[m [1;31m|[m * [33meef91b4e[m template: use bootstrap pager in ballot navigation.
[36m|[m [36m|[m [1;31m|[m * [33m843f82b6[m ui: update bootstrap and enable pager and pagination.
[36m|[m [36m|[m [1;31m|[m * [33mc697e777[m event: addanother note about the questionaire to registration form, even if its unabled. closes #466
[36m|[m [36m|[m [1;31m|[m [1;32m|[m * [33m8daf0f62[m[33m ([m[1;31morigin/feature/ornull[m[33m, [m[1;32mfeature/ornull[m[33m)[m query: Allow to search for equalornull and unequalornull
[36m|[m [36m|[m[36m_[m[1;31m|[m[36m_[m[1;32m|[m[36m/[m  
[36m|[m[36m/[m[36m|[m [1;31m|[m [1;32m|[m   
* [36m|[m [1;31m|[m [1;32m|[m [33m3d26f49f[m[33m ([m[1;32mfeature/lodgement-sum[m[33m)[m assembly/ui: Prevent moving preferential voting candidate within same box
* [36m|[m [1;31m|[m [1;32m|[m [33ma26dab33[m assembly: Add german translation
[1;33m|[m [36m|[m [1;31m|[m [1;32m|[m * [33m3a14d7c5[m[33m ([m[1;31morigin/fix/genesis_gender[m[33m)[m core: disallow not_specified as gender for event genesis cases.
[1;33m|[m [36m|[m[1;33m_[m[1;31m|[m[1;33m_[m[1;32m|[m[1;33m/[m  
[1;33m|[m[1;33m/[m[36m|[m [1;31m|[m [1;32m|[m   
* [36m|[m [1;31m|[m [1;32m|[m [33mb7f8c131[m assembly: hide add attachment button for non-Admins
* [36m|[m [1;31m|[m [1;32m|[m [33ma30d5bfe[m template: use bootstrap pager in ballot navigation.
* [36m|[m [1;31m|[m [1;32m|[m [33m58eb67af[m ui: update bootstrap and enable pager and pagination.
* [36m|[m [1;31m|[m [1;32m|[m [33m1363a5c8[m event: addanother note about the questionaire to registration form, even if its unabled. closes #466
[1;34m|[m [36m|[m [1;31m|[m [1;32m|[m * [33m0cd9859a[m[33m ([m[1;32mmltmp[m[33m)[m database: Draft for new ml database schema
[1;34m|[m [36m|[m[1;34m_[m[1;31m|[m[1;34m_[m[1;32m|[m[1;34m/[m  
[1;34m|[m[1;34m/[m[36m|[m [1;31m|[m [1;32m|[m   
* [36m|[m [1;31m|[m [1;32m|[m [33mb9c92cd1[m ml: implement first draft for MailinglistTypes.
[1;32m|[m [36m|[m[1;32m_[m[1;31m|[m[1;32m/[m  
[1;32m|[m[1;32m/[m[36m|[m [1;31m|[m   
* [36m|[m [1;31m|[m [33mc20f5e80[m assembly: use permanent link to wikipedia page of Schulze-Method
* [36m|[m [1;31m|[m [33m58b2d80c[m cde: Make buttons more beautiful for non-admins
* [36m|[m [1;31m|[m [33mb6fd4810[m event: add note about questionnaire to registration form. closes #466
* [36m|[m [1;31m|[m [33m9249e92a[m I change the expuls event export a bit. This close #538
* [36m|[m [1;31m|[m [33m6c67ddde[m fix some whitespace in mailto links
* [36m|[m [1;31m|[m [33m51b22622[m enhance Markus Link close #464
* [36m|[m [1;31m|[m [33m048076bb[m auto-build: Buster has been released.
* [36m|[m [1;31m|[m [33m483258de[m event: use the track.course_id, track.course_instructor and part.lodgement_id columns for the JS selector by providing choices for them.
* [36m|[m [1;31m|[m [33m301cac27[m event: make filter select field bigger.
* [36m|[m [1;31m|[m [33m0c9bfe85[m event: improve column titles for events with only one part/track. See #619
* [36m|[m [1;31m|[m [33m1c8e9310[m event: fix column names referenced by default queries and stats paged. See #619
* [36m|[m [1;31m|[m [33ma01a840e[m frontend/log: Fix count of log entries
* [36m|[m [1;31m|[m [33mb9947e1b[m frontend/menu: Show event realm for everyone
[36m|[m[36m/[m [1;31m/[m  
[36m|[m [1;31m|[m * [33mb9b1642e[m[33m ([m[1;31morigin/fix/birthday[m[33m, [m[1;32mfix/birthday[m[33m)[m cde: Warn if personas younger than 10 are batch admitted
[36m|[m [1;31m|[m * [33m1bd1351b[m core: Disallow birthdays in the future
[36m|[m [1;31m|[m[1;31m/[m  
[36m|[m [1;31m|[m * [33mab767ca4[m[33m ([m[1;31morigin/feature/admin_privacy[m[33m)[m i18n: fix translations
[36m|[m [1;31m|[m * [33mb9406afa[m core: add admin overview showing a list of all admins for the realms the user is a part of.
[36m|[m [1;31m|[m * [33m284dd8e9[m test: actually test that charly cannot use membersearch.
[36m|[m [1;31m|[m * [33m27dee1d9[m core: introduce a two-step, four-eye process for changing a personas admin bits.
[36m|[m [1;31m|[m[36m/[m  
[36m|[m[36m/[m[1;31m|[m   
* [1;31m|[m [33m64d5c567[m assembly: fix screw up in helper function to determine whether ballot is currently voting.
* [1;31m|[m [33m9e1ec2bf[m cde: adapt test to change in parse output format.
[1;31m|[m[1;31m/[m  
* [33m1fabe360[m ui: Improve layout of event/registration_query email button
* [33m31c23e7a[m parse: improve parse_statement results by being more robust regarding DB-IDs.
* [33m16472d75[m bin: handle duplicate names when importing course instructors from doku.
* [33m46f89986[m tests: Fix for recent change.
*   [33m5ca472cd[m Merge branch 'eye_candy/event_participant_email_mailto'
[32m|[m[33m\[m  
[32m|[m * [33m14a6a731[m template: Fix oversight in recent changes.
[32m|[m * [33m0eb67183[m templates: Improve code style.
[32m|[m * [33m387e7722[m drop one branch of mailto macro
[32m|[m * [33m33325910[m[33m ([m[1;31morigin/eye_candy/event_participant_email_mailto[m[33m)[m event: provide mailto link of all participants found by registration_query. closes #46.
[32m|[m * [33m488d1489[m templates: add macro for generating mailto links to query results and show_user. closes #535. closes part of #505
* [33m|[m [33mdfff3268[m cron: Make changelog reminder email less noisy.
* [33m|[m [33mf8c9990c[m bin: add script to identify and mark instructors of past courses.
* [33m|[m [33m700d1d47[m Make datetime fields more readable
* [33m|[m [33m8104b4d7[m doc: Correct offline VM documentation.
* [33m|[m [33m95565401[m test: fix more instances of parental agreement in test data.
* [33m|[m [33mb52e2ce0[m test: adjust test data to changes to parental_agreement
* [33m|[m [33m4a233d66[m assembly: fix order of checking ballot extension and grouping ballots.
* [33m|[m [33mceb5d917[m test: add option to make cgitb failure verbose.
* [33m|[m [33ma4a21d73[m assembly: link between ballots in the same order as they appear on list_ballots. closes #193
* [33m|[m [33m3381c6ee[m event: make sure lodgements don't have negative capacities. closes #190
* [33m|[m [33m2ddc9c15[m i18n: fix and improve translations.
* [33m|[m [33m2342612c[m event: improve info text for minors when no minorform is present. closes #169
* [33m|[m [33mfbae249f[m event: make parental_agreement not NULL. closes #548.
[33m|[m[33m/[m  
[33m|[m * [33mafad07d1[m[33m ([m[1;31morigin/feature/four-eyes_privilege_change[m[33m)[m test: make charly the second superadmin instead of ferdinand.
[33m|[m * [33ma567d304[m test: fix frontend tests.
[33m|[m * [33m159bab61[m core: implement privilege change frontend.
[33m|[m * [33m91a0b7ae[m core: improve backend for privilege changes. Allow storing note and introduce new final status "successful".
[33m|[m * [33mb9ff60c9[m test: add backend test for new privilege change process.
[33m|[m * [33me0a87278[m core: introduce a two-step, four-eye process for changing a personas admin bits.
[33m|[m[33m/[m  
[33m|[m * [33m266ead28[m[33m ([m[1;31morigin/feature/admin_overview[m[33m)[m test: add test for admin overview
[33m|[m * [33mfefc6b79[m core: add admin overview showing a list of all admins for the realms the user is a part of.
[33m|[m[33m/[m  
* [33m9a32492c[m i18n: add missing enum translations
* [33m51587902[m log: improve timestamps. closes #610
* [33m79298b97[m validation: make sure csvfile validator return a unified string. This now removes \r.
* [33m247ffece[m parse: include linenumber in problems. Add encoding kwarg to csvfile validator.
* [33me359dcea[m event-backend: Fix partial import.
* [33mc48a1fdf[m event-backend: Improve partial import functionality.
* [33m6db00ccc[m event-frontend: allow unlocking for orgas.
* [33m9021d41e[m tests: Fix tests.
*   [33m2ef1e4c2[m Merge branch 'fix/conclude_assembly'
[36m|[m[1;31m\[m  
[36m|[m * [33m31e4f464[m assembly: Make is_ballot_voting into a static helper.
[36m|[m * [33me640f900[m assembly: document assembly deletion/conclusion and ballot deletion blockers.
[36m|[m * [33m5b9c50cd[m[33m ([m[1;31morigin/fix/conclude_assembly[m[33m)[m assembly: improve ui for inactive assemblies
[36m|[m * [33m210b158c[m assembly: fix minor bugs and improve style
[36m|[m * [33mc71c87af[m assembly: allow assembly deletion in the frontend. Adapt to new conclusion interface.
[36m|[m * [33m5f4334c4[m assembly: improve readability by introducing checker function to determine, whether ballots are open.
[36m|[m * [33m98d61e74[m assembly: improve conclusion backend.
* [1;31m|[m   [33mb31f22dc[m Merge branch 'fix/download_localization'
[1;32m|[m[1;33m\[m [1;31m\[m  
[1;32m|[m * [1;31m|[m [33m404349bd[m test: add new test fot is_course_instructor functionality change.
[1;32m|[m * [1;31m|[m [33m17aa6335[m event: revert previous unification of column names
[1;32m|[m * [1;31m|[m [33macaa12c1[m event: update example query
[1;32m|[m * [1;31m|[m [33mb9233a24[m event: make column names unique
[1;32m|[m * [1;31m|[m [33m4e90b84c[m event: make column names unique and improve code style.
[1;32m|[m * [1;31m|[m [33m59921659[m[33m ([m[1;31morigin/fix/download_localization[m[33m)[m test: fix tests after registration_query changes.
[1;32m|[m * [1;31m|[m [33mb1c9cf0c[m event: fix titles and choices after additional select options for registration_query
[1;32m|[m * [1;31m|[m [33mea91da8f[m event: allow selecting id, moinker and notes separately for lodgements and notes for courses in registration_query
[1;32m|[m * [1;31m|[m [33m8e64e020[m event: fix titles for new selection options
[1;32m|[m * [1;31m|[m [33mc1202ea8[m event: allow selecting course id, nr, shortname and/or title separately
[1;32m|[m * [1;31m|[m [33m0f046d82[m event: refactor make_registration_query_aux title construction slightly
[1;32m|[m * [1;31m|[m [33m5b123f1e[m event: adjust test to changed csv download
[1;32m|[m * [1;31m|[m [33mf661bd10[m event: put fied values into downloads and descriptions into online display.
[1;32m|[m * [1;31m|[m [33m918a639e[m event: find course instructors not assigned to any course with 'instructs their course' query. closes #578
[1;32m|[m * [1;31m|[m [33m7bb31160[m core: undo zapping of choices in core::user_search. This does not do anything, but the template expects the parameter to be there, so we leave it.
[1;32m|[m * [1;31m|[m [33md86e3872[m event: zap all special caseing in download_csv_registration and instead call registration_query selecting all columns without constraints.
[1;32m|[m * [1;31m|[m [33m1f344a4e[m event: handle gettext on enums separately from titles in make_registration_query_aux. make fixed_gettext bool instead of passing a callable.
[1;32m|[m * [1;31m|[m [33m4c513474[m usersearch: use new default_gettext for user_search downloads. closes #580
[1;32m|[m * [1;31m|[m [33m7fad8eb2[m event: improve columns available in csv_registrations download. closes #592
[1;32m|[m * [1;31m|[m [33m0970bb32[m event: use new rs.default_gettext for processing registration_query downloads.
[1;32m|[m * [1;31m|[m [33mab4ced2f[m common: introduce default_gettext member to RequestState
* [1;33m|[m [1;31m|[m [33m6b10e06b[m core: Remove BuB-search attribute from view
* [1;33m|[m [1;31m|[m [33m1d734cce[m past_event: document past event and past course deletion blockers.
* [1;33m|[m [1;31m|[m [33m0dc574cf[m ml: document ml deletion blockers.
* [1;33m|[m [1;31m|[m [33mbf291481[m event: document event, course, lodgement and registration blockers.
* [1;33m|[m [1;31m|[m [33ma12ab04d[m core: document genesis case deletion blockers.
* [1;33m|[m [1;31m|[m [33m1717a439[m templates: fix call to PersonaSelectAPI by correctly referring aux.
* [1;33m|[m [1;31m|[m [33m7f3c76f8[m event: fix minor style issues
* [1;33m|[m [1;31m|[m [33mfddee4cd[m core-frontend: remove debug output
* [1;33m|[m [1;31m|[m [33m8527699d[m event: Ressurect additional changes from event deletion branch.
* [1;33m|[m [1;31m|[m [33m85e38065[m event-frontend: Fix typo.
* [1;33m|[m [1;31m|[m [33m9da6a0f6[m cron: Add reminder for open account changes.
* [1;33m|[m [1;31m|[m   [33mdc3dd753[m Merge branch 'feature/event_deletion'
[1;34m|[m[1;35m\[m [1;33m\[m [1;31m\[m  
[1;34m|[m * [1;33m|[m [1;31m|[m [33m8258c8c8[m[33m ([m[1;31morigin/feature/event_deletion[m[33m)[m test: adapt test to event deletion precaution.
[1;34m|[m * [1;33m|[m [1;31m|[m [33m181dd93d[m event: protect event from deletion if it is not concluded.
* [1;35m|[m [1;33m|[m [1;31m|[m [33m378f3455[m Revert "Merge branch 'feature/event_deletion'"
* [1;35m|[m [1;33m|[m [1;31m|[m   [33m7c7b3a45[m Merge branch 'feature/event_deletion'
[1;36m|[m[1;35m\[m [1;35m\[m [1;33m\[m [1;31m\[m  
[1;36m|[m [1;35m|[m[1;35m/[m [1;33m/[m [1;31m/[m  
[1;36m|[m * [1;33m|[m [1;31m|[m [33mdf17592d[m i18n: add missing translations for new LogCodes and other misc.
[1;36m|[m * [1;33m|[m [1;31m|[m [33m79ac228c[m event: implement event deletion in the frontend.
[1;36m|[m * [1;33m|[m [1;31m|[m [33mfab95481[m event: make backend event deletion work with registrations blocking course track deletion
[1;36m|[m [1;31m|[m [1;33m|[m[1;31m/[m  
[1;36m|[m [1;31m|[m[1;31m/[m[1;33m|[m   
* [1;31m|[m [1;33m|[m [33m23495577[m core: Replace deprecated function name
* [1;31m|[m [1;33m|[m [33m31d64fdf[m core/genesis: Move zip code test where it can always be done
* [1;31m|[m [1;33m|[m   [33mfd7a7d64[m Merge branch 'feature/filter'
[32m|[m[33m\[m [1;31m\[m [1;33m\[m  
[32m|[m * [1;31m|[m [1;33m|[m [33m481c9506[m[33m ([m[1;31morigin/feature/filter[m[33m)[m log: make sure start/stop are correctly passed through to generic_retrieve_log.
[32m|[m * [1;31m|[m [1;33m|[m [33m1b5c3bc2[m core/assembly: revert introduction of event_admin_user kind for select_persona
[32m|[m * [1;31m|[m [1;33m|[m [33m157173fb[m test: add test for new filtering in event log
[32m|[m * [1;31m|[m [1;33m|[m [33m3664c486[m frontend: allow filtering logs for persona_id and submitted_by
[32m|[m * [1;31m|[m [1;33m|[m [33m3d7461aa[m backend: allow filtering for persona_id and submitted_by in all logs. Also do some cleanup and some additional validation in retrieve_generic_log
[32m|[m * [1;31m|[m [1;33m|[m [33m2881d70a[m Draft for 'submitted by' and 'affected' filters for all logs
* [33m|[m [1;31m|[m [1;33m|[m   [33m79de819d[m Merge branch 'feature/hyperlinks'
[34m|[m[35m\[m [33m\[m [1;31m\[m [1;33m\[m  
[34m|[m * [33m|[m [1;31m|[m [1;33m|[m [33m3b88754f[m[33m ([m[1;31morigin/feature/hyperlinks[m[33m)[m add validation of weblinks for leading http or https, see #505
[34m|[m * [33m|[m [1;31m|[m [1;33m|[m [33m482b3ae0[m remove some whitespace and insert a http:// link
[34m|[m * [33m|[m [1;31m|[m [1;33m|[m [33mdaffa54a[m adding a macro for phonenumbers see #505
* [35m|[m [33m|[m [1;31m|[m [1;33m|[m   [33m4130418c[m Merge branch 'feature/public-courselist'
[36m|[m[1;31m\[m [35m\[m [33m\[m [1;31m\[m [1;33m\[m  
[36m|[m * [35m|[m [33m|[m [1;31m|[m [1;33m|[m [33me4962150[m event-frontend: Fix registration link visibility for anonymous users.
[36m|[m * [35m|[m [33m|[m [1;31m|[m [1;33m|[m [33m632edb52[m[33m ([m[1;31morigin/feature/public-courselist[m[33m)[m event: fix access list for event index
[36m|[m * [35m|[m [33m|[m [1;31m|[m [1;33m|[m [33m57002435[m event: fix permissions for anonymous user once more.
[36m|[m * [35m|[m [33m|[m [1;31m|[m [1;33m|[m [33m1f41c7d6[m event: fix access for anonymous users
[36m|[m * [35m|[m [33m|[m [1;31m|[m [1;33m|[m [33mf48db8cb[m event: fix public courselists and add test
[36m|[m * [35m|[m [33m|[m [1;31m|[m [1;33m|[m [33m6088d259[m templates: add explanation notes about public visibility of events.
[36m|[m * [35m|[m [33m|[m [1;31m|[m [1;33m|[m [33m7dc6a756[m event: make event overview, event page and courselist public, but hide orga and instructor names. see #431
[36m|[m[36m/[m [35m/[m [33m/[m [1;31m/[m [1;33m/[m  
* [35m|[m [33m|[m [1;31m|[m [1;33m|[m   [33m3794a1c4[m Merge branch 'feature/reverse-wish'
[1;32m|[m[1;33m\[m [35m\[m [33m\[m [1;31m\[m [1;33m\[m  
[1;32m|[m * [35m|[m [33m|[m [1;31m|[m [1;33m|[m [33maf51f559[m[33m ([m[1;31morigin/feature/reverse-wish[m[33m)[m event-frontend: Add reverse lodgement wish to puzzle.
[1;32m|[m [1;33m|[m [35m|[m[1;33m_[m[33m|[m[1;33m_[m[1;31m|[m[1;33m/[m  
[1;32m|[m [1;33m|[m[1;33m/[m[35m|[m [33m|[m [1;31m|[m   
* [1;33m|[m [35m|[m [33m|[m [1;31m|[m [33m0a29be6c[m tests: Fix tests
* [1;33m|[m [35m|[m [33m|[m [1;31m|[m [33m3fa90557[m event: Sort checkin form by name instead of id
* [1;33m|[m [35m|[m [33m|[m [1;31m|[m [33m70b859e9[m scripts: Import event log in offline instance.
* [1;33m|[m [35m|[m [33m|[m [1;31m|[m [33m1dfbd26f[m scripts: Add sanity check to detect missing data in offline instance.
* [1;33m|[m [35m|[m [33m|[m [1;31m|[m   [33m66b06fa7[m Merge branch 'stable'
[1;34m|[m[1;35m\[m [1;33m\[m [35m\[m [33m\[m [1;31m\[m  
[1;34m|[m * [1;33m|[m [35m|[m [33m|[m [1;31m|[m [33ma9880dfa[m event-backend: Fix event unlocking w.r.t. JSON handling.
* [1;35m|[m [1;33m|[m [35m|[m [33m|[m [1;31m|[m [33m58a28fa3[m frontend: Hide part of the main navigation during offline deployment.
* [1;35m|[m [1;33m|[m [35m|[m [33m|[m [1;31m|[m [33m5e779d60[m event-frontend: Fix checkin to always contain all participants.
* [1;35m|[m [1;33m|[m [35m|[m [33m|[m [1;31m|[m [33m68328486[m event-validation: Dissallow empty course numbers.
* [1;35m|[m [1;33m|[m [35m|[m [33m|[m [1;31m|[m [33mde173753[m core-frontend: Fix user editing during offline deployment.
* [1;35m|[m [1;33m|[m [35m|[m [33m|[m [1;31m|[m [33ma0eed40c[m scripts: make orgas into admins for offline deployment.
* [1;35m|[m [1;33m|[m [35m|[m [33m|[m [1;31m|[m [33m8e1817d3[m core-backend: take offline deployment into consideration.
* [1;35m|[m [1;33m|[m [35m|[m [33m|[m [1;31m|[m [33md450f448[m scripts: offline initialization script needs to take care of sequences
* [1;35m|[m [1;33m|[m [35m|[m [33m|[m [1;31m|[m [33mb81e10eb[m scripts: Fix offline initialization script in case of unlocked event.
[1;33m|[m [1;35m|[m[1;33m/[m [35m/[m [33m/[m [1;31m/[m  
[1;33m|[m[1;33m/[m[1;35m|[m [35m|[m [33m|[m [1;31m|[m   
* [1;35m|[m [35m|[m [33m|[m [1;31m|[m [33mdc612ca9[m cde/event: fix two small bugs, causing test failures
* [1;35m|[m [35m|[m [33m|[m [1;31m|[m [33md0cc1577[m event: make participant lists by part work.
* [1;35m|[m [35m|[m [33m|[m [1;31m|[m [33mf7378301[m event: rename incorrect translation of asset download and fix icon. closes #582
[1;31m|[m [1;35m|[m[1;31m_[m[35m|[m[1;31m_[m[33m|[m[1;31m/[m  
[1;31m|[m[1;31m/[m[1;35m|[m [35m|[m [33m|[m   
* [1;35m|[m [35m|[m [33m|[m [33mfc7b4b23[m i18n: fix typos
[33m|[m [1;35m|[m[33m_[m[35m|[m[33m/[m  
[33m|[m[33m/[m[1;35m|[m [35m|[m   
* [1;35m|[m [35m|[m [33m0b486993[m translation: Fix translation and spelling
* [1;35m|[m [35m|[m [33mec2c2216[m cde: improve csvfile validator to not require a third round when uploading a file with a newline at the end.
* [1;35m|[m [35m|[m [33mb080574b[m cde: grant membership on successful lastschrift. closes #536
* [1;35m|[m [35m|[m [33m75505dea[m event: filter for edited registrations after field_set. Also show the field.
* [1;35m|[m [35m|[m [33m8eafd6d6[m event: allow multiedit of notes and orga notes. closes #575
[1;35m|[m[1;35m/[m [35m/[m  
* [35m|[m   [33mdf0d7244[m Merge branch 'feature/genesis_deletion'
[35m|[m[31m\[m [35m\[m  
[35m|[m [31m|[m[35m/[m  
[35m|[m[35m/[m[31m|[m   
[35m|[m * [33m42860eea[m[33m ([m[1;31morigin/feature/genesis_deletion[m[33m)[m style: remove superflous code and logging
[35m|[m * [33m314194d6[m cron: store timestamp for genesis_forget and log number of deletions.
[35m|[m * [33m22114291[m cron: fix genesis_forget.
[35m|[m * [33mc675d2b5[m tests: Improve test infrastructure for cron tests.
[35m|[m * [33mb617b95f[m core: allow genesis case deletion and introduce periodic deletion. closes #550
* [31m|[m [33mc357f007[m ml-frontend: Fix template snafu.
* [31m|[m   [33m531d4ef0[m Merge branch 'eye_candy/make_shown_of_dictsort_meaningful'
[32m|[m[33m\[m [31m\[m  
[32m|[m * [31m|[m [33m918c1ca6[m style: remove List[Tuple[int, object]] in favor of OrderedDicts.
[32m|[m * [31m|[m [33mfa4175f2[m template: fix id in removemoderatorform and removesubscriberform
[32m|[m * [31m|[m [33m93b73460[m ml: sort moderators by name_key
[32m|[m * [31m|[m [33m84dbbaf0[m event: sort orgas by name_key
[32m|[m * [31m|[m [33m8b3cc8d2[m assembly: sort ballots by title
[32m|[m * [31m|[m [33mfadd204c[m assembly: sort attachments by title
[32m|[m * [31m|[m [33md87b4d44[m assembly: sort participants in assembly by name_key see #533
* [33m|[m [31m|[m [33madf3cc5f[m doc: Fix rst syntax and some minor issues.
* [33m|[m [31m|[m [33me03192e3[m assembly: Improve voting process.
* [33m|[m [31m|[m [33m76d5590a[m templates: Annotate a sorted collection.
* [33m|[m [31m|[m [33mee3f3e75[m cron: Improve usage of werkzeug Map.bind().
* [33m|[m [31m|[m [33m4f93ff5a[m tests: Test new asset download.
* [33m|[m [31m|[m [33mb87bd97b[m frontend: Improve mail template.
* [33m|[m [31m|[m [33m12d7e9d6[m cron: Fix URL building in cron frontend.
* [33m|[m [31m|[m [33m082ca515[m assembly: protect attachment deletion via ack_delete checkbox.
* [33m|[m [31m|[m [33m79b2b75e[m event: improve event and course logos by allowing pdfs and providing combined download. closes #528
* [33m|[m [31m|[m [33m333f4ac2[m assembly: move file handling to backend. see #537
* [33m|[m [31m|[m [33mafc53458[m templates: only add preselected values if no search has been done. closes #546
* [33m|[m [31m|[m [33m7abfd021[m core: validate postal_code upon genesis request. closes #551
[31m|[m [33m|[m[31m/[m  
[31m|[m[31m/[m[33m|[m   
* [33m|[m [33mee7350c4[m test: add tests for assembly bugs
* [33m|[m [33mf051d4bc[m cdedb: Remove urlmap attribute from request state.
* [33m|[m   [33m815741d6[m Merge branch 'feature/periodic-execution'
[34m|[m[35m\[m [33m\[m  
[34m|[m * [33m|[m [33m81c83c2e[m[33m ([m[1;31morigin/feature/periodic-execution[m[33m)[m core-forntend: Reintroduce different admin addresses.
[34m|[m * [33m|[m [33m4d7c5881[m core-frontend: Move template for genesis reminders to a more fitting location.
[34m|[m * [33m|[m [33mfc66455a[m cron: Add tests for the cron frontend.
[34m|[m * [33m|[m [33m8acea914[m cron: Implement the infrastructure for periodic jobs.
* [35m|[m [33m|[m [33m705fcb22[m doc: Improve markup of offline deployment doc.
* [35m|[m [33m|[m [33m9e4bdd8e[m scripts: Finally make the offline deployment script work.
* [35m|[m [33m|[m [33mee505845[m scripts: Fix the offline deployment script even further.
* [35m|[m [33m|[m [33meb9cc51c[m doc: Adjust the offline usage document to the actual workflow.
* [35m|[m [33m|[m [33m678ec562[m scripts: Add backup script.
* [35m|[m [33m|[m [33maf774fd2[m fix
* [35m|[m [33m|[m [33m7b133058[m event-frontend: Optimize space usage in lodgement puzzle
[35m|[m[35m/[m [33m/[m  
* [33m|[m [33mfc2c2649[m doc: Add offline deployment documentation
* [33m|[m [33mb4239800[m scripts: Modernize offline deployment script.
* [33m|[m [33m7ea1fc8f[m test: Adjust to new orga rate limit in config.
* [33m|[m [33m9ac5a8cb[m event-frontend: Fix minor TeX issues.
* [33m|[m [33m491e38e5[m config: Import the configured setting into the defaults.
* [33m|[m [33m744f8173[m event-frontend: Order the registrations in the lodgement puzzle by age.
* [33m|[m [33m681d0c2e[m event-frontend: Fix typo in lodgement puzzle.
* [33m|[m [33m7a255457[m event-frontend: Improve lodgement puzzle for events with only one part.
* [33m|[m [33m0414cc57[m event-frontend: Fix lodgement puzzle.
* [33m|[m [33mc4bb8c7a[m Revert "frontend: Fix wrong check for anonymous users."
* [33m|[m [33mfbae549b[m tests: Add new decorator to allow SQL manipulations.
* [33m|[m [33m09c94b1c[m frontend: Fix wrong check for anonymous users.
[33m|[m[33m/[m  
[33m|[m * [33m62252697[m[33m ([m[1;33mtag: archive/feature/periodic-execution-preview[m[33m, [m[1;31morigin/feature/periodic-execution-preview[m[33m)[m cron: Implement the infrastructure for periodic jobs.
[33m|[m[33m/[m  
* [33mfe084789[m assembly: fix critical bugs after vote display fix
* [33m08882035[m frontend: add current timestamp to debugstring.
* [33m7b284330[m log: add PersonaSelectAPI to log filters. closes #415
* [33mf19708c7[m assmbly-frontend: Fix vote display.
* [33mc3fb2776[m assembly: Fix embarrasing bug in tallying.
* [33mc1f10455[m assembly: Fix variable shadowing.
* [33me868f3ad[m doc: Move deployment doc to workflows document.
*   [33md2f249aa[m Merge branch 'enhance/make_download_filenames_static_distinctiv' of cdedb/cdedb2 into master
[1;31m|[m[1;32m\[m  
[1;31m|[m * [33me3d7c79c[m assembly: change "result.json" to "ballot_{id_ballot}_result.json"
[1;31m|[m * [33m671eb68c[m rename user_search result.* to "user_search_result.*"
[1;31m|[m * [33m572fb78a[m strip down internationalisation and enhance event-filenames
* [1;32m|[m [33m25970781[m event-frontend: Fix typo.
* [1;32m|[m [33mec4930c0[m event-frontend: Add link to questionnaire after registration.
* [1;32m|[m   [33m38dcd654[m Merge branch 'fix/deletion_interface'
[1;33m|[m[1;34m\[m [1;32m\[m  
[1;33m|[m * [1;32m|[m [33maf6883a1[m event: fix typo in delete_event
[1;33m|[m * [1;32m|[m [33mcfbe9d6b[m assembly: bring ballot deletion more in line with the others
[1;33m|[m * [1;32m|[m [33mebdb4ee5[m test: fix tests after past_event rewording
[1;33m|[m * [1;32m|[m [33m4c70d156[m test: fix tests after deletion interface changes
[1;33m|[m * [1;32m|[m [33m2c8a9706[m ml: refactor mailinglist deletion
[1;33m|[m * [1;32m|[m [33md48c8414[m past_event: refactor past_event and past_course deletion
[1;33m|[m * [1;32m|[m [33me84b17f6[m event: adapt partial event import
[1;33m|[m * [1;32m|[m [33m6ecc0194[m event: introduce event deletion to the backend.
[1;33m|[m * [1;32m|[m [33m5dfea328[m event: remove `are_courses_removable`
[1;33m|[m * [1;32m|[m [33mcb3be328[m event: refactor lodgement deletion
[1;33m|[m * [1;32m|[m [33m3fbe78cf[m event: refactor registration deletion
[1;33m|[m * [1;32m|[m [33mf01e8f82[m event: refactor course deletion
[1;33m|[m * [1;32m|[m [33mefcbd0aa[m assembly: implement assembly deletion in the backend.
[1;33m|[m * [1;32m|[m [33m5973bb6d[m assembly: refactor ballot deletion
* [1;34m|[m [1;32m|[m [33m63481ba7[m auto-build: Update to buster rc1.
[1;32m|[m [1;34m|[m[1;32m/[m  
[1;32m|[m[1;32m/[m[1;34m|[m   
* [1;34m|[m [33mb5bf346b[m core-backend: Make check_password_strength work.
* [1;34m|[m [33mdac416f3[m tests: Fix for recent changes.
* [1;34m|[m [33mcd16d2e3[m core-backend: Do not use private variant of validator.
* [1;34m|[m [33m42b9cc6c[m scripts: Move one-time scripts to a separate directory after use.
* [1;34m|[m [33mdce07d4f[m core: implement zxcvbn checks within the backend.
* [1;34m|[m [33m78d42be0[m path: add endpoint for adding participants to past courses.
* [1;34m|[m [33m2279eb26[m event: make log persona anchors link to registration if possible.
* [1;34m|[m [33m299d780a[m cde: check new balance against membership fee before granting membership.
* [1;34m|[m [33m4f24de51[m core: require superadmin privileges only for setting admin bits, not for unsetting.
* [1;34m|[m [33m627625c1[m doc: Streamline deployment tutorial.
[1;34m|[m[1;34m/[m  
* [33m1a9649bd[m i18n: Fix translation of course_choices' color key
* [33mab983298[m ui: Add cross reference from event/index to past events
* [33md94a9da7[m doc: Fix reST.
* [33m7bb93d0c[m doc: Create deployment documentation.
* [33mb2a001aa[m tests: Fix tests for latest merges.
*   [33m4bd0f23d[m Merge branch 'feature/improve_tex_templates'
[1;35m|[m[1;36m\[m  
[1;35m|[m * [33m1503f9ec[m[33m ([m[1;31morigin/feature/improve_tex_templates[m[33m)[m event: validate course_room_field datatype in the backend.
[1;35m|[m * [33mf3329d88[m event: use course_logo and course_room_field in courselists download
[1;35m|[m * [33m3ee02702[m event: add option to set `course_room_field` where a courses room can be saved. closes #487
* [1;36m|[m   [33me5190d1e[m Merge remote-tracking branch 'origin/master'
[31m|[m[32m\[m [1;36m\[m  
[31m|[m * [1;36m|[m [33m2a469715[m assembly: improve english info texts on ballot page and fix some translations.
* [32m|[m [1;36m|[m   [33m5263bfe9[m Merge branch 'feature/csv_format_for_excel'
[32m|[m[34m\[m [32m\[m [1;36m\[m  
[32m|[m [34m|[m[32m/[m [1;36m/[m  
[32m|[m[32m/[m[34m|[m [1;36m|[m   
[32m|[m * [1;36m|[m [33m4806a9df[m frontend: Encapsulate the BOM-handling in a separate function.
[32m|[m * [1;36m|[m [33m6f71f158[m sample-data: Synchronize changelog with new content.
[32m|[m * [1;36m|[m [33m006b7bbe[m[33m ([m[1;31morigin/feature/csv_format_for_excel[m[33m)[m test: Improve sample data to check CSV doublequotes
[32m|[m * [1;36m|[m [33ma74799dd[m test: Adapt tests for new CSV format
[32m|[m * [1;36m|[m [33m5be42de8[m frontend: Change CSV format to use doublequotes instead of escaping
[32m|[m * [1;36m|[m [33m33866472[m frontend: Add UTF-8 BOM to CSV downloads
* [34m|[m [1;36m|[m   [33m0018296b[m Merge branch 'feature/email_sender' of cdedb/cdedb2 into master
[35m|[m[36m\[m [34m\[m [1;36m\[m  
[35m|[m * [34m|[m [1;36m|[m [33m5ecfe5bb[m frontend: Do not set an empty Reply-To header.
[35m|[m * [34m|[m [1;36m|[m [33m4f4e650b[m assembly: slightly improve assembly signup mail.
[35m|[m * [34m|[m [1;36m|[m [33mf3f7b083[m assembly: allow setting mail_address for assemblies. Meant to be used as reply-to for assembly mails.
[35m|[m * [34m|[m [1;36m|[m [33mbf8a24f2[m event: allow event_admins who are also ml_admins to create event_mailinglists during event_creation.
[35m|[m * [34m|[m [1;36m|[m [33me9740298[m ml: add verify_existence for mailinglist address.
[35m|[m * [34m|[m [1;36m|[m [33mdfd01664[m event: use orga_address as reply-to for registration mail. Also improve the subject.
[35m|[m * [34m|[m [1;36m|[m [33mebad70db[m event: allow specifying orga_address for events.
[35m|[m * [34m|[m [1;36m|[m [33m6dad9d56[m frontend: do not user reply-to header if it is identical to from.
[35m|[m * [34m|[m [1;36m|[m [33m6f491d7a[m config: send all mails from datenbank@cde-ev.de by default.
* [36m|[m [34m|[m [1;36m|[m [33mb4a11853[m scripts: Add dry-run mode to stable push script.
* [36m|[m [34m|[m [1;36m|[m   [33m96a917b0[m Merge branch 'fix/query_result_columnnames' of cdedb/cdedb2 into master
[1;31m|[m[1;32m\[m [36m\[m [34m\[m [1;36m\[m  
[1;31m|[m * [36m|[m [34m|[m [1;36m|[m [33m4a33cf09[m backend: Improve readability by using non-matching quotes.
[1;31m|[m * [36m|[m [34m|[m [1;36m|[m [33m1b800549[m Fix tests for new query result column names
[1;31m|[m * [36m|[m [34m|[m [1;36m|[m [33m6fb7312a[m backend: Include table name in result column names of generic query
[1;31m|[m [36m|[m[36m/[m [34m/[m [1;36m/[m  
* [36m|[m [34m|[m [1;36m|[m [33md1da8a98[m script: fix one mor file title.
* [36m|[m [34m|[m [1;36m|[m [33m62706198[m bin: add script to upload old assembly files.
* [36m|[m [34m|[m [1;36m|[m [33m229f5069[m js: Add selected row count to query results
* [36m|[m [34m|[m [1;36m|[m [33m47a8473d[m ui: Rename Participant Statistics page to 'Statistics'
* [36m|[m [34m|[m [1;36m|[m [33md88e3ab2[m event-frontend: Add number of (cancelled) courses to event/stats
* [36m|[m [34m|[m [1;36m|[m [33m43978129[m event-frontend: Fix course assignment statistics
* [36m|[m [34m|[m [1;36m|[m [33ma22d702b[m ui: Improve style of listselect tables to avoid jiggling on unfocussing
* [36m|[m [34m|[m [1;36m|[m [33m93159684[m js: Force write back for prefential vote when submitting JS form
* [36m|[m [34m|[m [1;36m|[m [33m62d59e82[m ui: Remember active preferential voting tab via cookie
* [36m|[m [34m|[m [1;36m|[m [33m0b0511c8[m assembly-frontend: Allow abstaining with empty preferential vote
* [36m|[m [34m|[m [1;36m|[m [33m6eb67530[m assembly-frontend: Don't redirect on voting validation errors
* [36m|[m [34m|[m [1;36m|[m [33mff080c73[m event-frontend: Fix course_choices(): Don't change track_id filter
* [36m|[m [34m|[m [1;36m|[m [33ma33c4372[m event-backend: Allow registrations_by_course to filter for unassigned participants
[34m|[m [36m|[m[34m/[m [1;36m/[m  
[34m|[m[34m/[m[36m|[m [1;36m|[m   
* [36m|[m [1;36m|[m [33meb31e0e6[m event-backend: Make datetime datafields in queries timezone-aware
[36m|[m[36m/[m [1;36m/[m  
* [1;36m|[m [33m8cddc848[m templates: fix linebreaks filter to correctly escape HTML. revert b462325d14.
* [1;36m|[m [33m1bb25fe4[m i18n: fix translation of zxcvbn messages with quotation marks.
* [1;36m|[m [33m32023ce8[m template: fix error display on lastschrift index
* [1;36m|[m [33mfaa2c4e1[m ui: Fix queryform JS: input type and placeholder of range inputs
* [1;36m|[m [33ma92ae597[m backend: Fix implementation of QueryOperators.otherthan
* [1;36m|[m [33m4bddeba7[m event-backend: Fix registration_query for sorting by datafields with uppercase letters
* [1;36m|[m [33m2b32f93a[m i18n: Translate em dashes with em dashes
* [1;36m|[m [33mb3a417e9[m ui: Fix title of enable checkboxes at event/change_registrations
* [1;36m|[m [33mb965e9e3[m ui: Add hint on information visible to registered people to event/change_registration[s]
* [1;36m|[m [33mfb121371[m ui/event: Fix links from course_stats to course_choices
* [1;36m|[m [33me551f5a5[m i18n: fix translations. closes #503
* [1;36m|[m [33m8f160e60[m frontend: improve default queries. closes #491
* [1;36m|[m   [33m570ac601[m Merge branch 'feature/outside_audience' of cdedb/cdedb2 into master
[1;33m|[m[1;34m\[m [1;36m\[m  
[1;33m|[m * [1;36m|[m [33mec4b249d[m[33m ([m[1;31morigin/feature/outside_audience[m[33m)[m ml: Change user-facing documentation to reflect new behavior
[1;33m|[m * [1;36m|[m [33mabafbe17[m ml: Do not show users outside of audience
[1;33m|[m * [1;36m|[m [33m78497af0[m ml: Make subscription state changes more oversseable
[1;33m|[m * [1;36m|[m [33m172d599f[m test: Add test that mods can add users out of audience
[1;33m|[m * [1;36m|[m [33m7c73c87f[m ml: Allow moderators to add users out of audience
* [1;34m|[m [1;36m|[m   [33m4e871ab1[m Merge branch 'feature/archival_note'
[1;35m|[m[1;36m\[m [1;34m\[m [1;36m\[m  
[1;35m|[m * [1;34m|[m [1;36m|[m [33m8706adf4[m core-frontend: Make validation failure notice more meaningful.
[1;35m|[m * [1;34m|[m [1;36m|[m [33md91341ad[m core-frontend: Make archival note entry a text area.
[1;35m|[m * [1;34m|[m [1;36m|[m [33m178d358a[m core-frontend: Fix double-check for non-empty note.
[1;35m|[m * [1;34m|[m [1;36m|[m [33ma09233dc[m core-frontend: Improve show_user usage by directly passing the confirm_id.
[1;35m|[m * [1;34m|[m [1;36m|[m [33m897b3fc7[m ui: Improve layout of 'note' input of archivepersonaform
[1;35m|[m * [1;34m|[m [1;36m|[m [33m93edcec6[m core: allow internal acces of show_user via parameter. see #475
[1;35m|[m * [1;34m|[m [1;36m|[m [33m2a9bc6ec[m backend: fix archival of lastschrift.
[1;35m|[m * [1;34m|[m [1;36m|[m [33m7c5d4e8b[m[33m ([m[1;31morigin/feature/archival_note[m[33m)[m i18n: add archival note translation
[1;35m|[m * [1;34m|[m [1;36m|[m [33m4b04ff25[m test: adapt tests to archival note change
[1;35m|[m * [1;34m|[m [1;36m|[m [33m0aae191c[m core: make archival require providing a note. closes #421
* [1;36m|[m [1;34m|[m [1;36m|[m [33m8c2f6a2b[m frontend: Fix event/course_assignment_checks for empty course list and unassigned course instructors
[1;34m|[m [1;36m|[m[1;34m/[m [1;36m/[m  
[1;34m|[m[1;34m/[m[1;36m|[m [1;36m|[m   
* [1;36m|[m [1;36m|[m [33ma07928c7[m template: improve admin infolink on member_search page. #498
* [1;36m|[m [1;36m|[m [33m107f9fd1[m cde: add hint about which users can be found via member_search for admins. closes #498
* [1;36m|[m [1;36m|[m [33mca20b924[m event: make batch_fee require manual validation step in all cases.
* [1;36m|[m [1;36m|[m   [33mabf84093[m Merge branch 'feature/course_stats_all_regs'
[31m|[m[32m\[m [1;36m\[m [1;36m\[m  
[31m|[m * [1;36m|[m [1;36m|[m [33md7ea68ba[m event-frontend: Fix is_involved.
[31m|[m * [1;36m|[m [1;36m|[m [33m4bfaa85b[m[33m ([m[1;31morigin/feature/course_stats_all_regs[m[33m)[m i18n: add missing translations
[31m|[m * [1;36m|[m [1;36m|[m [33mb925d59f[m ui/event: Reformat filter form at event/course_choices
[31m|[m * [1;36m|[m [1;36m|[m [33m146cca56[m frontend: Add include_active parameter to event/course_choices_form
[31m|[m * [1;36m|[m [1;36m|[m [33m9d170815[m backend/event: Allow to pass relevant stati to registrations_by_course()
[31m|[m * [1;36m|[m [1;36m|[m [33mbeb32784[m frontend: Allow to include all active registrations at event/course_stats
* [32m|[m [1;36m|[m [1;36m|[m [33mf3ee91af[m ml: document that only admins may add users outside of audience. see #482
* [32m|[m [1;36m|[m [1;36m|[m [33m6afca956[m cde: fix display of balance deadline. closes #486
* [32m|[m [1;36m|[m [1;36m|[m [33m6d2a9596[m core: show link to lastschrift page for non-member cde users. closes #494
* [32m|[m [1;36m|[m [1;36m|[m [33mae6a6aad[m ml: only check gateway subscription status if user is not privileged. closes #495
* [32m|[m [1;36m|[m [1;36m|[m [33mb462325d[m frontend: escape mail before writing to debugemail in CDEDB_DEV mode.
[32m|[m[32m/[m [1;36m/[m [1;36m/[m  
[32m|[m [1;36m|[m [1;36m|[m * [33ma7cb2cb5[m[33m ([m[1;31morigin/feature/orga_address[m[33m)[m event: only allow automatic creation of event-mailinglists for event_admins who are also ml_admins.
[32m|[m [1;36m|[m [1;36m|[m * [33m4b9161d5[m event: allow nulloption for orga_address
[32m|[m [1;36m|[m [1;36m|[m * [33m0ded76b8[m ml: cascadingly delete references to mailinglist from event.events table
[32m|[m [1;36m|[m [1;36m|[m * [33m9aa4354f[m event: check existence of event mailinglists before attempting to create them
[32m|[m [1;36m|[m [1;36m|[m * [33ma163c680[m ml: allow verifying the existance of mailinglist with given address.
[32m|[m [1;36m|[m [1;36m|[m * [33m5cdb7904[m test: test for mailinglist creation
[32m|[m [1;36m|[m [1;36m|[m * [33m9635195b[m event: make creation of event mailinglists optional.
[32m|[m [1;36m|[m [1;36m|[m * [33mccad5625[m event: improve registration email. closes #483 closes #471
[32m|[m [1;36m|[m [1;36m|[m * [33m9411baa0[m frontend: make event creation also create orga and participant mailinglists. Allow configuring an orga address via change_event.
[32m|[m [1;36m|[m [1;36m|[m * [33mbd2e2a14[m ml: allow listing mailinglists belonging to specific events. Allow create_mailinglist for event_admins.
[32m|[m [1;36m|[m [1;36m|[m * [33m6e2de81c[m database: add orga_address column and add it to EVENT_FIELDS and validation
[32m|[m [1;36m|[m[32m_[m[1;36m|[m[32m/[m  
[32m|[m[32m/[m[1;36m|[m [1;36m|[m   
[32m|[m [1;36m|[m [1;36m|[m * [33m38623fdd[m[33m ([m[1;31morigin/fix/deletion_interface[m[33m)[m frontend: adjust call to backend. Also handle file deletion for ballot attachments.
[32m|[m [1;36m|[m [1;36m|[m * [33maeadba9d[m backend: simplify cascade parameter
[32m|[m [1;36m|[m [1;36m|[m * [33m69043d0d[m test: add test for ballot deletion
[32m|[m [1;36m|[m [1;36m|[m * [33mcfb65bd8[m backend: improve blocker and cascade syntax
[32m|[m [1;36m|[m [1;36m|[m * [33mef05cea6[m frontend: adapt frontend to changed deletion interface.
[32m|[m [1;36m|[m [1;36m|[m * [33mea6da185[m backend: begin standardizing of deletion interface.
[32m|[m [1;36m|[m[32m_[m[1;36m|[m[32m/[m  
[32m|[m[32m/[m[1;36m|[m [1;36m|[m   
* [1;36m|[m [1;36m|[m [33m73c1fdcc[m cde: make sure transfers checksum can be calculated in case of file upload
* [1;36m|[m [1;36m|[m [33m50cebd1b[m event-frontend: Fix error path in registration_status.
* [1;36m|[m [1;36m|[m [33mc751ac9e[m core-backend: Always return a valid value from change_persona_balance.
* [1;36m|[m [1;36m|[m [33m36b183f5[m cde: don't redirect on sepapain failure to not lose errors.
[1;36m|[m [1;36m|[m[1;36m/[m  
[1;36m|[m[1;36m/[m[1;36m|[m   
* [1;36m|[m [33mc35a47f3[m templates: improve the download page layout.
* [1;36m|[m   [33mb2cc03bb[m Merge branch 'feature/ml_subscription_address' of cdedb/cdedb2 into master
[35m|[m[36m\[m [1;36m\[m  
[35m|[m * [1;36m|[m [33m9080a7ad[m[33m ([m[1;31morigin/feature/ml_subscription_address[m[33m)[m ml: display subscription addresses in ml-management. closes #373
* [36m|[m [1;36m|[m   [33m2cc8636e[m Merge branch 'feature/course_logos'
[1;31m|[m[1;32m\[m [36m\[m [1;36m\[m  
[1;31m|[m * [36m|[m [1;36m|[m [33mc0a58936[m test: add test for setting and viewing course logos.
[1;31m|[m * [36m|[m [1;36m|[m [33m831b250c[m event: fix copy-paste error and do not differentiate set_logo and get_logo in URL. See #472
[1;31m|[m * [36m|[m [1;36m|[m [33mb3f48a26[m Deploy: The 'course_logo' directory must be created in the storage directory.
[1;31m|[m * [36m|[m [1;36m|[m [33me5196a5d[m[33m ([m[1;31morigin/feature/course_logos[m[33m)[m test: fix test after url change
[1;31m|[m * [36m|[m [1;36m|[m [33m003a453a[m event: allow deletion of minor_form
[1;31m|[m * [36m|[m [1;36m|[m [33m30aadc22[m event: make minor_form accessible to orgas and admins if event is locked.
[1;31m|[m * [36m|[m [1;36m|[m [33m93860ba4[m event: allow uploading of course_logos
[1;31m|[m * [36m|[m [1;36m|[m [33m76a4a4f3[m event: implement event logo removal form.
[1;31m|[m [36m|[m[36m/[m [1;36m/[m  
* [36m|[m [1;36m|[m [33m84f0d699[m core-frontend: Fix password reset workflow.
* [36m|[m [1;36m|[m   [33mc0693734[m Merge branch 'feature/past_event_deletion' of cdedb/cdedb2 into master
[1;33m|[m[1;34m\[m [36m\[m [1;36m\[m  
[1;33m|[m * [36m|[m [1;36m|[m [33ma56b3919[m past_event: remove duplicate query. see #477
[1;33m|[m * [36m|[m [1;36m|[m [33m856488a1[m Deploy: `DELETE` must be granted to cdb_admin for the `past_event.events` table.
[1;33m|[m * [36m|[m [1;36m|[m [33m931258f8[m[33m ([m[1;31morigin/feature/past_event_deletion[m[33m)[m test: add tests for deleting past events.
[1;33m|[m * [36m|[m [1;36m|[m [33m63c5b581[m frontend: allow deletion of past events.
[1;33m|[m * [36m|[m [1;36m|[m [33m5fc80ae1[m backend: allow deletion of past events.
[1;33m|[m [1;36m|[m [36m|[m[1;36m/[m  
[1;33m|[m [1;36m|[m[1;36m/[m[36m|[m   
* [1;36m|[m [36m|[m [33m355501ab[m core-frontend: Remove redirect to make validation work correctly.
* [1;36m|[m [36m|[m [33m81e4ce8a[m tests: Fix test after spelling adjustments.
* [1;36m|[m [36m|[m   [33me9e60b5d[m Merge branch 'fix/spelling'
[1;35m|[m[1;36m\[m [1;36m\[m [36m\[m  
[1;35m|[m * [1;36m|[m [36m|[m [33m8f9cbc4c[m i18n: improve spelling.
* [1;36m|[m [1;36m|[m [36m|[m   [33mea02e795[m Merge branch 'feature/allow_ml_deletion'
[31m|[m[32m\[m [1;36m\[m [1;36m\[m [36m\[m  
[31m|[m * [1;36m|[m [1;36m|[m [36m|[m [33m29ca7840[m test: add test for deleting ml.
[31m|[m * [1;36m|[m [1;36m|[m [36m|[m [33mb9147a62[m i18n: add delete_ml translations
[31m|[m * [1;36m|[m [1;36m|[m [36m|[m [33mb28d6725[m ml: allow deletion of mailinglists. closes #141
* [32m|[m [1;36m|[m [1;36m|[m [36m|[m [33m3f5d67f3[m i18n: fix weird translation.
* [32m|[m [1;36m|[m [1;36m|[m [36m|[m [33mb786ec52[m test: add test for membersearch phone parameter
* [32m|[m [1;36m|[m [1;36m|[m [36m|[m [33m735406f6[m cde: fix membersearch phone parameter.
* [32m|[m [1;36m|[m [1;36m|[m [36m|[m   [33md528837f[m Merge branch 'fix/reword_username_to_emailadress'
[1;36m|[m[34m\[m [32m\[m [1;36m\[m [1;36m\[m [36m\[m  
[1;36m|[m [34m|[m[1;36m_[m[32m|[m[1;36m/[m [1;36m/[m [36m/[m  
[1;36m|[m[1;36m/[m[34m|[m [32m|[m [1;36m|[m [36m|[m   
[1;36m|[m * [32m|[m [1;36m|[m [36m|[m [33m8f7e3e47[m[33m ([m[1;31morigin/fix/reword_username_to_emailadress[m[33m)[m fix: hope, I get now all invalid spelling, see #460
[1;36m|[m * [32m|[m [1;36m|[m [36m|[m [33mfece93ab[m unify: try to unify "email address" in the english UI
[1;36m|[m * [32m|[m [1;36m|[m [36m|[m [33m7931dcb1[m remove: obsolte hint "E-Mail-Adress, which is your username" closes #402
[1;36m|[m * [32m|[m [1;36m|[m [36m|[m [33m58dff2d5[m change: error strings from "username" to "E-Mail-Address"
[1;36m|[m * [32m|[m [1;36m|[m [36m|[m [33mb3a026b6[m change: uservisible strings from "username" to "E-Mail-Adress" see issue #402
* [34m|[m [32m|[m [1;36m|[m [36m|[m [33m6f0048c2[m scripts: Fix performance of push-stable script.
[32m|[m [34m|[m[32m/[m [1;36m/[m [36m/[m  
[32m|[m[32m/[m[34m|[m [1;36m|[m [36m|[m   
* [34m|[m [1;36m|[m [36m|[m [33m8eca4f4b[m test: adjust parse_statement test.
* [34m|[m [1;36m|[m [36m|[m [33m90ff697e[m parse: improve type predictions
* [34m|[m [1;36m|[m [36m|[m [33md2e7cf17[m parse: use re.findall instead of re.search, capitalize checkdigit and filter output some more.
* [34m|[m [1;36m|[m [36m|[m [33m637b6237[m scripts: Add mechanism for detecting changes needing adjustments in production.
[1;36m|[m [34m|[m[1;36m/[m [36m/[m  
[1;36m|[m[1;36m/[m[34m|[m [36m|[m   
* [34m|[m [36m|[m [33mf562adf4[m test: fix some test data.
* [34m|[m [36m|[m [33m93eac087[m event: unmake params in helper function a generator, because we iterate it twice.
* [34m|[m [36m|[m [33mef93c142[m parse: fix file upload being required.
[36m|[m [34m|[m[36m/[m  
[36m|[m[36m/[m[34m|[m   
* [34m|[m [33mc0b09e06[m i18n: add logo translations.
* [34m|[m [33m32865b35[m test: add test for name collision in genesis request.
* [34m|[m   [33m6bb5bce9[m Merge branch 'fix/dont_exclude_orgas' of cdedb/cdedb2 into master
[35m|[m[36m\[m [34m\[m  
[35m|[m * [34m|[m [33mc64e8b2d[m[33m ([m[1;31morigin/fix/dont_exclude_orgas[m[33m)[m frontend/event: Don't exclude orgas' course choices
* [36m|[m [34m|[m   [33m848870a2[m Merge branch 'feature/CSP-nonce'
[1;31m|[m[1;32m\[m [36m\[m [34m\[m  
[1;31m|[m * [36m|[m [34m|[m [33m531b9aae[m frontend: Make CSP-header creation less confusing.
[1;31m|[m * [36m|[m [34m|[m [33m36fa0c90[m[33m ([m[1;31morigin/feature/CSP-nonce[m[33m)[m frontend: Use Content-Security-Policy with 'nonce-...'
* [1;32m|[m [36m|[m [34m|[m [33m12ba75d5[m core-backend: Restrict to non-final genesis states.
* [1;32m|[m [36m|[m [34m|[m   [33m23154daf[m Merge branch 'fix/checkin_workflow' of cdedb/cdedb2 into master
[1;33m|[m[1;34m\[m [1;32m\[m [36m\[m [34m\[m  
[1;33m|[m * [1;32m|[m [36m|[m [34m|[m [33ma127b4ec[m[33m ([m[1;31morigin/fix/checkin_workflow[m[33m)[m test: Add test for concurrent event checkin workflow
[1;33m|[m * [1;32m|[m [36m|[m [34m|[m [33m75f0aad7[m frontend/event: Add `skip` parameter to change_registration()
* [1;34m|[m [1;32m|[m [36m|[m [34m|[m [33m62cde72c[m core: take genesis cases into account when verifying the (non-)existance of usernames.
* [1;34m|[m [1;32m|[m [36m|[m [34m|[m [33mc7701f81[m test: add test for setting event logo.
* [1;34m|[m [1;32m|[m [36m|[m [34m|[m [33me954778b[m event: allow uploading event logos to be used in the downloads provided by the DB.
* [1;34m|[m [1;32m|[m [36m|[m [34m|[m [33m0c327c5a[m i18n: add trnaslations for new file uploads
* [1;34m|[m [1;32m|[m [36m|[m [34m|[m [33m435f755f[m frontend: allow file upload for money_transfers and batch_fees
* [1;34m|[m [1;32m|[m [36m|[m [34m|[m [33m8d40221d[m parse: allow uploading csv file. see #239
* [1;34m|[m [1;32m|[m [36m|[m [34m|[m [33mf65e9c56[m validation: add validator for csv files.
* [1;34m|[m [1;32m|[m [36m|[m [34m|[m [33m3e0bb7b5[m test: add tests for new log filters. closes #415
* [1;34m|[m [1;32m|[m [36m|[m [34m|[m [33m401df8c1[m templates: add input for filtering logs by ctime to generic log filter.
* [1;34m|[m [1;32m|[m [36m|[m [34m|[m [33m63d06574[m frontend: take and validate time filter parameters in the frontend and pass them on.
* [1;34m|[m [1;32m|[m [36m|[m [34m|[m [33mdce0ed2e[m backend: take time filter parameters in backend endpoints and pass them on to generic_retrieve_log
* [1;34m|[m [1;32m|[m [36m|[m [34m|[m [33m903f850f[m backend: allow filtering by ctime in retrieve_changelog_meta
* [1;34m|[m [1;32m|[m [36m|[m [34m|[m [33m33f0ce0d[m backend: allow generic_retrieve_log to filter for ctime. See #415
* [1;34m|[m [1;32m|[m [36m|[m [34m|[m   [33m526f926a[m Merge branch 'feature/course_assignment_checks' of cdedb/cdedb2 into master
[1;35m|[m[1;36m\[m [1;34m\[m [1;32m\[m [36m\[m [34m\[m  
[1;35m|[m * [1;34m|[m [1;32m|[m [36m|[m [34m|[m [33md19f7eef[m[33m ([m[1;31morigin/feature/course_assignment_checks[m[33m)[m frontend: Remove participant listings from event/stats
[1;35m|[m * [1;34m|[m [1;32m|[m [36m|[m [34m|[m [33m14e5af8a[m frontend/event: Fix copy/pasted docstring
[1;35m|[m * [1;34m|[m [1;32m|[m [36m|[m [34m|[m [33m131a26f8[m test: Add test for event/course_assignment_checks
[1;35m|[m * [1;34m|[m [1;32m|[m [36m|[m [34m|[m [33mca35f6c5[m frontend: Add event/course_assignment_checks
[1;35m|[m [36m|[m [1;34m|[m[36m_[m[1;32m|[m[36m/[m [34m/[m  
[1;35m|[m [36m|[m[36m/[m[1;34m|[m [1;32m|[m [34m|[m   
* [36m|[m [1;34m|[m [1;32m|[m [34m|[m   [33m39445993[m Merge branch 'fix/field_options_normalize' of cdedb/cdedb2 into master
[31m|[m[32m\[m [36m\[m [1;34m\[m [1;32m\[m [34m\[m  
[31m|[m * [36m|[m [1;34m|[m [1;32m|[m [34m|[m [33m4cbc2914[m[33m ([m[1;31morigin/fix/field_options_normalize[m[33m)[m validation: Normalize event datafield's option values according to type
* [32m|[m [36m|[m [1;34m|[m [1;32m|[m [34m|[m [33m0997ac3d[m test: fix sample data and tests after fe74ed345cc
* [32m|[m [36m|[m [1;34m|[m [1;32m|[m [34m|[m [33mcf198bea[m fix: some translations
[34m|[m [32m|[m[34m_[m[36m|[m[34m_[m[1;34m|[m[34m_[m[1;32m|[m[34m/[m  
[34m|[m[34m/[m[32m|[m [36m|[m [1;34m|[m [1;32m|[m   
* [32m|[m [36m|[m [1;34m|[m [1;32m|[m [33m313873a2[m test: fix csv test after #452
* [32m|[m [36m|[m [1;34m|[m [1;32m|[m [33mfe74ed34[m ui: Reword AttachmentPolicy option labels to point out HTML filtering
* [32m|[m [36m|[m [1;34m|[m [1;32m|[m [33m50b171c2[m ui: Fix 'guest' flag on event/checkin
* [32m|[m [36m|[m [1;34m|[m [1;32m|[m [33m08391ff0[m ui: Fix whitespace and translation of titles of course numbers on event/course_choices
* [32m|[m [36m|[m [1;34m|[m [1;32m|[m [33m787b6dd4[m ui: Add indication of course instructors at event/show_course
[36m|[m [32m|[m[36m/[m [1;34m/[m [1;32m/[m  
[36m|[m[36m/[m[32m|[m [1;34m|[m [1;32m|[m   
* [32m|[m [1;34m|[m [1;32m|[m [33m24728e84[m ui/cde: Add listselect JavaScript to lastschrift finalization table
* [32m|[m [1;34m|[m [1;32m|[m [33m7c73d0aa[m i18n: fix incorrect/inconsistent translation.
* [32m|[m [1;34m|[m [1;32m|[m [33m0a53099b[m test: add test for changes made for #452.
* [32m|[m [1;34m|[m [1;32m|[m [33mb0e77fd9[m validation: implement linebreak changes as discussed in #452.
* [32m|[m [1;34m|[m [1;32m|[m [33m93e01c8f[m template: fix orga overview in dashboard being empty if orga events are long enough in the past.
* [32m|[m [1;34m|[m [1;32m|[m [33m83dc5711[m event: show notification about archived event on every event page. closes #449
[32m|[m[32m/[m [1;34m/[m [1;32m/[m  
* [1;34m|[m [1;32m|[m [33m3ab63b27[m backend/event: Fix event datafield type conversion on TypeErrors (e.g. float→date)
[1;34m|[m[1;34m/[m [1;32m/[m  
* [1;32m|[m [33m90152294[m frontend: Add version parameter with GIT_COMMIT to static urls
* [1;32m|[m [33m01a665f1[m templates: Remove indirection of script names in util.cdedb_script()
[1;32m|[m[1;32m/[m  
* [33m766d51ca[m core-frontend: Fix access to lastschrift information.
* [33m8d4ac205[m event-backend: First draft of partial-import functionality.
* [33mbbfa8f9f[m tests: Fix several tests.
* [33m3d174464[m frontend: Enhance encoded parameters to signal timeouts.
* [33m2de61085[m cde-frontend: Clarify effect of terminating a membership.
* [33m25187c87[m past-event-backend: Archive event parts in deterministic order.
* [33m26b2c4eb[m cde-backend: Check that only one active permit persona is allowed.
*   [33m5823d48c[m Merge branch 'feature/lastschrift-workflow'
[33m|[m[34m\[m  
[33m|[m * [33m0f8253d2[m templates: Deduplicate via symlink.
[33m|[m * [33mbc6a7384[m lastschrift: iterate over lastschrifts not lastschrift ids.
[33m|[m * [33mc03a23c3[m lastschrift: check for pending transactions for a given lastschrift upon lastschrift rollback. see #440
[33m|[m * [33meba3d586[m lastschrift: fix calculation of payment date for some edge cases. closes #437
[33m|[m * [33m9033ea2d[m lastschrift: improve do_mail call, remove unneeded Atomizer, move notification around. see #440
[33m|[m * [33mc4e9f538[m templates: use more iban filters.
[33m|[m * [33mf75e7eea[m lastschrift: fix a few bugs. add a copy of the mail template to cde realm.
[33m|[m * [33m5739a5ab[m test: adjust tests to new lastschrift workflow. test that transactions were actually created.
[33m|[m * [33m4a766d12[m lastschrift: small text fixes
[33m|[m * [33m5090109e[m templates: improve and translate info texts
[33m|[m * [33mf5499365[m[33m ([m[1;31morigin/feature/lastschrift-workflow[m[33m)[m cde: send notification to Verwaltung if lastschrift is revoked while still pending. closes #435
[33m|[m * [33m9978a768[m core: send notification to Verwaltung if membership is revoked while member has pending lastschrift. see #435
[33m|[m * [33m224ee99d[m test: add test for revoking multiple lastschrifts. see #447
[33m|[m * [33m72b22c86[m core: make revoking membership revoke _all_ active permits. see #447
[33m|[m * [33mdde25f72[m lastschrift: fix template error with revoked pending lastschrift. closes #435
[33m|[m * [33m65460517[m cde: add mail template and send mail for sepa pre-notification. see #436 and #440
[33m|[m * [33m7c9694ae[m lastschrift: make lastschrift_generate_transactions only create the transactions not the sepapain file.
[33m|[m * [33m18ada539[m lastschrift: create separate function to permit stateless download of sepapain file. closes #426. Also see #436
[33m|[m * [33mc2cfa8e3[m lastschrift: ensure the payment date is a valid TARGET2 bankday. closes #437
* [34m|[m [33mffec1efa[m ml-backend: Fix missing access checks.
* [34m|[m [33mc6e4084d[m frontend: Be compliant to RFC 2045.
* [34m|[m [33m0b248038[m i18n: cleanup po-files
* [34m|[m [33m3edc2ea1[m test: Add test for past event links
* [34m|[m [33m77efaed1[m test: add test for #443
* [34m|[m [33ma3395f4d[m assembly: allow list_assemblies for "persona". closes #443
* [34m|[m [33mc2b1c41b[m ml: prevent non-moderators and non-admins from viewing the configuration page.
* [34m|[m [33mae6ede21[m templates: add noindex tag to all templates. See #445
* [34m|[m [33m2413386d[m parse: improve fuzzy matching of db-ids and improve testdata accordingly
* [34m|[m [33m55d06ace[m parse: improve test-data for new usage of EREF
* [34m|[m [33m33d530f5[m parse: small template fix
* [34m|[m [33mabecc874[m parse: output posting into other_transactions
* [34m|[m [33maf5e0f59[m parse: use end to end reference when parsing transactions.
* [34m|[m [33mdc67fb64[m ml: Add counts for subscribers, mods and whitelisted mails
* [34m|[m [33m0a52126a[m ui/event: Fix layout of questionaire preview
* [34m|[m [33mc1b5c4cf[m i18n: Fix spelling error
* [34m|[m [33m0d88d594[m ml: Actually allow moderators to use check_state
* [34m|[m [33m2816e70c[m doc: Bring Copyright up to date
* [34m|[m [33m299f3b6e[m fix: Correct errors from previous commits.
* [34m|[m [33m5c2a6956[m ml allow moderators to mark exceptions in check_states.
* [34m|[m [33m0bad6911[m cde-frontend: Add more info to semester overview.
* [34m|[m [33mbdacb847[m templates: Improve handling of unexpected errors.
* [34m|[m   [33m8a2c6765[m Merge branch 'master' of ssh://tracker.cde-ev.de:20009/cdedb/cdedb2
[35m|[m[36m\[m [34m\[m  
[35m|[m * [34m|[m [33m05aef5a7[m doc: Remove ldap example
[35m|[m * [34m|[m [33m27fda000[m translation: Add closing bracket
* [36m|[m [34m|[m [33m1a034615[m unifying event/stats translations. closes #364
[36m|[m[36m/[m [34m/[m  
* [34m|[m [33mdb2fc26f[m templates: make logo a link to index. closes #369
* [34m|[m [33md05b0f48[m ml: fix permissions for moderators using check_state.
* [34m|[m [33m18166fbf[m ml: allow check_states for moderators.
[34m|[m[34m/[m  
* [33ma33bc0cb[m test: fix one more test with new IBAN expectation.
* [33meb558f87[m frontend: add iban filter to display IBANs nicely. see #434
* [33mc35ef366[m test: fix testdata after iban whitespace adjustment.
* [33m51b62c67[m validation: remove spaces from iban during validation. closes #434
* [33mf6d44fc2[m core-frontend: Add ml_usage decorator where necessary.
* [33md363a938[m templates: Fix missing translations
*   [33mad31be78[m Merge branch 'fix/json-handling' of cdedb/cdedb2 into master
[1;31m|[m[1;32m\[m  
[1;31m|[m * [33mb9f27dac[m cdedb: Improve JSON-handling.
* [1;32m|[m [33m81a00c34[m templates: Improve wording of admin links.
* [1;32m|[m [33m41a38ad0[m cde: improve trailing whitespace handling in money_transfers
* [1;32m|[m [33m6b504489[m test: improve test_money_transfers to check for note generation
* [1;32m|[m [33m2c0684e4[m cde: fix note generation in perform_money_transfers.
[1;32m|[m[1;32m/[m  
* [33m6a45e066[m lint: Correct indentation.
* [33m0198f8f2[m query: Add export for dokuteam.
* [33m7029e09e[m doc: Remove leftover ldap from documentation.
* [33mff257b5c[m auto-build: Upgrade locking.
* [33m98a08cc2[m auto-build: Tweak some settings so that we hopefully have less hangs.
* [33m44c5556c[m frontend: Replace python-markdown-toc's anchorlink with permalink
* [33md80ab840[m templates: add inputs for filtering by submitted/reviewed_by. see #415
* [33m600d7f02[m frontend: allow filtering changelog_meta by add_info, submitted/reviewed_by and persona_id. see #415
* [33m83a11b6b[m backend: extend retrieve_changelog_meta to allow filtering by add_info, submitted/reviewed_by and persona_id. see #415
* [33m1f2e9a13[m backend: take additional_info parameter in backend functions to pass to generic_retrieve_log. see #415
* [33m4f8a8561[m backend: refactor retrieve_finance_log to use the generic_retrieve_log function. see #415
* [33mb1a2a68c[m backend: make use of additional_info to filter logs in backend/common. see #415.
* [33m3b220b7c[m frontend: take additional_info argument in frontend log endpoints. see #415
* [33med0aed0b[m templates: add filter option for additional info to all logs.
* [33mc1d3a6be[m templates: use new generic.log_filter in one more template.
* [33m87bc3b4c[m test: fix test regarding #195 after recent adjustments.
* [33me52ce314[m frontend: handle fields correctly in create_course. See #195 and email regarding this.
* [33m0fdffcbd[m backend: allow fields to be set in create_course. see #195 and email regarding commit f633dbeeee
* [33m33c8292b[m templates: deduplicate log filter code. This is in preparation for #415
* [33m8cefc794[m validation: validate IBAN length. closes #430
* [33mf98c039a[m scripts: Add script to activate all personas.
* [33m627b0a25[m Revert "core-backend: Make gaining Membership activate an account."
* [33m7631bdc2[m core-frontend: Make type of 'data' in select_persona consistent.
*   [33m46c642f1[m Merge branch 'fix/change_field_datatype'
[1;33m|[m[1;34m\[m  
[1;33m|[m * [33mb95e6374[m event-backend: Be noisy in case of unexpected conditions.
[1;33m|[m * [33m9f9bf239[m ui/event: Add warning about implicit data deletion upon change field definitions
[1;33m|[m * [33mfaef38ee[m backend/event: Add casting of data upon field datatype change
[1;33m|[m * [33mf6cbbc0f[m backend/event: Delete field values on deletion of field definition
[1;33m|[m * [33mda1aefb5[m test: Add test to reproduce #207
* [1;34m|[m [33m365b6829[m templates: Restrict error messages.
* [1;34m|[m [33m8bbdeee3[m templates: hide cde-navigation bar for anonymous users.
* [1;34m|[m [33md162941a[m core-backend: Add back in one more line I thought was redundant.
* [1;34m|[m [33madbb979b[m validation: Change source of postal code data.
* [1;34m|[m [33m7189becc[m core-backend: Fix changelog revision insertion.
* [1;34m|[m [33m017aa6a2[m lastschrift: asciificate the subject after inserting names and ID.
* [1;34m|[m [33m504cfb74[m tests: Fix tests for birth_name changes.
* [1;34m|[m [33m8cb7b307[m cde-frontend: Improve note generation for money transfers.
* [1;34m|[m [33m4c4cad7e[m utils: Improve comparison methods in InfiniteEnum.
* [1;34m|[m [33m56b1c39e[m core-frontend: Restrict birth_name to cde realm.
* [1;34m|[m [33m0202b7fd[m templates: Fix HTML.
* [1;34m|[m [33md32ede0f[m cde-frontend: Fix side-effect of is_active flag on past event participants.
* [1;34m|[m [33mb7f52868[m validation: Update list of postal codes.
* [1;34m|[m [33m4e856fef[m test: add test for #425
* [1;34m|[m [33m509a1338[m lastschrift: improve feedback when trying to issue transaction while another one is pending.
* [1;34m|[m [33m0fc40789[m lastschrift: fix bug where subject got too long due to asciification in validator.
* [1;34m|[m [33m018c22ef[m lastschrift: show errors on failed SEPA-PAIN file generation. #425
* [1;34m|[m [33mdb51f87e[m core: allow changing of ones birth name. add a test for this.
* [1;34m|[m [33m3ec3b931[m core: show link to edit changes on inspect_change page.
* [1;34m|[m [33m12047e68[m frontend/event: Fix course_choices for submit from unfiltered list
* [1;34m|[m [33m9dce4cdb[m Make InfiniteEnum class comparable and sortable
* [1;34m|[m [33md289b44f[m test: Fix tests for renamed field names on event/course_choices
* [1;34m|[m [33mc1071fba[m ui: Fix util.event_field_input for empty name parameter
* [1;34m|[m [33mbbb35625[m frontend/event: Show similarly filtered form after submitting course_choices_form
* [1;34m|[m [33mba84139b[m Make InfiniteEnums a real class and add .value property
* [1;34m|[m [33m7eb1bf0a[m frontend/event: Fix error handling of change_registrations_form
* [1;34m|[m [33medfaafc8[m backend/common: Simplify cast_fields() by using enum values
* [1;34m|[m [33m00d2aa0a[m ui: Fix form_event_field_input macro for not explicitly given name
* [1;34m|[m [33m214131e6[m test: adjust batch_fee test to changed parse_statement output.
* [1;34m|[m [33m24dfbafd[m test: adjust parse_statement test to changed date format.
* [1;34m|[m [33mc369f048[m cde: fix note generation in money_transfers
* [1;34m|[m [33mf4a7896e[m templates: use reverse filter instead of dictsort attribute reverse. closes #419
[1;34m|[m[1;34m/[m  
* [33me1f06a4b[m test: Enable the commented part in test_event_fields_unique_name
* [33m35139ee9[m cde/money_transfers: use date in comment field to build useful changenote.
* [33me990cbcc[m test: add test for unique event_field names. #409
* [33m19f14501[m test: fix cde search tests after regEx change. see #393
* [33m297046d9[m event: fix validation of unique field_name. closes #409
* [33mc059d680[m event: fix typo
* [33mc767a26f[m i18n: translate usage hint for first/second address. closes #408
* [33m8401e683[m test: add test for moderator access to mailinglist configuration and log
* [33m8c60bce8[m ml: allow modereators to view ml-configuration. closes #400
* [33m40d8a40c[m event-frontend: Detect non-unique field names.
* [33m62a5f149[m core-frontend: Use correct mime type for profile fotos,
* [33m3733aff3[m backend: Make regex query operators case-sensitive.
* [33m36f26541[m test: fix expected order of log messages upon set_event call.
* [33m668b0657[m test: add test for #414 and #124
* [33m6a054dc8[m test: fix test
* [33m3127662a[m cde: only allow view_misc for members.
* [33m3e0d1d9d[m backend/event: escape uppercase fieldnames in query.constraints. closes #124 (this time really for real)
* [33mdb8f81cf[m event: convert kind enum to name to lookup available QueryOperators. closes #414
* [33m12184967[m event-backend: Quote _all_ field occurences so that capital letters work.
* [33m48f43508[m core-frontend: Fix mail getting misdelivered.
[1;34m|[m * [33m65d328ef[m[33m ([m[1;31morigin/fix/event_backend_performance_v2[m[33m)[m event-backend: Restage the left out parts of the first version of this branch.
[1;34m|[m[1;34m/[m  
*   [33ma7540298[m Merge branch 'fix/event_backend_performance' of cdedb/cdedb2 into master
[1;36m|[m[31m\[m  
[1;36m|[m * [33md771429f[m event-backend: Unstage part of this branch to be discussed further.
[1;36m|[m * [33m8f43b9fa[m[33m ([m[1;31morigin/fix/event_backend_performance[m[33m)[m backend/event: Optimize concurrency of _set_course_choices
[1;36m|[m * [33m6cce12ab[m backend/event: Improve performance of delete_lodgement()
[1;36m|[m * [33m6f65966c[m backend/event: Improve create_event()
[1;36m|[m * [33m62fb7271[m backend/event: Improve performance by adding _get_event_course_segments
[1;36m|[m * [33m3e349eb7[m backend/event: Improve performance by adding _get_event_fields helper
[1;36m|[m * [33m8628145a[m backend: Improve performance of event/create_registration
* [31m|[m [33mdf28a7c6[m suggestion for first and second adress explaination (from CdE Webside)
* [31m|[m [33mf633dbee[m event: do field setting upon course creation in two steps, because creation doesn't allow setting fields.
* [31m|[m [33md1f747e6[m event: show Markdown info for course notes.
* [31m|[m [33mb97a1187[m script: Add script to fix migration slip for display names.
* [31m|[m [33m1478e167[m fix Breadcrumb translation
* [31m|[m [33m9ad808f3[m event: allow setting fields upon course creation. closes #195
* [31m|[m [33ma64c98d3[m i18n: fix a few missing translations.
* [31m|[m [33mffffd7af[m test: fix tests after making all change_notes German.
* [31m|[m [33md613704e[m cde: add misc page set via meta data. see #396
* [31m|[m [33m425c0872[m i18n: do not translate file names. closes #390
* [31m|[m [33m2f99df11[m core-backend: Make gaining Membership activate an account.
* [31m|[m [33m89da97c6[m core-frontend: Fix another TypeError.
* [31m|[m [33m1b24d280[m core-frontend: Fix TypeError.
* [31m|[m [33ma4408218[m template: fix typo
* [31m|[m [33m9c28f31c[m core: improve error handling during password reset.
* [31m|[m [33m2ee35099[m core: send infomail to old email upon username change.
* [31m|[m [33m8c4a99a1[m i18n: do not translate email subjects. closes #386
* [31m|[m [33ma19e7cef[m tests: Fix tests.
* [31m|[m [33mab080b59[m core-backend: Reduce log spam.
* [31m|[m [33m7c229dbd[m scripts: Add a script to fix imported emails with upper case letters.
* [31m|[m [33mca0b0aac[m ml: Add forgotten mapping of mime types to oldstyle ml export.
* [31m|[m [33m08f7ee4b[m pep8: fix small indentation error
* [31m|[m [33mf654ff3d[m templates: do not translate change_notes.
* [31m|[m [33m8f1fa218[m i18n: do not translate change_notes
* [31m|[m [33ma4a1e7df[m core: improve reset link error messages.
* [31m|[m [33m32a0e7d8[m frontend: localize the output of the money_filter and add new localized decimal_filter. closes #381
* [31m|[m [33mc1ee5683[m constants: change the name for decimal custom field datatype needs from decimal to float.
* [31m|[m [33m632b0d54[m translation fix fixed
* [31m|[m [33ma42d3374[m translate some minor things
* [31m|[m [33m24badf3a[m event: show infolink for text_only quetionnaire fields. closes #276.
* [31m|[m [33m12cc2c2b[m core: fix timeout parameter at one more point.
* [31m|[m [33m6b9033be[m core: fix reset link timeout of email parameter. see #366
* [31m|[m [33m31f16e76[m cde: fix handling of new count parameter before first search.
* [31m|[m [33m2d09559c[m test: add test for any_admin_query
* [31m|[m [33m19ecf8e1[m make: fix removal of logs and mails before executing test suite.
* [31m|[m [33m0576901d[m core: fix any_admin_query displayed_fields
* [31m|[m [33mc20ec79b[m test: add test for #377.
* [31m|[m [33m78027ea9[m core: make same username validation error for username change. closes #377
* [31m|[m [33m590185d5[m cde/member_search: improve feedback for result cutoff. closes #370
* [31m|[m [33m6cd9379d[m frontend: reverse the sorting of archived assemblies and past events on profile.
* [31m|[m [33md2596aa4[m bin: add small python script to extract the translation strings from PO-file.
* [31m|[m [33ma3cada89[m i18n: add missing translations
* [31m|[m [33mf20c8032[m ui: Use custom style for past events table on core/show_user
* [31m|[m [33m0395af1c[m ui: Move 'dots' design element a few pixels to fit larger logo
* [31m|[m [33m5d2925fb[m i18n: fix typo and missing translation.
* [31m|[m [33mffc2ceb9[m event: use new datatype enum in change_event lodge_field and reserve_field select.
* [31m|[m [33m1e3e5fef[m test: fix two more tests
* [31m|[m [33m10b33d96[m fix merging problems (Translations)
* [31m|[m [33m23ca5808[m fix some translations
* [31m|[m [33mc4e3442c[m test: adjust tests to Deppenleerzeichen removal
* [31m|[m [33ma76a5e20[m i18n: remove Deppenleerzeichen.
* [31m|[m [33m1167de8e[m core: show cp payment information for admins closes #334
* [31m|[m [33m1181664a[m ml: protect removing all problematic subscribers via JS.
* [31m|[m [33mb84fdd41[m ui: Fix missing translation on core/change_user
* [31m|[m [33m7713b446[m core: Do not spam with mails for rather common pending user changes.
* [31m|[m [33m83a12701[m samle-data: fix Berta's missing profilephoto
* [31m|[m [33mbf152895[m frontend/core: Change admin_send_password_reset_link to POST
* [31m|[m [33mdc6ef8fb[m core-backend: Fix reset cookie generation to actually use timeout parameter.
* [31m|[m [33md459f359[m test: adapt test to changed log title.
* [31m|[m [33m6923907a[m test: fix ml backend test
* [31m|[m [33m3a646fd4[m i18n: translate default queries again.
* [31m|[m [33m68faf0cd[m query: adjust default_query sorting prefixes so they are actually useful.
* [31m|[m [33m09171c51[m ui: Fix querform.js: Fix "Show in searchmask" for multi-field filters
* [31m|[m [33m4d79f47e[m templates: Fix typo so that given names actually appear.
* [31m|[m [33m57955684[m add translations
* [31m|[m [33m89857484[m core: Add default Query and search filter for any admin. default query is buggy see #365
* [31m|[m [33m94bd84dd[m add some translations
* [31m|[m [33m031700b4[m rename "core log" to "account log"
* [31m|[m [33me2d0bd65[m ml: Fix whitelist export for rklists.
* [31m|[m [33mc9e76196[m cde: provide saldo on money transfers. closes #363
* [31m|[m [33mcafc7559[m zxcvbn: improve test to include cde-specific passwords. #330
* [31m|[m [33m4758129e[m zxcvbn: provide cde_dictionary to zxcvbn. #330
* [31m|[m [33me1d67da7[m markdown: improve markdown infotext. closes #354
* [31m|[m [33meb961b88[m core: verify existancy of id before redirect in admin_show_user. cloes #351
* [31m|[m [33m56402a51[m cde: don't show past event participant count to non_admins. closes #357
* [31m|[m [33m007a419e[m i18n: Fix typo.
* [31m|[m [33m380b038c[m protected Form against accidently leaving the site closes #359
* [31m|[m [33mc5e48f40[m fix translation of "Vorstand" in Meta_info #359
* [31m|[m [33me04613e9[m ui: Fix layout of ml/management: Shorter label for "Add moderator"
* [31m|[m [33m96cbf2ff[m ui: Improve core/admin_change_user: Change note near submit button
* [31m|[m [33m122407b0[m ml: sort assemblies, events and mailinglists before passing them to "change_mailinglist". closes #355
* [31m|[m [33mde809527[m i18n: fix typo. closes #356
* [31m|[m [33medaa8b74[m cde/membersearch: fix birthname layout issue. closes #360
* [31m|[m [33mb8b0968a[m core/show_user: fix button layout of "send password reset link". closes #358
* [31m|[m [33m4aab6693[m frontend: allow <br> through bleach.
* [31m|[m [33macef85d4[m ui: Add linebreaks filter to notes on core/show_user
* [31m|[m [33m17efd42b[m frontend: Fix linebreaks_filter: Don't escape <br>
* [31m|[m [33m10fdba5c[m ui/core: Sort generations on show_history in ascending order
* [31m|[m [33m7c0f3799[m i18n: add some missing translation strings.
* [31m|[m [33m84392bd0[m lastschrift: add hint about availability only within SEPA.
* [31m|[m [33me80bdba1[m markdown: fix the prefix and adapt the test accordingly.
* [31m|[m [33m6d56d8cf[m core: only allow deleting foto via the delete form. closes #336
* [31m|[m [33m5e42ea7b[m frontend: add wrapper to prefix Markdown ids with custom prefix. closes #346
* [31m|[m [33m669b2915[m migration: Last adaptations.
* [31m|[m [33m2b064e4c[m migration: Start on second step of semester.
* [31m|[m [33mff3fc4f5[m core: Remove beta-specific code.
* [31m|[m [33mc3ec574b[m config: Remove unused option.
* [31m|[m [33mbe1e1ecb[m doc: Fix formatting.
* [31m|[m [33m40e9d56a[m i18n: fix translation format string and remove unneeded translations. closes #347
* [31m|[m [33me66e2293[m parse: remove flags on search with compiled pattern.
* [31m|[m [33m5fc1f445[m core: Improve reset cookie logic.
* [31m|[m [33m8eb2e121[m doc: One more comment for buster.
* [31m|[m [33mfe517ff2[m frontend: Complete markdown transition.
* [31m|[m   [33m0aafc0b4[m Merge branch 'feature/markdown'
[32m|[m[33m\[m [31m\[m  
[32m|[m * [31m|[m [33mfbabd2be[m test: replace test_rst with test_markdown. see #339
[32m|[m * [31m|[m [33m1d41e0ca[m test: update sample-data to markdown. see #339
[32m|[m * [31m|[m [33m45cbdf10[m markdown: use some markdown extensions and allow the required tags and attributes through bleach. see #339
[32m|[m * [31m|[m [33m7f134cc8[m[33m ([m[1;31morigin/feature/markdown[m[33m)[m doc: updated Markdown Crashcourse
[32m|[m * [31m|[m [33mb429df16[m event: add missing infotext to event description configuration.
[32m|[m * [31m|[m [33m562b95d4[m frontend: Fix handling of Markdown's internal state
[32m|[m * [31m|[m [33m834c71d5[m frontend: Add markdown Treeprocessor to reduce heading level
[32m|[m * [31m|[m [33m05ac2474[m auto-build: include markdown library in auto-build.
[32m|[m * [31m|[m [33m5fef6a5a[m cde: adjust error messages to changed formating
[32m|[m * [31m|[m [33m7661dc0f[m templates: fix some more infolinks
[32m|[m * [31m|[m [33m1ca6eb6f[m templates: change rst filters to md. Change rst info to md info
[32m|[m * [31m|[m [33mda008d4d[m markdown: add markdown jinja filter.
* [33m|[m [31m|[m   [33m1c100d30[m Merge branch 'fix/zxcvbn' of cdedb/cdedb2 into master
[34m|[m[35m\[m [33m\[m [31m\[m  
[34m|[m * [33m|[m [31m|[m [33mc0dc80b5[m zxcvbn: fix validation return value in case of no feedback. see #345
[34m|[m * [33m|[m [31m|[m [33mad5ab6cd[m[33m ([m[1;31morigin/fix/zxcvbn[m[33m)[m zxcvbn: Require stronger passwords for admins
* [35m|[m [33m|[m [31m|[m [33m8dec403b[m event: change expected input format of event/batch_fee. closes #338
* [35m|[m [33m|[m [31m|[m [33md083cd59[m cde: change expected input format of cde/money_transfers. see #338
* [35m|[m [33m|[m [31m|[m [33md188bde1[m event: fix link to course_choices from course_stats. closes #344
* [35m|[m [33m|[m [31m|[m [33mfc1d5860[m event: fix whitespace in hover text in course_choices template. closes #342
[35m|[m[35m/[m [33m/[m [31m/[m  
* [33m|[m [31m|[m [33mb55a1f8c[m core: Rework password logic.
* [33m|[m [31m|[m [33mf51580be[m templates: make past events on user profile shown in a table. see  #317
* [33m|[m [31m|[m [33m25e585b0[m event-frontend: Catch the attempt to delete all event parts.
* [33m|[m [31m|[m [33m045a55ec[m i18n: Revert two of the .format changes which were too eager.
* [33m|[m [31m|[m [33m90eff773[m doc: Improve documentation.
* [33m|[m [31m|[m [33mf4c2dce6[m migration: Explicitly add moderators for event mailing lists.
* [33m|[m [31m|[m [33m610ab345[m i18n: fix some format strings, use German for change_notes
* [33m|[m [31m|[m [33m3a7370f4[m i18n: fix typos
* [33m|[m [31m|[m [33m4074f351[m core: actually show the profile picture to normal users.
* [33m|[m [31m|[m [33mc0531712[m templates: Remove all str.format occurences (except for literals).
* [33m|[m [31m|[m [33m3b0f0963[m templates: Simplify pluralize constructs.
* [33m|[m [31m|[m [33mfb86ad1c[m i18n: add some missing translations and remove some unneeded translation markers
* [33m|[m [31m|[m [33me73cb2a9[m frontend: Fix missing checks for rs.errors to make CSRF protection work
* [33m|[m [31m|[m [33mdd6deabf[m frontend: Fix logout: Don't require anti CSRF token
* [33m|[m [31m|[m [33md1df24cb[m tests: Adapt tests to recent changes.
* [33m|[m [31m|[m   [33mc32bbb60[m Merge branch 'fix/field_datatype'
[36m|[m[1;31m\[m [33m\[m [31m\[m  
* [1;31m\[m [33m\[m [31m\[m   [33m16859295[m Merge branch 'feature/list_consent'
[1;32m|[m[1;33m\[m [1;31m\[m [33m\[m [31m\[m  
[1;32m|[m * [1;31m|[m [33m|[m [31m|[m [33m1217bbea[m i18n: prepare merge with master
[1;32m|[m * [1;31m|[m [33m|[m [31m|[m [33m6e1a2070[m ui/event: Make list_consent default-checked
[1;32m|[m * [1;31m|[m [33m|[m [31m|[m [33m36d151ea[m db: disallow list_consent being NULL.
[1;32m|[m * [1;31m|[m [33m|[m [31m|[m [33mbcd69066[m event: add info text about photos on registration page.
[1;32m|[m * [1;31m|[m [33m|[m [31m|[m [33m5e78d7dc[m event: remove foto consent checkboxes
[1;32m|[m * [1;31m|[m [33m|[m [31m|[m [33m1de022c1[m[33m ([m[1;31morigin/feature/list_consent[m[33m)[m translation: translate the new list_consent strings and some others.
[1;32m|[m * [1;31m|[m [33m|[m [31m|[m [33m1f89d2ae[m test: adjust test data to new list_consent field.
[1;32m|[m * [1;31m|[m [33m|[m [31m|[m [33m98c197fc[m event: introduce new list_consent field for registrations
* [1;33m|[m [1;31m|[m [33m|[m [31m|[m   [33m6d4e7168[m Merge branch 'feature/CSP'
[1;34m|[m[1;35m\[m [1;33m\[m [1;31m\[m [33m\[m [31m\[m  
[1;34m|[m * [1;33m|[m [1;31m|[m [33m|[m [31m|[m [33m03ad57e1[m frontend: Change Content-Security-Policy header to allow embedded images from anywhere
[1;34m|[m * [1;33m|[m [1;31m|[m [33m|[m [31m|[m [33m41648e9b[m frontend: Add Content-Security-Policy header
* [1;35m|[m [1;33m|[m [1;31m|[m [33m|[m [31m|[m   [33mdd6c2a8f[m Merge branch 'fix/anti_csrf'
[1;36m|[m[31m\[m [1;35m\[m [1;33m\[m [1;31m\[m [33m\[m [31m\[m  
[1;36m|[m * [1;35m|[m [1;33m|[m [1;31m|[m [33m|[m [31m|[m [33m636e0c43[m frontend: Change default logic for check_anti_csrf flag
[1;36m|[m * [1;35m|[m [1;33m|[m [1;31m|[m [33m|[m [31m|[m [33m914a36ae[m[33m ([m[1;31morigin/fix/anti_csrf[m[33m)[m frontend: Add anti CSRF token to all non-anonymous POST forms
[1;36m|[m * [1;35m|[m [1;33m|[m [1;31m|[m [33m|[m [31m|[m [33m02327d88[m test: Add test for CSRF mitigation
[1;36m|[m * [1;35m|[m [1;33m|[m [1;31m|[m [33m|[m [31m|[m [33m5c715a06[m frontend: Fix ml/oldstyle_bounce: Don't require anti CSRF token
[1;36m|[m * [1;35m|[m [1;33m|[m [1;31m|[m [33m|[m [31m|[m [33m438e52e6[m frontend: Move Anti-CSRF check to application and change behaviour
[1;36m|[m * [1;35m|[m [1;33m|[m [1;31m|[m [33m|[m [31m|[m [33m45f9bd35[m frontend: Add anti CSRF token to promote_user form
* [31m|[m [1;35m|[m [1;33m|[m [1;31m|[m [33m|[m [31m|[m [33m44606948[m auto-build: Improve fail2ban integration.
* [31m|[m [1;35m|[m [1;33m|[m [1;31m|[m [33m|[m [31m|[m [33m7b3d4645[m doc: Annotate LOCKDOWN semantics.
* [31m|[m [1;35m|[m [1;33m|[m [1;31m|[m [33m|[m [31m|[m [33m04462be7[m ui: Preselect identifying columns in user/registration query
* [31m|[m [1;35m|[m [1;33m|[m [1;31m|[m [33m|[m [31m|[m [33mc41c1582[m i18n: prepare merge of feature/list_consent
* [31m|[m [1;35m|[m [1;33m|[m [1;31m|[m [33m|[m [31m|[m [33m75321cfe[m parse: fix error output once more.
* [31m|[m [1;35m|[m [1;33m|[m [1;31m|[m [33m|[m [31m|[m [33mc710c020[m comments: Provide notes of possibilities with Debian Buster.
[31m|[m [31m|[m [1;35m|[m [1;33m|[m [1;31m|[m [33m|[m [31m|[m * [33md5a1e710[m[33m ([m[1;31morigin/fix/field_datatype[m[33m)[m event: address issues of PR#340.
[31m|[m [31m|[m [1;35m|[m [1;33m|[m [1;31m|[m [33m|[m[1;31m_[m[31m|[m[1;31m/[m  
[31m|[m [31m|[m [1;35m|[m [1;33m|[m [1;31m|[m[1;31m/[m[33m|[m [31m|[m   
[31m|[m [31m|[m [1;35m|[m [1;33m|[m * [33m|[m [31m|[m [33m94c954fd[m test: adapt tests to new FieldDatatype enum, add new test. closes #326
[31m|[m [31m|[m [1;35m|[m [1;33m|[m * [33m|[m [31m|[m [33m09caf0d5[m frontend: adapt handling of field kind to new datatype enum. see #326
[31m|[m [31m|[m [1;35m|[m [1;33m|[m * [33m|[m [31m|[m [33m8dce8c1c[m frontend: add validation for new FieldDatatype enum. see #326
[31m|[m [31m|[m [1;35m|[m [1;33m|[m * [33m|[m [31m|[m [33m0f4cba6b[m backend: change sql-scheme and backend handling to adjust to new event_field kind datatype. see #326
[31m|[m [31m|[m [1;35m|[m [1;33m|[m * [33m|[m [31m|[m [33m2cb02779[m event: create new enum with datatypes for fields and use it in templates. see #326
[31m|[m [31m|[m[31m_[m[1;35m|[m[31m_[m[1;33m|[m[31m/[m [33m/[m [31m/[m  
[31m|[m[31m/[m[31m|[m [1;35m|[m [1;33m|[m [33m|[m [31m|[m   
* [31m|[m [1;35m|[m [1;33m|[m [33m|[m [31m|[m [33m54c31eab[m test: fix tests after exception handling changes
* [31m|[m [1;35m|[m [1;33m|[m [33m|[m [31m|[m [33m66dbc0ac[m parse: adapt test to changed output
* [31m|[m [1;35m|[m [1;33m|[m [33m|[m [31m|[m [33mb8c2de27[m parse: tweak output and adjust test accordingly.
* [31m|[m [1;35m|[m [1;33m|[m [33m|[m [31m|[m [33m36506c96[m parse: compile most RegExes only once.
* [31m|[m [1;35m|[m [1;33m|[m [33m|[m [31m|[m [33m0380d1bb[m parse: make problem format consistant with rs.errors format.
* [31m|[m [1;35m|[m [1;33m|[m [33m|[m [31m|[m [33m2f70e794[m event: remove unneeded code from downloads template
* [31m|[m [1;35m|[m [1;33m|[m [33m|[m [31m|[m [33m6a11f0d5[m xss: use error messages %s formatting in error messages.
[31m|[m [31m|[m[31m_[m[1;35m|[m[31m_[m[1;33m|[m[31m_[m[33m|[m[31m/[m  
[31m|[m[31m/[m[31m|[m [1;35m|[m [1;33m|[m [33m|[m   
[31m|[m [31m|[m [1;35m|[m [1;33m|[m [33m|[m * [33mff267544[m[33m ([m[1;31morigin/fix/remove_atomizers[m[33m)[m backend/event: Remove Atomizers containing only one database operation
[31m|[m [31m|[m [1;35m|[m [1;33m|[m [33m|[m * [33m6bce43b3[m frontend/assembly: Remove Atomizer from remove_attachment()
[31m|[m [31m|[m [1;35m|[m [1;33m|[m [33m|[m * [33m93e1ff22[m backend/core: Remove Atomizer in login()
[31m|[m [31m|[m[31m_[m[1;35m|[m[31m_[m[1;33m|[m[31m_[m[33m|[m[31m/[m  
[31m|[m[31m/[m[31m|[m [1;35m|[m [1;33m|[m [33m|[m   
* [31m|[m [1;35m|[m [1;33m|[m [33m|[m [33m8774f2a9[m frontend: Make linebreaks-filter escaping-aware
* [31m|[m [1;35m|[m [1;33m|[m [33m|[m [33m07cb2ef5[m ui: Reword 'reserve lodgers' to 'camping mat users'
[33m|[m [31m|[m[33m_[m[1;35m|[m[33m_[m[1;33m|[m[33m/[m  
[33m|[m[33m/[m[31m|[m [1;35m|[m [1;33m|[m   
* [31m|[m [1;35m|[m [1;33m|[m [33m9636b5cc[m event: fix redirect of validation error in field_set.
* [31m|[m [1;35m|[m [1;33m|[m [33m6c677912[m event: prevent questionnaire from being submitted when in preview mode.
* [31m|[m [1;35m|[m [1;33m|[m [33m95daad16[m event: check for existance of CSV downloads before returning them.
* [31m|[m [1;35m|[m [1;33m|[m [33m330fdacb[m event: check for existance of compiled pdfs before returning them.
* [31m|[m [1;35m|[m [1;33m|[m [33m56780448[m frontend: check for existance of pdf before returning the file.
* [31m|[m [1;35m|[m [1;33m|[m [33m1928aed4[m frontend: use pathlig for file deletion
* [31m|[m [1;35m|[m [1;33m|[m [33mfa6cfda3[m xss: improve make rule
* [31m|[m [1;35m|[m [1;33m|[m [33m12e10a20[m xss: fix sample data to disallow script tags in protected fields
* [31m|[m [1;35m|[m [1;33m|[m [33mdab925ba[m core: make modifying a persona to no longer be a member automatically revoke lastschrift. closes #333
* [31m|[m [1;35m|[m [1;33m|[m [33m52aa8764[m ui: Unify breadcrumbs with navigation and fix missing translation
* [31m|[m [1;35m|[m [1;33m|[m [33mc17bfd79[m ui: Improve code on event/show_courses: Use Enum instead of magic value
* [31m|[m [1;35m|[m [1;33m|[m [33m6ae89a13[m ui: Remove dirty workaround for supressing whitespace compression
* [31m|[m [1;35m|[m [1;33m|[m [33mba6c50a5[m ui: Mark string literals for 'attributes' parameters as safe
* [31m|[m [1;35m|[m [1;33m|[m [33m84b8552b[m frontend: Allow selecting the --none-- option on event/manage_attendees
* [31m|[m [1;35m|[m [1;33m|[m [33m0d1db02e[m frontend: Improve code: Use nested generator expression instead of chaining
* [31m|[m [1;35m|[m [1;33m|[m [33m0fc2b2fa[m frontend: Show unassigend participants in event/manage_attendees
* [31m|[m [1;35m|[m [1;33m|[m [33mf4761205[m frontend: Only generate debugstring in DEV mode
* [31m|[m [1;35m|[m [1;33m|[m [33m8be9098f[m zxcvbn: Add proper umlaut support
[1;35m|[m [31m|[m[1;35m/[m [1;33m/[m  
[1;35m|[m[1;35m/[m[31m|[m [1;33m|[m   
* [31m|[m [1;33m|[m [33mfa789a27[m test: Improve escaping fuzzing script to find pages requiring URL parameters
* [31m|[m [1;33m|[m [33mc2e5660b[m ui: Fix escaping on event/course_choices
[31m|[m[31m/[m [1;33m/[m  
* [1;33m|[m [33mc197eff4[m frontend: Fix error handling of core/promote_user
* [1;33m|[m [33m8463806a[m backend: untranslate change_notes. Closes #329
* [1;33m|[m [33m75f11595[m i18n: Update translations.
* [1;33m|[m [33m22c7b8f2[m xss: revert gettext to return str, not markup. Add some improved handling of HTML characters
* [1;33m|[m [33m2a515682[m frontend: remove whitespace compression. closes #299
* [1;33m|[m [33m293aac1e[m xss: fix sample-data to disallow tags in data that isn't possible to be set that way.
* [1;33m|[m [33m2a50325f[m parse: fix error to allow translation.
* [1;33m|[m [33mba601209[m validation: Do not pass through validation errors but create our own.
* [1;33m|[m [33m5290716c[m validation: Use jinja-format-filter for formatting validation errors.
* [1;33m|[m [33m0d8b6b29[m event: validate the hidden parameters of field_set_select. See #255
* [1;33m|[m [33m37aee6f0[m cde: fix nonexistant redirect upon validation error in past_event. See #255
* [1;33m|[m [33mfa3bef9c[m cde/admission: fix TypeError on the gender column being empty. This now defaults to "Not Specified". See #255
* [1;33m|[m [33m349b69de[m event/questionnaire: check if registration exists before trying to unpack it
* [1;33m|[m [33m7db58762[m translation: fix typos
* [1;33m|[m [33mc9a884fa[m template: fix double escaping in lastschrift_show
* [1;33m|[m [33mafc15900[m xss: create make rules for running the xss-script and creating the test data
* [1;33m|[m [33meec8e022[m test: Improve XSS fuzzing script.
* [1;33m|[m [33mbb64af06[m migration: Add WA18/19.
* [1;33m|[m [33m796ed73f[m assembly: values['voted'] being set, does not necessarily mean a valid vote has been cast. fixes #323
* [1;33m|[m [33mb6e7819d[m event: fix tests after changing course deletion redirect
* [1;33m|[m [33m27e6d487[m event: improve courselists template. see #210
* [1;33m|[m [33m175654d7[m event: fix key generation in calculate_groups.
* [1;33m|[m [33mae2566e8[m event: fix infinite recursion on validation error in course_choices_form. closes #322
* [1;33m|[m [33m2526f6a7[m mail-templates: Plaintext emails do not need escaping.
* [1;33m|[m [33me3496649[m fix typos
* [1;33m|[m [33m7ba2d302[m Add check_escaping.py script and accompanying sample data set
* [1;33m|[m [33mb531e0c0[m event: protect changes in change_event. closes #318
* [1;33m|[m [33mbb87b4f9[m event: fix link to course_choices in show_course. closes #319
* [1;33m|[m [33m3fb0052e[m event: redirect to course_stats after deleting course. closes #320
* [1;33m|[m [33m989d4436[m translation: one more missing english string. see #321
* [1;33m|[m [33m3eba7d0c[m templates: improve past_event list of sore/show_user. see #317
* [1;33m|[m [33mbb944b6c[m template: small template fixes
* [1;33m|[m [33m181d675e[m templates: adjust design of the "Go to Search/Filter" buttons. closes #316
* [1;33m|[m [33mc6d427b4[m translation: translate Enums to English. closes #321
* [1;33m|[m [33m5dd56693[m add: declaration of datafield type in documentation
* [1;33m|[m [33m67ad4d56[m translation: minor translation fixes
* [1;33m|[m [33mda1ed49f[m event: translate lodgement problems beofre joining them together. closes #315
* [1;33m|[m [33m6b242934[m assembly: mark ' as safe when inserted into JavaScript. closes #311
* [1;33m|[m [33m44ff2dfa[m assembly: fix javascript. closes #312
[1;33m|[m[1;33m/[m  
* [33m878a98fd[m frontend: Convert jinja to use auto-escaping.
* [33mffc4c542[m zxcvbn: Add script to count German Wikipedia words
* [33m47a40794[m event: improve the participant_list template and provide an orga_only version.
* [33m5261326a[m template: adjust info text to the fact that we can do lastschriften from non-german accounts aswell
*   [33m0d505809[m Merge branch 'feature/pep8'
[34m|[m[35m\[m  
[34m|[m * [33m14d25f86[m pep8: cleanup whitespace after trailing comma before closing parenthesis
[34m|[m * [33m427687b0[m pep8: refactor general files
[34m|[m * [33ma9a95cef[m pep8: refactor frontend
[34m|[m * [33m17b19dce[m pep8: refactor database files
[34m|[m * [33meb55d018[m pep8: refactor backend to comply with pep8
* [35m|[m [33m9d158755[m core-backend: Fix archiving of personas.
[35m|[m[35m/[m  
* [33m894bc043[m core-backend: Harden doppelganger detection against resource exhaustion.
* [33m829f2dad[m event-backend: Make code resistent against non-existant entities.
* [33mc980c9ea[m frontend: Add one more tag to the allowed list of bleach.
* [33mc8c14dd4[m event-backend: Fix sanity check for cross-event access.
* [33mc1cf99b5[m sample-data: Fix Inga's changelog entry to contain her free form text.
* [33mab55942a[m translation: translate consent form. see #180. awaiting feedback.
* [33m4c79199e[m translation: translate I25+ information
* [33me735560f[m past_event: sort courses per Participant on show_past_event. closes #118
* [33ma565cacd[m common: mark notify_return_code default values for translation
* [33m77e04c03[m assembly: mark the filename field as incorrect, if the default filename is invalid. closes #172
* [33mf8107271[m migration: adaptation script for mailinglist handling done.
* [33mb50ab399[m event: fix foto consent text. closes #305
* [33made660f4[m fix typo
* [33m6e138c1d[m improve: transfere data
* [33m5e080158[m migration: Prepare script for adapting mailing lists to new DB.
* [33m521a5eeb[m migration: Tune the migration flow.
* [33ma7a6700d[m create_user: make duplicate username a validation error.
* [33m5e05e7e0[m event: add additional info text to change_event form.
* [33ma0cbd4fb[m template: use meta_info for Vorstand names in welcome mail. closes #295
* [33m4cfba5ae[m event: fix typos
* [33m7e0d4a98[m doc: update migration plan and information. This includes adding "Vorstand" to the initialization of the meta info table.
* [33mcd3dfe9f[m lastschrift: zap max_dsa parameter
* [33mdbfb5465[m log: normalize log entries to English. closes #300
* [33m91fd6fac[m translation: fix some translations.
* [33m68b92a98[m test: adjust test to changes in change_notes language.
* [33m0b6ae04e[m assembly: validate vote end date and extension date to be after vote begin and vote end. closes #185
* [33m2eaa1ab5[m frontend: add jump to bottom button to Log pages and member search form. closes #194
* [33m7a1e5a88[m cde: make change_past_event form use type date for tempus
* [33maf206899[m core/show_user: attempt to render a nicer list of past events and courses. see #232
* [33m41977025[m test: fix expectation to account for new meta_info
* [33m8fe3d823[m templates: omit the info sign on Validation errors, if no message is given. closes #283
* [33m2fafcf9c[m parse: slightly adjust sample data to account for custom escaping
* [33m70323400[m frontend: make welcome mail generation consistent again.
* [33md07c1d7f[m translation: submit change_notes untranslated into the db
* [33m1739d2c7[m cleanup: Remove stray file.
* [33m40614040[m avoid conflicts with Markus push
* [33mbb8d76a0[m add: field "Vorstand" to meta_info
* [33m498dc2e5[m migration: Some more small fixes.
* [33m3e31859c[m migrate: Remove debug output.
* [33m7371138c[m migration: Migrate lastschrift transactions.
*   [33md6efd26f[m Merge branch 'feature/zipcode_search'
[36m|[m[1;31m\[m  
[36m|[m * [33m2526e4b8[m cde: revert member_search query separator to " ", give more verbose name to mangle_query_input parameter
[36m|[m * [33m70e4f10f[m query+cde: revert functionality change to mangle_query_input, instead make use of default parameter.
[36m|[m * [33m231fb22f[m test: add test for the zipcode search
[36m|[m * [33md002cdfa[m query: make zipcode default membersearch operator between, allow mangle_query_input to take additional dict.
[36m|[m * [33mbd6ba5be[m query: allow comparison operators for strings
[36m|[m * [33m8b78fb08[m template: show error description for unknown errors
* [1;31m|[m   [33m41ce62b6[m Merge branch 'feature/zxcvbn'
[1;32m|[m[1;33m\[m [1;31m\[m  
[1;32m|[m * [1;31m|[m [33m9b3c9ba3[m core-frontend: Use actually available information for password hints.
[1;32m|[m * [1;31m|[m [33mf97ae2ac[m test: Fix typo.
[1;32m|[m * [1;31m|[m [33m72e7a6b8[m[33m ([m[1;31morigin/feature/zxcvbn[m[33m)[m core: Incorporate feedback
[1;32m|[m * [1;31m|[m [33mcc42b323[m securtiy: Pass shorter user_inputs to zxcvbn
[1;32m|[m * [1;31m|[m [33m21654b6c[m security: Check password for common German words with zxcvbn
[1;32m|[m * [1;31m|[m [33m9fa77028[m security: Add word counts from German Wikipedia
[1;32m|[m * [1;31m|[m [33m04d04bcd[m core: Add mock German dictionary for zxcvbn
[1;32m|[m * [1;31m|[m [33mdc7852a9[m templates: Adjust password template texts to zxcvbn
[1;32m|[m * [1;31m|[m [33m25cb1623[m test: Add zxcvbn test for test_reset_password
[1;32m|[m * [1;31m|[m [33me99a54ff[m test: fix usage of assertPresence for notification
[1;32m|[m * [1;31m|[m [33m75485fea[m test: Provide basic test for zxcvbn in change_password
[1;32m|[m * [1;31m|[m [33m7ea31306[m core: Adjust password change/reset logic
[1;32m|[m * [1;31m|[m [33m1ad07a3b[m auto-build: Pull in zxcvbn via apt
[1;32m|[m * [1;31m|[m [33m5f421172[m translation: add zxcvbn feedback to i18n-additional.py for translation.
[1;32m|[m * [1;31m|[m [33m579fc152[m core: Replace password strength logic with basic zxcvbn
[1;32m|[m * [1;31m|[m [33me70001b0[m templates: somewhat fix utils.href if readonly is True
* [1;33m|[m [1;31m|[m [33mc3d04499[m frontend: Fix path to be more RESTy.
* [1;33m|[m [1;31m|[m [33md21a7733[m parse: use custom escape function to remove all re special characters from names
* [1;33m|[m [1;31m|[m [33m30a8fda6[m parse: slightly adjust output to be more consistent
* [1;33m|[m [1;31m|[m [33mbb92966d[m welcome: make reset link in welcome mail use EMAIL_PARAMETER_TIMEOUT
* [1;33m|[m [1;31m|[m [33m089786fa[m parse: remove some hardcoded values, add clarification comment on dirty template hack
* [1;33m|[m [1;31m|[m [33mff29d969[m mail: Revert indentation of mail text.
* [1;33m|[m [1;31m|[m [33mbc5d2a7b[m core-frontend: Fix call to get_persona.
* [1;33m|[m [1;31m|[m [33m2e6cb461[m parse: add try except block around apparently problematic regEx searches.
* [1;33m|[m [1;31m|[m [33mf267f167[m parse: do some dirty hacking to ensure whitespace in parsed data is preserved.
* [1;33m|[m [1;31m|[m [33m6170b3e7[m parse: improve output for debugging purposes
* [1;33m|[m [1;31m|[m [33mafdf90c8[m parse: fix pattern generation for events not matching any of the given replacements
* [1;33m|[m [1;31m|[m [33m22dbf67c[m auto-build: Clean up work directory.
* [1;33m|[m [1;31m|[m [33m418dc58b[m translation: translate some more strings, fix a few translations
* [1;33m|[m [1;31m|[m   [33m889acc15[m Merge branch 'feature/parse_statement'
[1;34m|[m[1;35m\[m [1;33m\[m [1;31m\[m  
[1;34m|[m * [1;33m|[m [1;31m|[m [33meaa27556[m parse: adjust sample data and tests, add tests for other_transactions
[1;34m|[m * [1;33m|[m [1;31m|[m [33m2206a4e9[m parse: perform re.escape on names before performing search
[1;34m|[m * [1;33m|[m [1;31m|[m [33m3612771d[m parse: move csv field definitions into parse_statement.py
[1;34m|[m * [1;33m|[m [1;31m|[m [33mbc00aaed[m parse: improve test_parse_statement_additional and adjust test_parse_statement to new output
[1;34m|[m * [1;33m|[m [1;31m|[m [33m00852d75[m parse: make invalid input line a validation error.
[1;34m|[m * [1;33m|[m [1;31m|[m [33m51366edd[m parse: deduplicate output generation. improve helper classes Member and Event.
[1;34m|[m * [1;33m|[m [1;31m|[m [33m8d65b405[m parse: enhance template formatting
[1;34m|[m * [1;33m|[m [1;31m|[m [33m948d94ad[m[33m ([m[1;31morigin/feature/parse_statement[m[33m)[m cde-frontend: Remove redundant validation.
[1;34m|[m * [1;33m|[m [1;31m|[m [33mdb0809f3[m parse: adress Issues of PR #281.
[1;34m|[m * [1;33m|[m [1;31m|[m [33mbc9405e5[m cde-frontend: Fix minor issues like typos.
[1;34m|[m * [1;33m|[m [1;31m|[m [33m73f3031b[m frontend: Make the diacritic_patterns function more understandable.
[1;34m|[m * [1;33m|[m [1;31m|[m [33mb0b17d95[m parse: prepare merge with master
[1;34m|[m * [1;33m|[m [1;31m|[m [33mb171ed5e[m parse: fix test, reverse test-data to match reversed reading of statement
[1;34m|[m * [1;33m|[m [1;31m|[m [33md2ec06e1[m cde: enhance parse output files, check for account existance in money_transfers
[1;34m|[m * [1;33m|[m [1;31m|[m [33m32942ff4[m event/batch_fees: check for existance of Account
[1;34m|[m * [1;33m|[m [1;31m|[m [33me85e03d1[m parse: fix detection of External registrations (although this will be redundant soon).
[1;34m|[m * [1;33m|[m [1;31m|[m [33m71ff0dd1[m parse: add additional doc, remove old_db support, fix test.
[1;34m|[m * [1;33m|[m [1;31m|[m [33mb4ba659d[m parse: make parse_statement read event names from db.
[1;34m|[m * [1;33m|[m [1;31m|[m [33mc34088cd[m parse: translate to German
[1;34m|[m * [1;33m|[m [1;31m|[m [33m3e393b34[m parse: add new test for parse_statement functionality
[1;34m|[m * [1;33m|[m [1;31m|[m [33me12e0fce[m parse: make some template improvements
[1;34m|[m * [1;33m|[m [1;31m|[m [33me75b8865[m parse: move all parse code to external file.
[1;34m|[m * [1;33m|[m [1;31m|[m [33m2b40eaa5[m parse: do some major cleanup. Move enums to cdedb.constants.py, remove Confidence class.
[1;34m|[m * [1;33m|[m [1;31m|[m [33md2be49e9[m parse: move Transaction method calls out of init
[1;34m|[m * [1;33m|[m [1;31m|[m [33m42a5251f[m parse: make the download happen via forms passing csv_output produced data so send_file
[1;34m|[m * [1;33m|[m [1;31m|[m [33m9f24bf9d[m parse: change output generation to use csv.DictWriter, adjust template
[1;34m|[m * [1;33m|[m [1;31m|[m [33mc1d2c7fd[m cde: add new parse functionality
[1;34m|[m * [1;33m|[m [1;31m|[m [33m9682a099[m translation: fix missing title translation
[1;34m|[m * [1;33m|[m [1;31m|[m [33m8cc6711b[m common: add two-way-replacement option to diacritic_patterns
[1;34m|[m * [1;33m|[m [1;31m|[m [33m60354f87[m cde: new template for parsing bank statements
* [1;35m|[m [1;33m|[m [1;31m|[m [33m13a54485[m doc: Clarify migration document.
* [1;35m|[m [1;33m|[m [1;31m|[m [33m1552ce55[m auto-build: Fix stage1 build issues.
* [1;35m|[m [1;33m|[m [1;31m|[m [33m31c21a90[m core: fix typo in log validation
* [1;35m|[m [1;33m|[m [1;31m|[m [33mcb78a339[m template: display rs.errors dict in debugstring
[1;31m|[m [1;35m|[m[1;31m_[m[1;33m|[m[1;31m/[m  
[1;31m|[m[1;31m/[m[1;35m|[m [1;33m|[m   
* [1;35m|[m [1;33m|[m [33m1020337d[m test: test for reset link in welcome mail.
* [1;35m|[m [1;33m|[m [33macf0ae92[m create_user: send password reset link to user on account creation. closes #35.
* [1;35m|[m [1;33m|[m [33mf4542520[m doc: fix typos
* [1;35m|[m [1;33m|[m [33md99e22ce[m log: disallow negative start and stop. Closes #221.
* [1;35m|[m [1;33m|[m [33mc6cf991d[m auto-build: Update preseed.cfg from template for Buster.
* [1;35m|[m [1;33m|[m [33m794dc769[m auto-build: Update to Buster alpha5.
* [1;35m|[m [1;33m|[m [33mc2e49e51[m auto-build: Use Debian archives for all packages.
* [1;35m|[m [1;33m|[m [33m5313f72a[m doc: Change guzzle project name zu CdEDBv2
* [1;35m|[m [1;33m|[m [33m29e47d7b[m frontend: Fix error handling and add error messages
* [1;35m|[m [1;33m|[m [33m017b4813[m ui/event: Fix navigation: batch_fees_form is not available for locked events
* [1;35m|[m [1;33m|[m [33m344a4cd1[m ui: Fix util.href's readonly functionality
* [1;35m|[m [1;33m|[m   [33m6028a7a0[m Merge branch 'fix/remove_consent_redirect'
[1;33m|[m[31m\[m [1;35m\[m [1;33m\[m  
[1;33m|[m [31m|[m[1;33m_[m[1;35m|[m[1;33m/[m  
[1;33m|[m[1;33m/[m[31m|[m [1;35m|[m   
[1;33m|[m * [1;35m|[m [33md7de08c9[m core-backend: Better doc-string.
[1;33m|[m * [1;35m|[m [33m48a7c52d[m fix
[1;33m|[m * [1;35m|[m [33maf14758e[m fix
[1;33m|[m * [1;35m|[m [33m06500d88[m fix
[1;33m|[m * [1;35m|[m [33m7a465628[m fix
[1;33m|[m * [1;35m|[m [33mf879c1ad[m fix
[1;33m|[m * [1;35m|[m [33m17597db1[m core: Escalate DB connection on successful login.
[1;33m|[m * [1;35m|[m [33mfd20b4d6[m[33m ([m[1;31morigin/fix/remove_consent_redirect[m[33m)[m WIP: backend: Enhance CoreBackend.login() to retreive user information
[1;33m|[m * [1;35m|[m [33m33adee15[m backend/session: Refactor lookupsession() to return a User object
[1;33m|[m * [1;35m|[m [33m50b337e6[m frontend: Remove unrequired redirect and 'stay' parameter from cde/consent_decision_form
[1;33m|[m * [1;35m|[m [33m06ff3590[m ui: Fix cde/consent_decision template for case of searchable user
[1;33m|[m * [1;35m|[m [33mfe0e60e2[m frontend: Only redirect to cde/consent_decision after login if neccessary
* [31m|[m [1;35m|[m [33m01bd08cd[m event: translate download labels
* [31m|[m [1;35m|[m [33m529d7b51[m event: protect fields used as 'lodge_field' or 'reserve_field' from deletion.
* [31m|[m [1;35m|[m   [33mfcfe429f[m Merge branch 'test/performance' of dimitri/cdedb2 into master
[32m|[m[33m\[m [31m\[m [1;35m\[m  
[32m|[m * [31m|[m [1;35m|[m [33me83b49ef[m load testing: Respect chromedriver path
[32m|[m * [31m|[m [1;35m|[m [33mbbb07e5e[m * load testing: Remove some unsafe print()s
[32m|[m * [31m|[m [1;35m|[m [33m5448206d[m * load testing: Slight improvement
[32m|[m * [31m|[m [1;35m|[m [33mc77938b9[m * load testing: Write performance testing code
[32m|[m * [31m|[m [1;35m|[m [33m884bdaa7[m * load testing: Debug (in parts) and modularize DB model creation.
[32m|[m * [31m|[m [1;35m|[m [33m7d6ca4ff[m load testing: More work on a DB model.
[32m|[m * [31m|[m [1;35m|[m [33mdb679d04[m load testing: Start working on a DB model.
[32m|[m * [31m|[m [1;35m|[m [33me166cbd1[m load testing: Finalize automated registration.
[32m|[m * [31m|[m [1;35m|[m [33m60ee8d27[m load testing: Add automated registration script.
* [33m|[m [31m|[m [1;35m|[m   [33m4d71952a[m Merge branch 'sphinxtheme' of cdedb/cdedb2 into master
[34m|[m[35m\[m [33m\[m [31m\[m [1;35m\[m  
[34m|[m * [33m|[m [31m|[m [1;35m|[m [33m40823e22[m auto-build: Automatically install theme for docs.
[34m|[m * [33m|[m [31m|[m [1;35m|[m [33md5eb402c[m change Sphinx theme from classic to guzzle
* [35m|[m [33m|[m [31m|[m [1;35m|[m [33m145f4ba9[m core-backend: Wrap db connection manipulation to guarantee deescalation.
* [35m|[m [33m|[m [31m|[m [1;35m|[m [33m8fddb6b6[m infra: remove obsolete symlink.
[1;35m|[m [35m|[m[1;35m_[m[33m|[m[1;35m_[m[31m|[m[1;35m/[m  
[1;35m|[m[1;35m/[m[35m|[m [33m|[m [31m|[m   
* [35m|[m [33m|[m [31m|[m [33m236a403b[m templates: show rs.values instead of rs.request.values in footer.
* [35m|[m [33m|[m [31m|[m [33m9d0486b3[m event: redirect to registration overview after deleting a registration. see #269
* [35m|[m [33m|[m [31m|[m [33m7cf7c25c[m templates: Remove even more debug output.
[35m|[m[35m/[m [33m/[m [31m/[m  
* [33m|[m [31m|[m [33m140a6886[m translation: make use of get_locale
* [33m|[m [31m|[m [33md07cb09c[m database: remove some unneeded unique keys. closes #273
* [33m|[m [31m|[m [33md11bd3e2[m templates: Remove debug output.
* [33m|[m [31m|[m [33mc9baf883[m templates: Add one more link to reST help
* [33m|[m [31m|[m   [33m4c357cb0[m Merge branch 'feature/translation-event'
[36m|[m[1;31m\[m [33m\[m [31m\[m  
[36m|[m * [33m|[m [31m|[m [33mb6dadebf[m translation: prepare merge with master
[36m|[m * [33m|[m [31m|[m [33m8c166dfa[m translation: adapt tests to translation changes
[36m|[m * [33m|[m [31m|[m [33m961a3ba9[m translation: add retranslations
[36m|[m * [33m|[m [31m|[m [33m6dd669e2[m translation: fix some inconsistencies
[36m|[m * [33m|[m [31m|[m [33m700ebdbc[m translation: translate event templates
* [1;31m|[m [33m|[m [31m|[m   [33m9c8dacf3[m Merge branch 'feature/rest_bleach'
[1;32m|[m[1;33m\[m [1;31m\[m [33m\[m [31m\[m  
[1;32m|[m * [1;31m|[m [33m|[m [31m|[m [33m383d095a[m fix: Forgot to save. :/
[1;32m|[m * [1;31m|[m [33m|[m [31m|[m [33m87b5b2ba[m frontend: Memoize the bleach cleaner.
[1;32m|[m * [1;31m|[m [33m|[m [31m|[m [33mf57090c9[m[33m ([m[1;31morigin/feature/rest_bleach[m[33m, [m[1;31morigin/feature/rest+bleach[m[33m)[m frontend: Add sanitization with bleach.
[1;32m|[m * [1;31m|[m [33m|[m [31m|[m [33m56f38bb3[m frontend: Add help for reStructuredText.
* [1;33m|[m [1;31m|[m [33m|[m [31m|[m [33m5bff896d[m translation: prepare merge of feature/translation-event
* [1;33m|[m [1;31m|[m [33m|[m [31m|[m [33md6981083[m ui: Fix double-HTML-escaping on core/promote_user
* [1;33m|[m [1;31m|[m [33m|[m [31m|[m [33mfef0bcbd[m ui: Minor template improvements
* [1;33m|[m [1;31m|[m [33m|[m [31m|[m [33ma96e058e[m ui: Restructure and document utils.tmpl
* [1;33m|[m [1;31m|[m [33m|[m [31m|[m [33m04d4940e[m migration: Fix script to work nice with wacked data.
* [1;33m|[m [1;31m|[m [33m|[m [31m|[m   [33mb8625c53[m Merge branch 'feature/event_part_shortname' of cdedb/cdedb2 into master
[31m|[m[1;35m\[m [1;33m\[m [1;31m\[m [33m\[m [31m\[m  
[31m|[m [1;35m|[m[31m_[m[1;33m|[m[31m_[m[1;31m|[m[31m_[m[33m|[m[31m/[m  
[31m|[m[31m/[m[1;35m|[m [1;33m|[m [1;31m|[m [33m|[m   
[31m|[m * [1;33m|[m [1;31m|[m [33m|[m [33m3675cb62[m test: Fix test data.
[31m|[m * [1;33m|[m [1;31m|[m [33m|[m [33m99c4d4db[m test: Fix/adapt tests for new event_parts.shortname column
[31m|[m * [1;33m|[m [1;31m|[m [33m|[m [33m44a56c5f[m event: Add event_parts.shortname column
* [1;35m|[m [1;33m|[m [1;31m|[m [33m|[m [33mb1941df1[m frontend: Restrict removing orgas/ml-moderators to deny removing oneself
* [1;35m|[m [1;33m|[m [1;31m|[m [33m|[m [33m0f8fff56[m frontend/event: Add 403 errors to get_minor_form() and questionnaire_form()
* [1;35m|[m [1;33m|[m [1;31m|[m [33m|[m [33mcb583242[m ui/event: Remove the Questionaire Preview button from the sidebar
[1;35m|[m[1;35m/[m [1;33m/[m [1;31m/[m [33m/[m  
* [1;33m|[m [1;31m|[m [33m|[m [33mc6bdd6a5[m application: Fix error page to look same on Werkzeug 0.11 and 0.14
* [1;33m|[m [1;31m|[m [33m|[m [33m0534a84e[m test: Fix frontend tests, broken by 'secure' flag of sessionkey cookie
* [1;33m|[m [1;31m|[m [33m|[m [33mcbb51917[m translation: fix missing translation wrappers
* [1;33m|[m [1;31m|[m [33m|[m [33m79dfaf3c[m migrate: Fix past event data.
* [1;33m|[m [1;31m|[m [33m|[m [33m6e120c47[m ui: Change button label/placeholder on event/show_event to fix layout
* [1;33m|[m [1;31m|[m [33m|[m [33m5979a360[m doc: document the usage of podiff and pomerge scripts and how to disable them. Closes #222
* [1;33m|[m [1;31m|[m [33m|[m [33mb1af33cb[m event: make questionnaire preview use the same template as questionnaire. #274
* [1;33m|[m [1;31m|[m [33m|[m [33m47de8149[m event: add qustionnaire preview page. Closes #274
* [1;33m|[m [1;31m|[m [33m|[m [33m26035b50[m ui: Enlarge logo canvas size to make place for wider fonts
* [1;33m|[m [1;31m|[m [33m|[m [33m8f398bc8[m frontend: Protect session cookie with httponly and secure
* [1;33m|[m [1;31m|[m [33m|[m [33m134c4c5e[m fix: exclude strings in stringIn.
* [1;33m|[m [1;31m|[m [33m|[m [33m16facc23[m frontend: Fix MultiDict usage.
* [1;33m|[m [1;31m|[m [33m|[m [33m471a509e[m event-frontend: DRY, we only need to state the extraction once.
* [1;33m|[m [1;31m|[m [33m|[m [33m3384f3fa[m common: change string_in_filter to work with iterables of iterables. Closes #244
* [1;33m|[m [1;31m|[m [33m|[m [33medc2bbaf[m ml: add test for registration_stati changes. See issue #244
* [1;33m|[m [1;31m|[m [33m|[m [33m85ce1b62[m ml: Add interface for oldstyle mailing list software.
* [1;33m|[m [1;31m|[m [33m|[m [33m2dbc2c3a[m assembly: make use of ASSEMBLY_BAR_MONIKER. see #204
* [1;33m|[m [1;31m|[m [33m|[m [33m37ef9fc9[m translation: add some missing translations and fix minor issues. Closes #226
* [1;33m|[m [1;31m|[m [33m|[m [33m7f7d976d[m assembly: disallow _bar_ as moniker for candidates. Closes #204
* [1;33m|[m [1;31m|[m [33m|[m [33mc68a4616[m core: show DB-ID to anyone. Closes #262
* [1;33m|[m [1;31m|[m [33m|[m [33m6b028f66[m event: enforce unique course choices when manually adding or changing registrations.
[1;31m|[m [1;33m|[m[1;31m/[m [33m/[m  
[1;31m|[m[1;31m/[m[1;33m|[m [33m|[m   
* [1;33m|[m [33m|[m   [33m1e8ffd8d[m Merge branch 'feature/translation-ml' of cdedb/cdedb2 into master
[1;36m|[m[31m\[m [1;33m\[m [33m\[m  
[1;36m|[m * [1;33m|[m [33m|[m [33m8b589b65[m translation: adjust test to slightly changed titles
[1;36m|[m * [1;33m|[m [33m|[m [33m61c80a71[m ml: adjust calculation of when to show a link to an event.
[1;36m|[m * [1;33m|[m [33m|[m [33mccb521e9[m translation: add retranslations for ml templates
[1;36m|[m * [1;33m|[m [33m|[m [33mc8aad681[m translation: add missing wrapper in assembly log
[1;36m|[m * [1;33m|[m [33m|[m [33m45267355[m translation: translate ml templates
[1;36m|[m[1;36m/[m [1;33m/[m [33m/[m  
* [1;33m|[m [33m|[m   [33m9ca54273[m Merge branch 'feature/translation-core'
[32m|[m[33m\[m [1;33m\[m [33m\[m  
[32m|[m * [1;33m|[m [33m|[m [33mc04149df[m config: Do not change the config on this branch.
[32m|[m * [1;33m|[m [33m|[m [33m01de5686[m translation: manually merge po-files from this branch and master
[32m|[m * [1;33m|[m [33m|[m [33mef64d90c[m translation: prepare for merge with master
[32m|[m * [1;33m|[m [33m|[m [33mdc934686[m[33m ([m[1;31morigin/feature/translation-core[m[33m)[m translation: fix one more test
[32m|[m * [1;33m|[m [33m|[m [33m3929ca9b[m translation: fix the pluralization fix
[32m|[m * [1;33m|[m [33m|[m [33m3b8c8679[m translation: fix tests and missing translation wrappers
[32m|[m * [1;33m|[m [33m|[m [33m11f92023[m translation: fix missing escape on pluralization
[32m|[m * [1;33m|[m [33m|[m [33m653521d9[m translation: fix bug causing 'adminshowuserform' to not work correctly
[32m|[m * [1;33m|[m [33m|[m [33mc8f91da4[m translation: untranslate "CdE-Datenbank"
[32m|[m * [1;33m|[m [33m|[m [33m6894f0e9[m i18n: translate label in cdedb_historycollapse.js
[32m|[m * [1;33m|[m [33m|[m [33md53cb219[m translation: translate CoreLogCodes and MemberChangeStati
[32m|[m * [1;33m|[m [33m|[m [33m6bf4c974[m translation: fix small errors
[32m|[m * [1;33m|[m [33m|[m [33mdd273fbb[m translation: fix most test, fix some typos
[32m|[m * [1;33m|[m [33m|[m [33m082c9ca4[m translation: add strings to translation, that aren't explicitly marked
[32m|[m * [1;33m|[m [33m|[m [33mbff87683[m translation: translate core templates
[32m|[m * [1;33m|[m [33m|[m [33m4f27e73c[m frontend: fix email adress on error page
[32m|[m * [1;33m|[m [33m|[m [33m598cce91[m config: make this branch a dev environment
* [33m|[m [1;33m|[m [33m|[m [33m1f03aec5[m translation: prepare merge of feature/translation-core
* [33m|[m [1;33m|[m [33m|[m [33m00212ae2[m autobuild: Adapt patch to new debian.
* [33m|[m [1;33m|[m [33m|[m [33m87617e01[m migration: Fix up remaining course mappings by providing explicit hints.
* [33m|[m [1;33m|[m [33m|[m [33mab50cf25[m tests: Adapt tests to changed core semantics.
* [33m|[m [1;33m|[m [33m|[m [33ma235ad70[m core: Make more changes require review.
* [33m|[m [1;33m|[m [33m|[m [33m3d9d416a[m event: Fix rate limiting.
* [33m|[m [1;33m|[m [33m|[m [33m4249260c[m ldap: Remove ldap support.
* [33m|[m [1;33m|[m [33m|[m [33mc04ec205[m event: Add rate limiting for orgas adding persons.
[1;33m|[m [33m|[m[1;33m/[m [33m/[m  
[1;33m|[m[1;33m/[m[33m|[m [33m|[m   
* [33m|[m [33m|[m [33mc12be4bb[m migration: Migrate course descriptions.
* [33m|[m [33m|[m [33m74fb7c9d[m doc: Add more detail to the migration plan.
* [33m|[m [33m|[m [33ma7616bbf[m templates: Consistently do not escape the values/defaultvalues of form macros.
* [33m|[m [33m|[m [33ma239cf34[m event: indicate possible differing fees in registration email
* [33m|[m [33m|[m [33m7a0447a6[m test: fix test broken by paths changes
* [33m|[m [33m|[m [33m8fa9dae4[m cde: Invert logic for minor detection in lastschrift form.
* [33m|[m [33m|[m   [33m7fc6d24a[m Merge branch 'feature/I25p'
[33m|[m[35m\[m [33m\[m [33m\[m  
[33m|[m [35m|[m[33m_[m[33m|[m[33m/[m  
[33m|[m[33m/[m[35m|[m [33m|[m   
[33m|[m * [33m|[m [33m7b56abd0[m cde: Small cleanups.
[33m|[m * [33m|[m [33mde919318[m lastschrift: remove max_dsa from form as it is defunct. remove unneeded escapefilter.
[33m|[m * [33m|[m [33ma33ac0b6[m lastsschrift: add Disclaimer about German/English version of the form
[33m|[m * [33m|[m [33m184165d3[m lastschrift: address some more #259 issues
[33m|[m * [33m|[m [33m6a55d098[m lastschrift: fix some more untranslated strings
[33m|[m * [33m|[m [33m9ba63605[m lastschrift: add/adjust tests for subscription form
[33m|[m * [33m|[m [33mc3ab3047[m lastschrift: change some labels and translate them. Fix TeX Unicode bug.
[33m|[m * [33m|[m [33m991de569[m lastschrift: fix typo in i25p index and incorrect breadcumb link.
[33m|[m * [33m|[m [33mdcb7cf0c[m lastschrift: address the issues discussed in #259
[33m|[m * [33m|[m [33me95de60c[m lastschrift: update the info texts for I25+
[33m|[m * [33m|[m [33m26729a74[m cde/lastschrift: add Form to configure direct debit authorization pdf.
* [35m|[m [33m|[m [33m5677d2b8[m cde/lastschrift: fix attribute not allowing max_dsa between 0 and 1. Also fix incorrectly translated label.
[35m|[m[35m/[m [33m/[m  
* [33m|[m [33me5192573[m event/batchfees: prevent uncaught exception when entering negative amounts
* [33m|[m [33m31317808[m sql: Make SQL backwards compatible with postgres 9.6.
* [33m|[m [33m07725843[m translation: fix minor issue
* [33m|[m [33me800f753[m backend/event: fix returned tracks in get_events. Should close #251
* [33m|[m   [33m26f5c0bb[m Merge branch 'master' of ssh://tracker.cde-ev.de:20009/cdedb/cdedb2
[36m|[m[1;31m\[m [33m\[m  
[36m|[m * [33m|[m [33m2262f1a5[m auto-build: Empty commit to force auto-build.
[36m|[m * [33m|[m [33m9f4370e2[m fix: None happens to be a possible parameter here.
[36m|[m * [33m|[m [33mb97bed9c[m tests: Adapt to Buster.
[36m|[m * [33m|[m [33me54b5897[m auto-build: rebase to Debian 10 Buster
* [1;31m|[m [33m|[m [33md59d0cb8[m event: change order of course shortname and title upon creation or modification
* [1;31m|[m [33m|[m [33mb365cca2[m doc: improve Veranstaltungsleitfaden
[1;31m|[m[1;31m/[m [33m/[m  
* [33m|[m [33mf6923836[m ml: make moderators able to view ml_log. closes #247
* [33m|[m [33mf401246c[m cde: add stay option to privacy policy link, fix missingtranslation wrapper
* [33m|[m [33m71a07f69[m ml: fix wrong Enum to be given as options for AttachmentPolicy
* [33m|[m [33m95341139[m translation: fix missing translation wrapper
* [33m|[m [33mc0110db8[m doc:event: rewrite into consitent salutation
* [33m|[m [33m3187fb33[m event: correct some Mistakes in Veranstaltungsleitfaden angefangen, inhaltliche und Form-fehler zu korrigieren
* [33m|[m [33m7dfbc591[m translation: Fix German translation
[1;31m|[m [33m|[m * [33m5da20ec3[m[33m ([m[1;33mtag: archive/deploy/beta[m[33m, [m[1;31morigin/deploy/beta[m[33m)[m ldap: Disable ldap interaction.
[1;31m|[m [33m|[m[1;31m/[m  
[1;31m|[m[1;31m/[m[33m|[m   
* [33m|[m [33m85631d21[m cdedb: Revert ID checksum to old format.
* [33m|[m [33m6f34efee[m zw Anmeldeeröffnung und -schluss fertig,
* [33m|[m [33mdb4ac8a0[m fertigstellung vor der anmeldeeröffnung
* [33m|[m   [33mbadc32c3[m Merge branch 'fix/show_user'
[1;33m|[m[1;34m\[m [33m\[m  
[1;33m|[m * [33m|[m [33m4a893b21[m cdedb: Adapt links to profile pages to new regimen.
[1;33m|[m * [33m|[m [33m99a14cbe[m core: Revamp show_user w.r.t. displayed data.
* [1;34m|[m [33m|[m [33m4623f981[m event: Revert full export format back to trivial reflection of database structure.
* [1;34m|[m [33m|[m [33m264fbfe5[m auto-build: Automatically add po-git-handler scripts.
[1;34m|[m[1;34m/[m [33m/[m  
* [33m|[m [33m40d25bc6[m migration: Add better defaults for tempus of imported past events.
* [33m|[m   [33m38b11ee6[m Merge branch 'fix/query_course_instructors' of cdedb/cdedb2 into master
[1;35m|[m[1;36m\[m [33m\[m  
[1;35m|[m * [33m|[m [33m1d20e281[m event-backend: Update registration query sample.
[1;35m|[m * [33m|[m [33m10826a75[m frontend/event: Fix registration_query links on event/stats
[1;35m|[m * [33m|[m [33m43bb3bdd[m Add calculated is_course_instructor column to registration query
* [1;36m|[m [33m|[m   [33mdbb83bda[m Merge branch 'fix/unify_error_handling'
[31m|[m[32m\[m [1;36m\[m [33m\[m  
[31m|[m * [1;36m|[m [33m|[m [33m6f7e60fe[m errors: Final touches to error handling.
[31m|[m * [1;36m|[m [33m|[m [33m06d23201[m[33m ([m[1;31morigin/fix/unify_error_handling[m[33m)[m test: Fix error handling tests
[31m|[m * [1;36m|[m [33m|[m [33m2bb2823b[m frontend: Fix error.tmpl
[31m|[m * [1;36m|[m [33m|[m [33m4d12cc42[m frontend: Improve error displaying of 405 and 500 errors
[31m|[m * [1;36m|[m [33m|[m [33m2e760b5f[m frontend: Implement fallback if error page fails to render
[31m|[m * [1;36m|[m [33m|[m [33m35c34d45[m frontend: Fix error message on frontend access violation
[31m|[m * [1;36m|[m [33m|[m [33m0bd1077d[m frontend: Fix Werkzeug routing redirects (e.g. to add slashes to URL)
[31m|[m * [1;36m|[m [33m|[m [33mfd7e542e[m frontend: Unify error handling via Application.make_error_page()
* [32m|[m [1;36m|[m [33m|[m [33md6004572[m tests: Adapt to latest fixed sample data.
* [32m|[m [1;36m|[m [33m|[m [33m8e53a932[m errors: Final touches to error handling.
* [32m|[m [1;36m|[m [33m|[m [33m99481083[m test: Fix error handling tests
* [32m|[m [1;36m|[m [33m|[m [33mf2f93514[m frontend: Fix error.tmpl
* [32m|[m [1;36m|[m [33m|[m [33m4780eda2[m frontend: Improve error displaying of 405 and 500 errors
* [32m|[m [1;36m|[m [33m|[m [33mf1c8c4a1[m frontend: Implement fallback if error page fails to render
* [32m|[m [1;36m|[m [33m|[m [33ma0b9f3e8[m frontend: Fix error message on frontend access violation
* [32m|[m [1;36m|[m [33m|[m [33me5304ad9[m frontend: Fix Werkzeug routing redirects (e.g. to add slashes to URL)
* [32m|[m [1;36m|[m [33m|[m [33m35824568[m frontend: Unify error handling via Application.make_error_page()
* [32m|[m [1;36m|[m [33m|[m [33m53a19697[m migration: Improve assembly migration.
* [32m|[m [1;36m|[m [33m|[m [33mb2d16c38[m Fix sample data (again)
[1;36m|[m [32m|[m[1;36m/[m [33m/[m  
[1;36m|[m[1;36m/[m[32m|[m [33m|[m   
* [32m|[m [33m|[m [33m16965c32[m event: Implement past events as past (event parts).
[32m|[m[32m/[m [33m/[m  
* [33m|[m [33m58864aaf[m ui: Improve validation error presentation
* [33m|[m   [33mb8926deb[m Merge branch 'feature/improve_personaselect_privacy'
[33m|[m[34m\[m [33m\[m  
[33m|[m * [33m|[m [33m9ffbd69a[m frontend/core: Fix docstring of select_persona
[33m|[m * [33m|[m [33m1640f5b8[m[33m ([m[1;31morigin/feature/improve_personaselect_privacy[m[33m)[m frontend/core: Show email in select_persona if searched for it
[33m|[m * [33m|[m [33m26bce6e3[m test: Fix tests for changed select_persona API
[33m|[m * [33m|[m [33m719f2f1c[m frontend/core: Restrict select_persona results for non-core-admins
[33m|[m * [33m|[m [33mfe88a854[m frontend/core: Only show email via search_persona if allowed or required
[33m|[m * [33m|[m [33m832df468[m frontend/core: Remove select_persona's sphere parameter
[33m|[m * [33m|[m [33m98aea32c[m frontend: Add documentation to core/select_persona
* [34m|[m [33m|[m [33m464c9af6[m vor anmeldebeginn abgeschlossen, datenfelder hinzugefügt
* [34m|[m [33m|[m [33m27ad66f4[m auto-build: Add Redirect from / to /db/ to Apache's config
[33m|[m [34m|[m[33m/[m  
[33m|[m[33m/[m[34m|[m   
* [34m|[m [33mdf3bb2d2[m frontend: fix debug_email bug causing the link to not work.
* [34m|[m   [33m742faa29[m Merge branch 'master' of ssh://tracker.cde-ev.de:20009/cdedb/cdedb2
[35m|[m[36m\[m [34m\[m  
[35m|[m * [34m|[m [33m81fce962[m Make sample data valid
* [36m|[m [34m|[m [33m630f35e6[m frontend/cde/lastschrift: Use Money filter when displaying lastschrift amount
[36m|[m[36m/[m [34m/[m  
* [34m|[m [33m3335e67a[m i18n: Fix merge fubar.
* [34m|[m   [33m0a9d2146[m Merge branch 'feature/translation-cde'
[34m|[m[1;32m\[m [34m\[m  
[34m|[m [1;32m|[m[34m/[m  
[34m|[m[34m/[m[1;32m|[m   
[34m|[m * [33m751d40b7[m translation: remove unnecessary code for iterating through Genders Enum
[34m|[m * [33mc3ef5f5b[m[33m ([m[1;31morigin/feature/translation-cde[m[33m)[m i18n: Fix .po files for usage with merge driver
[34m|[m * [33m84d1c3c6[m translation: fix test failures
[34m|[m *   [33m0c7ac4ff[m Merge branch 'feature/translation-assembly' into feature/translation-cde
[34m|[m [1;33m|[m[1;34m\[m  
[34m|[m * [1;34m|[m [33m3fc050e4[m translation: re-translate English to German
[34m|[m * [1;34m|[m [33md5f7bc56[m translation: translate Log Codes into readable English strings, do minor cleanup
[34m|[m * [1;34m|[m [33m56dbb1b4[m translation: fix some minor error, do some cleanup
[34m|[m * [1;34m|[m [33m723d7ceb[m frontend: Add some of the retranslations from cde realm
[34m|[m * [1;34m|[m [33m90f7c299[m frontend: translate all hardcoded German strings to English and wrap them in translators
* [1;34m|[m [1;34m|[m [33m4b27d06f[m i18n: fix po-scripts.
* [1;34m|[m [1;34m|[m [33m537ab0f2[m translation: add translation for new helpbox
* [1;34m|[m [1;34m|[m [33m5c7749f2[m assembly: fix missing translation wrapper, add helpbox for tallied preferantial vote
* [1;34m|[m [1;34m|[m [33mf28e7e24[m i18n: make diff and merge scripts executable
* [1;34m|[m [1;34m|[m [33m3c3b7c58[m starting an detailed How-to for events
* [1;34m|[m [1;34m|[m [33me4d5951c[m integration Veranstaltungsleitfaden in Handbuch
* [1;34m|[m [1;34m|[m [33mb5668ea6[m hinzufügen Kurse, Unterkünfte im Veranstaltungsleitfaden
* [1;34m|[m [1;34m|[m [33mfb60cb12[m Veranstaltungsleitfaden begonnen
* [1;34m|[m [1;34m|[m [33me3241400[m first check of function
* [1;34m|[m [1;34m|[m   [33m6a953630[m Merge branch 'fix/rework_parameter_timeouts'
[1;35m|[m[1;36m\[m [1;34m\[m [1;34m\[m  
[1;35m|[m * [1;34m|[m [1;34m|[m [33m94370e14[m ml-frontend: Make one more parameter in a requested email expire faster.
[1;35m|[m * [1;34m|[m [1;34m|[m [33m1bc29261[m frontend: Restructure parameter timeouts to CRITICAL, UNCRITICAL and EMAIL
[1;35m|[m * [1;34m|[m [1;34m|[m [33maa1cbc4b[m frontend: Remove timeouts from encoded 'wants' parameters
* [1;36m|[m [1;34m|[m [1;34m|[m   [33me6b2608d[m Merge branch 'feature/partial-import-sample' of cdedb/cdedb2 into master
[31m|[m[32m\[m [1;36m\[m [1;34m\[m [1;34m\[m  
[31m|[m * [1;36m|[m [1;34m|[m [1;34m|[m [33mfdae0ead[m event: Add sample file for partial import.
* [32m|[m [1;36m|[m [1;34m|[m [1;34m|[m [33mcfbe6db6[m i18n: Fix .po files for usage with merge driver
* [32m|[m [1;36m|[m [1;34m|[m [1;34m|[m [33mfb1d738f[m Move po-diff-handler and improve comment
* [32m|[m [1;36m|[m [1;34m|[m [1;34m|[m [33mbde17724[m Add git merge driver for .po files
* [32m|[m [1;36m|[m [1;34m|[m [1;34m|[m [33mb9ee165a[m ui/core: Improve show_user: Hide archived info for non-admins and show hyphen when email is missing
* [32m|[m [1;36m|[m [1;34m|[m [1;34m|[m [33m646d384d[m event-frontend: Improve code.
* [32m|[m [1;36m|[m [1;34m|[m [1;34m|[m [33m77a8ce25[m tests: Fix remaining issues.
* [32m|[m [1;36m|[m [1;34m|[m [1;34m|[m   [33m836d39d1[m Merge branch 'feature/translation-assembly'
[33m|[m[1;34m\[m [32m\[m [1;36m\[m [1;34m\[m [1;34m\[m  
[33m|[m [1;34m|[m [32m|[m[1;34m_[m[1;36m|[m[1;34m_[m[1;34m|[m[1;34m/[m  
[33m|[m [1;34m|[m[1;34m/[m[32m|[m [1;36m|[m [1;34m|[m   
[33m|[m * [32m|[m [1;36m|[m [1;34m|[m [33m2448d77a[m translation: add translations for AssemblyLogCodes and QueryOperators. Fix some issues mentioned in Pull-Request (#181)
[33m|[m * [32m|[m [1;36m|[m [1;34m|[m [33m989e56cd[m translation: improve code style in translation. fix some translation strings
[33m|[m * [32m|[m [1;36m|[m [1;34m|[m [33ma42d842f[m translation: fix test failures due to translations
[33m|[m * [32m|[m [1;36m|[m [1;34m|[m   [33m8bffa1eb[m Merge branch 'master' into test
[33m|[m [1;34m|[m[36m\[m [32m\[m [1;36m\[m [1;34m\[m  
[33m|[m [1;34m|[m [36m|[m[1;34m_[m[32m|[m[1;34m_[m[1;36m|[m[1;34m/[m  
[33m|[m [1;34m|[m[1;34m/[m[36m|[m [32m|[m [1;36m|[m   
[33m|[m * [36m|[m [32m|[m [1;36m|[m [33m874b2854[m[33m ([m[1;31morigin/feature/translation-assembly[m[33m)[m frontend: Unify Log titles, fix a few missing translations
[33m|[m * [36m|[m [32m|[m [1;36m|[m [33me13aaf0e[m git: move, rename and explain po-diff-handler
[33m|[m * [36m|[m [32m|[m [1;36m|[m [33mf6ddbc4a[m frontend: fix translation placeholders and missing JavaScript Quotes
[33m|[m * [36m|[m [32m|[m [1;36m|[m [33me18c6ca5[m git: add custom diff handler for .po files
[33m|[m * [36m|[m [32m|[m [1;36m|[m [33m259178f6[m frontend: add Whitespace trimming to all trans environments.
[33m|[m * [36m|[m [32m|[m [1;36m|[m [33m0f7d2d88[m frontend: add re-translations, fix some typos
[33m|[m * [36m|[m [32m|[m [1;36m|[m [33m38dd2b8a[m frontend: fix variable use within trans environment, fix small typo
[33m|[m * [36m|[m [32m|[m [1;36m|[m [33m92daaea3[m frontend: translate and add gettext or trans wrappers to all german text in base and assembly templates.
* [36m|[m [36m|[m [32m|[m [1;36m|[m   [33m36583057[m Merge branch 'feature/additional_track_data'
[1;31m|[m[1;32m\[m [36m\[m [36m\[m [32m\[m [1;36m\[m  
[1;31m|[m * [36m|[m [36m|[m [32m|[m [1;36m|[m [33m735abdcb[m database: Add evolution.
[1;31m|[m * [36m|[m [36m|[m [32m|[m [1;36m|[m [33mf2e48dcf[m test: Add test for a posteriori change of num_choices
[1;31m|[m * [36m|[m [36m|[m [32m|[m [1;36m|[m [33me8eab866[m test: Fix tests related to event backend fixes
[1;31m|[m * [36m|[m [36m|[m [32m|[m [1;36m|[m [33m6da7caf4[m validation: Fix new infinite_enum validation
[1;31m|[m * [36m|[m [36m|[m [32m|[m [1;36m|[m [33m6c5d874a[m backend/event: Fix little bugs in _set_tracks() and registrations_by_course()
[1;31m|[m * [36m|[m [36m|[m [32m|[m [1;36m|[m [33ma0e07af0[m cdedb: Add infinite enums and use them on the course choice page.
[1;31m|[m * [36m|[m [36m|[m [32m|[m [1;36m|[m [33m3c8d6cc0[m[33m ([m[1;31morigin/feature/additional_track_data[m[33m)[m event: Fix small oversights.
[1;31m|[m * [36m|[m [36m|[m [32m|[m [1;36m|[m [33mb5e9cb6e[m frontend/event: Fix course_choices() for a posteriori change of num_choices
[1;31m|[m * [36m|[m [36m|[m [32m|[m [1;36m|[m [33m91858187[m backend/event: Fix registrations_by_course for a posteriori changes to num_choices
[1;31m|[m * [36m|[m [36m|[m [32m|[m [1;36m|[m [33mbcd4919c[m ui: Improve event/part_summary: Shorten add/remove labels for non-JS users
[1;31m|[m * [36m|[m [36m|[m [32m|[m [1;36m|[m [33mdb5a701c[m ui: Sort event tracks by sortkey field
[1;31m|[m * [36m|[m [36m|[m [32m|[m [1;36m|[m [33m5c82b4a9[m test: Fix test_frontend_event for new sample-data and frontend changes
[1;31m|[m * [36m|[m [36m|[m [32m|[m [1;36m|[m [33mf335aa63[m test: Fix test_event_backend for changed sample data
[1;31m|[m * [36m|[m [36m|[m [32m|[m [1;36m|[m [33m3001de2c[m sample-data: Change course_tracks.num_choices and fix course_choices
[1;31m|[m * [36m|[m [36m|[m [32m|[m [1;36m|[m [33mcde23319[m frontend: Fix event/stats, event/course_stats, event/register, event/show_registration
[1;31m|[m * [36m|[m [36m|[m [32m|[m [1;36m|[m [33m031411fd[m frontend: Fix event/course_choices for arbitrary number of course choices
[1;31m|[m * [36m|[m [36m|[m [32m|[m [1;36m|[m [33ma8a218f2[m frontend: Adapt event/part_summary to edit new track attributes
[1;31m|[m * [36m|[m [36m|[m [32m|[m [1;36m|[m [33m6182d0a8[m frontend/event: Consider track's num_choices attribute
[1;31m|[m * [36m|[m [36m|[m [32m|[m [1;36m|[m [33md6f327b5[m frontend/event: Fix frontend for new track data format (no usage of new data yet)
[1;31m|[m * [36m|[m [36m|[m [32m|[m [1;36m|[m [33m4408de21[m backend: Add 'shortname', 'num_choices', 'sortkey' fields to tracks
* [1;32m|[m [36m|[m [36m|[m [32m|[m [1;36m|[m [33mc88000f2[m test: Add test for events' is_visible and is_course_list_visible flags
* [1;32m|[m [36m|[m [36m|[m [32m|[m [1;36m|[m [33m42364756[m doc: Add hint to full_page_writes postgres option
* [1;32m|[m [36m|[m [36m|[m [32m|[m [1;36m|[m [33m1c9afa59[m validation: Enforce event registration start <= soft limit <= hart limit
* [1;32m|[m [36m|[m [36m|[m [32m|[m [1;36m|[m [33m7c70738f[m test: Fixup test_register_no_registraion_end
* [1;32m|[m [36m|[m [36m|[m [32m|[m [1;36m|[m [33medeb3f84[m frontend/event: Clarify registration_hard_end and _soft_end
* [1;32m|[m [36m|[m [36m|[m [32m|[m [1;36m|[m [33m7411a569[m test: Add test for registration without fixed registration_ends
* [1;32m|[m [36m|[m [36m|[m [32m|[m [1;36m|[m [33mc9ec3574[m test: Improve semester and expuls tests to test error handling
* [1;32m|[m [36m|[m [36m|[m [32m|[m [1;36m|[m [33m99a86224[m frontend/cde: Fix redirects to show_semester after error
[32m|[m [1;32m|[m[32m_[m[36m|[m[32m_[m[36m|[m[32m/[m [1;36m/[m  
[32m|[m[32m/[m[1;32m|[m [36m|[m [36m|[m [1;36m|[m   
* [1;32m|[m [36m|[m [36m|[m [1;36m|[m [33md543cace[m auto-build: Fix vdi networking.
[36m|[m [1;32m|[m[36m_[m[36m|[m[36m/[m [1;36m/[m  
[36m|[m[36m/[m[1;32m|[m [36m|[m [1;36m|[m   
* [1;32m|[m [36m|[m [1;36m|[m [33m1cdd9bdd[m test: compile i18n before testing
[1;36m|[m [1;32m|[m[1;36m_[m[36m|[m[1;36m/[m  
[1;36m|[m[1;36m/[m[1;32m|[m [36m|[m   
* [1;32m|[m [36m|[m [33m64d6df52[m tests: Add nice shell scripts for easier testing.
* [1;32m|[m [36m|[m [33m4431ad18[m assembly-frontend: Fix display of assembly conclusion form.
* [1;32m|[m [36m|[m [33mb29ee0c5[m assembly-backend: Fix conclusion of assembly with no participants.
[36m|[m [1;32m|[m[36m/[m  
[36m|[m[36m/[m[1;32m|[m   
* [1;32m|[m [33me2e7b303[m cde-frontend: Clarify batch admission format for genders.
* [1;32m|[m   [33m76166c2a[m Merge branch 'feature/change_locale'
[1;33m|[m[1;34m\[m [1;32m\[m  
[1;33m|[m * [1;32m|[m [33m24c1616b[m ui: Add alt text and title to locale change buttons
[1;33m|[m * [1;32m|[m [33m7ee8b78f[m frontend: Fix Jinja2 auto_reload logic
[1;33m|[m * [1;32m|[m [33m27e311f5[m test: Add test for changing locale
[1;33m|[m * [1;32m|[m [33m5c6cf646[m frontend: Small fixes to locale changing changes.
[1;33m|[m * [1;32m|[m [33m3f5d34f5[m frontend/core: Add missing docstring for change_locale
[1;33m|[m * [1;32m|[m [33mab81a195[m application: Ignore Accept-Language header until english translation is more complete
[1;33m|[m * [1;32m|[m [33m15d2ef6f[m frontend: Disable template reloading if not in development mode
[1;33m|[m * [1;32m|[m [33me627a0d4[m application: Fix locale of error pages and move static template parameters to globals
[1;33m|[m * [1;32m|[m [33ma50b7605[m frontend: Fix change_locale_form: Take locales from config, skip if not known
[1;33m|[m * [1;32m|[m [33m19a81cbe[m frontend: Move static template parameters to Jinja Env globals
[1;33m|[m * [1;32m|[m [33m031faefe[m frontend: prolong locale cookie to last for 10 years
[1;33m|[m * [1;32m|[m [33m3c86afdf[m ui: Fix logo width to prevent layout break on small screens
[1;33m|[m * [1;32m|[m [33m8b7e4ade[m ui: Add famfamfam.com flag icons for locale changing
[1;33m|[m * [1;32m|[m [33m97b65443[m frontend: Add endpoint 'core/change_locale' and corresponding form
[1;33m|[m * [1;32m|[m [33mc50c615b[m frontend: Allow changing locale via cookie and Accept-Language header
* [1;34m|[m [1;32m|[m [33m447211b5[m test: Add test for event CSV exports
* [1;34m|[m [1;32m|[m [33maa738bb9[m frontend/cde: Show number of hidden participants on show_past_event,course
* [1;34m|[m [1;32m|[m [33mcef6b003[m sql: Mark most booleans as NOT NULL
* [1;34m|[m [1;32m|[m [33me7c20358[m migration: Adapt to stricter validation in assembly realm.
* [1;34m|[m [1;32m|[m [33m45723b73[m validation: Improve IBAN validation.
* [1;34m|[m [1;32m|[m [33m4a13959c[m migration: Fix migration script.
* [1;34m|[m [1;32m|[m   [33ma3137c00[m Merge branch 'fix/login_redirect' of cdedb/cdedb2 into master
[1;35m|[m[1;36m\[m [1;34m\[m [1;32m\[m  
[1;35m|[m * [1;34m|[m [1;32m|[m [33mbb864234[m frontend: Fix redirect after login for already logged-in user
[1;35m|[m * [1;34m|[m [1;32m|[m [33mff716069[m frontend: Refactor login form into new template core/login.tmpl
[1;35m|[m [1;34m|[m[1;34m/[m [1;32m/[m  
* [1;34m|[m [1;32m|[m [33m49776161[m frontend: Fix core/show_user for past event participants without course
* [1;34m|[m [1;32m|[m [33m1149f5dd[m config: Fix registration_query default queries (view field family_name)
[1;34m|[m[1;34m/[m [1;32m/[m  
* [1;32m|[m [33m0af7e77d[m core: Improve privilege implementation.
* [1;32m|[m   [33m92fb9ec1[m Merge branch 'feature/rework_admin_privileges'
[31m|[m[32m\[m [1;32m\[m  
[31m|[m * [1;32m|[m [33m11e80104[m cdedb: Fix typo
[31m|[m * [1;32m|[m [33m5c3e2c84[m[33m ([m[1;31morigin/feature/rework_admin_privileges[m[33m)[m backend: Restrict admins to create personas only in their realms (+ implied realms)
[31m|[m * [1;32m|[m [33m83ec3fdc[m test: Make Emilia assembly and event user to test admin privileges
[31m|[m * [1;32m|[m [33m2f91dd4d[m test: Fix test_user_search for changed user_search behaviour
[31m|[m * [1;32m|[m [33m7205dc20[m backend: Restrict realm user searches to users editable by realm admins
[31m|[m * [1;32m|[m [33m1f1ed2a6[m backend: Rework relative admin permission model
[31m|[m [1;32m|[m[1;32m/[m  
* [1;32m|[m [33mf04572b8[m ui: Improve cde/show_past_event: Add course number to participant list
* [1;32m|[m [33m3adb4e68[m ui: Fix cde/show_past_course,show_past_event: Allow adding event users via persona_select dropdown
* [1;32m|[m [33m86675d60[m frontend: Fix core/show_user: Group past event participations by event
* [1;32m|[m [33mba9f3302[m frontend: Fix show_user_link() to allow quote_me=False
* [1;32m|[m [33m638a17a1[m core-frontend: Fix ml genesis cases.
* [1;32m|[m [33mcb26f971[m auto-build: Fix echo invocation.
[1;32m|[m[1;32m/[m  
* [33mf2ca9b60[m tools: Fixup 4fa1918832: Bring back the exit statement to prevent accidental execution
* [33mc008f2c2[m test: Make sample data consistent.
* [33mcad38369[m ui: ml/management: Remove 'sphere' parameter for select_persona.
* [33m7e5eb75a[m frontend: Add event/download_csv_registrations
* [33m226bdbdd[m ui: Improve query_form.js: Re-focus field select box after selecting a view field
* [33m5959b8cc[m ui: Fix debug_email link insertion
* [33m4fa19188[m tools: Fix reset-ldap-schema.sh
* [33m51b3c423[m ui: Add new logo
* [33m46b7605d[m JS: Fix query queryform.js: Allow search after download
* [33m605ca055[m frontend: Pass query form choices as sorted list to JavaScript
* [33m1acadef0[m ldap: Add shell script to reset ldap schema
* [33m6a4211e2[m core: Remove cloud_account in code and schema
* [33m23430f2b[m tests: Adapt to recent changes.
* [33m4c9c8b23[m sample-data: Add Emilia to the PfingstAkademie 2014 past event
* [33mc3ce9124[m frontend: Add info box about possibility to search for past event courses
* [33me2a191fd[m frontend: Add 'reverse' parameter to xdictsort_filter
* [33m2d733dd5[m frontend: sort past events alphabetically if they have the same date
* [33mdacdb892[m frontend: all enum choices are now sorted
* [33mabf29798[m doc: Update documentation for VM performance
* [33m6e9f2ad5[m migration: event mailinglists and mgv mailinglists should now be assigned the correct visibility
* [33m835dc445[m cdedb2: fix typo from 86524bdf1b
* [33m6d7891a0[m Remove links to past events for event-only users
* [33mf507ba4a[m core-frontend: Fix core/show_user: Really show lastschrift correctly
* [33maf429187[m i18n: add missing translations of Genders members in en locale
* [33m86524bdf[m cdedb2: add new choice for Genders
* [33m40fbbc76[m i18n: use the n_() function to extract translatable strings
* [33me914fd38[m core-frontend: Fix core/show_user: Show lastschrift correctly
* [33m454adafc[m auto-build: Move editor preference to the correct file.
* [33ma687af19[m doc: fix typo and slightly extended documentation
* [33m12bc09be[m auto-build: Use nano as default editor.
* [33md37f9c3b[m core-ui: Remove null option for gender
* [33mf040b1c1[m auto-build: Replace command to make sample data
* [33m4463e0a9[m tests: Fix tests after recent edits.
* [33mcb5783cd[m event: Sort lodgement table by name instead of id
* [33mf070bb36[m refactor: fix remaining issues from commit 596a6d4141
* [33m0a6fb26a[m cde-frontend: Fix links from past events/courses to profile: Only quote_me if not an admin
* [33m4b05dc66[m ui: Hide shortname from cde/show_past_event's heading
* [33m8bb94b2a[m core-frontend: Quoting a cde admin does have no effect.
* [33m35188a5f[m template: Fix template markup.
* [33m3fb94138[m Remove TODO.org
* [33m596a6d41[m refactor: rename _() to n_()
* [33m71482668[m frontend: Remove Deppenleerzeichen and rename team to Datenbankentwicklungsteam
* [33m3be400a1[m frontend: move event/registration_query default queries to config.py
* [33m2302c60f[m Restrict events to use bank account 8068901
* [33m844e9a40[m event: Add bank accounts to config
* [33mfbbc43d9[m doc: Add more hints to the VM usage section.
* [33m4f6a46c8[m frontend: add new default queries
* [33m2c232092[m auto-build: Fix sed invocation.
* [33m61146038[m Rename "Abgeschlossene Veranstaltungen" to "Vergangene Veranstaltungen"
* [33mbfa28a55[m UI: Rename Start and CdE realm
* [33m4a11f636[m UI: Replace hardocded realm breadcrumbs with super()
* [33m50aafcae[m auto-build: Make the image a bit smaller.
* [33m00704dec[m added translation functionality to default queries, actual translations still need to be done.
* [33m57a043ab[m auto-build: Use actually working upstream URL
* [33mc809735c[m auto-build: Add the i18n files which are now missing.
* [33m11aed680[m removed duplicate form endtag
* [33maabd37a4[m default queries are now sorted before being sliced. This should achieve stability, but the search parameters (currently the key) might need to be modified to enforce a certain order
* [33m46b71f4b[m exclude pycharm files from tracking
* [33m08eaf928[m auto-build: Disable apache private temp.
* [33m316c4689[m infra: touching the wsgi file doesn't work.
* [33mc4bf0c2c[m auto-build: Set time zone in postgres to UTC
* [33mb3e71ae1[m auto-build: Replace emacs by leaner variant.
* [33mbc21a245[m event: Change export format.
* [33m4a8ea1fa[m [backend] Fix registration query: Don't return multiple rows for recreated registrations when ctime is queried
* [33m296754d0[m [frontend] Fix event/download_csv_courses,lodgements for unfilled extra fields
* [33mfe6492f6[m cdedb: Remove accidentially commited file.
* [33m738f260e[m event-frontend: Actually check the safety checkbox.
* [33m8fbee2c8[m [frontend] Add CSV export of event courses and lodgements
* [33mecac38c0[m event: Implement course deletion.
* [33m201f2297[m doc: Start creation of a user handbook.
* [33m185bd541[m doc: Add type information for parameters
* [33ma36dd4a9[m frontend: Keep whitespace in output in develpoment environment.
* [33m03f9913b[m event: Add one more test for field input in questionnaire
* [33me761a147[m event-backend: Quote field names.
* [33m3a5e0798[m event: Improve event fields even further.
* [33mea67612c[m event: Introduce prefix 'xfield_' to JSON fields for queries
* [33mccc28257[m migration: Document the need to manually fix course titles.
* [33m960ac8ee[m tests: Fix all failing tests.
* [33me4a2c60b[m [UI] Fix layout of event/reorder_questionaire for long labels
* [33m9f7b7713[m [test] Fix tests broken by 8f4362e415
* [33md05792a5[m [UI] Fix size of event/questionaire text fields and their labels
* [33made25841[m [UI] Format date/datetime in queryresults, hide deko_checkbox if value is None
* [33mdbf47b8f[m [UI] Fix event/change_registration: Validate checkin as datetime
* [33m7fdcc567[m [UI] Fix queryform.js: Disable unused filter-value und sort-order fields on submit
* [33m98036249[m [UI] Fix event/course_choices: Correct list of ids in query link
* [33me3def4a2[m [UI] Make counting of inhabitants on event/lodgements more intuitive
* [33m776213e0[m [UI] Fix event/registration_status for people without course choices (e.g. orgas)
* [33m66458a5a[m [UI] Show information about active course segments to everyone (see #120)
* [33m7fb58d79[m [UI] event: Make mixed_lodging and photo_consent default for manually added registrations
* [33m8f4362e4[m [frontend] Improve whitespace stripping
* [33m89385001[m [frontend] Speed up TeX template rendering: Cache Jinja Env to allow caching of templates
* [33ma74f49b3[m [UI] utils: Even more whitespace control
* [33mafd885b5[m [UI] More whitespace control for input macros
* [33m334c5a7a[m [UI] Allow setting label of nulloption of input_select
* [33mb86ebb30[m [frontend] Add xdict_entries_filter to replace more Jinja list comprehension workarounds
* [33mfc21877b[m [frontend] Use Jinja do-expressions and whitespace control for remaining list comprehension workarounds
* [33m2866623c[m [frontend] Add enum_entries_filter and dict_entries_filter to replace Jinja list comprehension workaround where possible
* [33m8df9867a[m [backend] EventBackend.get_events: Add track id to aggregated tracks
* [33m91d1ae03[m [UI] Add placeholder to cdedbSearchPersona() (fixes #107)
* [33m57738d6c[m [i18n] Translate query form and add missing german translations
* [33mbfdaa16a[m [i18n] Make JS query form translatable
* [33m8a684c0e[m [UI] Hide setfield button and show info on event/field_set in case of no registrations
* [33md95fec42[m [UI] Improve spacings and button positions in forms and event/show_ballot
* [33m4efbb6e9[m [test] Fix tests broken by 755217d501 and df23543b8d
* [33mdf23543b[m [UI] Add profile/registration button to query results and remove links on ids (fixes #109)
* [33maff811b1[m [UI] add color legend for event/course_stats, course_choices and lodgements (fixes #90)
[32m|[m * [33m5b9d4683[m[33m ([m[1;31morigin/feature/event-import[m[33m)[m [UI] Add template json_import_check
[32m|[m * [33m122528d0[m [UI] Change some event/downloads related icons
[32m|[m * [33m9abc014c[m [UI] Change some event/downloads related icons
[32m|[m * [33m9c2f2540[m [frontend] Add endpoints and first template for JSON import
[32m|[m[32m/[m  
* [33mc323fff6[m [UI] Small fixes
* [33md411ab15[m [test] Make test output less verbose on Python exceptions in frontend
* [33m755217d5[m [test] Add additional event 'CdE-Party 2050' to sample data and improve event tests
* [33m703edf28[m [UI] Improve core/show_user: Show link to existing lastschrift to user
* [33m3dc7aee7[m [a11y] Improve query form: Include tabs into form and label form
* [33m2524b45b[m [test] Fix realm_admin_view_profile(): Special id field name in event user search
* [33m6e2ec3d2[m [UI] Hide lastschrift_receipt and link to it from unprivileged users
* [33ma73e7f0f[m [UI] Improve cde/member_search: Move results above search form
* [33m5a6fd118[m [UI] Improve layout of docurl link and create macro for easy re-use.
* [33m6f04ffed[m documentation: Add docurl function to link to the documentation.
* [33mf4857cd0[m assembly: Disallow the vote begin of a ballot to be in the past.
* [33medb94cd3[m migration: Deduplicate MusikAkademie as well as WinterAkademie.
* [33m884bedc4[m core: Make relative admins work.
* [33m8a7e8600[m event-frontend: Be more defensive about dates.
* [33mcebc5c8a[m event-frontend: Include tracks only in expuls export, if multi-part event.
* [33m36887299[m [test] Test user operations as relative (non-core) admin
* [33m499011d5[m [a11y][i18n] Add aria-labels to fancy preference voting form
* [33m223fe8f8[m [UI] Fix event/lodgments: Only show existing problems in title
* [33mef75fb50[m event-frontend: Orga-added registrations now default to state participant.
* [33mfa1841d1[m templates: Replace 'String' with 'Text' in user-facing text.
* [33m6ca32184[m templates: Improve spelling.
*   [33m90044d92[m Merge branch 'fix/relative_admin_profile' of cdedb/cdedb2 into master
[34m|[m[35m\[m  
[34m|[m * [33md4b9a719[m[33m ([m[1;31morigin/fix/relative_admin_profile[m[33m)[m [frontend] Fix core/show_user: Allow relative admins to see user's core data
* [35m|[m [33mc117ca75[m core-backend: Fix changlog generation numbering.
* [35m|[m [33mb6573d71[m [test] Fix tests failing due to 1946417f97
* [35m|[m [33m992f30f1[m [UI] Fix core/show_history: Hide fields not relevant for current user role
* [35m|[m [33mcef090fa[m [UI] Fix event/course_choices: Use padded sort for course assignment box
[35m|[m[35m/[m  
* [33m230c45e5[m [UI] Some form improvements: Mailinglists are active by default, warnings about visibility of new past events
* [33mecb050fb[m [UI] Improve assembly/show_ballot: Candidate monikers and errors
* [33m4645d002[m [UI] Redirect to core/show_user after password change
* [33mdb6f6316[m [UI] Improve error template
* [33mc2998039[m [UI] Add select persona script for event/add_registration
*   [33m788f44fc[m Merge branch 'feature/move-event-meta' of cdedb/cdedb2 into master
[36m|[m[1;31m\[m  
[36m|[m * [33mf13afc8d[m[33m ([m[1;31morigin/feature/move-event-meta[m[33m)[m event-backend: Inline functions which were used exactly once.
[36m|[m * [33m445d8bbf[m Fix bugs and tests related to EventBackend.get_events()
[36m|[m * [33mfdfefba6[m Always do event_begin() and event_end() in EventBackend.get_event()
[36m|[m * [33m1b565b52[m Do event_gather_tracks() and registration_is_open() always in EventBackend.get_event()
* [1;31m|[m [33m31dc562d[m [UI] Fix core/index: Correctly handle registration time span (fixes Exceptions upon missing limits)
* [1;31m|[m [33m7492721c[m [UI] Fix xdictsort for None values
* [1;31m|[m [33m1946417f[m frontend: It's exPuls not ExPuls
* [1;31m|[m [33m1e322028[m validation: Disallow empty course numbers.
* [1;31m|[m [33m837a74c7[m test: Remove left-over debug output.
* [1;31m|[m [33mb01346b5[m validation: Implement IBAN validation.
* [1;31m|[m [33m19bbdd93[m core-backend: Fix archive_user type confusion.
* [1;31m|[m [33md8b7057f[m core-frontend: Enable unpriveleged users to use persona select API.
* [1;31m|[m [33m5aeca66d[m frontend: Fix persona select calls.
* [1;31m|[m [33mfb579ce0[m [UI] Sort mailinglists on ml/index and ml/list_mailinglists by name
* [1;31m|[m [33m4e5947de[m [UI] Show button for lastschrift_receipt to the (unprivileged) user
* [1;31m|[m [33m3103b193[m cde-frontend: Adapt batch addmission to legacy encoding of genders
[1;31m|[m[1;31m/[m  
* [33m25e2b30d[m [UI] Improve markup of cde/member_search
* [33m6043c62b[m [UI] Sort participants on event/course_choices by name
* [33m83510ffe[m [UI] Fix cde/show_past_event: Sort courses by course nr
* [33m5c5bccf1[m [UI] Fix visibility of links to lastschrift_show and lastschrift_create
* [33mb6ff2380[m [UI] Improve accessibility of navigation
* [33m7d1d2f74[m Fix some indentation and solved TODO
* [33m8acb0543[m [UI] Improve cde/show_past_event: Hide heading 'Kurse' if no course present
* [33m1d1267eb[m [UI] Improve cde/show_past_event/_course: Link to full profile instantly
* [33ma4ebdb5c[m [frontend] Fix cde/show_past_course/_event: Hide inactive users, show name of unviewable users
* [33m0feedc8b[m [UI] Fix orga shortcuts on core/index: Only link to course page if course tracks are present
* [33m761b78ea[m i18n: Eliminate i18n via folder structure in templates.
* [33me6fde1ff[m core-frontend: Fix handling of errors during archiving.
* [33m02c2cfdc[m migration: One more doc improvement.
* [33m46817e51[m migration: Improve documentation.
* [33me0efc44c[m migration: Add script.
* [33mc5bfb055[m [UI] Improve dynamicrow.js: Add dynamic id and label reference update
* [33m31bd0645[m [UI] Fix dynamicrow.js: Remove name attributes from prototype row
* [33maadc258b[m [UI] More aria-* markup for breadcrumbs and navbar
* [33m4cb39a7c[m [UI] Swap heading and alerts, add div[role="main"]
* [33ma35a82fa[m [UI] Fix wording on assembly/list_attendees
* [33m447508d0[m [UI] Add aria-labels to all inputs without labels
* [33m8b012eaa[m [UI] Improve from_input_* macros: Auto generate id if not given
* [33m200c1e11[m [UI] Add cdedbProtectChanges() to event/register
* [33m63078dc8[m [UI] Add labels or aria-labels for manually placed inputs
* [33md19e9dd8[m [UI] Prepare form_input_* macros for referencing of labels
* [33me99ab31a[m Exclude .po files from versioning; add make target 'reload'
* [33m6e065b19[m Remove unused template cde/show_archived_user
* [33m6e31c9e0[m [UI] Improve core/show_persona: Hide all edit buttons for archived users
* [33m3948d120[m Fix mail templates: Include account information from meta_info and link to cde/index for further information
* [33ma4ca9965[m [UI] Fix/improve design of core/show_user
* [33mf11b972b[m [UI] Fix and unify ack/confirm of dangerous buttons (fixes #70)
* [33m58fe9575[m [UI] Move dangerous buttons to end of page (fixes #30)
* [33me4b0308a[m core-backend: Prepare for test-migration.
* [33mea01aeaa[m assembly: Fix get_vote to cope with concluded assemblies.
[1;31m|[m * [33m1bc4c2eb[m[33m ([m[1;33mtag: archive/sql-template-for-test[m[33m, [m[1;31morigin/sql-template-for-test[m[33m)[m test: Use db templates to speed up the test suite.
[1;31m|[m[1;31m/[m  
* [33m0173cf29[m db: Make the port configurable on which the database is accessed.
* [33m004a8c99[m [test] Fix tests related to moved adminshowpersonaform and new layout of cde/batch_admission
* [33mfc415bb0[m [test] Add test for correct display of events with 0 or 1 tracks and no courses
* [33md77c137e[m [test] Improve FrontendTest.assert[Non]Presence: Allow testing content of arbitrary HTML tags
* [33m33b705fd[m [UI][test] Remove unneccessary hidden inputs from query results and fix related tests
* [33mef254337[m [UI] Fix field_summary: Show tabs only when Javascript is available
* [33mdac212e1[m [frontend] Show error message if one tries to add course to event without tracks
* [33mf7eceaf3[m [UI] Hide course track name in orga area if an event has only one track
* [33mf7af0030[m [UI] Improve cde/batch_admission
* [33mc64045b8[m [i18n] Add missing translation of lodgement problems
* [33mda5c796d[m [UI] Remove needless panel boxes for action buttons at */user_search
* [33me4e1aa89[m [UI] Add cdedb_csv_tools.js to cde/money_transfers and event/batch_fees
* [33me04bd852[m [UI] Make batch_admission.js a general purpose jQuery plugin for csv searches
* [33mcc11bf86[m Reword 'Reserve'  'Isomatte'
* [33mb603542e[m [UI] Fix query form: Correctly remove just selected field from add*field selectize.js box
* [33m91771c5f[m [UI] Several minor fixes
* [33me83536db[m [UI][i18n] Move QueryOperator titles into i18n strings and reword some
* [33m9431c791[m [UI] Remove unnecessary form on event/registration_query
* [33mfa99e7cb[m [UI] Fix query results: show js enabled buttons instead of hiding them
* [33md65df9be[m Update selectize.js to 0.12.6
* [33m0d36fe55[m [UI] Minor style fix
* [33m740fcf57[m [UI] Improve JavaScript performance
* [33m09279862[m Update jQuery to 3.3.1
* [33m27304cc9[m [UI] Improve query form: Add tabs to switch to simple tabular query form
* [33m1e5adf6c[m [UI] Improve event/checkin: Filter users on load (if a search string is present)
* [33m64870991[m [UI] Improve accessibility of query form: Add labels
* [33m668c6fc0[m [UI] Fix CSS of selectize.js in input-groups
* [33m1de302cb[m [UI] Use selectize.js for query form 'add*field' select boxes
* [33m2df54e0d[m [UI] Change titles of event/registration_query (incl. missing translations)
* [33mb4d98aec[m [UI] Improve core/show_history
* [33m0ffdd318[m [UI] Move user quick search to dashboard
* [33m2c0a0c5c[m [i18n] Update translation files
* [33mfafe664c[m [i18n] Add missing translations of MlLogCodes and FinanceLogCodes
* [33mc6a8e78f[m [UI] Fix lastschrift workflow
* [33m1308377b[m [i18n] Add missing translations of EventLogCodes
* [33m2c8a5ce8[m event-frontend: Fix typo.
* [33mbdb6ec18[m [frontend] Hide real_persona_id in online mode and reformat process_orga_registration_input()
* [33m91a6cb8a[m [frontend] Fix 'max() arg is an empty sequence' error when course list is empty
* [33mfe8b8ccf[m [UI] Fix accessibility and missing titles of icons and tabs
* [33m22e0a7e4[m [autobuild] Try to reduce image size by suppressing recommended packages and cleaning apt cache
* [33m46e11335[m Empty commit to trigger auto-build.
* [33m95040694[m Uncomment one more line.
* [33m90989afe[m Fix vdi target of auto-build.
* [33md5b8256e[m Update Debian in autobuild, disable vdi image generation.
* [33m3db2bc8e[m event: Add log in export.
* [33m07028f82[m test: Add registration creation log entries.
* [33mdf761ac8[m event-backend: Improve export to be key-value instead of array based.
* [33m83a3597f[m [UI] Fix event/change_event: Show field_names in lodge_field and reserve_field
* [33m8246419a[m cdedb: Use pathlib for path manipulations.
* [33m1f0bd3a6[m cdedb: Use utf8 encoding with all opened text files.
* [33m222e2dd5[m event: Disallow field names to end in digits.
* [33m89f28249[m cde-frontend: Add check for archived personas when booking money transfers.
* [33m78bdecf1[m frontend-core: Modify icons for archiving and purging.
* [33m436d280c[m Implement archiving and purging of personas.
* [33m9191d611[m ml-frontend: Add button to remove all inconsistencies on check page.
* [33m15e48bc6[m ml-frontend: Add global consistency check.
* [33m4633f5a2[m cdedb: Change gender handling.
* [33m6ba19b85[m ml: Implement script access.
* [33m9d1a6c41[m event-frontend: Add batch entry of paid fees.
* [33m4dfb8424[m event-frontend: Fix deletion of registration to honor safety checkbox.
* [33m57499df8[m event: Add functionality to delete registrations.
* [33m538de3b5[m Add preliminary version of mailinglist software.
* [33m397b5a24[m [UI/event] Add notification about visibility at event/course_list (and some comment)
* [33ma251ce23[m [backend/event][frontend] Fix semantics of event.is_visible
* [33mf106e0bf[m [UI] Include error description in to HTTP 403/404 page
* [33mf5a5f757[m [UI/cde] Change cancel button target on cde/consent_decision for non-initial decision
* [33mc1670a37[m [frontend/event] Fix some rough edges (invalid links) of invisible course lists and events
* [33md25ef54c[m [frontend/event] Add warning for invisible couse_list and show HTTP 403 instead of readirect for invisible event
* [33m2f296132[m [test] Add test for changing consent decision
* [33m5239a783[m [frontend/cde] Improve consent_decision: Redirect to cde/index if not decided initially
* [33mff4bd06e[m [frontend/cde] Fix consent_decision: Allow users to change consent decisiion when already decided
* [33m93007a27[m [frontend/core] Add checkbox to allow admins to change privacy consent decision (closes #29)
* [33m9c016873[m [UI] Clear core/genesis_list_cases from texts and headings of old genesis process
* [33mb3fcbaad[m event: Prevent part/track creation and deletion if registrations are present.
* [33mf42b8887[m event: Add visibility toggles to events.
* [33m5415d7cd[m event: Change registration time limits to timestamps.
* [33m801e1291[m [UI] Add help text about (active_)segments inputs on event/change_course
* [33mca2624a9[m Revert "Fix event/register and event/amend_registration: Allow chosing of courses without active segment"
* [33mf0a89ae6[m frontend: Unify xdictsort_filter and xdictsortpad_filter.
* [33m8984540b[m [backend] Fix creation order of course tracks (fixes #54)
* [33mdd2a06fd[m [frontend] Fix sorting of courses: Sort numerically (fixes #50)
* [33ma37e557c[m [UI] Fix minor styling things on core/genesis_list_cases and core/genesis_modify_form
* [33m2fb8720d[m core: Fix default password hashes.
* [33ma1e7880f[m core-frontend: Improve select_persona API
* [33m65ced1a3[m [UI] Fix layout of core/genesis_request and core/genesis_modify_form and add dynamic hiding of event-only fields (fixes #52 and #49)
* [33m901ce6ed[m Fix event/register and event/amend_registration: Allow chosing of courses without active segment
* [33mdc6c786d[m [UI] Fix Layout of cde/member_search: First names before last name
* [33m14379172[m [UI] Fix Layout of event/lodgements: Header with correct width
* [33m1fccc623[m Adjust to secrets module being absent.
* [33mac7f3b52[m Improve security.
* [33m3da956d7[m genesis: Make account creation more strict.
* [33mfe9ee2c0[m core: rework the genesis process
* [33m1bddd5ae[m auto-build: One less log.
* [33m1399dab0[m core: Add functionality to view emails sent by test instances.
* [33mc1c22af5[m auto-build: Add more logfiles to localconfig
* [33m9751080d[m doc: Consolidate documentation.
* [33m97b9c817[m i18n: Update strings.
* [33m1062b759[m cde: Modify membership state on new transfers.
* [33med2c284b[m cde: Check for negative amounts in money_transfer.
* [33md99c6ee5[m doc: move access credentials to project wiki.
* [33m6b4d0337[m core: Allow not consenting to be searchable.
* [33m87ae677d[m [UI] Add JS to disable checkboxes at event/change_course dynamically
* [33mf4b3ae61[m Remove leftover icons in static/ and update COPYING
* [33m38ef6435[m [UI] Add edit and manage_attendees buttons to event/course_stats
* [33mff303741[m [UI] Format date and datetime values according to locale (closes #5)
* [33meb33397e[m [frontend/event] Fix error preventing nametag generation due to missing lodgement information
* [33mdc3bf56b[m [UI] Add missing placeholders for date-type input fields
* [33mf4ed4885[m [UI] Fix dynamic hiding of course choices at event/register
* [33m356c455b[m [UI] Upgrade jQuery to version 3.2.1
* [33mf752f9f7[m [UI] Remove jquery-ui, which is not used anymore
* [33m09144ddb[m [UI] Fix change_mailinglist.js
* [33m56bbaa3b[m [UI] Fix typo in core/do_username_change_form
* [33m1f9ff744[m [UI] Improve layout of core/do_username_change_form
* [33ma29da6c8[m [frontend/core] Fix email address in description at core/do_username_change_form (closes #33)
[1;32m|[m * [33mbba81cca[m[33m ([m[1;31morigin/email[m[33m)[m core: Fix email change confirmation change for emails with --
[1;32m|[m * [33mdb713718[m core: Fix display error on email change confirmation page
[1;32m|[m[1;32m/[m  
*   [33m0d1510f9[m Merge branch 'feature/event_registration_multiedit' of cdedb/cdedb2 into master
[1;34m|[m[1;35m\[m  
[1;34m|[m * [33m599b3636[m event-frontend: Add input validation check.
[1;34m|[m *   [33m353df256[m Merge branch 'master' into feature/event_registration_multiedit
[1;34m|[m [1;36m|[m[31m\[m  
[1;34m|[m * [31m|[m [33mc9898bc9[m [frontend/event] Add error handling and useful redirect to event/change_registrations
[1;34m|[m * [31m|[m [33m83c98718[m [frontend] Remove event/registration_action
[1;34m|[m * [31m|[m [33mf85961b4[m [test] Fix test event/test_multiedit
[1;34m|[m * [31m|[m [33m7e10326d[m [UI] Add dynamic hightlighting of changed fields in event/change_registrations
[1;34m|[m * [31m|[m [33me904ad5a[m [frontend] Fix default enabled state of currently empty data fields in event/change_registrations
[1;34m|[m * [31m|[m [33mf922485c[m [frontend] Fix javascript enabled link buttons using cdedburl's magic_placeholders
[1;34m|[m * [31m|[m [33m73f9a385[m frontend: Make magic URL placeholders a bit safer.
[1;34m|[m * [31m|[m [33mb518dc22[m frontend: Add magic URL placeholders.
[1;34m|[m * [31m|[m [33m18ce894a[m event-frontend: Improve multiedit.
[1;34m|[m * [31m|[m [33m6cccc4fa[m [frontend] Fix event/change_registrations: Add missing template file
[1;34m|[m * [31m|[m [33m4cc6126b[m [frontend] Add event/change_registrations: Selective edit for multiple registrations
* [31m|[m [31m|[m   [33mee132e2d[m Merge branch 'fix/stop_pgbouncer' of cdedb/cdedb2 into master
[32m|[m[33m\[m [31m\[m [31m\[m  
[32m|[m * [31m|[m [31m|[m [33m0b0ee72f[m Stop pgbouncer while recreating database via `make sql`
[32m|[m [31m|[m [31m|[m[31m/[m  
[32m|[m [31m|[m[31m/[m[31m|[m   
* [31m|[m [31m|[m [33mffc13afa[m [UI/event] Sort event parts by part_begin instead of id
* [31m|[m [31m|[m [33m4f3c98e9[m [UI] Fix checkin time label on event/show_registration
* [31m|[m [31m|[m [33m60d8ef18[m [frontend/event] Redirect after checkin instead of directly rendering form
* [31m|[m [31m|[m [33m563e7725[m [UI] Fix layout of event/checkin (closes #31)
* [31m|[m [31m|[m [33m7a57a5b1[m [UI] Add warnings about visibility of changes for assemblies and ballots. And a new link to assembly configuration
* [31m|[m [31m|[m [33maf7a8b2f[m event-frontend: Improve validation to not swallow errors.
[31m|[m[31m/[m [31m/[m  
* [31m|[m [33me05acb9c[m [backend] Fix typo in admin role check
* [31m|[m [33m1794462c[m tests: repair stats test
* [31m|[m   [33m2ae0b235[m Merge branch 'feature/stats_with_query_links' of cdedb/cdedb2 into master
[34m|[m[35m\[m [31m\[m  
[34m|[m * [31m|[m [33m81ab516a[m [frontend/event] Restore participant lists by part at event/stats
[34m|[m * [31m|[m [33m69944f6f[m [frontend] Fix querytoparams filter for list-constraints and add orga-query to event/stats
[34m|[m * [31m|[m [33m14e1c3f7[m event-frontend: Make some code style fixes.
[34m|[m * [31m|[m [33m14f09d74[m [frontend] Workaround for event/stats: Remove invalid 'orgas' query
[34m|[m * [31m|[m [33md1258801[m [frontend] Add query links to event/stats and remove lists where redundant
* [35m|[m [31m|[m [33m4cf03781[m event: Add more columns to the registration query.
* [35m|[m [31m|[m [33m2553df0a[m [test] Fix test for event/stats
* [35m|[m [31m|[m [33m8e4e60ac[m [frontend/event] Fix event/manange_inhabitants: Process deletions and reserve lodgers correctly
* [35m|[m [31m|[m [33me01d012f[m [frontend] Refactor lodgement errors and implement fancy error display in lodgement list
* [35m|[m [31m|[m [33m3baba6ed[m [frontend][backend] Event: Add is_reserve to registration_query
* [35m|[m [31m|[m [33m674ab11c[m [UI] Fix deleted rows highlighting on event/manage_inhabitants
* [35m|[m [31m|[m [33m23c7fed0[m auto-build: Fix left-over of gitea migration.
* [35m|[m [31m|[m [33mfee2a50f[m autobuild: Tune concurrency control.
* [35m|[m [31m|[m [33m96dec67c[m [frontend] Event: Add displaying and modification of is_reserve flags
[35m|[m[35m/[m [31m/[m  
* [31m|[m [33m782d847a[m [UI] Fix layout of event/stats
* [31m|[m [33mefde1f02[m [UI] Fix table cell background colors in event/course_choices
* [31m|[m [33m205841c2[m autobuild: Add safety against concurrent invocation.
* [31m|[m   [33me7a29cf8[m Merge branch 'typofix' of cdedb/cdedb2 into master
[36m|[m[1;31m\[m [31m\[m  
[36m|[m * [31m|[m [33mfa6d7764[m Fixed typo
* [1;31m|[m [31m|[m [33mb6345404[m [UI] Fix link to assembly for assembly mailinglists
* [1;31m|[m [31m|[m [33md8d20eb1[m [UI] Fix filters of selectpersona JS on ml/management
* [1;31m|[m [31m|[m [33mde346f11[m [UI] Hide 'create ballot' button on assembly/list_ballots for unprivileged users
* [1;31m|[m [31m|[m [33mef67c14e[m [frontend] Remove accidentally added import
* [1;31m|[m [31m|[m [33m42eb5871[m [frontend][UI] Add listselect JS, link to query and filtered column highlighting to event/course_choices
* [1;31m|[m [31m|[m [33m869aef28[m [UI] Dashboard: Fix display of event registration period
[1;31m|[m[1;31m/[m [31m/[m  
* [31m|[m [33m6b3a6849[m [frontend] event: Fix choices of multi-fields in registration_query
* [31m|[m [33m9f88fd44[m [UI] event: Improve templates for events with one part and/or one course track
* [31m|[m [33mf4b8a638[m [frontend] Event: Improve titles of course/lodgement/status query columns
* [31m|[m [33mf3753870[m Remove some completed items from TODO list
* [31m|[m [33m1de00943[m [frontend] Events: Sort courses by no and add course no to some selects
* [31m|[m [33m391c276e[m [UI] Use 'minus' icon instead of 'trash' where appropriate
* [31m|[m [33mc991e1f1[m [UI] Fix visibility of create_past_event button and improve heading styling in cde/show_past_course
* [31m|[m [33m89518e28[m [UI] Fix input type of date range fields in dynamic queryform
* [31m|[m [33m14e065f5[m Fix gitolite leftovers.
* [31m|[m [33mdce6e597[m Change URLs after move to gitea.
* [31m|[m [33m4881b57e[m [UI] Fix event/field_set to show participant names for bool fields
* [31m|[m [33m7dfb5240[m [UI] Fix queryform.js to allow CSV/JSON download and parsing of sorting from queryURL
* [31m|[m [33mca7105d3[m [UI] Change icon of participant remove button in inhabitant/attendee management
* [31m|[m [33m160e935b[m [UI] Fix display of non-saved course tracks on event/part_summary
* [31m|[m [33m7e0c99a8[m [UI] Fix layout of course track list in event/part_summary
* [31m|[m [33m977c21d4[m [UI] Add nested dynamicRow to event/part_summary. Not flawless yet.
* [31m|[m [33mcf6cbd38[m [UI] Improve dynamicRow.js to allow nesting of dynamic row forms
* [31m|[m [33m07f26bdb[m event: fix nametag creation
* [31m|[m [33m84420cac[m [UI] Fix layout of event/add_registration
* [31m|[m [33md4ea6539[m [UI] Fix several minor bugs and layout flaws. (partly related to new course tracks feature)
* [31m|[m [33me0dc7ca8[m todo: Delete finished items.
* [31m|[m   [33md873a08a[m Merge branch 'fix/dates_only_strptime'
[1;32m|[m[1;33m\[m [31m\[m  
[1;32m|[m * [31m|[m [33md1151551[m validation: Do not use dateutil since it's somewhat eccentric.
* [1;33m|[m [31m|[m [33m1e3736d0[m event: Make fields no longer magic.
* [1;33m|[m [31m|[m   [33m29bc47de[m Merge branch 'course-tracks'
[1;34m|[m[1;35m\[m [1;33m\[m [31m\[m  
[1;34m|[m * [1;33m|[m [31m|[m [33m5a5c9be6[m event-backend: Fix field handling in queries.
[1;34m|[m * [1;33m|[m [31m|[m [33m540ca099[m event: Add course tracks.
* [1;35m|[m [1;33m|[m [31m|[m [33mc86c02b8[m [UI] Fix preferential voting JS
[31m|[m [1;35m|[m[31m_[m[1;33m|[m[31m/[m  
[31m|[m[31m/[m[1;35m|[m [1;33m|[m   
* [1;35m|[m [1;33m|[m [33mf5ddd459[m [UI] Fix layout of checkboxes in form input macros
* [1;35m|[m [1;33m|[m [33me8ad7a27[m [UI][frontend] Improve layout of event/index and event/list_db_events and shortlinks for orgas on core/index
* [1;35m|[m [1;33m|[m [33m75a5979f[m [UI] Add date(time) types to inputs on event/change_registration and cdedbProtectChanges to event/field_set
* [1;35m|[m [1;33m|[m [33m83adf091[m [frontend] Enable filtering of event/set_field by registration ids
* [1;35m|[m [1;33m|[m [33mc78e5caf[m [UI] Pretty up some headings in event realm
* [1;35m|[m [1;33m|[m [33m103da632[m [UI] Fix layout of event/field_set[_select]
* [1;35m|[m [1;33m|[m [33m8df637ca[m [UI] Fix options of queryform filter with choices
* [1;35m|[m [1;33m|[m [33mbc927abe[m [backend][frontend] Add filtering of event/course_choices by reg_id and add link from event/registration_query
* [1;35m|[m [1;33m|[m [33m1d9f88ec[m [UI] Fix layout of event/course_choices and add colors to event/course_stats
* [1;35m|[m [1;33m|[m [33mae408e6a[m [frontend] Include orgas in to course statistics
* [1;35m|[m [1;33m|[m [33mb31cd5d0[m [frontend][UI] Rework event/manage_attendees (same changes as for event/manage_inhabitants) and tidy up event/manage_inhabitants
* [1;35m|[m [1;33m|[m [33mf44ebf67[m [UI] Improve layout of event/questionnaire_summary
* [1;35m|[m [1;33m|[m [33m5b831666[m [UI] Fix layout of event/lodgements
* [1;35m|[m [1;33m|[m [33mccc7a8ca[m [UI] Fix JS code style issues according to warnings of PyCharm's code inspection
* [1;35m|[m [1;33m|[m [33m67d52bb2[m [frontend][UI] Rework event/manage_inhabitants
* [1;35m|[m [1;33m|[m [33m4608ec5d[m [UI] Fix value formatting for datetime-local input fields
[1;33m|[m [1;35m|[m[1;33m/[m  
[1;33m|[m[1;33m/[m[1;35m|[m   
* [1;35m|[m [33mc6621114[m [UI] Improve event/show_registration: Add links to courses and lodgements
* [1;35m|[m [33mb7181903[m [UI] Fix JSHint in event/show_event: Only relevant for orgas and admins
* [1;35m|[m [33m6fddbf9d[m [UI] Fix layout of event/{show,create,change}_lodgement
* [1;35m|[m [33m9e8b9782[m [UI] Add cdedbProtectChanges to event/change_course and event/create_course
* [1;35m|[m [33mdb90aabf[m [frontend][UI] Fix core/index dashboard: Provide 'start' attribute for organized events and fix link to course list
* [1;35m|[m [33m02b9dd22[m [UI] Improve event/*registration templates: Hide things to avoid confusion with single-part and no-course events
* [1;35m|[m [33mce9302ca[m backend: correctly deserialize the event extra fields upon retrieval.
* [1;35m|[m [33m6f1a9bb6[m event: Enforce the existence of at least one part per event.
* [1;35m|[m [33ma2253898[m [test] Fix tests according to UI changes in event realm
* [1;35m|[m [33md67aef4b[m [UI] Move macros for query pages to generic.tmpl
* [1;35m|[m [33m29bb05de[m [UI] Add cdedbProtectChanges to event/change_registration and event/amend_registration
* [1;35m|[m [33m5d39e666[m [UI] Fix macros util.[form_]event_field_input() and use them in questionaire
* [1;35m|[m [33mcd222b34[m [UI] New bootstrap version with modified configuration: Less base padding, less form-group margin
* [1;35m|[m [33mb7e474a8[m [UI] Fix layout of event/change_registration and sligthly change event/show_registration
* [1;35m|[m [33me1c6c0fa[m event: Fix display of json date fields.
* [1;35m|[m [33m0570b097[m event: Allow None for fields with finite option list.
* [1;35m|[m [33m562dc5a5[m backend: Fix json serialization of event fields with complex types.
* [1;35m|[m [33m0702f74c[m [UI] Fix layout of event/show_registration
* [1;35m|[m [33m0960c09a[m [UI] Improve layout of event/field_summary: move explanation of options to bottom of document
* [1;35m|[m [33m5c80c35f[m event-frontend: Show course descriptions again.
* [1;35m|[m [33m9b7790ad[m assembly-frontend: Small fixme
[1;35m|[m[1;35m/[m  
*   [33m46b5be13[m Merge branch 'extra-fields'
[1;36m|[m[31m\[m  
[1;36m|[m * [33mb1b41bb8[m [UI] Modify event/show_course: Remove course description and move extra-fields
[1;36m|[m * [33m78ec443e[m [UI] Fix event/field_summary – including even fancier JS.
[1;36m|[m * [33m7651c1bc[m Improve display of new fields.
[1;36m|[m * [33m5e54336a[m event: Add customizable fields to lodgements and courses.
* [31m|[m [33m52b6a8b8[m [UI] Fix layout of event/registration_status and event/amend_registration
* [31m|[m [33m511f4bdb[m [UI] Fix layout of event/register
* [31m|[m [33m10c5e6da[m auto-build: Add additional safety sleep.
* [31m|[m [33m918f7de2[m auto-build: Update to new debian stable release.
* [31m|[m [33m6760e230[m event: Add free form text to registration mail.
* [31m|[m   [33mdae542d0[m Merge branch 'explicit-subs'
[31m|[m[33m\[m [31m\[m  
[31m|[m [33m|[m[31m/[m  
[31m|[m[31m/[m[33m|[m   
[31m|[m * [33mb9197879[m ml: Fix error path.
[31m|[m * [33m8dd04f28[m ml: Add override bit to subscriptions.
* [33m|[m [33me204ebbe[m event: Add note for part creation.
* [33m|[m [33m1bf00159[m UI/event: Fix layout of download page, fix tests and spelling of nametag url
* [33m|[m [33m5d0e0840[m UI/event: Change layout of course_list and show_course
* [33m|[m [33mf220cc10[m frontend/event: Fix default query 'minors'
* [33m|[m [33m40fb229e[m UI: Fix main navbar for non-JS users
* [33m|[m [33m85ec793f[m UI: Replace Bootstrap with customized version. Only required modules and less whitespace.
* [33m|[m [33m939a1ca3[m UI: Fix some CSS warnings and improve comments in css file
* [33m|[m [33mf0f472cb[m UI/assembly: Fix JS for multiple choice voting form: updates on page onload now
[33m|[m[33m/[m  
* [33mcbd38372[m Todos from wa1617
* [33m85706d7b[m core: pretty up this link a bit
* [33md338cdd1[m auto-build: Update to new debian point release.
* [33m1cdaa39b[m auto-build: ftp is blocked on the server, so use http
* [33m79b24140[m Frontend: Fix JSON encoding again. Was broken by encoding json special charcter ']'
* [33m4959e492[m event-frontend: Forbid adding of parts for events with registrations.
* [33m98f66a56[m frontend: Correct JSON MIME-type.
* [33m4215607e[m Fix tests
* [33mfc540f65[m UI: Fix HTML syntax issue in query form
* [33mf6d6d1c6[m UI/event: Fix layout of create_course and change_course
* [33m8a032b43[m UI/event: Fix layout of course_stats (not finished yet)
* [33ma6909ce9[m frontend: Final fix for JSON code injection vulnerability
* [33m412591e7[m frontend: Fix JS injection vulnerability via JSON strings provisionally
* [33mbcfeb966[m UI/event: Add information on event parts to show_event
* [33m1aa8729a[m UI/event/reorder_questionnarie: Fix hiding of text based form
* [33mfefbd43a[m UI: Add drag'n'drop js for event/reorder_questionnaire and fix bug in cdedb_voting.js
* [33m8b6d9854[m UI/event: Fix layout of reorder_questionnaire. (JS will follow)
* [33m34eeb7d6[m cde-frontend: Fix template syntax.
* [33mffd936a0[m UI/event: Fix layout of questionnaire
* [33m1ced3ba7[m UI: refactor template cde/institution_summary and fix dynamicRow in event/part_summary
* [33m1023db43[m UI: Add messages for cdedbProtectAction(), remove message of cdedbProtectChanges()
* [33mcd4cfe8c[m UI: Make dynamicRow JS localizable and fix error output
* [33mca118ad4[m frontend: Explicitly annotate possibly wrong-typed dates.
* [33m2d606b6a[m event-frontend: Fix syntax in some templates.
* [33m1413679e[m frontend: Make date filters handle strings gracefully.
* [33me4cbb3e8[m UI/event: Fix dynamicRow JS usage in field_summary, part_summary and questionnaire_summary
* [33mea59820d[m UI/event: Fix layout of questionnaire_summary and add dynamicRow JS and some special JS
* [33m164f93c6[m UI/event: Fix layout of field_summary and add dynamicRow JS
* [33m855d3fa4[m UI/event: Fix layout of part_summary and add dynamicRow js
* [33m6f4721b5[m UI/event: Fix sidebar navigation and some titles and breadcrumbs
* [33m9a969f41[m UI/event: Fix layout of view_log and view_event_log. Also fix disabled button-link style.
* [33mcc768a71[m UI/event: Fix layout of show_event and change_event
* [33m0d19d9e4[m UI/event: Change navigation titles of event lists and fix layout of create_event
* [33m8355cb55[m UI/event: Fix layout of general pages
* [33m1a3b3a6a[m UI/assembly: Fix styling of file list in show_assembly
* [33m9e032915[m assembly: Fix typo.
* [33m12a98113[m assembly-frontend: Provide more attachment information.
* [33m4f63c0cd[m core-frontend: Add link to full user page if relevant.
* [33m3eb2b3d5[m tests: Fix tests.
* [33m8f4ac332[m assembly-frontend: Make attechments accessible in overview page.
* [33m419ec66f[m frontend: Enable localized dates.
* [33ma4381d58[m frontend: Fix erroneous output.
* [33m3a02cc22[m UI: Add usage of HTML5 datetime-local input fields
* [33m1ba12dae[m UI: Add error output in query form
* [33m2656de77[m UI: Fix some breadcrumbs, navigation items, titles.
* [33mc7331969[m UI/assembly: Add protectChanges JS for voteform
* [33m9482eea4[m UI/assmbly: Fix keyboard behaviour of interactive preferential voting
* [33m72796832[m UI/assmbly: Fix layout of interactive prferential voting and add documentation
* [33mde804d89[m UI/assembly: Add touch and keyboard functionality for interactive preferential voting on show_ballot
* [33m83c95951[m UI/assembly: Add Fancy JS for preferential voting in show_ballot
* [33m2485a54b[m UI/assembly: Add first JS for show_ballot to dynamically disable checkboxes in classic voting
* [33m50498396[m tests: Fix breaking from i18n.
* [33mfccb4923[m i18n: Fix Typo.
* [33m87f680c6[m UI/assembly: Add usage information for preferential voting
* [33m1d6913f6[m frontend/assembly: Allow setting use_bar in crate_ballot
* [33mf5c5d59c[m i18n: Fix E-Mail spelling.
* [33ma30bb8da[m i18n: Add translations.
* [33mf5f6b7fe[m UI: Bulk fix spelling of 'E-Mail' and 'E-Mail-Adresse'
* [33me592da08[m frontend: Fix some Mail-Templates
* [33maf20ba68[m UI: Change design of 'dots'
* [33mf25f6066[m UI: Fix several layout issues, mainly concerning icons and accessibility
* [33m20e28033[m UI/assembly: add protectAction-JS for concludeassemblyform
* [33mfb20a504[m UI: Replace wide layout by wide content page
* [33ma5ff2069[m UI: Improve layout of new elements
* [33m5eb4223c[m lint: Make it happy.
* [33m4e5c079a[m errors: Add error message, so the user is not left in the dark.
* [33m3f19b495[m i18n: Switch from homebrew solution to GNU gettext.
* [33m5d85a9c1[m frontend: Add comment that got dropped somehow.
* [33m9c94b188[m cde: Actually test quota for member views.
* [33me63c5b30[m frontend: Also delete symlinks to csv template.
* [33m34253b4d[m cde-frontend: Fix special case of member search returning one result.
* [33mf4dcf28c[m frontend: Produce RFC 2822 compliant date header.
* [33mde0e9b17[m frontend: Remove now obsolete template
* [33m15cc8ab9[m frontend: Add JSON download capability to queries.
* [33m748f4fa0[m assembly: Add vote count to result of classical voting.
* [33m4221d740[m assembly-frontend: Do redirect upon POST.
* [33mf199d678[m query: Fix queries
* [33m533a99f8[m query: Document difference between qview_core_user and qview_persona.
* [33m8d3cabee[m config: Make current commit hash available.
* [33mca88a485[m Fix core/admin_change_user and fix tests
* [33mc354f28d[m UI: Add info about rst capable fields
* [33m283b190c[m UI: Improve HTTP 403/404 pages
* [33ma1289227[m query: Change column list and order, add column titles, fix tests
* [33mff79556b[m UI: Add missing jshints and cdedbProtectChanges
* [33mb715d153[m frontend,UI/assembly: Protect ballot delition with JS instead of checkbox
* [33me9a865a9[m UI: Add cdedbProtectChanges() for */create_user
* [33m1d652326[m UI/assembly: Add information about number of votes
* [33m5c5f2ddd[m UI: Fix and refactor jshint
* [33m1657a895[m past-courses: Display number of course.
* [33mfa6746e6[m [UI,frontend]/assembly: Fix tests and handling of rejection in classical vote
* [33mb82d02df[m UI: Change layout of add participant/candidate boxes
* [33m60c5f952[m UI/assembly: Improve presentation of results in show_ballot
* [33me9a84abc[m UI/assmbly: Restructure show_ballot
* [33m7808e729[m UI/assmbly: Add ballot state information, add bar option and change information order
* [33ma8fdd1c7[m UI/assembly: Improve state info in list_ballots
* [33md4640638[m frontend: Produce fully qualified URLs in some situations.
* [33maf9124d9[m cde-frontend: Fix money transfers.
* [33m6bcd2dcf[m frontend: Add customized error pages.
* [33mf39278b0[m ml: Add info text what entries are allowed.
* [33me766fe2e[m ldap: Make code compatible with ldap3 version 2.
* [33m7c42eddf[m assembly-frontend: Prepare for making rejection similar to other options.
* [33m5df385eb[m assembly-frontend: Add better representation of result to ballot page.
* [33me8b93799[m assembly: Revamp bar semantics
* [33m42ce4895[m assembly-frontend: Add voting info to ballot list.
* [33m6c860cbb[m UI/assembly: Fix general layout of assembly/show_ballot
* [33m750036ae[m assembly: Fix some issues.
* [33ma45f77e3[m frontend,UI/assembly: Fix and improve assembly/list_ballots
* [33mdb0509c4[m frontend,UI/assembly: Move external_signup form to list_attendees
* [33m49f356eb[m frontend: Quick hack to make attachments with utf-8 chars work.
* [33m41c9edc9[m assembly-frontend: Do more fine-grained listing of ballots.
* [33md6ea46e6[m assembly: Fix snafu.
* [33m713fa2dc[m Revert "assembly-frontend: Fix encoding problem."
* [33m7156ecde[m assembly: Fix mail template and minor cleanup.
* [33m8d4b44b4[m assembly: Tune assembly functionality.
* [33m2324a278[m UI/assembly: Fix layouts
* [33m87c62bda[m frontend,UI: Some fixes related to money formatting and information on I25+
* [33m01eb346b[m auto-build: Correct remote URL
* [33me1e790be[m frontend,UI/cde: Fix index for non-members
* [33mc9a6ff37[m UI/cde: Fix layout of index
* [33m18e4e775[m cde-frontend: Fix date replacement.
* [33maaf6a789[m UI: Fix some minor issues related to queryform and scripts
* [33m791f5563[m frontend,UI/core: Improve styling of dashboard
* [33mdfe89c46[m UI: Add template macro for bootstrap panels
* [33m7fb0fcba[m core: Fix tests.
* [33mc6dec3ad[m core-frontend: Add rudimentary dashboard.
* [33m9671b7c3[m genesis: Improve verbosity of messages.
* [33m4687328c[m core: Fix tests
* [33m2ac9726d[m core: Fix history view to not mask rejected changes.
* [33md13ec5ca[m core: Make interface work for realm admins.
* [33m2c516a7b[m assembly-frontend: Fix mime type of attachments.
* [33mb54e6bda[m assembly: Move addition of attachment URLs.
* [33ma7658281[m assembly-frontend: Fix encoding problem.
* [33maefdd0ca[m cde-frontend: Improve membership balance presentation.
* [33m28cb1951[m UI/assembly: Improve layouts of single assembly and related pages
* [33m5d909339[m UI/assembly: Tidy up general area of assembly
* [33m6492394f[m tests: Fix tests.
* [33m258debcd[m frontend: Add separate banners before and after login.
* [33m7de4c142[m cde-frontend: Restrict to cde users.
* [33mac182595[m cde-frontend: Add membership fee information on cde index page.
* [33mf50a3948[m frontend: Make debugstring exclusive to dev environment.
* [33m5d99afa6[m query: Fix testing of non-string fields.
* [33m1802aceb[m genesis: Tweak default value for MAX_RATIONALE.
* [33m515f52ef[m genesis: Propagate MAX_RATIONALE to the template.
* [33m9676a4ee[m genesis: Add helpful message, if email is already taken.
* [33m356a424c[m core: Tweak password strength criteria.
* [33mdd9c0c8a[m core-frontend: No password reset email for admins.
* [33m5761cddc[m ml: Require correct audience for linked events and assemblies.
* [33mec537963[m ml-backend: Prevent moderators from upgrading to opt-out lists.
* [33mabe24edb[m UI/core: Improve user search sites
* [33mc39c68bd[m UI: Fix event navigation and navbar layout
* [33mebbe47d0[m UI: Make sidebar navigation titel screenreader-only and fix collapsed navbar layout
* [33m68e062ad[m UI/core: Small improvements for core/show_user
* [33mc7f4c657[m UI: Complete rework of site layout to approach CdE corporate design
* [33m883af076[m UI: Disable prefilling password fields
* [33m48c3af3b[m UI/ml: Clarify mailinglist audience management, add js to dynamically hide conflicting fields.
* [33mef1b6204[m UI: Improve queryform JS: Enable filtering for selected rows and preview of default queries
* [33mb055d31b[m UI: Use dynamic url for cdedbSearchPerson AJAX request
* [33m5ed158a6[m UI: Improve search_persona with selectize. Adds DB-ID and email display and improves entering DB-ID.
* [33m53371561[m db: Add some documentation about mailinglists.
* [33m4159b767[m UI: Improve layout of ml/list_mailinglists and fix ml/index, ml/management
* [33m67bdc623[m UI: Fix links on ml/show_mailinglist using visible flags
* [33me1ba61d1[m frontend,UI/ml: Improve show_mailinglist page: Add information about pending subscription request
* [33m5230317f[m ml: Further restrict mailinglists.
* [33ma162252e[m frontend: Make validation ready for i18n.
* [33ma547c8e1[m frontend: Adapt notifications to new scheme.
* [33md4808bd5[m frontend: Revamp notifications in preparation of i18n.
* [33m2a680178[m doc: Fix docstring.
* [33m9d040198[m lint: Fix whitespace w.r.t. tests.
* [33m3d55da3a[m lint: pretty up the code
* [33m627aee76[m ml-frontend: Make additional infos in list_mailinglist available.
* [33m5184d00c[m ml: Make resetting of subscription address work.
* [33m3c42d5a5[m ml: Disallow simultaneously linking to an event and an assembly.
* [33mfac330e2[m ml: Actually check for AudiencePolicy.
* [33mfa77e97f[m ml-backend: Allow cancellation of subscription requests.
* [33m65b50e04[m ml-backend: Add lookup for subscription relation.
* [33maf65340d[m ml-frontend: Improve visibilty checking.
* [33m4ee82cef[m Really fix import error.
* [33mad0e5f7f[m Fix import error.
* [33m38b0fdf5[m frontend: make event registration check more global
* [33m310c805a[m core-frontend: reenable more searches in select_persona
* [33meef26508[m query: Expose primary key in query results.
* [33m4332159c[m Frontend/UI:ml: Show more information on ml/show_mailinglist and improve layout of ml/index
* [33mb0eed673[m Fix tests related to new whitespace elimination and mailinglist UI changes
* [33mecec5195[m UI:ml: Fix layout of ml/management, ml/check_states and ml navigation
* [33m1f9df230[m UI:ml: Restyle ml/management (and fix some other layout things)
* [33m13112973[m UI:ml: Restyle create_mailinglist
* [33m1b8a4ed1[m UI:ml: Add breadcrumbs
* [33m5ab4c831[m UI: Change sidebar navigation heading
* [33m004aeed8[m UI:ml: Restyle show_mailinglist
* [33mf01c8b34[m UI: Change assembly icon 'stats' → 'bullhorn'
* [33m0741d91b[m frontend: Fix and improve whitespace elimination
* [33m16b8704f[m UI:ml: Fix layout of ml/base, change_mailinglist and ml logs
* [33ma535c0dd[m UI:CdE: Fix show_past_course title
* [33ma6d3c83f[m test: Change assertTitle to check html title instead of h1 headings
* [33m9566f426[m core-frontend: Fix select_persona to work the similar to the js code.
* [33m6c1a792b[m Frontend/UI:CdE: Correct participant delition and addition selection list in past events and past courses
* [33m5a2c3d01[m UI/CdE: Add selectize.js for adding participants to past events.
* [33m7fde0b9d[m Frontend/UI:cde: Improve participant listing of past events and past courses
* [33m72a48542[m cde-frontend: Fix participation handling for past events/courses.
* [33me8c8f492[m past-event-backend: Fix cascading deletion of a past course.
* [33m6a540095[m Test: Fix batch-admission test
* [33me58043c2[m Frontend,UI: Improve batch-admission (2): Fix magic links for 'pcourse_id' key and improve submit buttons
* [33mbf456c3b[m Frontend,UI: Improve batch-admission: hide invalid resolution options and add magic link javascript
* [33m90fd6759[m tests: Add test for new API.
* [33mf2c6778b[m core-frontend: Add API for JSON persona information.
* [33m78191c8b[m Test: Fix tests related to query results
* [33m5c957eb9[m UI: Add listselect javascript and improve query result list
* [33m4f37514c[m UI: Add selectize.js to queryform list filters
* [33m4d48d693[m core-frontend: Include more information in changelog metadata.
* [33m1af13e18[m core-frontend: Show change history.
* [33md186ce1c[m frontend: textareas also have to preserve newlines.
* [33mda74677b[m cdedb: Miscellaneous changes, mostly adding a number to past courses.
* [33mfe8cd9d5[m frontend: Notify if maintenance mode is active.
* [33m4e82bd4f[m core-backend: Improve maintenance mode.
* [33mb94b480b[m tests: Improve quick-check.
* [33mea659234[m tests: Fix tests and add quick-check.
* [33m0fce0c37[m core: Implement maintenance mode.
* [33m46bfabe3[m config: Tidy up config.
* [33m63c39e18[m core-frontend: Add message_of_the_day in meta_info form.
* [33mb865a010[m cdedb: Add sanity checks for live instance.
* [33m03da8545[m UI/Core,CdE: Fix layout FIXMEs from recent modifications and enhance information on affected pages
* [33mdb4ceb68[m cdedb: Rework logging.
* [33mf120135b[m auto-build: One more package for postgresql
* [33m17d8c4df[m ldap: Create local password location.
* [33md7340664[m core: Fix listing of genesis cases.
* [33mff4547f1[m query: Add fuzzy operator.
* [33m65c48fa6[m batch-admission: Actually add past-event stuff.
* [33m16d16bb3[m core-frontend: Add enhanced admin user search.
* [33m78b5580b[m event-frentond: Add automatic assignment.
* [33m4c6e43ab[m event: Add minimal and maximal sizes to courses.
* [33m1c7529f7[m event: Add information whether a course part is actually happening.
* [33m3f7727fc[m cdedb: Remove all 0 values from enums.
* [33meecc875b[m cdedb: Rename cde_info to meta_info.
* [33m268b8b03[m core-frontend: Add message of the day.
* [33m149c5df1[m cdedb: Make lint happy.
* [33m0a56c8ea[m cdedb: Add a lot more internationalization.
* [33m63486416[m cdedb: Even more zapping of redundant 'data'
* [33me9ea8c8c[m cdedb: Excise the left over _data suffixes
* [33m051103d6[m event: Transition from 'field_data' to 'fields'
* [33m4d279613[m event: Excise _data suffix.
* [33ma86a399c[m mailinglist: Excise _data suffix
* [33mc275a97e[m assembly: Excise _data suffix
* [33mb3adca5c[m doc: Add page about typical request.
* [33m32e22404[m event-frontend: Provide additional data for event listings.
* [33meee74938[m validation: Fix picture validation.
* [33m9c2b64f2[m tests: Fixes pertaining to recent password policy changes.
* [33mdffe472b[m core: Tune password policy.
* [33m63c4de63[m core-frontend: Allow resetting of foto.
* [33m060774ac[m genesis: Make realm attribute configurable by core admins only.
* [33md8f171bb[m UI/CdE: Fix layout and js-protect-script in lastschrift_index
* [33md33ac7ec[m UI/Core: Fix layout of set_foto and modify_membership and some breadcrumbs
* [33mc5b4c0bd[m auto-build: Make documentation available.
* [33m1fe5fe38[m auto-build: Make qemu caching strategy configurable.
* [33mfe967245[m auto-build: Make tests run in auto-build VM.
* [33m98c543f9[m doc: Mention cache=unsafe option to qemu.
* [33m4d9c86cf[m UI: Add javascript to allow user ids without check digit.
* [33m70ebaf3c[m auto-build: Update to new debian point release.
* [33m2c54892a[m query: fix to fix to displaying queries.
* [33mb2dac72d[m frontend: Avoid redirects after validation errors.
* [33m3caa8a2d[m core-frontend: Tune password reset pages.
* [33m31b1e347[m cde-frontend: Process multiple lastschrift transactions at once.
* [33maf50fc03[m core-backend: Change return code of user editing if no change was made.
* [33m28cbbfad[m query: Fix default queries.
* [33m0bd8a590[m sql: Increase the available precision for max_dsa.
* [33me8acbf96[m cde-frontend: Replace exceptions with user parsable error messages.
* [33md30e0e32[m frontend: Fix inter-realm accesses.
* [33me19732a6[m cde: Fix consent form.
* [33m5775dfa9[m UI/core: Fix problematic highlighting due to omitted versions.
* [33m44ff52bd[m UI/Core: Highlight uncommited versions in profile history view.
* [33m39d12bc0[m UI/Cde: Adapt navigation and index page to users' privileges
* [33me4487d99[m UI/CdE: Fix navigation and layout of money transfers
* [33m6b8a41c6[m UI: Change core navigation
* [33mc2fb0bda[m cde-frontend: Add finance log.
* [33mac1f36d5[m sql: Do explicit close on database connection.
* [33mb41f8257[m genesis: Move work to realm admins.
* [33m3398f2e7[m profile-page: Tune presented data.
* [33m45e2eb5d[m lastschrift: Add success buttons.
* [33m9e82721e[m frontend: Unify admin_change functionality.
* [33me24192bc[m auto-build: Update config files with values from vanilla debian.
* [33m336d8e6f[m frontend: Finish unification of profie page.
* [33m8f3b4688[m code: Kill magic white-space.
* [33mb1eb1123[m tests: Add missing file.
* [33m59819250[m frontend: Redirect all links to the unified profile page.
* [33m48f64238[m cde-frontend: Implement money transfer processing.
* [33mf84e0bd0[m test: Fix tests broken with recent changes.
* [33m0c31731e[m core-frontend: Centralize all user editing.
* [33mda3495ad[m frontend: No edit forms for archived users. II
* [33m039d588f[m frontend: No edit forms for archived users.
* [33m7b8a6c9d[m UI: Add critical form confirm javascript
* [33m5fd88746[m UI: Improve genesis guidance texts and layout of genesis case list
* [33ma8a23124[m UI: Improve user edit, promote and privileges forms
* [33mf1905f2d[m UI: Fix form input macros to display errors correctly
* [33m37c147f0[m UI: Fix CdE member search and improve layout of semester management
* [33m16394dd9[m past-event: Fuse two queries.
* [33m9e205841[m past-events: Restrict links to user profile pages.
* [33m2ecf0937[m core: Tighten screws on member data sets.
* [33m7c799812[m cde-frontend: Revamp past-event handling.
* [33m017f92c8[m frontend: Add pending change notification to user edit page.
* [33m6824f01a[m UI: Restyle batch_admission validation results
* [33mb3f5f538[m UI: Rename past events in navigation to prepare access for non-admin users
* [33m8d1019fc[m frontend/UI: Restyle past events list
* [33m3e7cf1cb[m past-event: Tune the past_event_stats method again.
* [33m06766236[m past-event: Fix the past_event_stats method for empty past events.
* [33m5c4a5069[m UI: Fix dynamic row JS in institution_summary page for validation failures.
* [33m3d4735e6[m UI: Add form change protection JS, remove auto bootstrap tooltips
* [33m0cdf7daa[m frontend: Explicitly notify for failed validation.
* [33mb6ef9e57[m admin_change: Add note if there is a pending change.
* [33me4566545[m changelog: Improve changelog semantics.
* [33m1eacfee6[m frontend: Tune create_last_index.
* [33mdba1fccf[m past-event: Tune the past_event_stats method.
* [33m5c0b233d[m frontend: Add knowledge about number of newly created entries.
* [33mf519757c[m past-event: Add statistics about past events.
* [33m0f6f543d[m UI: Clean up template code and improve user profile layout
* [33m2c28fd64[m UI: Reorder fields in change_user forms
* [33m88e94a51[m UI: Redesign pending changes inspection
* [33m12d01def[m lastschrift: Fix logic to not show unrelated transactions.
* [33m59e959f6[m frontend: Replace list by tuple.
* [33m199299d8[m UI: Fix layout of past events and related pages
* [33m6baf0285[m UI: Fix layout of consent decision form and improve rensposiveness of member search
* [33mf2e8f9d7[m UI: Fix minor misbehaviours in javascripts and show_user.
* [33m1231fd51[m UI/frontend: Redesign user history page
* [33mc880f340[m UI: Add macro output_given_displayname to improve name rendering in profile
* [33mf5618061[m UI: Improve definition list layout
* [33m10ba365f[m UI: Add responsiveness for sidebar navigation
* [33m94017fdb[m UI: Fix core user profile
* [33m4156d270[m UI: Add make_icon template macro
* [33mac9177af[m UI: Add conditional link to lastschrift at CdE index page
* [33mb055b550[m Add fancy JS for fancy editable list forms and implement in instituation_summary.
* [33mb6fbf9e1[m UI: Fix some minor layout issues in CdE realm.
* [33maa44227c[m UI: Fix layout of cde logs and semester page
* [33m6d4aa565[m UI: CdE realm: Fix navigation, add breadcrumbs, fill index page
* [33ma60c0716[m frontend: Decrease heading level in rst display.
* [33m0d50d8ce[m auto-build: Increase number of database connections.
* [33mdf6bab74[m Templates: Fix layout of lastschrift related pages
* [33m40bb3a68[m Templates: Fix styling of CdE member search
* [33me66c214b[m Templates: Fix styling of cde user search, batch admission and user search
* [33mb78e98ad[m Templates: Add 'horizontal' option for form_input_* macros
* [33m02d1fd62[m event: Add course assignment tool.
* [33m30a54148[m core-frontend: Mark more fields as private.
* [33m5392c5be[m core-frontend: Unify profile pages, step 1.
* [33mb1b7d104[m frontend: Reduce redundant writes.
* [33m51c8ca9b[m cde-frontend: Make institutions into a summary page.
* [33m0be46d50[m past-event: Move past-event stuff to cde realm.
*   [33m6a2aa056[m event: Untangle event/past-event functionality
[34m|[m[35m\[m  
[34m|[m * [33mec10b361[m one last fix to make it work
[34m|[m * [33m79be7ef0[m ...
[34m|[m * [33m0234509e[m fix to previous fix
[34m|[m * [33maccfba8f[m fix for removing list_events
[34m|[m * [33md370cee4[m remove list_courses from backend events
[34m|[m * [33m88b8576c[m remove list_events from backend events
[34m|[m * [33m4e1a1e4d[m fix some typos in doc
[34m|[m * [33m2d1bc038[m remove 'past' parameter from frontend list_events and offer alternatives
[34m|[m * [33mf69fd3ee[m remove 'past' parameter from frontend 'list_courses' and offer alternatives
* [35m|[m [33md38a5a02[m Fix template registration_query + small change on util.format_query template macro
* [35m|[m [33mb67154f2[m doc: Fix docstring syntax.
[35m|[m[35m/[m  
* [33ma260b9f3[m cde-frontend: Improve member search.
* [33m770f5764[m cdedb: Shape up deletion of things.
* [33m2e6423aa[m query: Add primary key to all queries.
* [33m7797fc5a[m query: Make ordering easier.
* [33m2b80a71a[m frontend: Add missing links to csv template.
* [33md66e0a34[m Restyle default queries and add action areas to query pages
* [33m78435e74[m event-frontend: Check for deletability.
* [33mc9b8a5fc[m validation: Check for empty file uploads.
* [33me66adc78[m event-frontend: remove locking where superfluous.
* [33m808947db[m Add breadcrumbs for core realm and fix navigation and some forms there
* [33m61e2a41d[m Simplify template code for breadcrumbs
* [33m9bfede3e[m frontend: Make separator configurable.
* [33m92a09cde[m Fix CSV-Download in query form template and readonly option of util.href
* [33m681c5e62[m Add javascript to shorten query URLs
* [33m0714702c[m Fix tests dependend on queryform's name-attribute
* [33maf937cbb[m Restyle query result tables
* [33me3512d7e[m Add validation error display for query form filter values
* [33m610f6244[m Finish javascript query form
* [33me50e2ad2[m Adapt template and javascript to new query operators
* [33mf9840b4f[m Add fancy javascript query form.
* [33md81e49b4[m Fix query form list input
* [33mc7231210[m event-frontend: Add manipulation of event fields via summary page.
* [33m9cb57f9b[m cdedb: Clarify deletion and removal code.
* [33m89ce0bae[m doc: Note on how to handle data destruction.
* [33m61421df3[m query: Add more operators.
* [33m8a4eae04[m Change queryform filter value format and add 'no filter' to operator select.
* [33m4dc7d6c7[m Add javascript to auto focus login form
* [33m651a3691[m Remove jquery_preamble macro and fix jquery_ui scripts.
* [33me84d9521[m doc: Add section about performance enhancements.
* [33me38c158f[m makefile: Use existing example.
* [33md530a061[m event-frontend: Implement manipulation functionality for parts.
* [33m5327ddff[m event-frontend: Add information to course stats.
* [33mc4eda70b[m event-frontend: Implement new questionnaire manipulation functionality.
* [33m354af2c9[m event-frontend: Automatically provide is_locked in event templates.
* [33m207b3f22[m ml-frontend: flatten hierachy
* [33m56483ac9[m frontend: Kill unnecessary third component of entries array in util
* [33m31630fa4[m frontend: move batch admission to cde realm
* [33mc25da039[m event-frontend: Move some functionality around.
* [33mcb08ba01[m validation: Make more use of "id" validator.
* [33mb3b5197a[m query: Disable some operators for fields with selection lists.
* [33m9078f602[m validation: Add _id validator
* [33m57712286[m Redesign query form for non-javascript users.
* [33ma3382847[m Improve input macros
* [33mb5d16248[m frontend: Fix empty lists in werkzeug MultiDicts.
* [33m2f701a12[m database: Move some data around.
* [33mbd44b5a5[m Fix checkbox template, so they keep their selection.
* [33m97aeda7d[m tests: Fix tests for good.
* [33mc801479f[m tests: Fix more tests
* [33meb969488[m tests: Fix some tests failing due to frontend changes.
* [33m898f175c[m frontend: Fuse query forms and results.
* [33m5728908c[m Simplify breadcrumb and improve layout of genesis forms and genesis list
* [33m65ff91b0[m Fix event_field_input
* [33mcf4e8da0[m frontend: Fix other half of log watching with possible None values.
* [33md2eed00c[m Improve core log filter forms and layout of username change forms
* [33mc191b4d1[m Clean up /core/self/change and /*/persona/*/adminchange
* [33m77f9c366[m Refactor template macros for input fields
* [33mcb9a4e16[m Fix formular layout and clarify text of genesis request and password reset
* [33mf6102687[m frontend: Sanitize requested IDs.
*   [33m61c954db[m Merge branch 'ui-bootstrap2'
[36m|[m[1;31m\[m  
[36m|[m * [33m611aeac0[m Fix layout of core/log and core/changelog/view
[36m|[m * [33m060574b6[m Add favicon and remove area for logo
[36m|[m * [33m3cb42600[m Fix main navbar
[36m|[m * [33m6a197296[m Add support for wide layout for unrestricted display of wide lists on large screens.
[36m|[m * [33m1f016257[m Fix sidebar navigation in Core realm
* [1;31m|[m [33m5350251e[m frontend: Add CdE-logo
* [1;31m|[m [33m340ea43c[m core-backend: Allow multiple logins from the same IP.
* [1;31m|[m [33me235f4e1[m frontend: Make timeout of encoded parameters configurable.
* [1;31m|[m [33m83a05996[m frontend: Add realm transitions.
[1;31m|[m[1;31m/[m  
* [33ma9ac6ba9[m frontend: Enable ambience for institutions.
* [33mf0aeb65b[m event-frontend: Fix link appearing twice.
* [33m70927fb3[m event-frontend: Fix missing doc-strings.
* [33m5be849bf[m auto-build: Update Debian to 8.4.0
* [33m13a45517[m event: Move institutions to their own table.
* [33m4220ac39[m frontend: Add reStructuredText
* [33maec2798a[m event-frontend: Improve LaTeX puzzles
* [33me4127c90[m cdedb: Use python3.5
* [33m87e92322[m core-frontend: Add history view
* [33m8912f7f0[m cdedb: Implement batch admission.
* [33m25cf44b6[m auto-build: Prefer IPv4 over IPv6
* [33m12dfe0c1[m event: Allow batch input of courses when creating a past event.
* [33mca237c53[m cde: Make use of trial membership.
* [33mf83e4e79[m cde: Add period and expuls management.
* [33mebc39ec1[m event: Typo in nametags
* [33m46d8eb85[m event: Improve nametags
* [33m3ed62a77[m validation: Add upper case letters to asciificator.
* [33mce774c7d[m auto-build: Fix preseeding.
* [33md6d01701[m event: Implement offline support
* [33m65772370[m auto-build: Use newer ldap3.
* [33m810db99d[m cdedb: Fix a bit of test coverage.
* [33mb40782c7[m cdedb: Fix FIXMEs
* [33m1a1bfc48[m frontend: Move archived user search to core realm.
* [33m2aec4df2[m core-frontend: Add page for adjusting privileges
* [33md6f4cb8f[m frontend: Make more user management stuff generic.
* [33m36518f44[m frontend: deduplicate user detail pages
* [33m82059d0f[m auto-build: Adapt to removal of RPC.
* [33m957974c9[m cdedb: remove RPC mechanism.
* [33mbe18dcc6[m core: Reintroduce the fulltext attribute
* [33mbbcae8e8[m event: Seperate namespaces for events and past events
* [33md69799bf[m cdedb: Change user management to unified table.
* [33m14a1ec84[m frontend: Fix HTML
*   [33m9a3a7189[m Merge branch 'ui-bootstrap' into master
[1;32m|[m[1;33m\[m  
[1;32m|[m * [33m250c8974[m Fix test suite.
[1;32m|[m * [33m9363b37c[m tests: Use new syntax for detection of notifications.
[1;32m|[m * [33m4d6e0b4e[m Begin work on breadcrumbs. Parts of event realm finished.
[1;32m|[m * [33m021934cf[m Fix event/show_course.tmpl and lodgements.tmpl (new macro definition in util.tmpl)
[1;32m|[m * [33ma3f76284[m Fix sidebar navigation using new ambience data.
[1;32m|[m *   [33mae49cd13[m Merge branch 'master' into ui-bootstrap
[1;32m|[m [1;34m|[m[1;35m\[m  
[1;32m|[m * [1;35m\[m   [33m4184b209[m Merge branch master
[1;32m|[m [1;36m|[m[31m\[m [1;35m\[m  
[1;32m|[m * [31m|[m [1;35m|[m [33m1a993fc0[m UI: Fix forms by completly refactoring input macro names
[1;32m|[m * [31m|[m [1;35m|[m [33m9f51c45a[m UI: Improve user profile page (cde/show_user)
[1;32m|[m * [31m|[m [1;35m|[m [33m8c817f47[m UI: Fix login form
[1;32m|[m * [31m|[m [1;35m|[m [33mb7f3e76c[m UI: Apply new side navigation in all realms.
[1;32m|[m * [31m|[m [1;35m|[m [33m188c955c[m UI: Adapt more elements to Bootstrap theme
[1;32m|[m * [31m|[m [1;35m|[m [33m728fb629[m UI: Apply Bootstrap layout to base template
[1;32m|[m * [31m|[m [1;35m|[m [33m9c3c52e7[m Base template: recover dynamic jquery verson symlink
[1;32m|[m * [31m|[m [1;35m|[m [33mb4343f2f[m Replace jquery with minfied version and apply bootstrap theme to base layout
[1;32m|[m * [31m|[m [1;35m|[m [33med4d5e46[m Add full bootstrap css framework (css, js, icon font). Should be customized later to provide smaller css and js files, containing only the used bootstrap features.
* [31m|[m [31m|[m [1;35m|[m [33m14da9455[m auto-build: Note a FIXME
[1;35m|[m [31m|[m[1;35m_[m[31m|[m[1;35m/[m  
[1;35m|[m[1;35m/[m[31m|[m [31m|[m   
* [31m|[m [31m|[m [33m2989a8c9[m cdedb: Actually fix Pyro4 configuration
* [31m|[m [31m|[m [33m61dc5ac3[m frontend: Fix Pyro4 usage
[31m|[m [31m|[m[31m/[m  
[31m|[m[31m/[m[31m|[m   
* [31m|[m [33m510c1ac9[m frontend: Add ambience context
* [31m|[m [33m9a592fee[m cdedb: Add todos and make linter happy.
* [31m|[m [33mb0548d24[m cde-frontend: implement 'Initiative 25+'
* [31m|[m [33m5e223be5[m cde-backend: Implement direct debit functionality.
[31m|[m[31m/[m  
* [33m1cafcce3[m frontend: Change persistence of notifications through a redirect.
* [33m757f8aee[m past-event: Add column 'tempus' to past_event.events
* [33mad194333[m auto-build: Update to Debian 8.1.0
* [33me2afea9a[m database: Add lastschrift tables.
* [33m4ed7d649[m cdedb: Clarify data modell.
* [33mcd32734b[m doc: Update TODO document
* [33m5114655a[m todo: Add markup for some fields, so that users can be a bit more expressive.
* [33mc6801a1a[m assembly: Add a frontend.
* [33m5f039a22[m doc: more notes from PA15
* [33m5b06d64a[m doc: Update specification with discussion from PfingstAkademie.
* [33m8e8956d5[m auto-build: Add new backends.
* [33m2343b7c1[m auto-build: Adapt to Debian Jessie.
* [33m37f7033f[m doc: Fix renaming of sphinx default theme.
* [33m3088b2e1[m auto-build: Install make.
* [33mc513fa9e[m auto-build: Fix patch.
* [33m0a0025c5[m auto-build: Use something less huge than texlive-full.
* [33m03aa10e6[m event: Add archiving functionality.
* [33m10b381af[m assembly-backend: Introduce the assembly backend.
* [33mbc25571e[m cdedb: Add attributes to persona.
* [33m4e58ca1b[m ml-frontend: Create frontend for the ml realm.
* [33md2496db1[m cdedb: Add more logging.
* [33mb5948039[m ml-backend: Add mailinglist backend
* [33mdd01d70d[m cde-frontend: Mail notification of pending changes.
* [33m90b3ef1d[m event-frontend: Fix validation in registration_query_action.
* [33m1cc5a18a[m frontend: Centralize common javascript handlers.
* [33m3ce38529[m auto-build: Increase image size.
* [33m5a921ce1[m frontend: Improve generic notifications.
* [33m1f4908b5[m cdedb: fix style issues
* [33m864150ed[m frontend: Rename variable for number of LaTeX runs.
* [33m8e4bf2ab[m event-frontend: Implement event management.
* [33mf13c7ede[m autobuild: Update scripts for Jessie.
* [33m014074c4[m event-backend: Add registrations, lodgements, questionnaire and query.
* [33mf085fc34[m event: improve sidebar
* [33m5b0974a4[m event: Implement events and courses.
* [33m27e6fa71[m doc: Add info on refreshing from changed code.
* [33m9e4c0f54[m doc: Add section about vdi image.
* [33m1c9e5487[m autobuild: actually create vdi image
* [33m562440e3[m autobuild: Reintroduce vdi image
* [33mf73ef42d[m cdedb: Add account creation.
* [33m0a3ae1a7[m cdedb: Add modification of membership state and privilege levels.
* [33mbd2509a3[m cdedb: Add activity toggling.
* [33mf15d398c[m cdedb: refactor changelog functionality
* [33m6ee1dbf2[m cdedb: refactor privilege system
* [33me5e30888[m cdedb: Add administrative user change functionality.
* [33m4ade018d[m cde: Add archive search.
* [33m94d28f56[m cdedb: Improve general query functionality.
* [33m6e3a239f[m cdedb: Abstract queries and member search
* [33m8daafd23[m constants: use enums
* [33maeafabbd[m tests: adapt to latest changes
* [33m32340f68[m doc: Add user feedback
* [33mad84a79f[m frontend: place no misdirecting links on pages with big forms
* [33m8bb1ff99[m cde-frontend: Fixes relating to consent page.
* [33m3e6cd818[m auto-build: add sleep after posgresql restart
* [33mf0de325a[m auto-build: debian upgraded postgresql
* [33mdc246101[m cde-frontend: Add page for consenting to searchability
* [33md930d58a[m core-frontend: Add admin overrides for password reset and username change.
* [33m214732d2[m cde: Add profile pictures
* [33mdcb8e195[m sql: use json to store extfields
* [33mc810f5ea[m core-backend: Use unambiguous characters for autogenerated passwords
* [33m563bed56[m cde: Add frontend for administration of changelog
* [33mcf44da05[m cde: Add changelog functionality
* [33mf74aa855[m auto-build: move host-key to appropriate location
* [33m5aaafa20[m auto-build: Improve mail subject to mention v2
* [33md740c840[m auto-build: Fix host key for ssh
* [33mf203605d[m auto-build: Fix hack to repo URL
* [33me1e2335a[m auto-build: hack repo URL
* [33m76ec14f6[m cdedb: improve test-suite w.r.t. auto-build vm
* [33m28c23f76[m cdedb: bullet-proof makefile against non-bash environments
* [33m6733a5e4[m cdedb: repair verschlimmbessert makefile
* [33m87ff5eea[m auto-build: last fixes
* [33m327a3caf[m auto-build: Refactor and add documentation
* [33m40700f66[m auto-build: Typo
* [33m7dd03976[m auto-build: tune options (128 megs of default RAM are not enough for Debian)
* [33m269b1bf6[m auto-build: Scripts for running auto-build.
* [33mfe3321aa[m auto-build: Typo
* [33m57229bde[m cdedb: Add auto-build.
* [33m26367f33[m doc: include cdedb.frontend.uncommon
* [33m7cff6777[m templates: Small improvements due to parameterized id.
* [33m00fc675c[m frontend: remove unnecessary check
* [33mfc75fda4[m frontend: improve templates
* [33m1fd6c836[m frontend: rename args parameter to params
* [33m77c9a9fe[m cdedb: parameterize data display by id
* [33m68e84201[m frontend: Register custom exceptions.
* [33m4d590383[m doc: More example code and multithreading update.
* [33m36bfbf4b[m cdedb: factor out user management
* [33m6e048e17[m doc: Add psycopg minimal example
* [33m502a25b2[m cdedb: implement quotas, fulltext and event info
* [33m093346ee[m cdedb: Use sets, deprecate warn() and fix sql.
* [33mb3c93a14[m backend: Fail faster.
* [33mdbc8562e[m cde: Implement new features added to SQL
* [33m588043b0[m sql: Update tables
* [33me1a30670[m test: correct assertEqual semantics
* [33m74d1a078[m frontend: Add error correcting variant of id.
* [33m6f8b56ae[m doc: Update INSTALL.html
*   [33m6c370575[m Merge branch 'ldap'
[32m|[m[33m\[m  
[32m|[m * [33m308b8f8d[m ldap: Implement LDAP support.
[32m|[m * [33m952505fa[m ldap: Add infrastructure for LDAP support.
* [33m|[m [33m4ed28459[m cdedb: Make all time stamps aware (i.e. give them a time zone)
* [33m|[m [33mac0fec64[m frontend: create output filters for dates.
* [33m|[m [33m758cd5b0[m config: remove unused instances of BasicConfig
* [33m|[m [33me2938702[m validation: improve date/datetime handling
* [33m|[m [33m07852c0b[m validation: make _str and _printable_ascii check for non-emptiness
* [33m|[m [33m2a0af388[m templates: set default value for checkboxes to True
[33m|[m[33m/[m  
* [33m19916b57[m doc: Add more user feedback.
* [33m2c54ba03[m doc: add page for user feedback
* [33ma9f62216[m doc: more verbosity for config setup
* [33m8006dee3[m core-frontend: check password strength
* [33mad3c5ee3[m doc: Add creating /run/cdedb to setup
* [33mf4623738[m doc: document git checkout better and document make targets
* [33m25bfe001[m Initial tech preview.
