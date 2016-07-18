#!/usr/bin/env python3

"""Actual translations used by :py:mod:`cdedb.internationalization`."""

from cdedb.common import glue

I18N_STRINGS = {
    ##
    ## Enums
    ##
    "AgeClasses.full": "Volljährig",
    "AgeClasses.u18": "U18",
    "AgeClasses.u16": "U16",
    "AgeClasses.u14": "U14",

    "AssemblyLogCodes.assembly_created": "Versammlung angelegt",
    "AssemblyLogCodes.assembly_changed": "Versammlung geändert",
    "AssemblyLogCodes.assembly_concluded": "Versammlung beendet",
    "AssemblyLogCodes.ballot_created": "Abstimmung angelegt",
    "AssemblyLogCodes.ballot_changed": "Abstimmung geändert",
    "AssemblyLogCodes.ballot_deleted": "Abstimmung gelöscht",
    "AssemblyLogCodes.ballot_extended": "Abstimmung verlängert",
    "AssemblyLogCodes.ballot_tallied": "Abstimmung ausgezählt",
    "AssemblyLogCodes.candidate_added": "Option hinzugefügt",
    "AssemblyLogCodes.candidate_updated": "Option geändert",
    "AssemblyLogCodes.candidate_removed": "Option entfernt",
    "AssemblyLogCodes.new_attendee": "Neuer Teilnehmer",
    "AssemblyLogCodes.attachment_added": "Anhang hinzugefügt",
    "AssemblyLogCodes.attachment_removed": "Anhang entfernt",

    "AttachmentPolicy.allow": "Alle Anhänge erlaubt",
    "AttachmentPolicy.pdf_only": "Nur PDF-Anhänge erlaubt",
    "AttachmentPolicy.forbid": "Keine Anhänge erlaubt",

    "AudiencePolicy.everybody": "Alle",
    "AudiencePolicy.require_assembly": "Nur Versammlungsnutzer",
    "AudiencePolicy.require_cde": "Nur CdE-Nutzer",
    "AudiencePolicy.require_event": "Nur Veranstaltungsnutzer",
    "AudiencePolicy.require_member": "Nur CdE-Mitglieder",

    "CdeLogCodes.advance_semester": "Nächstes Semester",
    "CdeLogCodes.advance_expuls": "Nächster Expuls",

    "CoreLogCodes.persona_creation": "Account erstellt",
    "CoreLogCodes.persona_change": "Account geändert",
    "CoreLogCodes.password_change": "Passwort geändert",
    "CoreLogCodes.password_reset_cookie": "Passwortrücksetzcookie erstellt",
    "CoreLogCodes.password_reset": "Passwort zurückgesetzt",
    "CoreLogCodes.password_generated": "Passwort generiert",
    "CoreLogCodes.genesis_request": "Neue Accountanfrage",
    "CoreLogCodes.genesis_approved": "Accountanfrage bestätigt",
    "CoreLogCodes.genesis_rejected": "Accountanfrage abgelehnt",

    "CourseFilterPositions.instructor": "Kursleiter",
    "CourseFilterPositions.first_choice": "Erstwahl",
    "CourseFilterPositions.second_choice": "Zweitwahl",
    "CourseFilterPositions.third_choice": "Drittwahl",
    "CourseFilterPositions.any_choice": "bel. Wahl",
    "CourseFilterPositions.assigned": "Kurs zugeteilt",
    "CourseFilterPositions.anywhere": "irgendwo",

    "EventLogCodes.event_created": "Veranstaltung erstellt",
    "EventLogCodes.event_changed": "Veranstaltung geändert",
    "EventLogCodes.orga_added": "Orga hinzugefügt",
    "EventLogCodes.orga_removed": "Orga entfernt",
    "EventLogCodes.part_created": "Veranstaltungsteil erstellt",
    "EventLogCodes.part_changed": "Veranstaltungsteil geändert",
    "EventLogCodes.part_deleted": "Veranstaltungsteil gelöscht",
    "EventLogCodes.field_added": "Feld hinzugefügt",
    "EventLogCodes.field_updated": "Feld geändert",
    "EventLogCodes.field_removed": "Feld entfernt",
    "EventLogCodes.lodgement_created": "Unterkunft erstellt",
    "EventLogCodes.lodgement_changed": "Unterkunft geändert",
    "EventLogCodes.lodgement_deleted": "Unterkunft gelöscht",
    "EventLogCodes.questionnaire_changed": "Fragebogen geändert",
    "EventLogCodes.course_created": "Kurs erstellt",
    "EventLogCodes.course_changed": "Kurs geändert",
    "EventLogCodes.course_parts_changed": "Kursteile geändert",
    "EventLogCodes.registration_created": "Anmeldung erstellt",
    "EventLogCodes.registration_changed": "Anmeldung geändert",
    "EventLogCodes.event_locked": "Veranstaltung gesperrt",
    "EventLogCodes.event_unlocked": "Veranstaltung entsperrt",

    "FinanceLogCodes.new_member": "Neues Mitglied",
    "FinanceLogCodes.gain_membership": "Mitgliedschaft erhalten",
    "FinanceLogCodes.lose_membership": "Mitgliedschaft verloren",
    "FinanceLogCodes.increase_balance": "Guthaben gutgeschrieben",
    "FinanceLogCodes.deduct_membership_fee": "Beitrag abgezogen",
    "FinanceLogCodes.end_trial_membership": "Ende der Probemitgliedschaft",
    "FinanceLogCodes.grant_lastschrift": "Einzugsermächtigung erteilt",
    "FinanceLogCodes.revoke_lastschrift": "Einzugsermächtigung widerrufen",
    "FinanceLogCodes.modify_lastschrift": "Einzugsermächtigung geändert",
    "FinanceLogCodes.lastschrift_transaction_issue": "Einzug erstellt",
    "FinanceLogCodes.lastschrift_transaction_success": "Einzug erfolgreich",
    "FinanceLogCodes.lastschrift_transaction_failure": "Einzug fehlgeschlagen",
    "FinanceLogCodes.lastschrift_transaction_skip": "Einzug pausiert",
    "FinanceLogCodes.lastschrift_transaction_cancelled": "Einzug abgebroche",
    "FinanceLogCodes.lastschrift_transaction_revoked": "Einzug zurückgebucht",

    "Genders.female": "weiblich",
    "Genders.male": "männlich",
    "Genders.unknown": "sonstiges",

    "LineResolutions.create": "Account erstellen",
    "LineResolutions.skip": "Eintrag ignorieren",
    "LineResolutions.renew_trial": "Probemitgliedschaft erneuern",
    "LineResolutions.update": "Daten übernehmen",
    "LineResolutions.renew_and_update": glue(
        "Probemitgliedschaft erneuern und Daten übernehmen"),

    "MemberChangeStati.pending": "Änderung wartet auf Bestätigung",
    "MemberChangeStati.committed": "Änderung übernommen",
    "MemberChangeStati.superseeded": "Änderung veraltet",
    "MemberChangeStati.nacked": "Änderung abgelehnt",
    "MemberChangeStati.displaced": "Änderung verdrängt",

    "MlLogCodes.list_created": "Mailingliste erstellt",
    "MlLogCodes.list_changed": "Mailingliste geändert",
    "MlLogCodes.list_deleted": "Mailingliste gelöscht",
    "MlLogCodes.moderator_added": "Moderator hinzugefügt",
    "MlLogCodes.moderator_removed": "Moderator entfernt",
    "MlLogCodes.whitelist_added": "Whitelist-Eintrag hinzugefügt",
    "MlLogCodes.whitelist_removed": "Whitelist-Eintrag entfernt",
    "MlLogCodes.subscription_requested": "Abonnement beantregt",
    "MlLogCodes.subscribed": "Abonniert",
    "MlLogCodes.subscription_changed": "Abonnement geändert",
    "MlLogCodes.unsubscribed": "Abbestellt",
    "MlLogCodes.request_approved": "Abonnementantrag bestätigt",
    "MlLogCodes.request_denied": "Abonnementantrag abgelehnt",

    "ModerationPolicy.unmoderated": "Alle dürfen schreiben",
    "ModerationPolicy.non_subscribers": "Abonnenten dürfen schreiben",
    "ModerationPolicy.fully_moderated": "Alle moderiert",

    "PastEventLogCodes.event_created": "Abg. Veranstaltung erstellt",
    "PastEventLogCodes.event_changed": "Abg. Veranstaltung geändert",
    "PastEventLogCodes.course_created": "Abg. Kurs erstellt",
    "PastEventLogCodes.course_changed": "Abg. Kurs geändert",
    "PastEventLogCodes.course_deleted": "Abg. Kurs gelöscht",
    "PastEventLogCodes.participant_added": "Teilnehmer hinzugefügt",
    "PastEventLogCodes.participant_removed": "Teilnehmer entfernt",
    "PastEventLogCodes.institution_created": "Organisation erstellt",
    "PastEventLogCodes.institution_changed": "Organisation geändert",
    "PastEventLogCodes.institution_deleted": "Organisation gelöscht",

    "RegistrationPartStati.not_applied": "Nicht angemeldet",
    "RegistrationPartStati.applied": "Offen",
    "RegistrationPartStati.participant": "Teilnehmer",
    "RegistrationPartStati.waitlist": "Warteliste",
    "RegistrationPartStati.guest": "Gast",
    "RegistrationPartStati.cancelled": "Abgemeldet",
    "RegistrationPartStati.rejected": "Abgelehnt",

    "SubscriptionPolicy.mandatory": "Alternativlos",
    "SubscriptionPolicy.opt_out": "Opt-Out",
    "SubscriptionPolicy.opt_in": "Opt-In",
    "SubscriptionPolicy.moderated_opt_in": "Moderiertes Opt-In",
    "SubscriptionPolicy.invitation_only": "Nur durch Moderatoren",

    ##
    ## Email subjects
    ##
    "Address check mail for ExPuls": "Adresskontrollmail für den Expulsversand",
    "CdE admission": "Aufnahme in den CdE",
    "CdEDB account approved": "CdEDB Accountanfrage bestätigt",
    "CdEDB account declined": "CdEDB Accountanfrage abgelehnt",
    "CdEDB account creation": "CdEDB Account erstellt",
    "CdEDB account request": "CdEDB Accountanfrage verifizieren",
    "CdEDB password reset": "CdEDB Passwort zurücksetzen",
    "CdEDB pending changes": "CdEDB Änderungen zu begutachten",
    "CdEDB username change": "CdEDB Neue Emailadresse verifizieren",
    "CdE money transfer received": "Überweisung beim CdE eingetroffen",
    "Confirm email address for CdE mailing list": glue(
        "Emailadresse für Mailingliste bestätigen"),
    "Ejection from CdE": "Austritt aus dem CdE e.V.",
    "Renew your CdE membership": "CdE-Mitgliedschaft verlängern",


    ##
    ## Notifications
    ##
    "Attachment added.": "Anhang hinzugefügt.",
    "Case abandoned.": "Antrag zu den Akten gelegt.",
    "Case approved.": "Antrag genehmigt.",
    "Change committed.": "Änderung übernommen.",
    "Change pending.": "Änderung wartet auf Bestätigung.",
    "Confirmation email sent.": "Verifizierungsemail verschickt.",
    "Consent noted.": "Zustimmung gespeichert.",
    "Course created.": "Kurs erstellt.",
    "Email sent.": "Email abgeschickt.",
    "Email verified.": "Emailadresse verifiziert.",
    "Entry changed.": "Eintrag geändert.",
    "Event archived.": "Veranstaltung archiviert.",
    "Event created.": "Veranstaltung erstellt.",
    "Failed validation.": "Validierung fehlgeschlagen.",
    "Session expired.": "Die Sitzung ist abgelaufen.",
    "Form updated.": "Formular aktualisiert.",
    "Foto updated.": "Bild aktualisiert.",
    "Login failure.": "Login fehlgeschlagen.",
    "New expuls started.": "Nächster Expuls initialisiert.",
    "New period started.": "Nächstes Semester initialisiert.",
    "Not sending mail.": "Keine Email verschickt.",
    "Password changed.": "Passwort geändert.",
    "Password reset.": "Passwort zurückgesetzt.",
    "Privileged user may not reset.": glue(
        "Administratoraccounts können nicht zurückgesetzt werden"),
    "Registered for event.": "Für Veranstaltung angemeldet.",
    "Reset verification failed.": glue(
        "Verifizierung des Zurücksetzens fehlgeschlagen"),
    "Signed up.": "Angemeldet.",
    "Skipped.": "Pausiert.",
    "Started ejection.": "Streichung inaktiver Mitglieder gestartet.",
    "Started sending mail.": "Emailversand hat begonnen.",
    "Started updating balance.": "Aktualisierung der Guthaben gestartet.",
    "Subscription request awaits moderation.": glue(
        "Abonnement wird durch einen Moderator geprüft"),
    "User created.": "Account erstellt.",
    "Username changed.": "Emailadresse geändert.",

    ##
    ## Validation errors
    ##
    "[<class 'decimal.ConversionSyntax'>]": "Keine Zahl gefunden.",
    "day is out of range for month": "Tag liegt nicht im Monat.",
    "Doppelganger choice doesn't fit resolution.": glue(
        "Accountzusammenführung inkonsistent mit Aktion."),
    "Doppelganger not a CdE-Account.": glue(
        "Accountzusammenführung mit einem nicht-CdE-Account."),
    "Doppelgangers found.": "Ähnlicher Account gefunden.",
    "Family name doesn't match.": "Nachname passt nicht.",
    "Must be printable ASCII.": glue(
        "Darf nur aus druckbaren ASCII-Zeichen bestehen."),
    "Invalid german postal code.": "Ungültige Postleitzahl.",
    "'Mandatory key missing.'": "Notwendige Angabe fehlt.",
    "Must be a datetime.date.": "Kein Datum gefunden.",
    "Mustn't be empty.": "Darf nicht leer sein.",
    "No course available.": "Kein Kurs verfügbar.",
    "No course found.": "Kein Kurs gefunden.",
    "No event found.": "Keine Veranstaltung gefunden.",
    "No input supplied.": "Keine Eingabe vorhanden.",
    "Unknown string format": "Unbekanntes Format.",
    "Wrong formatting.": "Falsches Format.",

    ##
    ## Filenames
    ##
    "course_lists.pdf": "Kursliste.pdf",
    "course_puzzle.pdf": "Kurspuzzle.pdf",
    "course_puzzle.tex": "Kurspuzzle.tex",
    "export_event.json": "Veranstaltungsexport.json",
    "expuls.tex": "Expuls.tex",
    "lastschrift_receipt.pdf": "Spendenbescheinigung.pdf",
    "lastschrift_subscription_form.pdf": "Einzugsermächtigung.pdf",
    "lodgement_lists.pdf": "Unterkunftsliste.pdf",
    "lodgement_puzzle.pdf": "Unterkunftspuzzle.pdf",
    "lodgement_puzzle.tex": "Unterkunftspuzzle.tex",
    "minor_form.pdf": "Elternbrief.pdf",
    "nametags.pdf": "Namenschilder.pdf",
    "participant_list.pdf": "Teilnehmerliste.pdf",
    "participant_list.tex": "Teilnehmerliste.tex",
    "result.json": "Ergebnis.json",
    "result.txt": "Ergebnis.txt",
    "sepa.cdd": "sepa.cdd",

    ##
    ## Miscellaneous
    ##
    "course (any part)": "Kurs zugeteilt (bel. Teil)",
    "course instuctor (any part)": "Kursleiter (bel. Teil)",
    "lodgement (any part)": "Unterkunf (bel. Teil)",
    "registration status (any part)": "Anmeldestatus (bel. Teil)",
    "Start": "Start",
    "": "",
    None: "Undefiniert.",
}

I18N_REGEXES = {
    r"No persona with id ([0-9]+)\.": r"Kein Nutzer mit ID \1 gefunden.",
    r"Ballot '([^)]+)' got tallied.": r"Abstimmung '\1' wurde ausgezählt.",
    r"Committed ([0-9]+) transfers.": r"\1 Überweisungen gebucht.",
    r"course instructor \(part ([^)]+)\)": r"Kursleiter (\1)",
    r"course \(part  ([^)]+)\)": r"Kurs zugeteilt (\1)",
    r"lodgement \(part ([^)]+)\)": r"Unterkunft (\1)",
    r"Created ([0-9]+) accounts.": r"\1 Accounts erstellt.",
    r"invalid literal for int\(\) with base 10: .*": r"Keine Zahl gefunden.",
    r"Lines ([0-9]+) and ([0-9]+) are the same.": glue(
        r"Zeilen \1 und \2 sind identisch."),
    glue(r"More than one transfer for this",
         r"account \(lines ([0-9]+) and ([0-9]+)\)."): glue(
             r"Mehrere Überweisungen für diesen Account (Zeilen \1 und \2)."),
    r"Registered for event (.*)": r"Für Veranstaltung \1 angemeldet",
    r"registration status \(part ([^)]+)\)": r"Anmeldestatus (\1)",
    r"Signed up for assembly (.*)": r"Anmeldung zur Versammlung \1",
    r"Stored email to hard drive at (.*)": glue(
        r"Email als \1 auf der Festplatte gespeichert."),
}
