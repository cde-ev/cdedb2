BEGIN;
    ALTER TABLE cde.finance_log ADD COLUMN transaction_date date;

    UPDATE cde.finance_log SET transaction_date = outer_tmp.transaction_date FROM (
        SELECT * FROM (
            SELECT changelog.ctime::date, substring(changelog.change_note FROM 0 FOR 100), to_date(substring(changelog.change_note FROM '\d\d\.\d\d\.\d\d\d\d'), 'DD.MM.YYYY') AS transaction_date, finance_log.id AS finance_log_id, changelog.persona_id
            FROM core.changelog LEFT JOIN cde.finance_log ON finance_log.persona_id = changelog.persona_id AND finance_log.submitted_by = changelog.submitted_by AND finance_log.ctime = changelog.ctime
            WHERE finance_log.code = 10 ORDER BY changelog.ctime
        ) AS inner_tmp WHERE transaction_date IS NOT NULL
    ) AS outer_tmp
    WHERE id = finance_log_id;
COMMIT;
