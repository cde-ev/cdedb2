-- This evolution represents the change made in bbfd3a89a0 and was recreated later.
-- This commit was part of PR #1226 and closed issue #1035, by unifying the naming of camping mat related columns.

ALTER TABLE event.events RENAME COLUMN reserve_field TO camping_mat_field;
ALTER TABLE event.lodgements RENAME COLUMN capacity TO regular_capacity;
ALTER TABLE event.lodgements RENAME COLUMN reserve TO camping_mat_capacity;
ALTER TABLE event.registration_parts RENAME COLUMN is_reserve TO is_camping_mat;
