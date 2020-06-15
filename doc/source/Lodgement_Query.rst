Lodgement Query
===============

.. highlight:: sql

To dynamically query information about lodgements, we have to construct a rather involved view on the fly.
This is necessary because the information is spread across multiple different tables and there are dynamically
many event parts in which a lodgement may be involved depending on the event.

We construct this view from the following main components:

- The general ``event.lodgements`` table. Here lies general lodgement information like moniker, capacity and orga notes.
- The general ``event.lodgement_groups`` table. Every lodgement may belong to one lodgement group.
- The custom lodgement related datafields. These are extracted from the JSON-column ``fields`` which is part of the
  ``event.lodgements`` table, but we have to do this on the fly to determine the appropriate fields for that event.
- A series of part tables, containing information for the lodgement in relation to all event parts of the event.
  This component will be discussed in further detail below.

The final view will be constructed as follows (slightly simplified). ::

  (
      SELECT
          id, id as lodgement_id, event_id,
          moniker, regular_capacity, camping_mat_capacity, notes, group_id
      FROM
          event.lodgements
  ) AS lodgement
  LEFT OUTER JOIN (
      SELECT
          id, moniker, regular_capacity, camping_mat_capacity
      FROM
          event.lodgement_groups
  ) AS lodgement_group ON lodgement.group_id = lodgement_group.id
  LEFT OUTER JOIN (
      SELECT
          *course_field_columns*, id
      FROM
          event.courses
      WHERE
          event_id = X
  ) AS lodgement_field ON lodgement.id = lodgement_fields.id
  LEFT OUTER JOIN (
      part_tableX
  ) AS partX ON lodgement.id = partX.base_id

``lodgement_field_columns`` will contain a JSON-cast from the ``fields`` column for every relevant lodgement field.
``part_tableX`` is an example for one of the dynamic tables that are all joined as described.

The following columns will be available in this view:

* ``lodgement.id``
* ``lodgement.event_id``
* ``lodgement.moniker``
* ``lodgement.regular_capacity``
* ``lodgement.notes``
* ``lodgement.group_id``
* ``lodgement.camping_mat_capacity``
* ``lodgement_group.moniker``
* ``lodgement_group.regular_capacity``
* ``lodgement_group.camping_mat_capacity``
* ``lodgement_fields.xfield_{field_name}`` *This is available for every custom data field with course association.*
* ``part{part_id}.regular_inhabitants``
* ``part{part_id}.camping_mat_inhabitants``
* ``part[part_id}.total_inhabitants``
* ``part{part_id}.group_regular_inhabitants``
* ``part{part_id}.group_camping_mat_inhabitants``
* ``part[part_id}.group_total_inhabitants``

*Note that some additional columns are present but omitted here, since they are not really useful like
``part{part_id}.base_id``.*

Implementation Details
----------------------

In this section we discuss some more involved details of the implementation. These need not be considered when using
the query view, rather you need to keep this in mind when chaning how the view is constructed.

Temporarily casting the group_id
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A lodgement can either be linked to a lodgement group via the ``event.lodgements.group_id`` foreign key to the
``event.lodgement_groups.id`` column, but it can also not belong to any lodgement group. For practical reasons we want
to group all lodgements that don't belong to any group together, but POSTGRES won't allow joining tables using
``NULL = NULL``. Due to this we need to temporarily cast the nullable ``event.lodgements.group_id`` column to a
non-nullable ``tmp_id`` column by replacing ``NULL``-entries with ``-1``, like this: ::

  SELECT
      -- replace NULL ids with temp value so we can join.
      id, COALESCE(group_id, -1) AS tmp_group_id
  FROM
      event.lodgements

We also need to create an artificial row for the ``event.ldogement_groups`` table to join to, like this: ::

  (
      SELECT
          id AS tmp_id, moniker
      FROM
          event.lodgement_groups
  )
  UNION
  (
      SELECT
          -1, ''
  )


Casting nested sums to bigint
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Summing rows of integer datatypes with POSTGRES converts the result to the next bigger numerical datatype. Summing
``integer`` results in ``bigint``. Summing ``bigint`` however results in ``numeric``, which is also used to store
fixed-point numbers and is thus converted to ``decimal.Decimal`` by ``psycopg2``. To avoid this we cast the sums for
group inhabitants to bigint, since we do not expect to need lodgement groups with more than 10^19 inhabitants.

Note that these sums are also normalized to zero in case a ``NULL``-value occurs, because there are no
inhabitants/lodgements for a lodgement (group).

The Part Tables
----------------

For every event part we gather the following data points:

* Regular inhabitants
* Reserve inhabitants
* Total inhabitants

We gather these both for each lodgement individually and summed for each lodgement group.

The part table starts out with a base table created by selecting all the appropriate lodgement ids, aswell as the
corresponding lodgement group ids. The lodgement id is selected as ``base_id`` so we can later use it to join the
part tables to the other components. This is necessary because there will be multiple columns called ``id`` in
a single part table and POSTGRES wouldn't know which to use in the ``JOIN`` otherwise: ::

  (
      SELECT
          id as base_id, COALESCE(group_id, -1) AS tmp_group_id
      FROM
          event.lodgements
      WHERE
          event_id = X
  ) AS base

The part table consists of two components, both of which use the *inhabitants_view*. The first is just the *inhabitants_view* itself: ::

  SELECT
      id, tmp_group_id,
      COALESCE(rp_regular.inhabitants, 0) AS regular_inhabitants,
      COALESCE(rp_camping_mat.inhabitants, 0) AS camping_mat_inhabitants,
      COALESCE(rp_total.inhabitants, 0) AS total_inhabitants
  FROM
      (
          SELECT id, COALESCE(group_id, -1) as tmp_group_id
          FROM event.lodgements
          WHERE event_id = X
      ) AS l
      LEFT OUTER JOIN (
          *regular_inhabitants_counter*
      ) AS rp_regular ON l.id = rp_regular.lodgement_id
      LEFT OUTER JOIN (
          *camping_mat_inahbitants_counter*
      ) AS rp_camping_mat ON l.id = rp_camping_mat.lodgement_id
      LEFT OUTER JOIN (
          *total_inhabitants_counter*
      ) AS rp_total ON l.id = rp_total.lodgement_id

The second component is the *group_inhabitants_view*: ::

  SELECT
      tmp_group_id,
      COALESCE(SUM(regular_inhabitants)::bigint, 0) AS group_regular_inhabitants,
      COALESCE(SUM(camping_mat_inhabitants)::bigint, 0) AS group_camping_mat_inhabitants,
      COALESCE(SUM(total_inhabitants)::bigint, 0) AS group_total_inhabitants
  FROM (
      *inhabitants_view*
  ) AS inhabitants_viewX
  GROUP BY
      tmp_group_id


The inhabitants counter
^^^^^^^^^^^^^^^^^^^^^^^

The inhabitants counter is a simple query where all inhabitants (with a specific camping_mat status are counted: ::

  SELECT
      lodgement_id, COUNT(registration_id) AS inhabitants
  FROM
      event.registration_parts
  WHERE
      part_id = X
      *camping_mat_condition*
  GROUP BY
      lodgement_id

Where camping_mat condition is either "is_camping_mat = True", "is_camping_mat = False" or nothing, for regular, camping_mat,
total inhabitants respectively.

The Complete View
-----------------
::

    (
        SELECT
            id, id as lodgement_id, event_id,
            moniker, regular_capacity, camping_mat_capacity, notes, group_id
        FROM
            event.lodgements
    ) AS lodgement
    LEFT OUTER JOIN (
        SELECT
            -- replace NULL ids with temp value so we can join.
            id, COALESCE(group_id, -1) AS tmp_group_id
        FROM
            event.lodgements
        WHERE
            event_id = 1
    ) AS tmp_group ON lodgement.id = tmp_group.id
    LEFT OUTER JOIN (
        SELECT
            (fields->>'contamination')::varchar AS "xfield_contamination",
            id
        FROM
            event.lodgements
        WHERE
            event_id = 1
    ) AS lodgement_fields ON lodgement.id = lodgement_fields.id
    LEFT OUTER JOIN (
        SELECT
            tmp_id, moniker, regular_capacity, camping_mat_capacity
        FROM (
            (
                (
                    SELECT
                        id AS tmp_id, moniker
                    FROM
                        event.lodgement_groups
                    WHERE
                        event_id = 1
                )
                UNION
                (
                    SELECT
                        -1, ''
                )
            ) AS group_base
            LEFT OUTER JOIN (
                SELECT
                    COALESCE(group_id, -1) as tmp_group_id,
                    SUM(regular_capacity) as regular_capacity,
                    SUM(camping_mat_capacity) as camping_mat_capacity
                FROM
                    event.lodgements
                WHERE
                    event_id = 1
                GROUP BY
                    tmp_group_id
            ) AS group_totals ON group_base.tmp_id = group_totals.tmp_group_id
        )
    ) AS lodgement_group ON tmp_group.tmp_group_id = lodgement_group.tmp_id
    LEFT OUTER JOIN (
        (
            SELECT
                id as base_id, COALESCE(group_id, -1) AS tmp_group_id
            FROM
                event.lodgements
            WHERE
                event_id = 1
        ) AS base
        LEFT OUTER JOIN (
            SELECT
                id, tmp_group_id,
                COALESCE(rp_regular.inhabitants, 0) AS regular_inhabitants,
                COALESCE(rp_camping_mat.inhabitants, 0) AS camping_mat_inhabitants,
                COALESCE(rp_total.inhabitants, 0) AS total_inhabitants
            FROM
                (
                    SELECT id, COALESCE(group_id, -1) as tmp_group_id
                    FROM event.lodgements
                    WHERE event_id = 1
                ) AS l
                LEFT OUTER JOIN (
                    SELECT
                        lodgement_id, COUNT(registration_id) AS inhabitants
                    FROM
                        event.registration_parts
                    WHERE
                        part_id = 1
                        AND is_camping_mat = False
                    GROUP BY
                        lodgement_id
                ) AS rp_regular ON l.id = rp_regular.lodgement_id
                LEFT OUTER JOIN (
                    SELECT
                        lodgement_id, COUNT(registration_id) AS inhabitants
                    FROM
                        event.registration_parts
                    WHERE
                        part_id = 1
                        AND is_camping_mat = True
                    GROUP BY
                        lodgement_id
                ) AS rp_camping_mat ON l.id = rp_camping_mat.lodgement_id
                LEFT OUTER JOIN (
                    SELECT
                        lodgement_id, COUNT(registration_id) AS inhabitants
                    FROM
                        event.registration_parts
                    WHERE
                        part_id = 1
                    GROUP BY
                        lodgement_id
                ) AS rp_total ON l.id = rp_total.lodgement_id
        ) AS inhabitants_view1 ON base.base_id = inhabitants_view1.id
        LEFT OUTER JOIN (
            SELECT
                tmp_group_id,
                COALESCE(SUM(regular_inhabitants)::bigint, 0) AS group_regular_inhabitants,
                COALESCE(SUM(camping_mat_inhabitants)::bigint, 0) AS group_camping_mat_inhabitants,
                COALESCE(SUM(total_inhabitants)::bigint, 0) AS group_total_inhabitants
            FROM (
                SELECT
                    id, tmp_group_id,
                    COALESCE(rp_regular.inhabitants, 0) AS regular_inhabitants,
                    COALESCE(rp_camping_mat.inhabitants, 0) AS camping_mat_inhabitants,
                    COALESCE(rp_total.inhabitants, 0) AS total_inhabitants
                FROM
                    (
                        SELECT id, COALESCE(group_id, -1) as tmp_group_id
                        FROM event.lodgements
                        WHERE event_id = 1
                    ) AS l
                    LEFT OUTER JOIN (
                        SELECT
                            lodgement_id, COUNT(registration_id) AS inhabitants
                        FROM
                            event.registration_parts
                        WHERE
                            part_id = 1
                            AND is_camping_mat = False
                        GROUP BY
                            lodgement_id
                        ) AS rp_regular ON l.id = rp_regular.lodgement_id
                            LEFT OUTER JOIN (
                                SELECT
                            lodgement_id, COUNT(registration_id) AS inhabitants
                        FROM
                            event.registration_parts
                        WHERE
                            part_id = 1
                            AND is_camping_mat = True
                        GROUP BY
                            lodgement_id
                        ) AS rp_camping_mat ON l.id = rp_camping_mat.lodgement_id
                        LEFT OUTER JOIN (
                            SELECT
                                lodgement_id, COUNT(registration_id) AS inhabitants
                            FROM
                                event.registration_parts
                            WHERE
                                part_id = 1

                            GROUP BY
                                lodgement_id
                        ) AS rp_total ON l.id = rp_total.lodgement_id
                ) AS inhabitants_view1
            GROUP BY
                tmp_group_id
        ) AS group_inhabitants_view1 ON base.tmp_group_id = group_inhabitants_view1.tmp_group_id
    ) AS part1 ON lodgement.id = part1.base_id
    LEFT OUTER JOIN (
        (
            SELECT
                id as base_id, COALESCE(group_id, -1) AS tmp_group_id
            FROM
                event.lodgements
            WHERE
                event_id = 1
        ) AS base
        LEFT OUTER JOIN (
            SELECT
                id, tmp_group_id,
                COALESCE(rp_regular.inhabitants, 0) AS regular_inhabitants,
                COALESCE(rp_camping_mat.inhabitants, 0) AS camping_mat_inhabitants,
                COALESCE(rp_total.inhabitants, 0) AS total_inhabitants
            FROM
                (
                    SELECT id, COALESCE(group_id, -1) as tmp_group_id
                    FROM event.lodgements
                    WHERE event_id = 1
                ) AS l
            LEFT OUTER JOIN (
                SELECT
                    lodgement_id, COUNT(registration_id) AS inhabitants
                FROM
                    event.registration_parts
                WHERE
                    part_id = 2
                    AND is_camping_mat = False
                GROUP BY
                    lodgement_id
                ) AS rp_regular ON l.id = rp_regular.lodgement_id
            LEFT OUTER JOIN (
                SELECT
                    lodgement_id, COUNT(registration_id) AS inhabitants
                FROM
                    event.registration_parts
                WHERE
                    part_id = 2
                    AND is_camping_mat = True
                GROUP BY
                    lodgement_id
            ) AS rp_camping_mat ON l.id = rp_camping_mat.lodgement_id
            LEFT OUTER JOIN (
                SELECT
                    lodgement_id, COUNT(registration_id) AS inhabitants
                FROM
                    event.registration_parts
                WHERE
                    part_id = 2

                GROUP BY
                    lodgement_id
            ) AS rp_total ON l.id = rp_total.lodgement_id
        ) AS inhabitants_view2 ON base.base_id = inhabitants_view2.id
        LEFT OUTER JOIN (
            SELECT
                tmp_group_id,
                COALESCE(SUM(regular_inhabitants)::bigint, 0) AS group_regular_inhabitants,
                COALESCE(SUM(camping_mat_inhabitants)::bigint, 0) AS group_camping_mat_inhabitants,
                COALESCE(SUM(total_inhabitants)::bigint, 0) AS group_total_inhabitants
            FROM (
                SELECT
                    id, tmp_group_id,
                    COALESCE(rp_regular.inhabitants, 0) AS regular_inhabitants,
                    COALESCE(rp_camping_mat.inhabitants, 0) AS camping_mat_inhabitants,
                    COALESCE(rp_total.inhabitants, 0) AS total_inhabitants
                FROM
                    (
                        SELECT id, COALESCE(group_id, -1) as tmp_group_id
                        FROM event.lodgements
                        WHERE event_id = 1
                    ) AS l
                    LEFT OUTER JOIN (
                        SELECT
                            lodgement_id, COUNT(registration_id) AS inhabitants
                        FROM
                            event.registration_parts
                        WHERE
                            part_id = 2
                            AND is_camping_mat = False
                        GROUP BY
                            lodgement_id
                    ) AS rp_regular ON l.id = rp_regular.lodgement_id
                    LEFT OUTER JOIN (
                        SELECT
                            lodgement_id, COUNT(registration_id) AS inhabitants
                        FROM
                            event.registration_parts
                        WHERE
                            part_id = 2
                            AND is_camping_mat = True
                        GROUP BY
                            lodgement_id
                    ) AS rp_camping_mat ON l.id = rp_camping_mat.lodgement_id
                    LEFT OUTER JOIN (
                        SELECT
                            lodgement_id, COUNT(registration_id) AS inhabitants
                        FROM
                            event.registration_parts
                        WHERE
                            part_id = 2

                        GROUP BY
                            lodgement_id
                    ) AS rp_total ON l.id = rp_total.lodgement_id
            ) AS inhabitants_view2
        GROUP BY
            tmp_group_id
        ) AS group_inhabitants_view2 ON base.tmp_group_id = group_inhabitants_view2.tmp_group_id
    ) AS part2 ON lodgement.id = part2.base_id
    LEFT OUTER JOIN (
        (
            SELECT
                id as base_id, COALESCE(group_id, -1) AS tmp_group_id
            FROM
                event.lodgements
            WHERE
                event_id = 1
        ) AS base
        LEFT OUTER JOIN (
            SELECT
                id, tmp_group_id,
                COALESCE(rp_regular.inhabitants, 0) AS regular_inhabitants,
                COALESCE(rp_camping_mat.inhabitants, 0) AS camping_mat_inhabitants,
                COALESCE(rp_total.inhabitants, 0) AS total_inhabitants
            FROM
                (
                    SELECT id, COALESCE(group_id, -1) as tmp_group_id
                    FROM event.lodgements
                    WHERE event_id = 1
                ) AS l
                LEFT OUTER JOIN (
                    SELECT
                        lodgement_id, COUNT(registration_id) AS inhabitants
                    FROM
                        event.registration_parts
                    WHERE
                        part_id = 3
                        AND is_camping_mat = False
                    GROUP BY
                        lodgement_id
                ) AS rp_regular ON l.id = rp_regular.lodgement_id
                LEFT OUTER JOIN (
                    SELECT
                        lodgement_id, COUNT(registration_id) AS inhabitants
                    FROM
                        event.registration_parts
                    WHERE
                        part_id = 3
                        AND is_camping_mat = True
                    GROUP BY
                        lodgement_id
                ) AS rp_camping_mat ON l.id = rp_camping_mat.lodgement_id
                LEFT OUTER JOIN (
                    SELECT
                    lodgement_id, COUNT(registration_id) AS inhabitants
                FROM
                    event.registration_parts
                WHERE
                    part_id = 3

                GROUP BY
                    lodgement_id
                    ) AS rp_total ON l.id = rp_total.lodgement_id
        ) AS inhabitants_view3 ON base.base_id = inhabitants_view3.id
        LEFT OUTER JOIN (
            SELECT
                tmp_group_id,
                COALESCE(SUM(regular_inhabitants)::bigint, 0) AS group_regular_inhabitants,
                COALESCE(SUM(camping_mat_inhabitants)::bigint, 0) AS group_camping_mat_inhabitants,
                COALESCE(SUM(total_inhabitants)::bigint, 0) AS group_total_inhabitants
            FROM (
                SELECT
                    id, tmp_group_id,
                    COALESCE(rp_regular.inhabitants, 0) AS regular_inhabitants,
                    COALESCE(rp_camping_mat.inhabitants, 0) AS camping_mat_inhabitants,
                    COALESCE(rp_total.inhabitants, 0) AS total_inhabitants
                FROM
                    (
                        SELECT id, COALESCE(group_id, -1) as tmp_group_id
                        FROM event.lodgements
                        WHERE event_id = 1
                    ) AS l
                    LEFT OUTER JOIN (
                        SELECT
                            lodgement_id, COUNT(registration_id) AS inhabitants
                        FROM
                            event.registration_parts
                        WHERE
                            part_id = 3
                            AND is_camping_mat = False
                        GROUP BY
                            lodgement_id
                    ) AS rp_regular ON l.id = rp_regular.lodgement_id
                    LEFT OUTER JOIN (
                        SELECT
                            lodgement_id, COUNT(registration_id) AS inhabitants
                        FROM
                            event.registration_parts
                        WHERE
                            part_id = 3
                            AND is_camping_mat = True
                        GROUP BY
                            lodgement_id
                    ) AS rp_camping_mat ON l.id = rp_camping_mat.lodgement_id
                    LEFT OUTER JOIN (
                        SELECT
                            lodgement_id, COUNT(registration_id) AS inhabitants
                        FROM
                            event.registration_parts
                        WHERE
                            part_id = 3
                        GROUP BY
                            lodgement_id
                    ) AS rp_total ON l.id = rp_total.lodgement_id
            ) AS inhabitants_view3
            GROUP BY
                tmp_group_id
        ) AS group_inhabitants_view3 ON base.tmp_group_id = group_inhabitants_view3.tmp_group_id
    ) AS part3 ON lodgement.id = part3.base_id
