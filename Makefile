help:
	@echo "run-core, run-cde, run-event, run-session"
	@echo "         -- run the respective backend (CONFIGPATH specifies configuration)"
	@echo "quit-core, quit-cde, quit-event, quit-session"
	@echo "          -- quit the respective backend"
	@echo "quit-all -- quit all running backends"
	@echo "quit-test-backends -- quit all running backends started by the test suite"
	@echo "pyro-nameserver -- run a pyro nameserver"
	@echo "doc -- build documentation"
	@echo "sql -- initialize database structures (DESTROYES DATA)"
	@echo "sql-test -- initialize database structures for test suite"
	@echo "sql-test-data -- fill test database with data for test suite"
	@echo "lint -- run pylint"
	@echo "check -- run test suite"
	@echo "         (TESTPATTERN specifies files, e.g. 'test_common.py')"
	@echo "single-check -- run a single test from the test suite"
	@echo "                (specified via TESTPATTERN, e.g."
	@echo "                 'test.test_common.TestCommon.test_realm_extraction')"
	@echo "coverage -- run coverage to determine test suite coverage"

CONFIGPATH ?= ""
PYTHONBIN ?= "python3"
TESTPATTERN ?= ""

pyro-nameserver:
	python -m Pyro4.naming

run-core:
	${PYTHONBIN} -m cdedb.backend.core -c ${CONFIGPATH}

quit-core:
	kill `cat /run/cdedb/coreserver.pid`

run-cde:
	${PYTHONBIN} -m cdedb.backend.cde -c ${CONFIGPATH}

quit-cde:
	kill `cat /run/cdedb/cdeserver.pid`

run-event:
	${PYTHONBIN} -m cdedb.backend.event -c ${CONFIGPATH}

quit-event:
	kill `cat /run/cdedb/eventserver.pid`

run-session:
	${PYTHONBIN} -m cdedb.backend.session -c ${CONFIGPATH}

quit-session:
	kill `cat /run/cdedb/sessionserver.pid`

quit-all:
	[ -f /run/cdedb/coreserver.pid ] && kill `cat /run/cdedb/coreserver.pid` || true
	[ -f /run/cdedb/cdeserver.pid ] && kill `cat /run/cdedb/cdeserver.pid` || true
	[ -f /run/cdedb/eventserver.pid ] && kill `cat /run/cdedb/eventserver.pid` || true
	[ -f /run/cdedb/sessionserver.pid ] && kill `cat /run/cdedb/sessionserver.pid` || true

quit-test-backends:
	[ -f /run/cdedb/test-coreserver.pid ] && kill `cat /run/cdedb/test-coreserver.pid` || true
	[ -f /run/cdedb/test-sessionserver.pid ] && kill `cat /run/cdedb/test-sessionserver.pid` || true
	[ -f /run/cdedb/test-cdeserver.pid ] && kill `cat /run/cdedb/test-cdeserver.pid` || true
	[ -f /run/cdedb/test-eventserver.pid ] && kill `cat /run/cdedb/test-eventserver.pid` || true

doc:
	make -C doc html

sql:
	psql -U postgres -f cdedb/database/cdedb-users.sql -v cdb_database_name=cdb
	psql -U postgres -f cdedb/database/cdedb-tables.sql -v cdb_database_name=cdb
	psql -U postgres -f test/ancillary_files/sample_data.sql -v cdb_database_name=cdb

sql-test:
	psql -U postgres -f cdedb/database/cdedb-tables.sql -v cdb_database_name=cdb_test
	psql -U postgres -f test/ancillary_files/sample_data.sql -v cdb_database_name=cdb_test

sql-test-data:
	psql -U postgres -f test/ancillary_files/clean_data.sql -v cdb_database_name=cdb_test
	psql -U postgres -f test/ancillary_files/sample_data.sql -v cdb_database_name=cdb_test

lint:
	/usr/lib/python-exec/python3.4/pylint --rcfile='./lint.rc' cdedb || true
	@echo ""
	@echo "================================================================================"
	@echo "And now only errors and warnings"
	@echo "================================================================================"
	@echo ""
	/usr/lib/python-exec/python3.4/pylint --rcfile='./lint.rc' cdedb | egrep '^(\*\*\*\*|E:|W:)' | egrep -v "Module 'cdedb.validation' has no '[a-zA-Z_]*' member" | egrep -v "Instance of '[A-Za-z]*Config' has no '[a-zA-Z_]*' member"

check:
	make quit-test-backends
	make sql-test &> /dev/null
	[ -f cdedb/testconfig.py.off ] && mv cdedb/testconfig.py.off cdedb/testconfig.py || true
	${PYTHONBIN} -m test.main ${TESTPATTERN}
	[ -f cdedb/testconfig.py ] && mv cdedb/testconfig.py cdedb/testconfig.py.off || true

single-check:
	make quit-test-backends
	make sql-test &> /dev/null
	[ -f cdedb/testconfig.py.off ] && mv cdedb/testconfig.py.off cdedb/testconfig.py || true
	${PYTHONBIN} -m unittest ${TESTPATTERN}
	[ -f cdedb/testconfig.py ] && mv cdedb/testconfig.py cdedb/testconfig.py.off || true

.coverage: $(wildcard cdedb/*.py) $(wildcard cdedb/database/*.py) $(wildcard cdedb/frontend/*.py) $(wildcard cdedb/backend/*.py) $(wildcard test/*.py)
	/usr/lib/python-exec/python3.4/coverage run -m test.main

coverage: .coverage
	coverage report -m --omit='test/*,related/*'

.PHONY: help pyro-nameserver run-core quit-core run-cde quit-cde run-event quit-event run-session quit-session quit-all quit-test-backends doc sql sql-test sql-test-data lint check single-check .coverage coverage
