#!/usr/bin/env python3

"""Additional strings for i18n which do not occur literally."""

from cdedb.common import _

I18N_STRINGS = (
    ##
    ## Enums
    ##
    _("AgeClasses.full"),
    _("AgeClasses.u18"),
    _("AgeClasses.u16"),
    _("AgeClasses.u14"),

    _("AssemblyLogCodes.assembly_created"),
    _("AssemblyLogCodes.assembly_changed"),
    _("AssemblyLogCodes.assembly_concluded"),
    _("AssemblyLogCodes.ballot_created"),
    _("AssemblyLogCodes.ballot_changed"),
    _("AssemblyLogCodes.ballot_deleted"),
    _("AssemblyLogCodes.ballot_extended"),
    _("AssemblyLogCodes.ballot_tallied"),
    _("AssemblyLogCodes.candidate_added"),
    _("AssemblyLogCodes.candidate_updated"),
    _("AssemblyLogCodes.candidate_removed"),
    _("AssemblyLogCodes.new_attendee"),
    _("AssemblyLogCodes.attachment_added"),
    _("AssemblyLogCodes.attachment_removed"),

    _("AttachmentPolicy.allow"),
    _("AttachmentPolicy.pdf_only"),
    _("AttachmentPolicy.forbid"),

    _("AudiencePolicy.everybody"),
    _("AudiencePolicy.require_assembly"),
    _("AudiencePolicy.require_cde"),
    _("AudiencePolicy.require_event"),
    _("AudiencePolicy.require_member"),

    _("CdeLogCodes.advance_semester"),
    _("CdeLogCodes.advance_expuls"),

    _("CoreLogCodes.persona_creation"),
    _("CoreLogCodes.persona_change"),
    _("CoreLogCodes.password_change"),
    _("CoreLogCodes.password_reset_cookie"),
    _("CoreLogCodes.password_reset"),
    _("CoreLogCodes.password_generated"),
    _("CoreLogCodes.genesis_request"),
    _("CoreLogCodes.genesis_approved"),
    _("CoreLogCodes.genesis_rejected"),

    _("CourseFilterPositions.instructor"),
    _("CourseFilterPositions.first_choice"),
    _("CourseFilterPositions.second_choice"),
    _("CourseFilterPositions.third_choice"),
    _("CourseFilterPositions.any_choice"),
    _("CourseFilterPositions.assigned"),
    _("CourseFilterPositions.anywhere"),

    _("EventLogCodes.event_created"),
    _("EventLogCodes.event_changed"),
    _("EventLogCodes.orga_added"),
    _("EventLogCodes.orga_removed"),
    _("EventLogCodes.part_created"),
    _("EventLogCodes.part_changed"),
    _("EventLogCodes.part_deleted"),
    _("EventLogCodes.field_added"),
    _("EventLogCodes.field_updated"),
    _("EventLogCodes.field_removed"),
    _("EventLogCodes.lodgement_created"),
    _("EventLogCodes.lodgement_changed"),
    _("EventLogCodes.lodgement_deleted"),
    _("EventLogCodes.questionnaire_changed"),
    _("EventLogCodes.track_added"),
    _("EventLogCodes.track_updated"),
    _("EventLogCodes.track_removed"),
    _("EventLogCodes.course_created"),
    _("EventLogCodes.course_changed"),
    _("EventLogCodes.course_segments_changed"),
    _("EventLogCodes.course_segment_activity_changed"),
    _("EventLogCodes.registration_created"),
    _("EventLogCodes.registration_changed"),
    _("EventLogCodes.registration_deleted"),
    _("EventLogCodes.event_locked"),
    _("EventLogCodes.event_unlocked"),

    _("FinanceLogCodes.new_member"),
    _("FinanceLogCodes.gain_membership"),
    _("FinanceLogCodes.lose_membership"),
    _("FinanceLogCodes.increase_balance"),
    _("FinanceLogCodes.deduct_membership_fee"),
    _("FinanceLogCodes.end_trial_membership"),
    _("FinanceLogCodes.grant_lastschrift"),
    _("FinanceLogCodes.revoke_lastschrift"),
    _("FinanceLogCodes.modify_lastschrift"),
    _("FinanceLogCodes.lastschrift_transaction_issue"),
    _("FinanceLogCodes.lastschrift_transaction_success"),
    _("FinanceLogCodes.lastschrift_transaction_failure"),
    _("FinanceLogCodes.lastschrift_transaction_skip"),
    _("FinanceLogCodes.lastschrift_transaction_cancelled"),
    _("FinanceLogCodes.lastschrift_transaction_revoked"),

    _("Genders.female"),
    _("Genders.male"),
    _("Genders.unknown"),

    _("LineResolutions.create"),
    _("LineResolutions.skip"),
    _("LineResolutions.renew_trial"),
    _("LineResolutions.update"),
    _("LineResolutions.renew_and_update"),

    _("MemberChangeStati.pending"),
    _("MemberChangeStati.committed"),
    _("MemberChangeStati.superseeded"),
    _("MemberChangeStati.nacked"),
    _("MemberChangeStati.displaced"),

    _("MlLogCodes.list_created"),
    _("MlLogCodes.list_changed"),
    _("MlLogCodes.list_deleted"),
    _("MlLogCodes.moderator_added"),
    _("MlLogCodes.moderator_removed"),
    _("MlLogCodes.whitelist_added"),
    _("MlLogCodes.whitelist_removed"),
    _("MlLogCodes.subscription_requested"),
    _("MlLogCodes.subscribed"),
    _("MlLogCodes.subscription_changed"),
    _("MlLogCodes.unsubscribed"),
    _("MlLogCodes.request_approved"),
    _("MlLogCodes.request_denied"),

    _("ModerationPolicy.unmoderated"),
    _("ModerationPolicy.non_subscribers"),
    _("ModerationPolicy.fully_moderated"),

    _("PastEventLogCodes.event_created"),
    _("PastEventLogCodes.event_changed"),
    _("PastEventLogCodes.course_created"),
    _("PastEventLogCodes.course_changed"),
    _("PastEventLogCodes.course_deleted"),
    _("PastEventLogCodes.participant_added"),
    _("PastEventLogCodes.participant_removed"),
    _("PastEventLogCodes.institution_created"),
    _("PastEventLogCodes.institution_changed"),
    _("PastEventLogCodes.institution_deleted"),

    _("RegistrationPartStati.not_applied"),
    _("RegistrationPartStati.applied"),
    _("RegistrationPartStati.participant"),
    _("RegistrationPartStati.waitlist"),
    _("RegistrationPartStati.guest"),
    _("RegistrationPartStati.cancelled"),
    _("RegistrationPartStati.rejected"),

    _("SubscriptionPolicy.mandatory"),
    _("SubscriptionPolicy.opt_out"),
    _("SubscriptionPolicy.opt_in"),
    _("SubscriptionPolicy.moderated_opt_in"),
    _("SubscriptionPolicy.invitation_only"),

    _("LastschriftTransactionStati.issued"),
    _("LastschriftTransactionStati.skipped"),
    _("LastschriftTransactionStati.success"),
    _("LastschriftTransactionStati.failure"),
    _("LastschriftTransactionStati.cancelled"),
    _("LastschriftTransactionStati.rollback"),

    ##
    ## Validation errors
    ##
    _("day is out of range for month"),
    _("[<class 'decimal.ConversionSyntax'>]"),
)
