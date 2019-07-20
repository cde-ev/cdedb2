Workflows
=========

This page aims to provide descriptions on how to do things.

Internationalization
--------------------

We use GNU gettext in combination with the python babel library for
internationalization.

* Translatable strings have to be marked. In python you can do this in two ways:
	* using ``n_()``. This only marks the string for extraction into internationalization files,
	  but does not translate it.
	* using ``rs.gettext()``. This marks the string, but also replaces it with the translation.

* You can also translate strings in templates, by wrapping them in either of the following. Both of these way replace the marked string with the appropriate translation.
	* the ``rs.gettext()`` function or it' common alias ``_()`` where appropriate.
	* the ``{% trans -%}`` / ``{%- endtrans %}`` environment.

* Marked strings are extracted via the ``make i18n-refresh`` command.

* The extracted strings need to be translated in the ``*.po`` files in the ``i18n``
  directory for each language.

* Ultimately pybabel needs to be compiled(``make i18n-compile``) and the apache restarted. This can both be done via one command: ``make reload``.

Be aware that messages that need to be translated, but do not appear explicitly in the code,
are listed in ``i18n_additional.py``. This applies especially human-readable descriptions of enum members.

Deployment
----------

The stable branch tracks the revision deployed to the server. Use the
following steps to deploy a new revision.

* Locally set the stable branch to the desired revision::

    git checkout stable
    git merge master # or another branch or an explicit commit

* Run the push-stable.sh script. If any new commits with deployment
  relevance are present (marked by a line starting with "Deploy:" in the
  commit message) they will be displayed and there will be the option to
  abort the push. If no such commits are present the push simply
  proceeds. The script accepts the parameter "-d" which enables the dry-run
  mode where no actual push happens.

  ::

     ./bin/push-stable.sh

* Log into the server. If no commits with deployment relevance exist, simply
  execute the cdedb-update.sh script::

    ssh cde-db2 # replace with your alias from your ssh config
    sudo cdedb-update.sh

  If commits with deployment relevance exist, the call to the script needs
  to be replaced by the commands inside the script interspersed with the
  server adjustments.

Mailinglist Management
----------------------

We use a fairly complex state schema to manage mailinglist subscription states
internally. These states are only incompletely displayed to moderators and
admins using the management page, however a raw CSV file can be downloaded
showing the actual internal states.

.. image:: SubscriptionStates.png
   :width: 60 %
   :alt: Subscription state schema
   :align: right

We are using a total of seven distinct states, which allow a consistent and
useful subscription management, even if the mailinglist configuration changes.
These states are modeled in a way that external factors only determine which
state transitions may be done, but never to which state a given transition leads
to. Notably, not the state transitions, but the state obtained by a transition
determines the log codes. The only exemption to this rule is the decision of
subscription requests, which is using specific log codes.

There is a strict separation between transitions done by users and by moderators;
they are using different frontend endpoints which are accessed by different
interfaces. This way, even moderators and admins can request subscriptions to
lists they can manage, while they can only subscribe directly using the
management interface. Analogous, they can only subscribe to invitation only
lists using the management interface.

To maintain the correct states, we use a cron job running every 15 minutes to
take care of automatic state transitions. In contrast to user induced changes,
the changes done by the cron job are not logged.

In the CdEDBv2, we distinct between subscribing and other states, where users
listed in subscribing states receive list emails. For subscribers, there is no
visible distinction between the different subscribing states. Subscribing states
are:

Explicit Subscribed
    Users, which have been actively subscribed to a mailinglist, either by
    themselves or by a moderator, are saved as explicitly subscribed.
    If these users have no more means to access a list, for example because they
    lost membership, or because they no longer attend an event, they are removed
    from the mailinglist.
    Mailinglists without special membership implicators only have explicit
    subscribers.

Subscribe Override
    Subscribe Overrides are a special kind of explicit subscriptions, which are
    kept even if the user should not be able to access a list anymore. However,
    except for mandatory lists, they do not prevent a user from unsubscribing
    themselves.
    The list of Subscribe Overrides can be accessed by moderators via the
    management interface.

Implicit Subscribed
    Users, which are subscribed to a mailinglist, because it is opt-out or
    linked to an event or assembly, are listed as implicit subscribers. If they
    lose the automatic implicator that subscribes them to the list, they are
    removed even if they would still be able to access it.
    Implicit subscribers are stored in the database explicitly. This ensures the
    subscriber list displayed is always identical to the list of users emails
    are actually sent to.

Other states are:

None
    This is the standard state for users having no relationship to a list
    whatsoever, because they never were listed on it or lost access to it.
    This state is the only one not explicitly saved in the database.

Explicit Unsubscribed
    Users, which have specified they do not want to receive emails from a
    specifc mailinglist anymore. This decision is permanent, until manually
    reverted by them or a moderator. Even if they lose access to a list and
    regain it later on, they will not be receiving emails from it.
    However, if they are explicitly subscribed again, they do not receive
    special treatment.

Unsubscribe Override
    Unsubscribe Overrides are a special kind of explicit unsubscriptions, which
    can not be removed by the affected user. Except for mandatory lists, they
    can be used to block a specific user from any kind of subscription or
    subscription request and are displayed to a user when accessing the
    mailinglist information page.
    The list of Subscribe Overrides can be accessed by moderator via the
    management interface.

Waiting for moderation
    This is a special case only existing for mailinglists with moderated opt-in
    subscription policy for a group of users. These users are displayed on a
    specific list to moderators, so they can decide if they want to approve or
    deny their request. It is also possible to block further request by this
    user.

The only case, where a list configuration change explicitly changes subscription
states (Explicit and implicit subscriptions can still be removed if the
configuration change makes them lose their means of access!) is a conversion to
a mandatory list. In this case, all explicit unsubscriptions, including
Unsubscribe Overrides, are deleted.

Email adresses for specific mailinglists are saved separate from the
subscription state to make them persistent over all states.
