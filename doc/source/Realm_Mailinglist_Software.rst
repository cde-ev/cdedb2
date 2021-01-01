Mailinglist software
====================

The actual mail processing is done by Mailman on another VM. The state is
synchronised between CdEDB and Mailman via a push approach implemented by a
periodic cron job. The consequence of this is that it can take up to a
quarter hour for changes to be effective.

Legacy
------

Additionally currently some lists are handled by ezml and rklist.
