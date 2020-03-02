Course Query
============

.. highlight:: sql

The view for course queries looks something like this::

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
