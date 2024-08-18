Anonymous Contact
=================

The core realm provides a functionality to send anonymous messages to a
configurable selection of people and/or mailinglists.

The same functionality can be used to send non-anonymous messages, but
they are little more than a small wrapper around a regular email sent directly.
These are not stored or logged in any way, and won't be further discussed here.

Relevant Interests
------------------

- **Anonymity**:
    We want people to be able to provide feedback anonymously.
- **Accountabilty**:
    At the same time we want to be able to hold people accountable in case they abuse
    the system.
- **Responding to Messages**:
    In order to properly address feedback directed to our teams, they need to be able
    to respond to the feedback, even if it is sent anonymously.

Anonymity
^^^^^^^^^

Having true anonymity would be technically possible, but would immediately violate
the other interests. Therefore we store the identity of the anonymous sender in an
encrypted form, allowing the recipients of the anonymous message to retrieve this data
in order to realise the other two interests.

In order to respond to a message, the anonymity of the sender is not be violated
(in practice). In contrast the act of holding an abuser accountable purposely violates
this anonymity.

Accountability
^^^^^^^^^^^^^^

In order to hold an abuser accountable it is not sufficient to decrypt the stored
identity for internal use, rather it needs to also be *revealed* to someone.

Since this is only required in actual cases of abuse, there is no implementation to do
this via the frontend. The envisioned workflow requires two separate pieces:

- The secret only known to the recipients of the anonymous message.
- Server access to use that secret to decrypt and reveal the stored identity.

Responding to Messages
^^^^^^^^^^^^^^^^^^^^^^

In order to respond to an anonymous message, the recipient needs to provide the secret
(which is only known to them and not saved anywhere), allowing for the internal
retrieval of the stored identity in order to send the reply. During this process the
identity is decrypted but not actually revealed to the responding user.

Responding requires being logged in, but other than providing the secret no other
authorisation checks are made.

Encryption
----------

Definition of Terms
^^^^^^^^^^^^^^^^^^^

- The ``message id`` is used to identify a specifc anonymous message. This consists of
  12 random Bytes encoded as 16 urlsafe Base64 characters.
- The ``encryption key`` is used to encrypt/decrypt the stored information. It consists
  of 32 random Bytes encoded as 44 urlsafe Base64 characters (including padding).
  Internally half of the key is actually used for message signing, rather than
  encryption, meaning that the encryption uses 16 Bytes or 128 Bit.
- The ``secret`` refers to the string of 60 urlsafe Base64 characters that is the
  concatenation of the ``message id`` and the ``encryption key``. The secret is sent
  to the recipients of an anonymous message and is required to respond to a message
  or to rotate it's encryption. It can be split into its parts by taking the first
  16 and last 44 characters respectively.

Stored Data
^^^^^^^^^^^

The following information is stored in a symmetrically encrypted form:

- The persona id of the sender
- The username of the sender
- The subject of the message

The persona id and username are used to send the reply, while the subject is used to
give context on which message is being responded too.

The message content is not stored, so even with the secret it cannot be retrieved
afterwards. Note however, that the subject might also containt sensitive information.

Rotation of Encryption Key
^^^^^^^^^^^^^^^^^^^^^^^^^^

In case the secret is leaked, it is possible to rotate the encryption key. The user
needs to provide the current secret, which is used to decrypt the data, which is then
reencrypted with a newly generated key. The new secret is sent to the original
recipient(s). In addition a new message id is generated, so the entire secret will be
new.

Potential Actors and Threats
----------------------------

- **Uninvolved**:

  An uninvolved actor is not party to any exchange of anonymous messages. Their only
  capability is the usage of the CdEDB frontend.

  There exists no frontend overview of existing or previous anonymous messages,
  regardless of the privileges of the uninvolved user.

  However core admins may view the Core Log, where every sent anonymous message and
  every reply is logged. However the only information in this log is the time at which
  an anonymous message was sent and the recipient.
  For replies the user sending the reply is logged along with the time of the reply and
  the original recipient.

  Threats:
    - Unprivileged user:

      - None
    - Core Admin:

      - Knowledge of the time when anonymous messages are sent may provide advantages
        for other side channel attacks. This is deemed acceptable, since Core Admins
        are trusted users and we want there to be a way to have an overview of the
        usage of the contact facility via the frontend.

- **Sender of an anonmyous message**:

  Any user, regardless of their privileges may use the form to send anonymous messages.
  The sender does not receive the secret associated with their message.

  Threats:
    - Misuse of the anonymous contact form (spam, trolling, verbal abuse, etc.)

      - Mitigated by the principle of accountability.
      - The user sending the message has no access to the corresponding secret.

- **Unprivileged Responder**:

  Any user, regardless of their privileges may use the form to reply to anonymous
  messages, provided they know (or are able to guess) the corresponding secret of
  a message.
  An unprivileged responder is a user who is trying to use the form to reply to a
  message they are not meant to.

  Threats:
    - Use of leaked secret.

      - If an unprivileged user gains access to a valid secret, they may reply
        to the corresponding message just in the same way as a privileged user would.
        This could reduce the trust of the user into the process and the contacted
        institution.
      - Knowledge of the secret does not give the user access to any sensitive
        information via the frontend (like the identity of the sender, subject of the
        message or content of the message).
      - This is mitigated by logging all replies (including persona id of the user
        replying), and sending a copy of each reply to the actual recipients, so that
        such unprivileged responses do not go unnoticed.
      - The reply will also contain the name and username of the responder,
        meaning the original sender should be able to see if they received an invalid
        reply, especially since the intended recipients are able to inform them about
        this incident.
      - Further mitigated by the option to rotate the encryption with knowledge of the
        secret. The secret will then again only be known to the intended recipients.
        (Although the makeup of the recipients could have changed in the meantime,
        see below).
    - Guessing a secret.

      - Unsurprisingly, successfully guessing a secret has the same consequences as
        knowledge of a leaked secret does. The threat is also mitigated by the same
        mechanisms.
      - Additionally guessing the secret is mitigated by (internal) logging of such
        attempts (providing an invalid secret via the form).
      - Furthermore the search space for guessing a valid secret is extremely large
        (44 Bytes or ~350 Bits).

- **Recipient of an anonymous message**:

  The recipient of an anonymous message has knowledge of the associated secret and
  thus the capability to reply to that message, as well as rotate the encryption for
  this message.
  Additionally they have knowledge of the actual content of the anonymous message.

  Knowledge of the secret and the message content comes with the implicit capability
  to (unintentionally or intentionally) leak either.

  Threats:
    - Leaking of the message content:

      - There is not much that can be done, should a recipient of an anonmyous message
        (whether intentionally or not) leak the content of such a message.
    - Leaking of the secret:

      - The consequences of and mitigations for after leaking the secret to others are
        discussed above.

- **Uninvolved Server-Admin**:

  An admin with advanced access to the CdEDB-Server has the capability to retrieve the
  encrypted data and the unencrypted metadata for all anonymous messages.

  They do not have the capability to decrypt the identity of the sender, or the
  subject of the message, without circumventing the encryption.

  Threats:
    - Offline attack on encryption:

      - By extracting the encrypted data from the database, a server admins has the
        capability to attack the encryption offline, thus bypassing all logging and
        other mitigations like rate limiting.
      - Not much can be done to prevent this, however the strength of the symmetric
        encryption should be enough to still make this unfeasible.
    - Sidechannel (Length of Encrypted Data):

      - The length of the encrypted data increases with the length of the username of
        the sender and the subject of the message. This allows the Server-Admin to gain
        some information and differentiate different messages even across encryption
        rotations.
    - Sidechannel (Reconfiguration of Contact Recipients):

      - A server admin can alter the configuration, so that messages are sent to
        arbitrary email addresses rather than the intended recipients.

Sidechannel Attacks
^^^^^^^^^^^^^^^^^^^

- **ML-Admin with knowledge of secret**:

  For recipients which are mailinglists a mailinglist admin (or another admin with
  privileges for the mailinglist) has the capability to remove all regular subscribers
  of the mailinglist, add themself as a subscriber and then (with knowledge of the
  secret) rotate the encryption for a message.

  This causes the new secret to only be sent to the malicious admin, rendering the
  intended recipients unable to reply to (or even to rotate the encryption of) the
  affected message.

  The rotated message can be identified from the internal log. This allows a server
  admin to delete the compromised message. Changes to mailinglist subscribers via the
  frontend are logged.

- **Interception of email**:

  Since most recipients are mailinglists (and even if they weren't), we cannot send the
  actual mails in an encrypted form. Interception of emails may leak both a secret and
  the actual message contents to the intercepting party.

  Similar access to the full messages is possible via administrative access to CdE mail
  infrastructure, i.e. the `mail2`-vm and the `mailman`/`postorius` services which keep
  records of all mails sent (to a cde mailinglist).
