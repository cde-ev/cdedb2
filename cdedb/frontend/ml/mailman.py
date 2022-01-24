#!/usr/bin/env python3

"""Mailman interface for the database.

This utilizes the mailman REST API to drive the mailinglists residing
on the mail VM from within the CdEDB.
"""
from mailmanclient import Client, MailingList

import cdedb.database.constants as const
from cdedb.common import CdEDBObject, RequestState
from cdedb.frontend.common import cdedburl, make_persona_name, periodic
from cdedb.frontend.ml.base import MlBaseFrontend

POLICY_MEMBER_CONVERT = {
    const.ModerationPolicy.unmoderated: 'accept',
    const.ModerationPolicy.non_subscribers: 'accept',
    const.ModerationPolicy.fully_moderated: 'hold',
}


POLICY_OTHER_CONVERT = {
    const.ModerationPolicy.unmoderated: 'accept',
    const.ModerationPolicy.non_subscribers: 'hold',
    const.ModerationPolicy.fully_moderated: 'hold',
}


def template_url(name: str) -> str:
    """Construct an HTTP URL to a published mailman template.

    The handling of templates in mailman is a bit tricky involving a
    separate URI for each template which we construct here.
    """
    return "https://db.cde-ev.de/mailman_templates/{}".format(name)


class MlMailmanMixin(MlBaseFrontend):
    def mailman_sync_list_meta(self, rs: RequestState, mailman: Client,
                               db_list: CdEDBObject,
                               mm_list: MailingList) -> None:
        prefix = ""
        if db_list['subject_prefix']:
            prefix = "[{}] ".format(db_list['subject_prefix'] or "")

        # First, specify the generally desired settings, templates and header matches.
        desired_settings = {
            'send_welcome_message': False,
            # Available only in mailman-3.3
            # 'send_goodbye_message': False,
            # block the usage of the self-service facilities which should
            # not be used to prevent synchronisation issues
            'subscription_policy': 'moderate',
            'unsubscription_policy': 'moderate',
            'archive_policy': 'private',
            'convert_html_to_plaintext': True,
            'dmarc_mitigate_action': 'wrap_message',
            'dmarc_mitigate_unconditionally': False,
            'dmarc_wrapped_message_text': (
                "Diese Nachricht wurde mit modifizierter Senderadresse weitergeleitet,"
                " da die DMARC-Sicherheitsrichtlinien des initialen Mailproviders"
                " mit Maillinglisten inkompatibel sind."),
            'administrivia': True,
            'member_roster_visibility': 'moderators',
            'advertised': True,
            'display_name': db_list['title'],
            'description': db_list['title'],
            'info': db_list['description'] or "",
            'subject_prefix': prefix,
            'max_message_size': db_list['maxsize'] or 0,
            'default_member_action': POLICY_MEMBER_CONVERT[
                db_list['mod_policy']],
            'default_nonmember_action': POLICY_OTHER_CONVERT[
                db_list['mod_policy']],
            # TODO handle attachment_policy, only available in mailman-3.3
            # 'filter_content': True,
            # 'filter_action': 'forward',
            # 'pass_extensions': ['pdf'],
            # 'pass_types': ['multipart', 'text/plain', 'application/pdf'],
        }
        desired_templates = {
            # pylint: disable=line-too-long
            # Funny split to protect trailing whitespace
            'list:member:regular:footer': '-- ' + f"""
Dies ist eine Mailingliste des CdE e.V.
Zur Abo-Verwaltung benutze die Datenbank ({cdedburl(rs, 'ml/index', force_external=True)})""",
            'list:admin:action:post': f"""
As list moderator, your authorization is requested for the
following mailing list posting:

    List:    $listname
    From:    $sender_email
    Subject: $subject

The message is being held because:

$reasons

At your convenience, visit the CdEDB [1] to approve or deny the request. Note
that the paragraph below about email moderation is wrong. Sending mails will
do nothing.

[1] {cdedburl(rs, 'ml/message_moderation', {'mailinglist_id': db_list['id']}, force_external=True)}
""".strip(),
        }
        desired_header_matches = {
            ('x-spam-flag', 'YES', 'hold'),
        }
        if not db_list['is_active']:
            desired_settings.update({
                'advertised': False,
                'default_member_action': 'reject',
                'default_nonmember_action': 'reject',
            })
            desired_templates['list:user:notice:rejected'] = """
Your message to the $listname mailing-list was rejected for the following
reasons:

The list is currently inactive and does not process messages.

The original message as received by Mailman is attached.
""".strip()
            desired_header_matches = {
                ('x-spam-flag', 'YES', 'discard'),
            }

        # Second, update values to mailman if changed
        changed = False
        for key, val in desired_settings.items():
            if mm_list.settings[key] != val:
                mm_list.settings[key] = val
                changed = True
        if changed:
            mm_list.settings.save()

        existing_header_matches = {
            (match.rest_data['header'], match.rest_data['pattern'],
             match.rest_data['action'])
            for match in mm_list.header_matches
        }
        if desired_header_matches != existing_header_matches:
            header_matches = mm_list.header_matches
            for match in header_matches:
                match.delete()
            for header, pattern, action in desired_header_matches:
                mm_list.header_matches.add(header, pattern, action)

        existing_templates = {
            t.name: t for t in mm_list.templates
        }
        store_path = self.conf["STORAGE_DIR"] / 'mailman_templates'
        for name, text in desired_templates.items():
            file_name = "{}__{}".format(db_list['id'], name)
            file_path = store_path / file_name
            todo = False
            if not file_path.exists():
                todo = True
            else:
                with open(file_path) as f:
                    current_text = f.read()
                if current_text != text:
                    todo = True
            url = template_url(file_name)
            if name not in existing_templates:
                todo = True
            elif existing_templates[name].uri != url:
                todo = True
            if todo:
                with open(file_path, 'w') as f:
                    f.write(text)
                mm_list.set_template(
                    name, template_url(file_name),
                    username=self.conf["MAILMAN_BASIC_AUTH_USER"],
                    password=mailman.template_password)
        for name in set(existing_templates) - set(desired_templates):
            existing_templates[name].delete()

    def mailman_sync_list_subs(self, rs: RequestState, mailman: Client,
                               db_list: CdEDBObject,
                               mm_list: MailingList) -> None:
        subscribing_states = const.SubscriptionState.subscribing_states()
        persona_ids = set(self.mlproxy.get_subscription_states(
            rs, db_list['id'], states=subscribing_states))
        db_addresses = self.mlproxy.get_subscription_addresses(
            rs, db_list['id'], persona_ids)
        personas = self.coreproxy.get_personas(rs, persona_ids)
        db_subscribers = {
            address: make_persona_name(personas[pid])
            for pid, address in db_addresses.items() if address
        }
        mm_subscribers = {m.email: m for m in mm_list.members}

        new_subs = set(db_subscribers) - set(mm_subscribers)
        delete_subs = set(mm_subscribers) - set(db_subscribers)

        for address in new_subs:
            mm_list.subscribe(address, display_name=db_subscribers[address],
                              pre_verified=True, pre_confirmed=True,
                              pre_approved=True)
        for address in delete_subs:
            mm_list.unsubscribe(address, pre_confirmed=True, pre_approved=True)

    def mailman_sync_list_mods(self, rs: RequestState, mailman: Client,
                               db_list: CdEDBObject,
                               mm_list: MailingList) -> None:
        personas = self.coreproxy.get_personas(
            rs, db_list['moderators'])
        db_moderators = {
            persona['username']: make_persona_name(persona)
            for persona in personas.values() if persona['username']
        }
        mm_moderators = {m.email: m for m in mm_list.moderators}

        new_mods = set(db_moderators) - set(mm_moderators)
        delete_mods = set(mm_moderators) - set(db_moderators)

        for address in new_mods:
            mm_list.add_moderator(address)
        for address in delete_mods:
            mm_list.remove_moderator(address)

        mm_owners = {m.email: m for m in mm_list.owners}
        new_owners = set(db_moderators) - set(mm_owners)
        delete_owners = set(mm_owners) - set(db_moderators)

        for address in new_owners:
            mm_list.add_owner(address)
        for address in delete_owners:
            mm_list.remove_owner(address)

    def mailman_sync_list_whites(self, rs: RequestState, mailman: Client,
                                 db_list: CdEDBObject, mm_list: MailingList) -> None:
        db_whitelist = db_list['whitelist']
        mm_whitelist = {n.email: n for n in mm_list.nonmembers}

        # implicitly whitelist username for personas with custom address
        if db_list['mod_policy'] == const.ModerationPolicy.non_subscribers:
            db_whitelist |= self.mlproxy.get_implicit_whitelist(rs, db_list['id'])

        new_whites = set(db_whitelist) - set(mm_whitelist)
        current_whites = set(mm_whitelist) - new_whites
        delete_whites = set(mm_whitelist) - set(db_whitelist)

        for address in new_whites:
            mm_list.add_role('nonmember', address)
            # get_nonmember is only available in mailman 3.3
            # white = mm_list.get_nonmember(address)
        mm_updated_whitelist = {n.email: n for n in mm_list.nonmembers}
        for address in new_whites:
            # because of the unavailability of get_nonmember we do a
            # different lookup
            white = mm_updated_whitelist.get(address)
            if white is not None:
                white.moderation_action = 'accept'
                white.save()
        for address in current_whites:
            white = mm_whitelist[address]
            if white.moderation_action != 'accept':
                white.moderation_action = 'accept'
                white.save()
        for address in delete_whites:
            mm_list.remove_role('nonmember', address)

    def mailman_sync_list(self, rs: RequestState, mailman: Client,
                          db_list: CdEDBObject, mm_list: MailingList) -> None:
        self.mailman_sync_list_meta(rs, mailman, db_list, mm_list)
        if db_list['is_active']:
            self.mailman_sync_list_subs(rs, mailman, db_list, mm_list)
            self.mailman_sync_list_mods(rs, mailman, db_list, mm_list)
            self.mailman_sync_list_whites(rs, mailman, db_list, mm_list)

    @periodic("mailman_sync")
    def mailman_sync(self, rs: RequestState, store: CdEDBObject) -> CdEDBObject:
        """Synchronize the mailing list software with the database.

        This has an @periodic decorator in the frontend.
        """
        if (self.conf["CDEDB_OFFLINE_DEPLOYMENT"] or (
                self.conf["CDEDB_DEV"] and not self.conf["CDEDB_TEST"])):  # pragma: no cover
            self.logger.debug("Skipping mailman sync in dev/offline mode.")
            return store
        mailman = self.get_mailman()
        # noinspection PyBroadException
        try:
            _ = mailman.system  # cause the client to connect
        except Exception:  # sadly this throws many different exceptions
            self.logger.exception("Mailman client connection failed!")
            return store
        db_lists = self.mlproxy.get_mailinglists(
            rs, self.mlproxy.list_mailinglists(rs, active_only=False))
        db_lists = {lst['address']: lst for lst in db_lists.values()}
        mm_lists = {lst.fqdn_listname: lst for lst in mailman.lists}
        new_lists = set(db_lists) - set(mm_lists)
        current_lists = set(db_lists) - new_lists
        deleted_lists = set(mm_lists) - set(db_lists)

        for address in new_lists:
            local_part, domain = address.split('@')
            mm_list = mailman.get_domain(domain).create_list(local_part)
            self.mailman_sync_list(rs, mailman, db_lists[address], mm_list)
        for address in current_lists:
            self.mailman_sync_list(rs, mailman, db_lists[address],
                                   mm_lists[address])
        for address in deleted_lists:
            mailman.delete_list(address)
        return store
