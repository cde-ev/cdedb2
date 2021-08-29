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
An attachment can only be deleted if it has no attachment_ballot_link and no attachment_version.

An attachment_ballot_link can only be deleted if the ballot it links to is before its voting phase.

An attachment_version must not be deleted if its attachment has at least one attachment_ballot_link which voting phase had started.

Changing
--------
An attachment can not be changed.

An attachment_ballot_link can not be changed.

An attachment_version can be changed if and only if it may also be deleted.
Only the filename, authors and title attributes of an attachment_version can be changed.

Versions of interest
--------------------

Each attachment_ballot_link of an attachment has 1:n versions_of_interest (voi) of this attachment (which may differ between different ballots):

Before voting phase started
    The latest attachment_version is the only voi of the ballot.

After voting phase started
    The last attachment_version which was uploaded before the voting phase started is a voi of the ballot.
    Each attachment_version which was uploaded after the voting phase started and before it ended is a voi of the ballot.

In a legal context we consider the voi with the highest version number as relevant.
It is up to the presiders of an assembly to restrict uploads and corrections of attachment_versions once a ballot started voting.
