#!/usr/bin/env python3

"""Routing table for the WSGI-application. This will get pretty big so put
it here where it is out of the way.
"""

import werkzeug.routing

rule = werkzeug.routing.Rule
sub = werkzeug.routing.Submount


class FilenameConverter(werkzeug.routing.BaseConverter):
    """Handles filename inputs in URL path."""
    regex = '[a-zA-Z0-9][-a-zA-Z0-9._]*'


# shorthands, mainly to avoid missing the comma to make a tuple for POST
_GET = ("GET", "HEAD")
_POST = ("POST",)

#: Using a routing map allows to do lookups as well as the reverse process
#: of generating links to targets instead of hardcoding them.


CDEDB_PATHS = werkzeug.routing.Map((
    werkzeug.routing.EndpointPrefix('core/', (
        rule("/", methods=_GET,
             endpoint="index"),
        sub('/core', (
            rule("/api/resolve", methods=_GET,
                 endpoint="api_resolve_username"),
            rule("/login", methods=_POST,
                 endpoint="login"),
            rule("/logout", methods=_POST,
                 endpoint="logout"),
            rule("/logout/all", methods=_POST,
                 endpoint="logout_all"),
            rule("/locale", methods=_POST,
                 endpoint="change_locale"),
            rule("/admin_views", methods=_POST,
                 endpoint="modify_active_admin_views"),
            rule("/admins", methods=_GET,
                 endpoint="view_admins"),
            rule("/log", methods=_GET,
                 endpoint="view_log"),
            rule("/meta", methods=_GET,
                 endpoint="meta_info_form"),
            rule("/meta", methods=_POST,
                 endpoint="change_meta_info"),
            rule("/user/create", methods=_GET,
                 endpoint="create_user_form"),
            rule("/user/create/redirect", methods=_GET,
                 endpoint="create_user"),
            rule("/persona/adminshow", methods=_GET,
                 endpoint="admin_show_user"),
            rule("/persona/select", methods=_GET,
                 endpoint="select_persona"),
            rule("/changelog/list", methods=_GET,
                 endpoint="list_pending_changes"),
            rule("/changelog/view", methods=_GET,
                 endpoint="view_changelog_meta"),
            rule("/foto/<filename:foto>", methods=_GET,
                 endpoint="get_foto"),
            rule("/vcard/<vcard>", methods=_GET,
                 endpoint="download_vcard"),
            rule("/debugemail/<token>", methods=_GET,
                 endpoint="debug_email"),
            sub('/self', (
                rule("/show", methods=_GET,
                     endpoint="mydata"),
                rule("/change", methods=_GET,
                     endpoint="change_user_form"),
                rule("/change", methods=_POST,
                     endpoint="change_user"),
                rule("/password/change", methods=_GET,
                     endpoint="change_password_form"),
                rule("/password/change", methods=_POST,
                     endpoint="change_password"),)),
            sub('/self/username', (
                rule("/change", methods=_GET,
                     endpoint="change_username_form"),
                rule("/change/mail", methods=_GET,
                     endpoint="send_username_change_link"),
                rule("/change/confirm", methods=_GET,
                     endpoint="do_username_change_form"),
                rule("/change", methods=_POST,
                     endpoint="do_username_change"),)),
            sub('/password', (
                rule("/reset", methods=_GET,
                     endpoint="reset_password_form"),
                rule("/reset/mail", methods=_GET,
                     endpoint="send_password_reset_link"),
                rule("/reset/confirm", methods=_GET,
                     endpoint="do_password_reset_form"),
                rule("/reset", methods=_POST,
                     endpoint="do_password_reset"),)),
            sub('/search', (
                rule("/user", methods=_GET,
                     endpoint="user_search"),
                rule("/archiveduser", methods=_GET,
                     endpoint="archived_user_search"),)),
            sub('/persona/<int:persona_id>', (
                rule("/adminchange", methods=_GET,
                     endpoint="admin_change_user_form"),
                rule("/adminchange", methods=_POST,
                     endpoint="admin_change_user"),
                rule("/password/reset", methods=_POST,
                     endpoint="admin_send_password_reset_link"),
                rule("/password/invalidate", methods=_POST,
                     endpoint="invalidate_password"),
                rule("/privileges", methods=_GET,
                     endpoint="change_privileges_form"),
                rule("/privileges", methods=_POST,
                     endpoint="change_privileges"),
                rule("/promote", methods=_GET,
                     endpoint="promote_user_form"),
                rule("/promote", methods=_POST,
                     endpoint="promote_user"),
                rule("/membership/change", methods=_GET,
                     endpoint="modify_membership_form"),
                rule("/membership/change", methods=_POST,
                     endpoint="modify_membership"),
                rule("/balance/change", methods=_GET,
                     endpoint="modify_balance_form"),
                rule("/balance/change", methods=_POST,
                     endpoint="modify_balance"),
                rule("/foto/change", methods=_GET,
                     endpoint="set_foto_form"),
                rule("/foto/change", methods=_POST,
                     endpoint="set_foto"),
                rule("/username/adminchange", methods=_GET,
                     endpoint="admin_username_change_form"),
                rule("/username/adminchange", methods=_POST,
                     endpoint="admin_username_change"),
                rule("/changelog/inspect", methods=_GET,
                     endpoint="inspect_change"),
                rule("/changelog/resolve", methods=_POST,
                     endpoint="resolve_change"),
                rule("/show", methods=_GET,
                     endpoint="show_user"),
                rule("/history", methods=_GET,
                     endpoint="show_history"),
                rule("/archive", methods=_POST,
                     endpoint="archive_persona"),
                rule("/dearchive", methods=_POST,
                     endpoint="dearchive_persona"),
                rule("/purge", methods=_POST,
                     endpoint="purge_persona"),
                rule("/activity/change", methods=_POST,
                     endpoint="toggle_activity"),)),
            sub('/genesis', (
                rule("/request", methods=_GET,
                     endpoint="genesis_request_form"),
                rule("/request", methods=_POST,
                     endpoint="genesis_request"),
                rule("/verify", methods=_GET,
                     endpoint="genesis_verify"),
                rule("/list", methods=_GET,
                     endpoint="genesis_list_cases"),
                rule("/attachment/<filename:attachment>", methods=_GET,
                     endpoint="genesis_get_attachment"))),
            sub('/genesis/<int:genesis_case_id>', (
                rule("/show", methods=_GET,
                     endpoint="genesis_show_case"),
                rule("/modify", methods=_GET,
                     endpoint="genesis_modify_form"),
                rule("/modify", methods=_POST,
                     endpoint="genesis_modify"),
                rule("/decide", methods=_POST,
                     endpoint="genesis_decide"),)),
            sub('/privileges', (
                rule("/list", methods=_GET,
                     endpoint="list_privilege_changes"),)),
            sub('/privileges/<int:privilege_change_id>', (
                rule("/show", methods=_GET,
                     endpoint="show_privilege_change"),
                rule("/decide", methods=_POST,
                     endpoint="decide_privilege_change"),)),
        )),)),
    werkzeug.routing.EndpointPrefix('cde/', (
        sub('/cde', (
            rule("/", methods=_GET,
                 endpoint="index"),
            rule("/log", methods=_GET,
                 endpoint="view_cde_log"),
            rule("/misc", methods=_GET,
                 endpoint="view_misc"),
            rule("/finances", methods=_GET,
                 endpoint="view_finance_log"),
            rule("/user/create", methods=_GET,
                 endpoint="create_user_form"),
            rule("/user/create", methods=_POST,
                 endpoint="create_user"),
            rule("/admission", methods=_GET,
                 endpoint="batch_admission_form"),
            rule("/admission", methods=_POST,
                 endpoint="batch_admission"),
            rule("/parse", methods=_GET,
                 endpoint="parse_statement_form"),
            rule("/parse", methods=_POST,
                 endpoint="parse_statement"),
            rule("/parse/download", methods=_POST,
                 endpoint="parse_download"),
            rule("/transfers", methods=_GET,
                 endpoint="money_transfers_form"),
            rule("/transfers", methods=_POST,
                 endpoint="money_transfers"),
            sub('/self', (
                rule("/consent", methods=_GET,
                     endpoint="consent_decision_form"),
                rule("/consent", methods=_POST,
                     endpoint="consent_decision"),)),
            sub('/search', (
                rule("/member", methods=_GET,
                     endpoint="member_search"),
                rule("/user", methods=_GET,
                     endpoint="user_search"),
                rule("/course", methods=_GET,
                     endpoint="past_course_search"),)),
            rule("/i25p", methods=_GET,
                 endpoint="i25p_index"),
            sub("/lastschrift/", (
                rule("/", methods=_GET,
                     endpoint="lastschrift_index"),
                rule("/create", methods=_GET,
                     endpoint="lastschrift_create_form"),
                rule("/create", methods=_POST,
                     endpoint="lastschrift_create"),
                rule("/form/download", methods=_GET,
                     endpoint="lastschrift_subscription_form"),
                rule("/form/fill", methods=_GET,
                     endpoint="lastschrift_subscription_form_fill"),
                rule("/transaction/download", methods=_GET,
                     endpoint="lastschrift_download_sepapain"),
                rule("/transaction/generate", methods=_POST,
                     endpoint="lastschrift_generate_transactions"),
                rule("/transaction/finalize", methods=_POST,
                     endpoint="lastschrift_finalize_transactions"),)),
            sub('/past/', (
                rule("/institution/summary", methods=_GET,
                     endpoint="institution_summary_form"),
                rule("/institution/summary", methods=_POST,
                     endpoint="institution_summary"),
                rule("/event/list", methods=_GET,
                     endpoint="list_past_events"),
                rule("/event/create", methods=_GET,
                     endpoint="create_past_event_form"),
                rule("/event/create", methods=_POST,
                     endpoint="create_past_event"),
                rule("/log", methods=_GET,
                     endpoint="view_past_log"),
                sub('/event/<int:pevent_id>', (
                    rule("/show", methods=_GET,
                         endpoint="show_past_event"),
                    rule("/download", methods=_GET,
                         endpoint="download_past_event_participantlist"),
                    rule("/change", methods=_GET,
                         endpoint="change_past_event_form"),
                    rule("/change", methods=_POST,
                         endpoint="change_past_event"),
                    rule("/delete", methods=_POST,
                         endpoint="delete_past_event"),
                    rule("/course/create", methods=_GET,
                         endpoint="create_past_course_form"),
                    rule("/course/create", methods=_POST,
                         endpoint="create_past_course"),
                    rule("/participant/add", methods=_POST,
                         endpoint="add_participants"),
                    rule("/participant/remove", methods=_POST,
                         endpoint="remove_participant"),
                    sub('/course/<int:pcourse_id>', (
                        rule("/participant/add", methods=_POST,
                             endpoint="add_participants"),
                        rule("/participant/remove", methods=_POST,
                             endpoint="remove_participant"),
                        rule("/show", methods=_GET,
                             endpoint="show_past_course"),
                        rule("/change", methods=_GET,
                             endpoint="change_past_course_form"),
                        rule("/change", methods=_POST,
                             endpoint="change_past_course"),
                        rule("/delete", methods=_POST,
                             endpoint="delete_past_course"),)),)),)),
            sub('/lastschrift/<int:lastschrift_id>', (
                rule("/skip", methods=_POST,
                     endpoint="lastschrift_skip"),
                rule("/change", methods=_GET,
                     endpoint="lastschrift_change_form"),
                rule("/change", methods=_POST,
                     endpoint="lastschrift_change"),
                rule("/revoke", methods=_POST,
                     endpoint="lastschrift_revoke"),
                sub('/transaction/<int:transaction_id>', (
                    rule("/finalize", methods=_POST,
                         endpoint="lastschrift_finalize_transaction"),
                    rule("/receipt", methods=_GET,
                         endpoint="lastschrift_receipt"),
                    rule("/rollback", methods=_POST,
                         endpoint="lastschrift_rollback_transaction"),)),)),
            sub('/user/<int:persona_id>', (
                rule("/lastschrift", methods=_GET,
                     endpoint="lastschrift_show"),
                rule("/lastschrift/create", methods=_GET,
                     endpoint="lastschrift_create_form"),
                rule("/lastschrift/create", methods=_POST,
                     endpoint="lastschrift_create"),)),
            sub('/semester', (
                rule("/show", methods=_GET,
                     endpoint="show_semester"),
                rule("/bill", methods=_POST,
                     endpoint="semester_bill"),
                rule("/eject", methods=_POST,
                     endpoint="semester_eject"),
                rule("/balance", methods=_POST,
                     endpoint="semester_balance_update"),
                rule("/advance", methods=_POST,
                     endpoint="semester_advance"),)),
            sub('/expuls', (
                rule("/address", methods=_POST,
                     endpoint="expuls_addresscheck"),
                rule("/advance", methods=_POST,
                     endpoint="expuls_advance"),)),
        )),)),
    werkzeug.routing.EndpointPrefix('event/', (
        sub('/event', (
            rule("/", methods=_GET,
                 endpoint="index"),
            rule("/search/user", methods=_GET,
                 endpoint="user_search"),
            rule("/registration/select", methods=_GET,
                 endpoint="select_registration"),
            rule("/user/create", methods=_GET,
                 endpoint="create_user_form"),
            rule("/user/create", methods=_POST,
                 endpoint="create_user"),
            rule("/event/list", methods=_GET,
                 endpoint="list_events"),
            rule("/event/create", methods=_GET,
                 endpoint="create_event_form"),
            rule("/event/create", methods=_POST,
                 endpoint="create_event"),
            rule("/event/log", methods=_GET,
                 endpoint="view_log"),
            rule("/offline/partial", methods=_GET,
                 endpoint="download_quick_partial_export"),
            sub('/event/<int:event_id>', (
                rule("/show", methods=_GET,
                     endpoint="show_event"),
                rule("/log", methods=_GET,
                     endpoint="view_event_log"),
                rule("/change", methods=_GET,
                     endpoint="change_event_form"),
                rule("/change", methods=_POST,
                     endpoint="change_event"),
                rule("/minorform", methods=_GET,
                     endpoint="get_minor_form"),
                rule("/orga/add", methods=_POST,
                     endpoint="add_orga"),
                rule("/orga/remove", methods=_POST,
                     endpoint="remove_orga"),
                rule("/minorform/change", methods=_POST,
                     endpoint="change_minor_form"),
                rule("/ml/create", methods=_POST,
                     endpoint="create_event_mailinglist"),
                rule("/part/summary", methods=_GET,
                     endpoint="part_summary_form"),
                rule("/part/summary", methods=_POST,
                     endpoint="part_summary"),
                rule("/course/list", methods=_GET,
                     endpoint="course_list"),
                rule("/course/stats", methods=_GET,
                     endpoint="course_stats"),
                rule("/course/create", methods=_GET,
                     endpoint="create_course_form"),
                rule("/course/create", methods=_POST,
                     endpoint="create_course"),
                rule("/course/query", methods=_GET,
                     endpoint="course_query"),
                rule("/stats", methods=_GET,
                     endpoint="stats"),
                rule("/course/choices", methods=_GET,
                     endpoint="course_choices_form"),
                rule("/course/choices", methods=_POST,
                     endpoint="course_choices"),
                rule("/course/checks", methods=_GET,
                     endpoint="course_assignment_checks"),
                rule("/export", methods=_GET,
                     endpoint="download_export"),
                rule("/lock", methods=_POST,
                     endpoint="lock_event"),
                rule("/unlock", methods=_POST,
                     endpoint="unlock_event"),
                rule("/batchfees", methods=_GET,
                     endpoint="batch_fees_form"),
                rule("/batchfees", methods=_POST,
                     endpoint="batch_fees"),
                rule("/register", methods=_GET,
                     endpoint="register_form"),
                rule("/register", methods=_POST,
                     endpoint="register"),
                rule("/register/config", methods=_GET,
                     endpoint="configure_registration_form"),
                rule("/register/config", methods=_POST,
                     endpoint="configure_registration"),
                rule("/questionnaire/config", methods=_GET,
                     endpoint="configure_additional_questionnaire_form"),
                rule("/questionnaire/config", methods=_POST,
                     endpoint="configure_additional_questionnaire"),
                rule("/questionnaire/reorder", methods=_GET,
                     endpoint="reorder_questionnaire_form"),
                rule("/questionnaire/reorder", methods=_POST,
                     endpoint="reorder_questionnaire"),
                rule("/registration/add", methods=_GET,
                     endpoint="add_registration_form"),
                rule("/registration/add", methods=_POST,
                     endpoint="add_registration"),
                rule("/lodgement/overview", methods=_GET,
                     endpoint="lodgements"),
                rule("/lodgement/create", methods=_GET,
                     endpoint="create_lodgement_form"),
                rule("/lodgement/create", methods=_POST,
                     endpoint="create_lodgement"),
                rule("/lodgement/group/summary", methods=_GET,
                     endpoint="lodgement_group_summary_form"),
                rule("/lodgement/group/summary", methods=_POST,
                     endpoint="lodgement_group_summary"),
                rule("/lodgement/query", methods=_GET,
                     endpoint="lodgement_query"),
                rule("/registration/query", methods=_GET,
                     endpoint="registration_query"),
                rule("/checkin", methods=_GET,
                     endpoint="checkin_form"),
                rule("/checkin", methods=_POST,
                     endpoint="checkin"),
                rule("/field/setselect", methods=_GET,
                     endpoint="field_set_select"),
                rule("/field/summary", methods=_GET,
                     endpoint="field_summary_form"),
                rule("/field/summary", methods=_POST,
                     endpoint="field_summary"),
                rule("/download", methods=_GET,
                     endpoint="downloads"),
                rule("/import", methods=_GET,
                     endpoint="partial_import_form"),
                rule("/import", methods=_POST,
                     endpoint="partial_import"),
                rule("/archive", methods=_POST,
                     endpoint="archive_event"),
                rule("/delete", methods=_POST,
                     endpoint="delete_event"),
                sub("/download", (
                    rule("/nametag", methods=_GET,
                         endpoint="download_nametags"),
                    rule("/coursepuzzle", methods=_GET,
                         endpoint="download_course_puzzle"),
                    rule("/lodgementpuzzle", methods=_GET,
                         endpoint="download_lodgement_puzzle"),
                    rule("/courselists", methods=_GET,
                         endpoint="download_course_lists"),
                    rule("/lodgementlists", methods=_GET,
                         endpoint="download_lodgement_lists"),
                    rule("/participantlist", methods=_GET,
                         endpoint="download_participant_list"),
                    rule("/expuls", methods=_GET,
                         endpoint="download_expuls"),
                    rule("/dokuteam_course", methods=_GET,
                         endpoint="download_dokuteam_courselist"),
                    rule("/dokuteam_participant", methods=_GET,
                         endpoint="download_dokuteam_participant_list"),
                    rule("/partial", methods=_GET,
                         endpoint="download_partial_export"),
                    rule("/csv_courses", methods=_GET,
                         endpoint="download_csv_courses"),
                    rule("/csv_lodgements", methods=_GET,
                         endpoint="download_csv_lodgements"),
                    rule("/csv_registrations", methods=_GET,
                         endpoint="download_csv_registrations"),)),
                sub('/course/<int:course_id>', (
                    rule("/show", methods=_GET,
                         endpoint="show_course"),
                    rule("/change", methods=_GET,
                         endpoint="change_course_form"),
                    rule("/change", methods=_POST,
                         endpoint="change_course"),
                    rule("/delete", methods=_POST,
                         endpoint="delete_course"),
                    rule("/manage", methods=_GET,
                         endpoint="manage_attendees_form"),
                    rule("/manage", methods=_POST,
                         endpoint="manage_attendees"),)),
                sub('/registration', (
                    rule("/status", methods=_GET,
                         endpoint="registration_status"),
                    rule("/amend", methods=_GET,
                         endpoint="amend_registration_form"),
                    rule("/amend", methods=_POST,
                         endpoint="amend_registration"),
                    rule("/questionnaire", methods=_GET,
                         endpoint="additional_questionnaire_form"),
                    rule("/questionnaire", methods=_POST,
                         endpoint="additional_questionnaire"),
                    rule("/quick", methods=_GET,
                         endpoint="quick_show_registration"),
                    rule("/list", methods=_GET,
                         endpoint="participant_list"),
                    rule("/multiedit", methods=_GET,
                         endpoint="change_registrations_form"),
                    rule("/multiedit", methods=_POST,
                         endpoint="change_registrations"),)),
                sub('/registration/<int:registration_id>', (
                    rule("/show", methods=_GET,
                         endpoint="show_registration"),
                    rule("/change", methods=_GET,
                         endpoint="change_registration_form"),
                    rule("/change", methods=_POST,
                         endpoint="change_registration"),
                    rule("/delete", methods=_POST,
                         endpoint="delete_registration"),)),
                sub('/lodgement/<int:lodgement_id>', (
                    rule("/change", methods=_GET,
                         endpoint="change_lodgement_form"),
                    rule("/change", methods=_POST,
                         endpoint="change_lodgement"),
                    rule("/delete", methods=_POST,
                         endpoint="delete_lodgement"),
                    rule("/manage", methods=_GET,
                         endpoint="manage_inhabitants_form"),
                    rule("/manage", methods=_POST,
                         endpoint="manage_inhabitants"),
                    rule("/show", methods=_GET,
                         endpoint="show_lodgement"),)),
                sub('/field/<int:field_id>', (
                    rule("/set", methods=_GET,
                         endpoint="field_set_form"),
                    rule("/set", methods=_POST,
                         endpoint="field_set"),)),)),
        )),)),
    werkzeug.routing.EndpointPrefix('assembly/', (
        sub('/assembly', (
            rule("/", methods=_GET,
                 endpoint="index"),
            rule("/search/user", methods=_GET,
                 endpoint="user_search"),
            rule("/user/create", methods=_GET,
                 endpoint="create_user_form"),
            rule("/user/create", methods=_POST,
                 endpoint="create_user"),
            rule("/assembly/create", methods=_GET,
                 endpoint="create_assembly_form"),
            rule("/assembly/create", methods=_POST,
                 endpoint="create_assembly"),
            rule("/log", methods=_GET,
                 endpoint="view_log"),
            sub('/assembly/<int:assembly_id>', (
                rule("/show", methods=_GET,
                     endpoint="show_assembly"),
                rule("/presider/add", methods=_POST,
                     endpoint="add_presiders"),
                rule("/presider/remove", methods=_POST,
                     endpoint="remove_presider"),
                rule("/delete", methods=_POST,
                     endpoint="delete_assembly"),
                rule("/log", methods=_GET,
                     endpoint="view_assembly_log"),
                rule("/change", methods=_GET,
                     endpoint="change_assembly_form"),
                rule("/change", methods=_POST,
                     endpoint="change_assembly"),
                rule("/ml/create", methods=_POST,
                     endpoint="create_assembly_mailinglist"),
                rule("/signup", methods=_POST,
                     endpoint="signup"),
                rule("/signup/external", methods=_POST,
                     endpoint="external_signup"),
                rule("/attachments", methods=_GET,
                     endpoint="list_attachments"),
                rule("/attendees", methods=_GET,
                     endpoint="list_attendees"),
                rule("/attendees/download", methods=_GET,
                     endpoint="download_list_attendees"),
                rule("/conclude", methods=_POST,
                     endpoint="conclude_assembly"),
                sub("/attachment", (
                    rule("/add", methods=_GET,
                         endpoint="add_attachment_form"),
                    rule("/add", methods=_POST,
                         endpoint="add_attachment"),
                    sub("/<int:attachment_id>", (
                        rule("/get", methods=_GET,
                             endpoint="get_attachment"),
                        rule("/show", methods=_GET,
                             endpoint="show_attachment"),
                        rule("/change", methods=_GET,
                             endpoint="change_attachment_link_form"),
                        rule("/change", methods=_POST,
                             endpoint="change_attachment_link"),
                        rule("/delete", methods=_POST,
                             endpoint="delete_attachment"),
                        rule("/add", methods=_GET,
                             endpoint="add_attachment_form"),
                        rule("/add", methods=_POST,
                             endpoint="add_attachment"),
                        sub("/version/<int:version>", (
                            rule("/get", methods=_GET,
                                 endpoint="get_attachment"),
                            rule("/delete", methods=_POST,
                                 endpoint="delete_attachment"),
                            rule("/edit", methods=_GET,
                                 endpoint="edit_attachment_version_form"),
                            rule("/edit", methods=_POST,
                                 endpoint="edit_attachment_version"),
                        )),
                    )),
                )),
                rule("/ballot/list", methods=_GET,
                     endpoint="list_ballots"),
                rule("/ballot/create", methods=_GET,
                     endpoint="create_ballot_form"),
                rule("/ballot/create", methods=_POST,
                     endpoint="create_ballot"),
                rule("/ballot/summary", methods=_GET,
                     endpoint="summary_ballots"),
                sub('/ballot/<int:ballot_id>', (
                    rule("/show", methods=_GET,
                         endpoint="show_ballot"),
                    rule("/show", methods=_POST,
                         endpoint="show_old_vote"),
                    rule("/change", methods=_GET,
                         endpoint="change_ballot_form"),
                    rule("/change", methods=_POST,
                         endpoint="change_ballot"),
                    rule("/delete", methods=_POST,
                         endpoint="delete_ballot"),
                    rule("/start", methods=_POST,
                         endpoint="ballot_start_voting"),
                    rule("/vote", methods=_POST,
                         endpoint="vote"),
                    rule("/result", methods=_GET,
                         endpoint="get_result"),
                    sub("/attachment", (
                        rule("/add", methods=_GET,
                             endpoint="add_attachment_form"),
                        rule("/add", methods=_POST,
                             endpoint="add_attachment"),
                        sub("/<int:attachment_id>", (
                            rule("/get", methods=_GET,
                                 endpoint="get_attachment"),
                            rule("/show", methods=_GET,
                                 endpoint="show_attachment"),
                            rule("/change", methods=_GET,
                                 endpoint="change_attachment_link_form"),
                            rule("/change", methods=_POST,
                                 endpoint="change_attachment_link"),
                            rule("/delete", methods=_POST,
                                 endpoint="delete_attachment"),
                            rule("/add", methods=_GET,
                                 endpoint="add_attachment_form"),
                            rule("/add", methods=_POST,
                                 endpoint="add_attachment"),
                            sub("/version/<int:version>", (
                                rule("/get", methods=_GET,
                                     endpoint="get_attachment"),
                                rule("/delete", methods=_POST,
                                     endpoint="delete_attachment"),
                                rule("/edit", methods=_GET,
                                     endpoint="edit_attachment_version_form"),
                                rule("/edit", methods=_POST,
                                     endpoint="edit_attachment_version"),
                            )),
                        )),
                    )),
                    rule("/candidates/edit", methods=_POST,
                         endpoint="edit_candidates"),
                )),
            )),
        )),
    )),
    werkzeug.routing.EndpointPrefix('ml/', (
        sub('/ml', (
            rule("/", methods=_GET,
                 endpoint="index"),
            rule("/search/user", methods=_GET,
                 endpoint="user_search"),
            rule("/user/create", methods=_GET,
                 endpoint="create_user_form"),
            rule("/user/create", methods=_POST,
                 endpoint="create_user"),
            rule("/mailinglist/list", methods=_GET,
                 endpoint="list_mailinglists"),
            rule("/mailinglist/moderated", methods=_GET,
                 endpoint="moderated_mailinglists"),
            rule("/mailinglist/create", methods=_GET,
                 endpoint="create_mailinglist_form"),
            rule("/mailinglist/create", methods=_POST,
                 endpoint="create_mailinglist"),
            rule("/log", methods=_GET,
                 endpoint="view_log"),
            rule("/script/all", methods=_GET,
                 endpoint="export_overview"),
            rule("/script/one", methods=_GET,
                 endpoint="export_one"),
            rule("/script/all/compat", methods=_GET,
                 endpoint="oldstyle_mailinglist_config_export"),
            rule("/script/one/compat", methods=_GET,
                 endpoint="oldstyle_mailinglist_export"),
            rule("/script/mod/compat", methods=_GET,
                 endpoint="oldstyle_modlist_export"),
            rule("/script/bounce/compat", methods=_POST,
                 endpoint="oldstyle_bounce"),
            sub('/mailinglist/<int:mailinglist_id>', (
                rule("/show", methods=_GET,
                     endpoint="show_mailinglist"),
                rule("/change", methods=_GET,
                     endpoint="change_mailinglist_form"),
                rule("/change", methods=_POST,
                     endpoint="change_mailinglist"),
                rule("/type/change", methods=_GET,
                     endpoint="change_ml_type_form"),
                rule("/type/change", methods=_POST,
                     endpoint="change_ml_type"),
                rule("/delete", methods=_POST,
                     endpoint="delete_mailinglist"),
                rule("/log", methods=_GET,
                     endpoint="view_ml_log"),
                rule("/management", methods=_GET,
                     endpoint="management"),
                rule("/management/advanced", methods=_GET,
                     endpoint="show_subscription_details"),
                rule("/download/subscriptions", methods=_GET,
                     endpoint="download_csv_subscription_states"),
                rule("/force/add", methods=_POST,
                     endpoint="add_subscription_overrides"),
                rule("/force/remove", methods=_POST,
                     endpoint="remove_subscription_override"),
                rule("/block/add", methods=_POST,
                     endpoint="add_unsubscription_overrides"),
                rule("/block/remove", methods=_POST,
                     endpoint="remove_unsubscription_override"),
                rule("/moderator/add", methods=_POST,
                     endpoint="add_moderators"),
                rule("/moderator/remove", methods=_POST,
                     endpoint="remove_moderator"),
                rule("/whitelist/add", methods=_POST,
                     endpoint="add_whitelist"),
                rule("/whitelist/remove", methods=_POST,
                     endpoint="remove_whitelist"),
                rule("/requests/approve", methods=_POST,
                     endpoint="approve_request"),
                rule("/requests/deny", methods=_POST,
                     endpoint="deny_request"),
                rule("/requests/block", methods=_POST,
                     endpoint="block_request"),
                rule("/subscriptions/add", methods=_POST,
                     endpoint="add_subscribers"),
                rule("/subscriptions/remove", methods=_POST,
                     endpoint="remove_subscriber"),
                rule("/subscriptions/self/add", methods=_POST,
                     endpoint="subscribe"),
                rule("/subscriptions/self/remove", methods=_POST,
                     endpoint="unsubscribe"),
                rule("/subscriptions/self/request", methods=_POST,
                     endpoint="request_subscription"),
                rule("/subscriptions/self/cancel", methods=_POST,
                     endpoint="cancel_subscription"),
                rule("/subaddress/change", methods=_POST,
                     endpoint="change_address"),
                rule("/subaddress/confirm", methods=_GET,
                     endpoint="do_address_change"),)),
        )),)),
), converters={'filename': FilenameConverter})
