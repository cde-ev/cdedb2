#!/usr/bin/env python3

"""Mailman shell script.

As Mailman in version 3.2 does not expose all functionality over the
REST-API, we have to fiddle some bits on the command line.

This file has to be placed in /usr/local/lib/python3.7/dist-packages to be
found by the mailman shell.

It can be invoked as user 'list' via the following incantation:

mailman withlist -r custom_mailman_manipulate.default_settings -l <listaddress>

where `listaddress` is the posting address of the list
(e.g. cdedb@lists.cde-ev.de).

"""


from mailman.interfaces.mailinglist import SubscriptionPolicy
from mailman.interfaces.mime import FilterAction


def default_settings(mlist):
    """Provide sane default settings not accessible via REST-API."""
    if mlist.send_goodbye_message != False:
        mlist.send_goodbye_message = False
    if mlist.unsubscription_policy != SubscriptionPolicy.moderate:
        mlist.unsubscription_policy = SubscriptionPolicy.moderate
    if mlist.filter_content != True:
        mlist.filter_content = True
    if mlist.filter_action != FilterAction.forward:
        mlist.filter_action = FilterAction.forward
    if mlist.pass_types != ['multipart', 'text/plain', 'application/pdf']:
        mlist.pass_types = ['multipart', 'text/plain', 'application/pdf']
    if mlist.pass_extensions != ['pdf']:
        mlist.pass_extensions = ['pdf']
    if mlist.digests_enabled != False:
        mlist.digests_enabled = False


def lax_settings(mlist):
    """Provide lax settings not accessible via REST-API."""
    if mlist.pass_types != []:
        mlist.pass_types = []
    if mlist.pass_extensions != []:
        mlist.pass_extensions = []
