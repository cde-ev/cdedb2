BEGIN;
    UPDATE event.stored_queries
        SET serialized_query = (REPLACE(serialized_query::TEXT, '"qord_primary":', '"qord_1":'))::JSONB;
    UPDATE event.stored_queries
        SET serialized_query = (REPLACE(serialized_query::TEXT, '"qord_secondary":', '"qord_2":'))::JSONB;
    UPDATE event.stored_queries
        SET serialized_query = (REPLACE(serialized_query::TEXT, '"qord_tertiary":', '"qord_3":'))::JSONB;
    UPDATE event.stored_queries
        SET serialized_query = (REPLACE(serialized_query::TEXT, '"qord_primary_ascending":', '"qord_1_ascending":'))::JSONB;
    UPDATE event.stored_queries
        SET serialized_query = (REPLACE(serialized_query::TEXT, '"qord_secondary_ascending":', '"qord_2_ascending":'))::JSONB;
    UPDATE event.stored_queries
        SET serialized_query = (REPLACE(serialized_query::TEXT, '"qord_tertiary_ascending":', '"qord_3_ascending":'))::JSONB;
COMMIT;
