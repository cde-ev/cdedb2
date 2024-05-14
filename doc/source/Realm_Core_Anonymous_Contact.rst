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

Anonymity will not be violated in practice, in order to respond to a message, however
the act of holding an abuser accountable purposely violates the anonymity of the sender.

Accountability
^^^^^^^^^^^^^^

In order to hold an abuser accountable it is not sufficient to decrypt the store
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
identity is decrypted but not acutally revealed to the responding user.

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
- The ``secret`` refers to the string of 60 urlsage Base64 characters that is the
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

Threats
-------

- **Server Access**:
    Due the symmetric encryption, there is no direct way for anyone to discover the
    identity without bypassing the encryption, even with full server access, because
    the key is never stored anywhere and the identity is not directly logged either.
    Server (or database) access would allow an attacker to attack the encryption
    offline, circumventing any serverside logging and rate limiting.
    Note that apache access logs contain additional information which might allow
    someone with server access to discover the identity of an anonymous sender.
- **Guessing the Secret**:
    The frontend for responding to messages only requires the user to be logged in
    and to provide a valid secret. This makes it theoretically possible to guess a key,
    which is why usage of invalid secrets is logged.
    In practice the secret consists of 44 Bytes of Entropy and should be unfeasible to
    guess.
- **The Secret Leaking**:
    A leaked secret, e.g. by someone accidently forwarding the mail in which the
    secret was sent, allows anyone (with an account) to reply to the corresponding
    message, but not to discover the identity of the sender, unless they also have
    server/database access.
    In order to mitigate this, anyone with the secret may also trigger a rotation of
    the encryption key, sending a new secret to the recipients of the original message.
- **Intercepting Outgoing Mails**:
    Since most configured recipients for the contact form are actually mailinglists
    no special care is taken to protect the actual mails. Thus if one of these mails is
    intercepted along the way, both the content of the message, as well as the identity
    of the anonymous sender could be compromised.
    This implementation makes no effort to protect against this kind of threat.
