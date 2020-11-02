BEGIN;
    ALTER TABLE event.registrations ALTER COLUMN amount_paid
        SET DATA TYPE NUMERIC(8,2);
    ALTER TABLE event.registrations ALTER COLUMN amount_owed
        SET DATA TYPE NUMERIC(8,2);
    ALTER TABLE cde.lastschrift ALTER COLUMN amount
        SET DATA TYPE NUMERIC(8,2);
    ALTER TABLE cde.lastschrift_transactions ALTER COLUMN amount
        SET DATA TYPE NUMERIC(8,2);
    ALTER TABLE cde.lastschrift_transactions ALTER COLUMN tally
        SET DATA TYPE NUMERIC(8,2);
    ALTER TABLE cde.finance_log ALTER COLUMN delta
        SET DATA TYPE NUMERIC(8,2);
    ALTER TABLE cde.finance_log ALTER COLUMN new_balance
        SET DATA TYPE NUMERIC(8,2);
COMMIT;