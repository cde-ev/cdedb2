ALTER TABLE event.registrations ALTER amount_paid
    SET DATA TYPE NUMERIC(8,2);
ALTER TABLE event.registrations ALTER amount_owed
    SET DATA TYPE NUMERIC(8,2);
ALTER TABLE cde.lastschrift ALTER amount
    SET DATA TYPE NUMERIC(8,2);
ALTER TABLE cde.lastschrift_transactions ALTER amount
    SET DATA TYPE NUMERIC(8,2);
ALTER TABLE cde.lastschrift_transactions ALTER tally
    SET DATA TYPE NUMERIC(8,2);
ALTER TABLE cde.finance_log ALTER delta
    SET DATA TYPE NUMERIC(8,2);
ALTER TABLE cde.finance_log ALTER new_balance
    SET DATA TYPE NUMERIC(8,2);
