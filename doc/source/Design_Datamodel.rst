Data Model Design
=================

In python, entities are modeled as ``dataclasses``, using the same named python package.
This makes coding with an IDE very convenient, since it provides proper knowledge about
methods and attributes of those entities.

The dataclass definitions are considered as ``models`` and are stored in ``cdedb.models``.
The model of an entity is its "single source of truth". In particular, it keeps track
of the following things:

  - The database fields, and the serialization of the dataclass to save it into the database.
  - The request fields, which are accepted by the frontend.
  - The validation fields, and the type they shall conform to.

The only (necessary) duplication should therefore be between the postgres database schema and
the database fields of the model.

Usage
-----

An entity is presented as dataclass iff the validity and completeness of the data are guaranteed.
This is the case after the entity has passed the frontend validation during creation,
or if the data comes from the backend.

Changes to an entity are modeled as incomplete data – only changes with regard to
the current state of the entity are transmitted, not the entity as a whole in the new desired state.
Consequently, changes which shall be applied to an entity are not modeled as dataclass,
but as dict.

At the moment, most entities are always modeled as dict. A long term goal is to rewrite
the respective code to follow the paradigms described above.
