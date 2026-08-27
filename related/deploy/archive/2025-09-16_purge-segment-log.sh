#!/usr/bin/env sh

sudo -u cdb psql -U cdb -d cdb -c "DELETE FROM event.log WHERE code = ANY(ARRAY[42, 43])"
