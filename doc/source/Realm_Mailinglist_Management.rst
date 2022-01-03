Mailinglist Management
======================

To manage subscriptions, we use *Subman*, a fairly complex library to
manage subscriptions of our own creation. While it can in principle be
used for general subscriptions, we are only using it for mailinglists
internally.

Subman
------
Further information regarding the library used can be found at `Subman`_.

Use of subman
-------------
In our use of subman, we choose to store implicit subscribers to the database
explicitly. This ensures the subscriber list displayed is always identical to
the list of users emails are actually sent to. In contrast, the Implicitly
Unsubscribed state is not saved explicitly.

To maintain the correct states, we use a cron job running every 15 minutes to
take care of automatic state transitions on all active mailinglists.

To simplify our logging, some subscription actions are summarized to a single log code,
as can be seen in ``MlLogCodes.from_subman``. In contrast to user induced changes,
we only log unsubscriptions done by the cronjob, while new subscriptions are
not logged. This is done to simplify reversing unwanted unsubscriptions manually.

We maintain the strict separation between transitions done by users and by moderators
as proposed by subman; they are using different frontend endpoints which are
accessed by different interfaces. This way, even moderators and admins can request
subscriptions to lists they can manage, while they can only subscribe directly using the
management interface. Analogous, they can only subscribe to invitation only
lists using the management interface.

This mailinglist management interface gives moderators a comprehensive, yet incomplete
overview over all relevant state information. Nevertheless, a raw CSV file can be downloaded
showing the actual internal states.

This interface also displays the email addresses for specific mailinglists.
Those are saved separately from the subscription state to make them persistent
over state handling.
