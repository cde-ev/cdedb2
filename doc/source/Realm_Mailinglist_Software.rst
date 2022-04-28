Mailinglist software
====================

The actual mail processing is done by Mailman on another VM. The state is
synchronised between CdEDB and Mailman via a push approach implemented by a
periodic :ref:`cron job <cron-jobs>`. The consequence of this is that it can take up to a
quarter hour for changes to be effective.
