Registration Query
==================

.. highlight:: sql

To dynamically query information about registrations, we have to construct a rather involved view on the fly. This is necessary because the information is spread across multiple different tables and we also want to gather secondary information about a participants courses and lodgements.

We construct this view from six main components:

* The general ``event.registrations`` columns. This contains some general information, like how much of the fee was already paid.
* The ``core.personas`` data. Here we get the personal information of the participant, like name, email and birthday.
* The custom registration datafields. These are individually configured per event and are added to the fixed information above.
* A series of part tables, containing information about the registrations status regarding a given part. This includes lodgement information for any assigned lodgement in a part.
* A series of track tables, containing information about the courses a registration is associated with. This includes both the course they are assigned and any course they are isntructing.
* The timestamps of registration creation and last modification from ``event.log``.

The final view will be constructed as follows. ::

  event.registrations as reg
  LEFT OUTER JOIN (
      SELECT
          registration_field_columns, id
      FROM
          event.registrations
      WHERE
          event_id = X
  ) AS reg_fields ON reg.id = reg_fields.id
  LEFT OUTER JOIN (
      part_tableX
  ) AS partX ON reg.id = partX.registration_id
  LEFT OUTER JOIN (
      lodgement_tableX
  ) AS lodgementX ON partX.lodgement_id = lodgementX.id
  LEFT OUTER JOIN (
      track_tableX
  ) AS trackX ON reg.id = trackX.registration_id
  LEFT OUTER JOIN (
      course_tableX
  ) AS courseX ON trackX.course_id = courseX.id
  LEFT OUTER JOIN (
      course_tableX
  ) AS course_instructorX ON trackX.course_id = course_instructorX.id

``reg_fields_colum`` will contain a JSON-cast from the ``fields`` column for every relevant course field.
``part_tableX`` and ``lodgement_tableX`` will be present for every part X of the event.
``track_tableX``, ``courseX``, ``course_instructorX`` will be present for every part X of the event.

The following fields are avalable in the dynamic tables:

* ``reg_fields.xfield_{field_name}`` *For every custom registration datafield.*
* ``part{part_id}.status``
* ``part{part_id}.lodgement_id``
* ``part{part_id}.is_camping_mat``
* ``lodgement{part_id}.xfield_{field_name}`` *For every part and every custom lodgement datafield.*
* ``lodgement{part_id}.title``
* ``lodgement{part_id}.notes``
* ``track{track_id}.course_id``
* ``track{track_id}.course_instructor``
* ``track{track_id}.course_is_course_instructor``
* ``course{track_id}.xfield_{field_name}`` *For every track and every custom course datafield.*
* ``course{track_id}.nr``
* ``course{track_id}.title``
* ``course{track_id}.shortname``
* ``course{track_id}.notes``
* ``course{track_id}.instructors``
* ``course_instructor{track_id}.xfield_{field_name}`` *For every track and every custom course datafield.*
* ``course_instructor{track_id}.nr``
* ``course_instructor{track_id}.title``
* ``course_instructor{track_id}.shortname``
* ``course_instructor{track_id}.notes``
* ``course_instructor{track_id}.instructors``
* ``ctime.creation_time``
* ``mtime.modification_time``

The Part Tables
---------------

For every part we have two tables.

The first table contains information from ``event.registration_parts``, including the registration's status in that part: ::

  SELECT
      registration_id, status, lodgement_id, is_camping_mat
  FROM
      event.registration_parts
  WHERE
      part_id = X

The second table provides a view of the assigned lodgement, should one exist. All these columns will be ``NULL`` if no lodgement is assigned in this part: ::

  SELECT
      lodge_field_columns,
      title, notes, id
  FROM
      event.lodgements
  WHERE
      event_id = X

These tables are joined ``ON partX.lodgement_id = lodgementX.id``.

The Track Tables
----------------

For every track we have three tables.

The first tables contains information from ``event.registration_tracks``, mainly about the assigned and any instructed course::

  SELECT
      registration_id, course_id, course_instructor,
      (NOT(course_id IS NULL AND course_instructor IS NOT NULL)
       AND course_id = course_instructor) AS is_course_instructor
  FROM
      event.registration_tracks
  WHERE
      track_id = X

After that we have two views on the ``event.courses`` table for both the assigned and instrcuted course. All columns will be None, if no course is assigned/instructed::

  SELECT
      course_field_columns,
      id, nr, title, shortname, notes, instructors
  FROM
      event.courses
  WHERE
      event_id = X

The Complete View
-----------------

The final view for regisration queries looks something like this: ::

  event.registrations AS reg
  LEFT OUTER JOIN
      core.personas
  AS persona ON reg.persona_id = persona.id
  LEFT OUTER JOIN (
      SELECT
          (fields->>'brings_balls')::boolean AS "xfield_brings_balls",
          (fields->>'transportation')::varchar AS "xfield_transportation",
          (fields->>'lodge')::varchar AS "xfield_lodge",
          (fields->>'may_reserve')::boolean AS "xfield_may_reserve",
          id
      FROM
          event.registrations
      WHERE
          event_id = 1
  ) AS reg_fields ON reg.id = reg_fields.id
  LEFT OUTER JOIN (
      SELECT
          registration_id, status, lodgement_id, is_camping_mat
      FROM
          event.registration_parts
      WHERE
          part_id = 1
  ) AS part1 ON reg.id = part1.registration_id
  LEFT OUTER JOIN (
      SELECT
          (fields->>'contamination')::varchar AS "xfield_contamination", title, notes, id
      FROM
          event.lodgements
      WHERE
          event_id = 1
  ) AS lodgement1 ON part1.lodgement_id = lodgement1.id
  LEFT OUTER JOIN (
      SELECT
          registration_id, status, lodgement_id, is_camping_mat
      FROM
          event.registration_parts
      WHERE
          part_id = 2
  ) AS part2 ON reg.id = part2.registration_id
  LEFT OUTER JOIN (
      SELECT
          (fields->>'contamination')::varchar AS "xfield_contamination",
          title, notes, id
      FROM
          event.lodgements
      WHERE
          event_id = 1
  ) AS lodgement2 ON part2.lodgement_id = lodgement2.id
  LEFT OUTER JOIN (
      SELECT
          registration_id, status, lodgement_id, is_camping_mat
      FROM
          event.registration_parts
      WHERE
          part_id = 3
  ) AS part3 ON reg.id = part3.registration_id
  LEFT OUTER JOIN (
      SELECT
          (fields->>'contamination')::varchar AS "xfield_contamination",
          title, notes, id
      FROM
          event.lodgements
      WHERE
          event_id = 1
  ) AS lodgement3 ON part3.lodgement_id = lodgement3.id
  LEFT OUTER JOIN (
      SELECT
          registration_id, course_id, course_instructor,
          (NOT(course_id IS NULL AND course_instructor IS NOT NULL)
           AND course_id = course_instructor) AS is_course_instructor
      FROM
          event.registration_tracks
      WHERE
          track_id = 1
  ) AS track1 ON reg.id = track1.registration_id
  LEFT OUTER JOIN (
      SELECT
          (fields->>'room')::varchar AS "xfield_room",
          id, nr, title, shortname, notes, instructors
      FROM
          event.courses
      WHERE
          event_id = 1
  ) AS course1 ON track1.course_id = course1.id
  LEFT OUTER JOIN (
      SELECT
          (fields->>'room')::varchar AS "xfield_room",
          id, nr, title, shortname, notes, instructors
      FROM
          event.courses
      WHERE
          event_id = 1
  ) AS course_instructor1 ON track1.course_instructor = course_instructor1.id
  LEFT OUTER JOIN (
      SELECT
          registration_id, course_id, course_instructor,
          (NOT(course_id IS NULL AND course_instructor IS NOT NULL)
           AND course_id = course_instructor) AS is_course_instructor
      FROM
          event.registration_tracks
      WHERE
          track_id = 2
  ) AS track2 ON reg.id = track2.registration_id
  LEFT OUTER JOIN (
      SELECT
          (fields->>'room')::varchar AS "xfield_room",
          id, nr, title, shortname, notes, instructors
      FROM
          event.courses
      WHERE
          event_id = 1
  ) AS course2 ON track2.course_id = course2.id
  LEFT OUTER JOIN (
      SELECT
          (fields->>'room')::varchar AS "xfield_room",
          id, nr, title, shortname, notes, instructors
      FROM
          event.courses
      WHERE
          event_id = 1
  ) AS course_instructor2 ON track2.course_instructor = course_instructor2.id
  LEFT OUTER JOIN (
      SELECT
          registration_id, course_id, course_instructor,
          (NOT(course_id IS NULL AND course_instructor IS NOT NULL)
           AND course_id = course_instructor) AS is_course_instructor
      FROM
          event.registration_tracks
      WHERE
          track_id = 3
  ) AS track3 ON reg.id = track3.registration_id
  LEFT OUTER JOIN (
      SELECT
          (fields->>'room')::varchar AS "xfield_room",
          id, nr, title, shortname, notes, instructors
      FROM
          event.courses
      WHERE
          event_id = 1
  ) AS course3 ON track3.course_id = course3.id
  LEFT OUTER JOIN (
      SELECT
          (fields->>'room')::varchar AS "xfield_room",
          id, nr, title, shortname, notes, instructors
      FROM
          event.courses
      WHERE
          event_id = 1
  ) AS course_instructor3 ON track3.course_instructor = course_instructor3.id
  LEFT OUTER JOIN (
      SELECT
          persona_id, MAX(ctime) AS creation_time
      FROM
          event.log
      WHERE
          event_id = 1 AND code = 50
      GROUP BY
          persona_id
  ) AS ctime ON reg.persona_id = ctime.persona_id
  LEFT OUTER JOIN (
      SELECT
          persona_id, MAX(ctime) AS modification_time
      FROM
          event.log
      WHERE
          event_id = 1 AND code = 51
      GROUP BY
          persona_id
  ) AS mtime ON reg.persona_id = mtime.persona_id

