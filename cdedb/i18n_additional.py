#!/usr/bin/env python3

"""Additional strings for i18n which do not occur literally."""

from cdedb.common.n_ import n_

I18N_STRINGS = (
    #
    # Enums
    #
    n_("AgeClasses.full"),
    n_("AgeClasses.u18"),
    n_("AgeClasses.u16"),
    n_("AgeClasses.u14"),
    n_("AgeClasses.u10"),

    n_("AssemblyLogCodes.assembly_created"),
    n_("AssemblyLogCodes.assembly_changed"),
    n_("AssemblyLogCodes.assembly_concluded"),
    n_("AssemblyLogCodes.assembly_deleted"),
    n_("AssemblyLogCodes.ballot_created"),
    n_("AssemblyLogCodes.ballot_changed"),
    n_("AssemblyLogCodes.ballot_deleted"),
    n_("AssemblyLogCodes.ballot_extended"),
    n_("AssemblyLogCodes.ballot_tallied"),
    n_("AssemblyLogCodes.candidate_added"),
    n_("AssemblyLogCodes.candidate_updated"),
    n_("AssemblyLogCodes.candidate_removed"),
    n_("AssemblyLogCodes.new_attendee"),
    n_("AssemblyLogCodes.assembly_presider_added"),
    n_("AssemblyLogCodes.assembly_presider_removed"),
    n_("AssemblyLogCodes.attachment_added"),
    n_("AssemblyLogCodes.attachment_removed"),
    n_("AssemblyLogCodes.attachment_changed"),
    n_("AssemblyLogCodes.attachment_ballot_link_created"),
    n_("AssemblyLogCodes.attachment_ballot_link_deleted"),
    n_("AssemblyLogCodes.attachment_version_added"),
    n_("AssemblyLogCodes.attachment_version_removed"),
    n_("AssemblyLogCodes.attachment_version_changed"),

    n_("AttachmentPolicy.allow"),
    n_("AttachmentPolicy.pdf_only"),
    n_("AttachmentPolicy.forbid"),

    n_("CdeLogCodes.semester_bill"),
    n_("CdeLogCodes.semester_bill_with_addresscheck"),
    n_("CdeLogCodes.semester_ejection"),
    n_("CdeLogCodes.semester_balance_update"),
    n_("CdeLogCodes.semester_advance"),
    n_("CdeLogCodes.expuls_addresscheck"),
    n_("CdeLogCodes.expuls_addresscheck_skipped"),
    n_("CdeLogCodes.expuls_advance"),
    n_("CdeLogCodes.automated_archival_notification_done"),
    n_("CdeLogCodes.automated_archival_done"),

    n_("CoreLogCodes.persona_creation"),
    n_("CoreLogCodes.persona_change"),
    n_("CoreLogCodes.persona_archived"),
    n_("CoreLogCodes.persona_dearchived"),
    n_("CoreLogCodes.persona_purged"),
    n_("CoreLogCodes.password_change"),
    n_("CoreLogCodes.password_reset_cookie"),
    n_("CoreLogCodes.password_reset"),
    n_("CoreLogCodes.password_invalidated"),
    n_("CoreLogCodes.genesis_request"),
    n_("CoreLogCodes.genesis_approved"),
    n_("CoreLogCodes.genesis_rejected"),
    n_("CoreLogCodes.genesis_deleted"),
    n_("CoreLogCodes.genesis_verified"),
    n_("CoreLogCodes.genesis_merged"),
    n_("CoreLogCodes.genesis_change"),
    n_("CoreLogCodes.privilege_change_pending"),
    n_("CoreLogCodes.privilege_change_approved"),
    n_("CoreLogCodes.privilege_change_rejected"),
    n_("CoreLogCodes.realm_change"),
    n_("CoreLogCodes.username_change"),
    n_("CoreLogCodes.quota_violation"),

    n_("EventLogCodes.event_created"),
    n_("EventLogCodes.event_changed"),
    n_("EventLogCodes.event_deleted"),
    n_("EventLogCodes.event_archived"),
    n_("EventLogCodes.orga_added"),
    n_("EventLogCodes.orga_removed"),
    n_("EventLogCodes.part_created"),
    n_("EventLogCodes.part_changed"),
    n_("EventLogCodes.part_deleted"),
    n_("EventLogCodes.field_added"),
    n_("EventLogCodes.field_updated"),
    n_("EventLogCodes.field_removed"),
    n_("EventLogCodes.lodgement_created"),
    n_("EventLogCodes.lodgement_changed"),
    n_("EventLogCodes.lodgement_deleted"),
    n_("EventLogCodes.questionnaire_changed"),
    n_("EventLogCodes.track_added"),
    n_("EventLogCodes.track_updated"),
    n_("EventLogCodes.track_removed"),
    n_("EventLogCodes.course_created"),
    n_("EventLogCodes.course_changed"),
    n_("EventLogCodes.course_deleted"),
    n_("EventLogCodes.course_segments_changed"),
    n_("EventLogCodes.course_segment_activity_changed"),
    n_("EventLogCodes.registration_created"),
    n_("EventLogCodes.registration_changed"),
    n_("EventLogCodes.registration_deleted"),
    n_("EventLogCodes.event_locked"),
    n_("EventLogCodes.event_unlocked"),
    n_("EventLogCodes.event_partial_import"),
    n_("EventLogCodes.lodgement_group_created"),
    n_("EventLogCodes.lodgement_group_changed"),
    n_("EventLogCodes.lodgement_group_deleted"),
    n_("EventLogCodes.fee_modifier_created"),
    n_("EventLogCodes.fee_modifier_changed"),
    n_("EventLogCodes.fee_modifier_deleted"),
    n_("EventLogCodes.minor_form_updated"),
    n_("EventLogCodes.minor_form_removed"),
    n_("EventLogCodes.query_stored"),
    n_("EventLogCodes.query_deleted"),
    n_("EventLogCodes.part_group_created"),
    n_("EventLogCodes.part_group_changed"),
    n_("EventLogCodes.part_group_deleted"),
    n_("EventLogCodes.part_group_link_created"),
    n_("EventLogCodes.part_group_link_deleted"),
    n_("EventLogCodes.track_group_created"),
    n_("EventLogCodes.track_group_changed"),
    n_("EventLogCodes.track_group_deleted"),
    n_("EventLogCodes.track_group_link_created"),
    n_("EventLogCodes.track_group_link_deleted"),
    n_("EventLogCodes.orga_token_created"),
    n_("EventLogCodes.orga_token_changed"),
    n_("EventLogCodes.orga_token_revoked"),
    n_("EventLogCodes.orga_token_deleted"),
    n_("EventLogCodes.custom_filter_created"),
    n_("EventLogCodes.custom_filter_changed"),
    n_("EventLogCodes.custom_filter_deleted"),

    n_("FinanceLogCodes.new_member"),
    n_("FinanceLogCodes.gain_membership"),
    n_("FinanceLogCodes.lose_membership"),
    n_("FinanceLogCodes.increase_balance"),
    n_("FinanceLogCodes.deduct_membership_fee"),
    n_("FinanceLogCodes.end_trial_membership"),
    n_("FinanceLogCodes.manual_balance_correction"),
    n_("FinanceLogCodes.remove_balance_on_archival"),
    n_("FinanceLogCodes.start_trial_membership"),
    n_("FinanceLogCodes.grant_lastschrift"),
    n_("FinanceLogCodes.revoke_lastschrift"),
    n_("FinanceLogCodes.modify_lastschrift"),
    n_("FinanceLogCodes.lastschrift_deleted"),
    n_("FinanceLogCodes.lastschrift_transaction_issue"),
    n_("FinanceLogCodes.lastschrift_transaction_success"),
    n_("FinanceLogCodes.lastschrift_transaction_failure"),
    n_("FinanceLogCodes.lastschrift_transaction_skip"),
    n_("FinanceLogCodes.lastschrift_transaction_cancelled"),
    n_("FinanceLogCodes.lastschrift_transaction_revoked"),
    n_("FinanceLogCodes.other"),

    n_("FieldAssociations.registration"),
    n_("FieldAssociations.course"),
    n_("FieldAssociations.lodgement"),

    n_("FieldDatatypes.str"),
    n_("FieldDatatypes.bool"),
    n_("FieldDatatypes.int"),
    n_("FieldDatatypes.float"),
    n_("FieldDatatypes.date"),
    n_("FieldDatatypes.datetime"),

    n_("Genders.female"),
    n_("Genders.male"),
    n_("Genders.other"),
    n_("Genders.not_specified"),

    n_("GenesisStati.unconfirmed"),
    n_("GenesisStati.to_review"),
    n_("GenesisStati.approved"),
    n_("GenesisStati.successful"),
    n_("GenesisStati.existing_updated"),
    n_("GenesisStati.rejected"),

    n_("LineResolutions.none"),
    n_("LineResolutions.create"),
    n_("LineResolutions.skip"),
    n_("LineResolutions.renew_trial"),
    n_("LineResolutions.update"),
    n_("LineResolutions.renew_and_update"),

    n_("PersonaChangeStati.pending"),
    n_("PersonaChangeStati.committed"),
    n_("PersonaChangeStati.superseded"),
    n_("PersonaChangeStati.nacked"),
    n_("PersonaChangeStati.displaced"),

    n_("MlLogCodes.email_trouble"),
    n_("MlLogCodes.list_created"),
    n_("MlLogCodes.list_changed"),
    n_("MlLogCodes.list_deleted"),
    n_("MlLogCodes.moderator_added"),
    n_("MlLogCodes.moderator_removed"),
    n_("MlLogCodes.whitelist_added"),
    n_("MlLogCodes.whitelist_removed"),
    n_("MlLogCodes.subscription_requested"),
    n_("MlLogCodes.subscribed"),
    n_("MlLogCodes.subscription_changed"),
    n_("MlLogCodes.unsubscribed"),
    n_("MlLogCodes.marked_override"),
    n_("MlLogCodes.marked_blocked"),
    n_("MlLogCodes.request_approved"),
    n_("MlLogCodes.request_denied"),
    n_("MlLogCodes.request_cancelled"),
    n_("MlLogCodes.request_blocked"),
    n_("MlLogCodes.automatically_removed"),
    n_("MlLogCodes.reset"),
    n_("MlLogCodes.moderate_accept"),
    n_("MlLogCodes.moderate_reject"),
    n_("MlLogCodes.moderate_discard"),

    n_("ModerationPolicy.unmoderated"),
    n_("ModerationPolicy.non_subscribers"),
    n_("ModerationPolicy.fully_moderated"),

    n_("PastEventLogCodes.event_created"),
    n_("PastEventLogCodes.event_changed"),
    n_("PastEventLogCodes.event_deleted"),
    n_("PastEventLogCodes.course_created"),
    n_("PastEventLogCodes.course_changed"),
    n_("PastEventLogCodes.course_deleted"),
    n_("PastEventLogCodes.participant_added"),
    n_("PastEventLogCodes.participant_removed"),

    n_("PrivilegeChangeStati.pending"),
    n_("PrivilegeChangeStati.approved"),
    n_("PrivilegeChangeStati.successful"),
    n_("PrivilegeChangeStati.rejected"),

    n_("QuestionnaireUsages.registration"),
    n_("QuestionnaireUsages.additional"),

    n_("EventPartGroupType.mutually_exclusive_participants"),
    n_("EventPartGroupType.mutually_exclusive_courses"),
    n_("EventPartGroupType.Statistic"),

    n_("CourseTrackGroupType.course_choice_sync"),

    n_("RegistrationPartStati.not_applied"),
    n_("RegistrationPartStati.applied"),
    n_("RegistrationPartStati.participant"),
    n_("RegistrationPartStati.waitlist"),
    n_("RegistrationPartStati.guest"),
    n_("RegistrationPartStati.cancelled"),
    n_("RegistrationPartStati.rejected"),

    n_("LastschriftTransactionStati.issued"),
    n_("LastschriftTransactionStati.skipped"),
    n_("LastschriftTransactionStati.success"),
    n_("LastschriftTransactionStati.failure"),
    n_("LastschriftTransactionStati.cancelled"),
    n_("LastschriftTransactionStati.rollback"),

    n_("PastInstitutions.cde"),
    n_("PastInstitutions.dsa"),
    n_("PastInstitutions.dja"),
    n_("PastInstitutions.jgw"),
    n_("PastInstitutions.basf"),
    n_("PastInstitutions.van"),

    n_("QueryOperators.empty"),
    n_("QueryOperators.nonempty"),
    n_("QueryOperators.equal"),
    n_("QueryOperators.unequal"),
    n_("QueryOperators.oneof"),
    n_("QueryOperators.otherthan"),
    n_("QueryOperators.equalornull"),
    n_("QueryOperators.unequalornull"),
    n_("QueryOperators.match"),
    n_("QueryOperators.unmatch"),
    n_("QueryOperators.regex"),
    n_("QueryOperators.notregex"),
    n_("QueryOperators.containsall"),
    n_("QueryOperators.containsnone"),
    n_("QueryOperators.containssome"),
    n_("QueryOperators.fuzzy"),
    n_("QueryOperators.less"),
    n_("QueryOperators.lessequal"),
    n_("QueryOperators.between"),
    n_("QueryOperators.outside"),
    n_("QueryOperators.greaterequal"),
    n_("QueryOperators.greater"),

    n_("MailinglistGroup.public"),
    n_("MailinglistGroup.cde"),
    n_("MailinglistGroup.team"),
    n_("MailinglistGroup.event"),
    n_("MailinglistGroup.assembly"),
    n_("MailinglistGroup.cdelokal"),

    n_("MailinglistTypes.member_mandatory"),
    n_("MailinglistTypes.member_opt_out"),
    n_("MailinglistTypes.member_opt_in"),
    n_("MailinglistTypes.member_moderated_opt_in"),
    n_("MailinglistTypes.member_invitation_only"),
    n_("MailinglistTypes.team"),
    n_("MailinglistTypes.restricted_team"),
    n_("MailinglistTypes.event_associated"),
    n_("MailinglistTypes.event_orga"),
    n_("MailinglistTypes.assembly_associated"),
    n_("MailinglistTypes.assembly_opt_in"),
    n_("MailinglistTypes.assembly_presider"),
    n_("MailinglistTypes.general_mandatory"),
    n_("MailinglistTypes.general_opt_in"),
    n_("MailinglistTypes.general_moderated_opt_in"),
    n_("MailinglistTypes.general_invitation_only"),
    n_("MailinglistTypes.general_moderators"),
    n_("MailinglistTypes.cdelokal_moderators"),
    n_("MailinglistTypes.semi_public"),
    n_("MailinglistTypes.public_member_implicit"),
    n_("MailinglistTypes.cdelokal"),

    n_("MailinglistRosterVisibility.none"),
    n_("MailinglistRosterVisibility.subscribable"),
    n_("MailinglistRosterVisibility.viewers"),

    n_("EventFeeType.common"),
    n_("EventFeeType.storno"),
    n_("EventFeeType.external"),
    n_("EventFeeType.solidarity"),
    n_("EventFeeType.donation"),

    #
    # Validation errors
    #
    n_("day is out of range for month"),
    n_("[<class 'decimal.ConversionSyntax'>]"),

    # zxcvbn feedback
    n_('Use a few words, avoid common phrases.'),
    n_('No need for symbols, digits, or uppercase letters.'),
    n_('Add another word or two. Uncommon words are better.'),
    n_('Straight rows of keys are easy to guess.'),
    n_('Short keyboard patterns are easy to guess.'),
    n_('Use a longer keyboard pattern with more turns.'),
    n_('Repeats like "aaa" are easy to guess.'),
    n_('Repeats like "abcabcabc" are only slightly harder to guess than '
       '"abc".'),
    n_('Avoid repeated words and characters.'),
    n_('Sequences like "abc" or "6543" are easy to guess.'),
    n_('Avoid sequences.'),
    n_("Recent years are easy to guess."),
    n_('Avoid recent years.'),
    n_('Avoid years that are associated with you.'),
    n_('Avoid dates and years that are associated with you.'),
    n_('This is a top-10 common password.'),
    n_('This is a top-100 common password.'),
    n_('This is a very common password.'),
    n_('This is similar to a commonly used password.'),
    n_('A word by itself is easy to guess.'),
    n_('Names and surnames by themselves are easy to guess.'),
    n_('Common names and surnames are easy to guess.'),
    n_("Capitalization doesn't help very much."),
    n_("All-uppercase is almost as easy to guess as all-lowercase."),
    n_("Reversed words aren't much harder to guess."),
    n_('Predictable substitutions like "@" instead of "a" don\'t help very '
       'much.'),

    #
    # subman localization
    #
    n_("subman_managing_not-pending"),
    n_("subman_managing_is-subscribed"),
    n_("subman_managing_is-unsubscribed"),
    n_("subman_managing_is-subscription-overridden"),
    n_("subman_managing_is-unsubscription-overridden"),
    n_("subman_managing_is-pending"),
    n_("subman_managing_not-subscription-overridden"),
    n_("subman_managing_not-unsubscription-overridden"),
    n_("subman_self_is-subscribed"),
    n_("subman_self_is-unsubscribed"),
    n_("subman_self_is-unsubscription-overridden"),
    n_("subman_self_is-pending"),
    n_("subman_self_not-pending"),
    n_("subman_managing_not-subscribable"),
    n_("subman_self_not-self-subscribable"),
    n_("subman_self_not-requestable"),
    n_("subman_managing_no-unsubscribe-possible"),
    n_("subman_managing_not-privileged"),
    n_("subman_managing_no-cleanup-necessary"),

    #
    # Default Strings
    #
    n_("Cancel"),
    n_("Save"),

    #
    # country codes, see validationdata.py
    #
    n_("CountryCodes.HY"),
    n_("CountryCodes.AF"),
    n_("CountryCodes.AX"),
    n_("CountryCodes.AL"),
    n_("CountryCodes.DZ"),
    n_("CountryCodes.AS"),
    n_("CountryCodes.AD"),
    n_("CountryCodes.AO"),
    n_("CountryCodes.AI"),
    n_("CountryCodes.AQ"),
    n_("CountryCodes.AG"),
    n_("CountryCodes.AR"),
    n_("CountryCodes.AM"),
    n_("CountryCodes.AW"),
    n_("CountryCodes.AU"),
    n_("CountryCodes.AT"),
    n_("CountryCodes.AZ"),
    n_("CountryCodes.BS"),
    n_("CountryCodes.BH"),
    n_("CountryCodes.BD"),
    n_("CountryCodes.BB"),
    n_("CountryCodes.BY"),
    n_("CountryCodes.BE"),
    n_("CountryCodes.BZ"),
    n_("CountryCodes.BJ"),
    n_("CountryCodes.BM"),
    n_("CountryCodes.BT"),
    n_("CountryCodes.BO"),
    n_("CountryCodes.BA"),
    n_("CountryCodes.BW"),
    n_("CountryCodes.BV"),
    n_("CountryCodes.BR"),
    n_("CountryCodes.IO"),
    n_("CountryCodes.VG"),
    n_("CountryCodes.BN"),
    n_("CountryCodes.BG"),
    n_("CountryCodes.BF"),
    n_("CountryCodes.BI"),
    n_("CountryCodes.KH"),
    n_("CountryCodes.CM"),
    n_("CountryCodes.CA"),
    n_("CountryCodes.CV"),
    n_("CountryCodes.BQ"),
    n_("CountryCodes.KY"),
    n_("CountryCodes.CF"),
    n_("CountryCodes.TD"),
    n_("CountryCodes.CL"),
    n_("CountryCodes.CN"),
    n_("CountryCodes.CX"),
    n_("CountryCodes.CC"),
    n_("CountryCodes.CO"),
    n_("CountryCodes.KM"),
    n_("CountryCodes.CG"),
    n_("CountryCodes.CD"),
    n_("CountryCodes.CK"),
    n_("CountryCodes.CR"),
    n_("CountryCodes.CI"),
    n_("CountryCodes.HR"),
    n_("CountryCodes.CU"),
    n_("CountryCodes.CW"),
    n_("CountryCodes.CY"),
    n_("CountryCodes.CZ"),
    n_("CountryCodes.DK"),
    n_("CountryCodes.DJ"),
    n_("CountryCodes.DM"),
    n_("CountryCodes.DO"),
    n_("CountryCodes.EC"),
    n_("CountryCodes.EG"),
    n_("CountryCodes.SV"),
    n_("CountryCodes.GQ"),
    n_("CountryCodes.ER"),
    n_("CountryCodes.EE"),
    n_("CountryCodes.SZ"),
    n_("CountryCodes.ET"),
    n_("CountryCodes.FK"),
    n_("CountryCodes.FO"),
    n_("CountryCodes.FJ"),
    n_("CountryCodes.FI"),
    n_("CountryCodes.FR"),
    n_("CountryCodes.GF"),
    n_("CountryCodes.PF"),
    n_("CountryCodes.TF"),
    n_("CountryCodes.GA"),
    n_("CountryCodes.GM"),
    n_("CountryCodes.GE"),
    n_("CountryCodes.DE"),
    n_("CountryCodes.GH"),
    n_("CountryCodes.GI"),
    n_("CountryCodes.GR"),
    n_("CountryCodes.GL"),
    n_("CountryCodes.GD"),
    n_("CountryCodes.GP"),
    n_("CountryCodes.GU"),
    n_("CountryCodes.GT"),
    n_("CountryCodes.GG"),
    n_("CountryCodes.GN"),
    n_("CountryCodes.GW"),
    n_("CountryCodes.GY"),
    n_("CountryCodes.HT"),
    n_("CountryCodes.HM"),
    n_("CountryCodes.HN"),
    n_("CountryCodes.HK"),
    n_("CountryCodes.HU"),
    n_("CountryCodes.IS"),
    n_("CountryCodes.IN"),
    n_("CountryCodes.ID"),
    n_("CountryCodes.IR"),
    n_("CountryCodes.IQ"),
    n_("CountryCodes.IE"),
    n_("CountryCodes.IM"),
    n_("CountryCodes.IL"),
    n_("CountryCodes.IT"),
    n_("CountryCodes.JM"),
    n_("CountryCodes.JP"),
    n_("CountryCodes.JE"),
    n_("CountryCodes.JO"),
    n_("CountryCodes.KZ"),
    n_("CountryCodes.KE"),
    n_("CountryCodes.KI"),
    n_("CountryCodes.KW"),
    n_("CountryCodes.KG"),
    n_("CountryCodes.LA"),
    n_("CountryCodes.LV"),
    n_("CountryCodes.LB"),
    n_("CountryCodes.LS"),
    n_("CountryCodes.LR"),
    n_("CountryCodes.LY"),
    n_("CountryCodes.LI"),
    n_("CountryCodes.LT"),
    n_("CountryCodes.LU"),
    n_("CountryCodes.MO"),
    n_("CountryCodes.MG"),
    n_("CountryCodes.MW"),
    n_("CountryCodes.MY"),
    n_("CountryCodes.MV"),
    n_("CountryCodes.ML"),
    n_("CountryCodes.MT"),
    n_("CountryCodes.MH"),
    n_("CountryCodes.MQ"),
    n_("CountryCodes.MR"),
    n_("CountryCodes.MU"),
    n_("CountryCodes.YT"),
    n_("CountryCodes.MX"),
    n_("CountryCodes.FM"),
    n_("CountryCodes.MD"),
    n_("CountryCodes.MC"),
    n_("CountryCodes.MN"),
    n_("CountryCodes.ME"),
    n_("CountryCodes.MS"),
    n_("CountryCodes.MA"),
    n_("CountryCodes.MZ"),
    n_("CountryCodes.MM"),
    n_("CountryCodes.NA"),
    n_("CountryCodes.NR"),
    n_("CountryCodes.NP"),
    n_("CountryCodes.NL"),
    n_("CountryCodes.NC"),
    n_("CountryCodes.NZ"),
    n_("CountryCodes.NI"),
    n_("CountryCodes.NE"),
    n_("CountryCodes.NG"),
    n_("CountryCodes.NU"),
    n_("CountryCodes.NF"),
    n_("CountryCodes.KP"),
    n_("CountryCodes.MK"),
    n_("CountryCodes.MP"),
    n_("CountryCodes.NO"),
    n_("CountryCodes.OM"),
    n_("CountryCodes.PK"),
    n_("CountryCodes.PW"),
    n_("CountryCodes.PS"),
    n_("CountryCodes.PA"),
    n_("CountryCodes.PG"),
    n_("CountryCodes.PY"),
    n_("CountryCodes.PE"),
    n_("CountryCodes.PH"),
    n_("CountryCodes.PN"),
    n_("CountryCodes.PL"),
    n_("CountryCodes.PT"),
    n_("CountryCodes.PR"),
    n_("CountryCodes.QA"),
    n_("CountryCodes.RE"),
    n_("CountryCodes.RO"),
    n_("CountryCodes.RU"),
    n_("CountryCodes.RW"),
    n_("CountryCodes.WS"),
    n_("CountryCodes.SM"),
    n_("CountryCodes.ST"),
    n_("CountryCodes.SA"),
    n_("CountryCodes.SN"),
    n_("CountryCodes.RS"),
    n_("CountryCodes.SC"),
    n_("CountryCodes.SL"),
    n_("CountryCodes.SG"),
    n_("CountryCodes.SX"),
    n_("CountryCodes.SK"),
    n_("CountryCodes.SI"),
    n_("CountryCodes.SB"),
    n_("CountryCodes.SO"),
    n_("CountryCodes.ZA"),
    n_("CountryCodes.GS"),
    n_("CountryCodes.KR"),
    n_("CountryCodes.SS"),
    n_("CountryCodes.ES"),
    n_("CountryCodes.LK"),
    n_("CountryCodes.BL"),
    n_("CountryCodes.SH"),
    n_("CountryCodes.KN"),
    n_("CountryCodes.LC"),
    n_("CountryCodes.MF"),
    n_("CountryCodes.PM"),
    n_("CountryCodes.VC"),
    n_("CountryCodes.SD"),
    n_("CountryCodes.SR"),
    n_("CountryCodes.SJ"),
    n_("CountryCodes.SE"),
    n_("CountryCodes.CH"),
    n_("CountryCodes.SY"),
    n_("CountryCodes.TW"),
    n_("CountryCodes.TJ"),
    n_("CountryCodes.TZ"),
    n_("CountryCodes.TH"),
    n_("CountryCodes.TL"),
    n_("CountryCodes.TG"),
    n_("CountryCodes.TK"),
    n_("CountryCodes.TO"),
    n_("CountryCodes.TT"),
    n_("CountryCodes.TN"),
    n_("CountryCodes.TR"),
    n_("CountryCodes.TM"),
    n_("CountryCodes.TC"),
    n_("CountryCodes.TV"),
    n_("CountryCodes.UM"),
    n_("CountryCodes.VI"),
    n_("CountryCodes.UG"),
    n_("CountryCodes.UA"),
    n_("CountryCodes.AE"),
    n_("CountryCodes.GB"),
    n_("CountryCodes.US"),
    n_("CountryCodes.UY"),
    n_("CountryCodes.UZ"),
    n_("CountryCodes.VU"),
    n_("CountryCodes.VA"),
    n_("CountryCodes.VE"),
    n_("CountryCodes.VN"),
    n_("CountryCodes.WF"),
    n_("CountryCodes.EH"),
    n_("CountryCodes.YE"),
    n_("CountryCodes.ZM"),
    n_("CountryCodes.ZW"),
)
