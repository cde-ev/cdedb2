#!/usr/bin/env python3

"""Mailman interface for the database.

This utilizes the mailman REST API to drive the mailinglists residing
on the mail VM from within the CdEDB.
"""

import cdedb.database.constants as const
from cdedb.frontend.common import periodic
from cdedb.frontend.ml_base import MlBaseFrontend


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


def template_url(name):
    """Construct an HTTP URL to a published mailman template.

    The handling of templates in mailman is a bit tricky involving a
    separate URI for each template which we construct here.

    :type name: str
    :rtype: str
    """
    return "https://db.cde-ev.de/mailman_templates/{}".format(name)


class MailmanMixin(MlBaseFrontend):
    def mailman_connect(self):
        """Create a Mailman REST client."""
        url = f"http://{self.conf['MAILMAN_HOST']}/3.1"
        return self.mailman_create_client(url, self.conf["MAILMAN_USER"])

    def mailman_sync_list_meta(self, rs, mailman, db_list, mm_list):
        prefix = ""
        if db_list['subject_prefix']:
            prefix = "[{}] ".format(db_list['subject_prefix'])
        desired_settings = {
            'send_welcome_message': False,
            # block the usage of the self-service facilities which should
            # not be used to prevent synchronisation issues
            'subscription_policy': 'moderate',
            'unsubscription_policy': 'moderate',
            'archive_policy': 'private',
            'filter_content': True,
            'convert_html_to_plaintext': True,
            'dmarc_mitigations': 'wrap_message',
            'dmarc_mitigate_unconditionally': False,
            'dmarc_wrapped_message_text': 'Nachricht wegen DMARC eingepackt.',
            'administrivia': True,
            'member_roster_visibility': 'moderators',
            'advertised': True,
            'display_name': db_list['title'],
            'description': db_list['title'],
            'info': db_list['description'],
            'subject_prefix': prefix,
            'max_message_size': db_list['maxsize'],
            'default_member_action': POLICY_MEMBER_CONVERT[
                db_list['mod_policy']],
            'default_nonmember_action': POLICY_OTHER_CONVERT[
                db_list['mod_policy']],
            # TODO handle attachment_policy
        }
        if not db_list['is_active']:
            desired_settings.update({
                'advertised': False,
                'default_member_action': 'reject',
                'default_nonmember_action': 'reject',
            })
        changed = False
        for key, val in desired_settings.items():
            if mm_list.settings[key] != val:
                mm_list.settings[key] = val
                changed = True
        if changed:
            mm_list.settings.save()

        desired_templates = {
            'list:member:regular:footer': (
                "Dies ist eine Mailingliste des CdE e.V.\n"
                "Zur Abo-Verwaltung benutze die Datenbank"
                " (https://db.cde-ev.de/db/ml/)"),
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
            if todo:
                with open(file_path, 'w') as f:
                    f.write(text)
                mm_list.set_template(
                    name, template_url(file_name),
                    username=self.conf["MAILMAN_BASIC_AUTH_USER"],
                    password=self.mailman_template_password())

    def mailman_sync_list_subs(self, rs, mailman, db_list, mm_list):
        SS = const.SubscriptionStates
        persona_ids = set(self.mlproxy.get_subscription_states(
            rs, db_list['id'], states=SS.subscribing_states()))
        db_addresses = self.mlproxy.get_subscription_addresses(
            rs, db_list['id'], persona_ids)
        personas = self.coreproxy.get_personas(rs, persona_ids)
        db_subscribers = {
            address: "{} {}".format(personas[pid]['given_names'],
                                    personas[pid]['family_name'])
            for pid, address in db_addresses.items() if address
        }
        mm_subscribers = {m.address: m for m in mm_list.members}

        new_subs = set(db_subscribers) - set(mm_subscribers)
        delete_subs = set(mm_subscribers) - set(db_subscribers)

        for address in new_subs:
            mm_list.subscribe(address, display_name=db_subscribers[address],
                              pre_verified=True, pre_confirmed=True,
                              pre_approved=True)
        mm_list.mass_unsubscribe(delete_subs)

    def mailman_sync_list_mods(self, rs, mailman, db_list, mm_list):
        personas = self.coreproxy.get_personas(
            rs, db_list['moderators'])
        db_moderators = {
            persona['username']: "{} {}".format(persona['given_names'],
                                                persona['family_name'])
            for persona in personas.values() if persona['username']
        }
        mm_moderators = {m.address: m for m in mm_list.moderators}

        new_mods = set(db_moderators) - set(mm_moderators)
        delete_mods = set(mm_moderators) - set(db_moderators)

        for address in new_mods:
            mm_list.add_moderator(address, display_name=db_moderators[address])
        for address in delete_mods:
            mm_list.remove_moderator(address)

    def mailman_sync_list_whites(self, rs, mailman, db_list, mm_list):
        db_whitelist = db_list['whitelist']
        mm_whitelist = {n.address: n for n in mm_list.nonmembers}

        new_whites = set(db_whitelist) - set(mm_whitelist)
        current_whites = set(mm_whitelist) - new_whites
        delete_whites = set(mm_whitelist) - set(db_whitelist)

        for address in new_whites:
            white = mm_list.add_role('nonmember', address)
            white.moderation_action = 'accept'
            white.save()
        for address in current_whites:
            white = mm_whitelist[address]
            if white.moderation_action != 'accept':
                white.moderation_action = 'accept'
                white.save()
        for address in delete_whites:
            mm_list.remove_role('nonmember', address)

    def mailman_sync_list(self, rs, mailman, db_list, mm_list):
        self.mailman_sync_list_meta(rs, mailman, db_list, mm_list)
        self.mailman_sync_list_subs(rs, mailman, db_list, mm_list)
        self.mailman_sync_list_mods(rs, mailman, db_list, mm_list)
        self.mailman_sync_list_whites(rs, mailman, db_list, mm_list)

    @periodic("mailman_sync")
    def mailman_sync(self, rs, store):
        """Synchronize the mailing list software with the database.

        This has an @periodic decorator in the frontend.
        """
        mailman = self.mailman_connect()
        try:
            _ = mailman.system # cause the client to connect
        except Exception as e: # sadly this throws a host of different exceptions
            self.logger.exception("Mailman client connection failed!")
            return store
        db_lists = self.mlproxy.get_mailinglists(
            rs, self.mlproxy.list_mailinglists(rs))
        db_lists = {l['address']: l for l in db_lists.values()}
        mm_lists = {l.fqdn_listname: l for l in mailman.lists}
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
