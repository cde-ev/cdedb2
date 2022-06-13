BEGIN;
    WITH newGroups (id, event_id) AS (
        INSERT INTO event.lodgement_groups(event_id, title)
        SELECT DISTINCT l.event_id, e.title
        FROM event.lodgements AS l JOIN event.events AS e ON l.event_id = e.id
        WHERE group_id IS NULL
        RETURNING lodgement_groups.id, lodgement_groups.event_id
    )
    UPDATE event.lodgements
    SET group_id = newGroups.id
    FROM newGroups
    WHERE lodgements.group_id IS NULL AND lodgements.event_id = newGroups.event_id;

    ALTER TABLE event.lodgements ALTER COLUMN group_id SET NOT NULL;
COMMIT;
