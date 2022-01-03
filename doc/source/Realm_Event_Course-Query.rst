Course Query
============

.. highlight:: sql

To dynamically query information about courses, we have to construct a rather involved view on the fly. This is necessary because the information is spread across multiple different tables and there are dynamically many course tracks in which a course may be involved depending on the event.

We construct this view from three main components:

* The general ``event.courses`` table. Here lies general course information like title, description and orga notes.
* The custom course related datafields. These are extracted from the JSON-column ``fields`` which is part of the ``event.courses`` table, ut we have to do on the fly to determine the appropriate fields for that event.
* A series of track tables, containing information for the course in relation to all course tracks of the event. This component will be discussed in further detail below.

The final view will be constructed as follows. ::

  event.courses as course
  LEFT OUTER JOIN (
      SELECT
          course_field_columns, id
      FROM
          event.courses
      WHERE
          event_id = X
  ) AS course_fields ON courses.id = course_fields.id
  LEFT OUTER JOIN (
      track_tableX
  ) AS trackX ON courses.id = trackX.base_id

``course_field_columns`` will contain a JSON-cast from the ``fields`` column for every relevant course field. ``track_tableX`` is an example for one of the dynamic tables that are all joined as described.

The following columns will be available in this view:

* ``course.id``
* ``course.course_id`` *This is magically replaced by "{nr}. {shortname}" linking to the course.*
* ``course.event_id``
* ``course.nr``
* ``course.title``
* ``course.description``
* ``course.shortname``
* ``course.instructors``
* ``course.min_size``
* ``course.max_size``
* ``course.notes``
* ``course_fields.xfield_{field_name}`` *This is available for every custom data field with course association.*
* ``track{track_id}.is_offered``
* ``track{track_id}.takes_place``
* ``track{track_id}.attendees``
* ``track{track_id}.intructors``
* ``track{track_id}.num_choices{rank}`` *This is available for every available rank in that track.*

*Note that some additional columns are present but omitted here, since they are not really useful like ``track{track_id}.base_id``.*


The Track Tables
----------------

For every course track we gather three kinds of information:

* Course segment data. This comes from the ``event.course_segments`` table and contains information whether the course is offered in the specific track and whether it actually takes place.
* Attendee/Instructor counts. This comes from the ``event.registration_tracks`` table and contains information about the number of attendees and instructors of a course in the specific track.
* Course choices data. This comes from the ``event.course_choices`` table and contains a count of how many (active) registrations have chosen a course in the specific track and at a specific track.

The track table starts out with a base table created by simply selecting all the appropriate course ids, that is all ids of courses belonging to the event. The course id is selected as ``base_id`` so we can later use it to join the track tables to the other components. This is necessary because there will be multiple columns called ``id`` in a single track table and POSTGRES wouldn't know which to use in the ``JOIN`` otherwise.

All the components of a track table start out with the same base table. ::

  (SELECT id FROM event.courses WHERE event_id = X) AS c

This ensures that we get some kind of data in that component for all courses even if a course would not be present in that component otherwise. For example if a course is not present in the course choices part, we want the count of choices be 0 instead of NULL.


The Course Segment Table
^^^^^^^^^^^^^^^^^^^^^^^^

This part conatins two layers. In the inner layer we start with the usual base table and join that with the ``event.course_segments`` table, selecting the ``is_active`` column from there.

Afterwards we select the actual information we need from that joined table, while coalescing the ``is_active`` column so we get a bool instead of ``NULL`` ::

  SELECT
      c.id, COALESCE(is_active, False) AS takes_place,
      is_active IS NOT NULL AS is_offered
  FROM
      (SELECT id FROM event.courses WHERE event_id = X) AS c
      LEFT OUTER JOIN (
           SELECT
               is_active, course_id
           FROM
                event.course_segments
           WHERE track_id = X
      ) AS segment ON c.id = segment.course_id

The Attendees Table
^^^^^^^^^^^^^^^^^^^

This part contains two layers. In the inner layer, we start with the usual base table and join that with the ``event.registration_tracks`` table by joining on `c.id = rt.course_id`.

In the outer layer we count the registration ids while grouping by course id. Doing it this way results in a count of ``0`` instead of ``NULL`` for courses without attendees. ::

  SELECT
      c.id, COUNT(registration_id) AS attendees
  FROM
      (SELECT id FROM event.courses WHERE event_id = X) AS c
      LEFT OUTER JOIN (
          SELECT
              registration_id, course_id
          FROM
              event.registration_tracks
          WHERE track_id = X
      ) AS rt ON c.id = rt.course_id
  GROUP BY
      c.id


The Instructors Table
^^^^^^^^^^^^^^^^^^^^^

This works just like the ``attendees`` part of the track table, but we join on `c.id = rt.course_instructor` instead. ::

  SELECT
      c.id, COUNT(registration_id) AS instructors
  FROM
      (SELECT id FROM event.courses WHERE event_id = X) AS c
      LEFT OUTER JOIN (
          SELECT
              registration_id, course_instructor
          FROM
              event.registration_tracks
          WHERE track_id = X
      ) AS rt ON c.id = rt.course_instructor
  GROUP BY
      c.id

The Course Choices Table
^^^^^^^^^^^^^^^^^^^^^^^^

We have one of these tables for every possible rank in the specific track. So if a track allows up to 5 choices we have 5 of these tables.

This table contains three layers.

In the innermost layer we join ``event.course_choices`` filtered by track and rank with ``event.registration_parts`` (filtered by the part id corresponding with the specific track) via the registration id, so that we can get the registration status corresponsing to a course choice.

The middle layer starts with the usual base table, which we join with the innermost layer filtered by active registration stati.

In the outer layer we then count the registration ids while grouping by course id. See ``attendees`` table for more information why we do that in this way. ::

  SELECT
      c.id, COUNT(status.registration_id) AS num_choicesX
  FROM
      (SELECT id FROM event.courses WHERE event_id = X) AS c
      LEFT OUTER JOIN (
          SELECT
              choices.registration_id, choices.course_id
          FROM
              (
                  SELECT registration_id, course_id
                  FROM event.course_choices
                  WHERE rank = X AND track_id = X
              ) AS choices
              LEFT OUTER JOIN (
                  SELECT
                      registration_id AS reg_id, status
                  FROM
                      event.registration_parts
                  WHERE
                      part_id = X
              ) AS reg_part
              ON choices.registration_id = reg_part.reg_id
          WHERE
              status = ANY(X)
      ) AS status ON c.id = status.course_id
  GROUP BY
      c.id


The Complete View
-----------------

The final view for course queries looks something like this::

    event.courses AS course
    LEFT OUTER JOIN (
        SELECT
            (fields->>'room')::varchar AS "xfield_room", id
        FROM
            event.courses
        WHERE
            event_id = 1
    ) AS course_fields ON course.id = course_fields.id
    LEFT OUTER JOIN (
        (
            SELECT id AS base_id
            FROM event.courses
            WHERE event_id = 1
        ) AS base
        LEFT OUTER JOIN (
            SELECT
                c.id, COALESCE(is_active, False) AS is_active
            FROM
                (SELECT id FROM event.courses WHERE event_id = 1) AS c
                LEFT OUTER JOIN (
                    SELECT
                        is_active, course_id
                    FROM
                        event.course_segments
                    WHERE track_id = 1
                ) AS segment ON c.id = segment.course_id
        ) AS segment1 ON base_id = segment1.id
        LEFT OUTER JOIN (
            SELECT
                c.id, COUNT(registration_id) AS attendees
            FROM
                (SELECT id FROM event.courses WHERE event_id = 1) AS c
                LEFT OUTER JOIN (
                    SELECT
                        registration_id, course_id
                    FROM
                        event.registration_tracks
                    WHERE track_id = 1
                ) AS rt ON c.id = rt.course_id
            GROUP BY
                c.id
        ) AS attendees1 ON base_id = attendees1.id
        LEFT OUTER JOIN (
            SELECT
                c.id, COUNT(status.registration_id) AS num_choices0
            FROM
                (SELECT id FROM event.courses WHERE event_id = 1) AS c
                LEFT OUTER JOIN (
                    SELECT
                        choices.registration_id, choices.course_id
                    FROM
                        (
                            SELECT registration_id, course_id
                            FROM event.course_choices
                            WHERE rank = 0 AND track_id = 1
                        ) AS choices
                        LEFT OUTER JOIN (
                            SELECT
                                registration_id AS reg_id, status
                            FROM
                                event.registration_parts
                            WHERE
                                part_id = 2
                        ) AS reg_part
                        ON choices.registration_id = reg_part.reg_id
                    WHERE
                        status = ANY(ARRAY[1,2,3,4])
                ) AS status ON c.id = status.course_id
            GROUP BY
                c.id
        ) AS choices1_0 ON base_id = choices1_0.id LEFT OUTER JOIN (
            SELECT
                c.id, COUNT(status.registration_id) AS num_choices1
            FROM
                (SELECT id FROM event.courses WHERE event_id = 1) AS c
                LEFT OUTER JOIN (
                    SELECT
                        choices.registration_id, choices.course_id
                    FROM
                        (
                            SELECT registration_id, course_id
                            FROM event.course_choices
                            WHERE rank = 1 AND track_id = 1
                        ) AS choices
                        LEFT OUTER JOIN (
                            SELECT
                                registration_id AS reg_id, status
                            FROM
                                event.registration_parts
                            WHERE
                                part_id = 2
                        ) AS reg_part
                        ON choices.registration_id = reg_part.reg_id
                    WHERE
                        status = ANY(ARRAY[1,2,3,4])
                ) AS status ON c.id = status.course_id
            GROUP BY
                c.id
        ) AS choices1_1 ON base_id = choices1_1.id LEFT OUTER JOIN (
            SELECT
                c.id, COUNT(status.registration_id) AS num_choices2
            FROM
                (SELECT id FROM event.courses WHERE event_id = 1) AS c
                LEFT OUTER JOIN (
                    SELECT
                        choices.registration_id, choices.course_id
                    FROM
                        (
                            SELECT registration_id, course_id
                            FROM event.course_choices
                            WHERE rank = 2 AND track_id = 1
                        ) AS choices
                        LEFT OUTER JOIN (
                            SELECT
                                registration_id AS reg_id, status
                            FROM
                                event.registration_parts
                            WHERE
                                part_id = 2
                        ) AS reg_part
                        ON choices.registration_id = reg_part.reg_id
                    WHERE
                        status = ANY(ARRAY[1,2,3,4])
                ) AS status ON c.id = status.course_id
            GROUP BY
                c.id
        ) AS choices1_2 ON base_id = choices1_2.id LEFT OUTER JOIN (
            SELECT
                c.id, COUNT(status.registration_id) AS num_choices3
            FROM
                (SELECT id FROM event.courses WHERE event_id = 1) AS c
                LEFT OUTER JOIN (
                    SELECT
                        choices.registration_id, choices.course_id
                    FROM
                        (
                            SELECT registration_id, course_id
                            FROM event.course_choices
                            WHERE rank = 3 AND track_id = 1
                        ) AS choices
                        LEFT OUTER JOIN (
                            SELECT
                                registration_id AS reg_id, status
                            FROM
                                event.registration_parts
                            WHERE
                                part_id = 2
                        ) AS reg_part
                        ON choices.registration_id = reg_part.reg_id
                    WHERE
                        status = ANY(ARRAY[1,2,3,4])
                ) AS status ON c.id = status.course_id
            GROUP BY
                c.id
        ) AS choices1_3 ON base_id = choices1_3.id
    ) AS track1 ON course.id = track1.base_id
    LEFT OUTER JOIN (
        (
            SELECT id AS base_id
            FROM event.courses
            WHERE event_id = 1
        ) AS base
        LEFT OUTER JOIN (
            SELECT
                c.id, COALESCE(is_active, False) AS is_active
            FROM
                (SELECT id FROM event.courses WHERE event_id = 1) AS c
                LEFT OUTER JOIN (
                    SELECT
                        is_active, course_id
                    FROM
                        event.course_segments
                    WHERE track_id = 2
                ) AS segment ON c.id = segment.course_id
        ) AS segment2 ON base_id = segment2.id
        LEFT OUTER JOIN (
            SELECT
                c.id, COUNT(registration_id) AS attendees
            FROM
                (SELECT id FROM event.courses WHERE event_id = 1) AS c
                LEFT OUTER JOIN (
                    SELECT
                        registration_id, course_id
                    FROM
                        event.registration_tracks
                    WHERE track_id = 2
                ) AS rt ON c.id = rt.course_id
            GROUP BY
                c.id
        ) AS attendees2 ON base_id = attendees2.id
        LEFT OUTER JOIN (
            SELECT
                c.id, COUNT(status.registration_id) AS num_choices0
            FROM
                (SELECT id FROM event.courses WHERE event_id = 1) AS c
                LEFT OUTER JOIN (
                    SELECT
                        choices.registration_id, choices.course_id
                    FROM
                        (
                            SELECT registration_id, course_id
                            FROM event.course_choices
                            WHERE rank = 0 AND track_id = 2
                        ) AS choices
                        LEFT OUTER JOIN (
                            SELECT
                                registration_id AS reg_id, status
                            FROM
                                event.registration_parts
                            WHERE
                                part_id = 2
                        ) AS reg_part
                        ON choices.registration_id = reg_part.reg_id
                    WHERE
                        status = ANY(ARRAY[1,2,3,4])
                ) AS status ON c.id = status.course_id
            GROUP BY
                c.id
        ) AS choices2_0 ON base_id = choices2_0.id
    ) AS track2 ON course.id = track2.base_id
    LEFT OUTER JOIN (
        (
            SELECT id AS base_id
            FROM event.courses
            WHERE event_id = 1
        ) AS base
        LEFT OUTER JOIN (
            SELECT
                c.id, COALESCE(is_active, False) AS is_active
            FROM
                (SELECT id FROM event.courses WHERE event_id = 1) AS c
                LEFT OUTER JOIN (
                    SELECT
                        is_active, course_id
                    FROM
                        event.course_segments
                    WHERE track_id = 3
                ) AS segment ON c.id = segment.course_id
        ) AS segment3 ON base_id = segment3.id
        LEFT OUTER JOIN (
            SELECT
                c.id, COUNT(registration_id) AS attendees
            FROM
                (SELECT id FROM event.courses WHERE event_id = 1) AS c
                LEFT OUTER JOIN (
                    SELECT
                        registration_id, course_id
                    FROM
                        event.registration_tracks
                    WHERE track_id = 3
                ) AS rt ON c.id = rt.course_id
            GROUP BY
                c.id
        ) AS attendees3 ON base_id = attendees3.id
        LEFT OUTER JOIN (
            SELECT
                c.id, COUNT(status.registration_id) AS num_choices0
            FROM
                (SELECT id FROM event.courses WHERE event_id = 1) AS c
                LEFT OUTER JOIN (
                    SELECT
                        choices.registration_id, choices.course_id
                    FROM
                        (
                            SELECT registration_id, course_id
                            FROM event.course_choices
                            WHERE rank = 0 AND track_id = 3
                        ) AS choices
                        LEFT OUTER JOIN (
                            SELECT
                                registration_id AS reg_id, status
                            FROM
                                event.registration_parts
                            WHERE
                                part_id = 3
                        ) AS reg_part
                        ON choices.registration_id = reg_part.reg_id
                    WHERE
                        status = ANY(ARRAY[1,2,3,4])
                ) AS status ON c.id = status.course_id
            GROUP BY
                c.id
        ) AS choices3_0 ON base_id = choices3_0.id LEFT OUTER JOIN (
            SELECT
                c.id, COUNT(status.registration_id) AS num_choices1
            FROM
                (SELECT id FROM event.courses WHERE event_id = 1) AS c
                LEFT OUTER JOIN (
                    SELECT
                        choices.registration_id, choices.course_id
                    FROM
                        (
                            SELECT registration_id, course_id
                            FROM event.course_choices
                            WHERE rank = 1 AND track_id = 3
                        ) AS choices
                        LEFT OUTER JOIN (
                            SELECT
                                registration_id AS reg_id, status
                            FROM
                                event.registration_parts
                            WHERE
                                part_id = 3
                        ) AS reg_part
                        ON choices.registration_id = reg_part.reg_id
                    WHERE
                        status = ANY(ARRAY[1,2,3,4])
                ) AS status ON c.id = status.course_id
            GROUP BY
                c.id
        ) AS choices3_1 ON base_id = choices3_1.id LEFT OUTER JOIN (
            SELECT
                c.id, COUNT(status.registration_id) AS num_choices2
            FROM
                (SELECT id FROM event.courses WHERE event_id = 1) AS c
                LEFT OUTER JOIN (
                    SELECT
                        choices.registration_id, choices.course_id
                    FROM
                        (
                            SELECT registration_id, course_id
                            FROM event.course_choices
                            WHERE rank = 2 AND track_id = 3
                        ) AS choices
                        LEFT OUTER JOIN (
                            SELECT
                                registration_id AS reg_id, status
                            FROM
                                event.registration_parts
                            WHERE
                                part_id = 3
                        ) AS reg_part
                        ON choices.registration_id = reg_part.reg_id
                    WHERE
                        status = ANY(ARRAY[1,2,3,4])
                ) AS status ON c.id = status.course_id
            GROUP BY
                c.id
        ) AS choices3_2 ON base_id = choices3_2.id
    ) AS track3 ON course.id = track3.base_id
