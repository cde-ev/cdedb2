Attachments
============

An attachment is the idea of a file (the file itself may change between arbitrary versions) which has the following attributes:

- an **id** (id)
- the **assembly id** of the linked assembly (id)
- 0 to n attachment_ballot_links of the linked assembly (attachment_ballot_link)
- 1 to n attachment_versions (attachment_version)

An attachment_ballot_link has the following attributes:

- an **id** (id)
- the **attachment id** of its attachment (id)
- the **ballot id** of the linked ballot (id)

An attachment_version has the following attributes:

- an **id** (id)
- the **attachment id** of its attachment
- a **version number** (integer) starting at 1, incremented by one for each new attachment_version of an attachment
- a **file_hash** of the real file containing the current stand of the attachment idea (file)
- a **filename** (varchar)
- a **title** (varchar)
- the **authors** of the file (varchar)
- a **creation time** (timestamp)
- a **deletion time** (timestamp)

Creation
--------
An attachment may be created at any time during an assembly.

An attachment_ballot_link may be created if the ballot it links to is before its voting phase had started.

An attachment_version may be created at any time during an assembly (independently of any voting stuff).

Deletion
--------
An attachment can only be deleted if it has:

- no attachment_ballot_links or only attachment_ballot_links which may be deleted.
- no attachment_versions.

An attachment_ballot_link can only be deleted if the ballot it links to is before its voting phase.

An attachment_version must not be deleted if its attachment has at least one attachment_ballot_link which voting phase had started.

Changing
--------
Attachments, attachment_ballot_links and attachment_versions can not be changed.

Definitive Version
------------------

Each ballot with an existing attachment_ballot_link has exactly one definitive version of the linked attachment.
This version may may differ between different ballots and may change during the lifetime of an ballot:

Before voting phase started
    The latest attachment_version is the definitive version of the ballot.

After voting phase started
    The last attachment_version which was uploaded before the voting phase started is a the definitive version of the ballot.

The definitive version of an attachment is the relevant one in a legal context for the given ballot.
An attachment may get new versions after any linked ballots had started its voting phase, but they should be rare and contain only formal changes.
It is up to the presiders of an assembly to restrict uploads and corrections of attachment_versions once a ballot started voting.
