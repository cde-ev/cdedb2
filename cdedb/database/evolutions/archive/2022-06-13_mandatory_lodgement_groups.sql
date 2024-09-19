BEGIN;
    -- 4. Store these in a new temporary table.
    WITH newGroups (id, event_id) AS (
        -- 2. Insert a new lodgement group for every such event.
        INSERT INTO event.lodgement_groups(event_id, title)
        -- 1. Select event_id and event title once for every event with at least one groupless lodgement.
        SELECT DISTINCT l.event_id, e.title
        FROM event.lodgements AS l JOIN event.events AS e ON l.event_id = e.id
        WHERE group_id IS NULL
        -- 3. Return the id of the new group and the respective event.
        RETURNING lodgement_groups.id, lodgement_groups.event_id
    )
    -- 5. Using that temporary table update the groupless lodgements, linking them to the newly created ones.
    UPDATE event.lodgements
    SET group_id = newGroups.id
    FROM newGroups
    WHERE lodgements.group_id IS NULL AND lodgements.event_id = newGroups.event_id;

    -- 6. Disallow lodgements without a group.
    ALTER TABLE event.lodgements ALTER COLUMN group_id SET NOT NULL;
COMMIT;
