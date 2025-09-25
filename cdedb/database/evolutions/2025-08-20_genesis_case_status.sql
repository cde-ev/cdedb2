BEGIN;
    ALTER TABLE core.genesis_cases RENAME COLUMN case_status TO status;
    ALTER INDEX core.genesis_cases_case_status_idx RENAME TO genesis_cases_status_idx;
COMMIT;
