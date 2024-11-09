BEGIN;
    ALTER TABLE core.personas ADD COLUMN honorary_member boolean;
    UPDATE core.personas SET honorary_member = FALSE WHERE is_cde_realm = True;
    ALTER TABLE core.personas ADD CONSTRAINT personas_cde_honorary_member
        CHECK(is_cde_realm = (honorary_member IS NOT NULL));
    ALTER TABLE core.personas ADD CONSTRAINT personas_honorary_member_implicits
        CHECK(NOT honorary_member OR is_member);
    ALTER TABLE core.changelog ADD COLUMN honorary_member boolean;
COMMIT;
