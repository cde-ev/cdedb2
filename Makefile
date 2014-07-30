help:
	@echo "run-core, run-cde, run-event, run-session"
	@echo "         -- run the respective backend (CONFIGPATH specifies configuration)"
	@echo "quit-core, quit-cde, quit-event, quit-session"
	@echo "          -- quit the respective backend"
	@echo "quit-all -- quit all running backends"
	@echo "quit-test-backends -- quit all running backends started by the test suite"
	@echo "pyro-nameserver -- run a pyro nameserver"
	@echo "doc -- build documentation"
	@echo "sample-data -- initialize database structures (DESTROYES DATA!)"
	@echo "sample-data-test -- initialize database structures for test suite"
	@echo "sample-data-test-shallow -- initialize database structures for test suite"
	@echo "                            (this is a fast version of sample-data-test,"
	@echo "                             can be substituted after sample-data-test was"
	@echo "                             executed)"
	@echo "ldap -- initialize ldap (use sample-data instead)"
	@echo "ldap-test -- initialize ldap for test suite (use sample-data-test instead)"
	@echo "sql -- initialize postgres (use sample-data instead)"
	@echo "sql-test -- initialize postgres for test suite (use sample-data-test instead)"
	@echo "sql-test-shallow -- reset postgres for test suite"
	@echo "                    (use sample-data-test-shallow instead)"
	@echo "lint -- run pylint"
	@echo "check -- run test suite"
	@echo "         (TESTPATTERN specifies files, e.g. 'test_common.py')"
	@echo "single-check -- run a single test from the test suite"
	@echo "                (specified via TESTPATTERN, e.g."
	@echo "                 'test.test_common.TestCommon.test_realm_extraction')"
	@echo "coverage -- run coverage to determine test suite coverage"

CONFIGPATH ?= ""
PYTHONBIN ?= python3
TESTPATTERN ?= ""

pyro-nameserver:
	${PYTHONBIN} -m Pyro4.naming

run-core:
	make quit-core
	rm -f /run/cdedb/coreserver.pid /run/cdedb/coreserver.sock
	${PYTHONBIN} -m cdedb.backend.core -c ${CONFIGPATH}

quit-core:
	kill `cat /run/cdedb/coreserver.pid`

run-cde:
	make quit-cde
	rm -f /run/cdedb/cdeserver.pid /run/cdedb/cdeserver.sock
	${PYTHONBIN} -m cdedb.backend.cde -c ${CONFIGPATH}

quit-cde:
	kill `cat /run/cdedb/cdeserver.pid`

run-event:
	make quit-event
	rm -f /run/cdedb/eventserver.pid /run/cdedb/eventserver.sock
	${PYTHONBIN} -m cdedb.backend.event -c ${CONFIGPATH}

quit-event:
	kill `cat /run/cdedb/eventserver.pid`

run-session:
	make quit-session
	rm -f /run/cdedb/sessionserver.pid /run/cdedb/sessionserver.sock
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

sample-data:
	make sql
	make ldap

sample-data-test:
	make sql-test
	make ldap-test

sample-data-test-shallow:
	make sql-test-shallow
	make ldap-test

ldap:
	echo 'ou=personas,dc=cde-ev,dc=de\nou=personas-test,dc=cde-ev,dc=de' | ldapdelete -c -r -x -D `cat .ldap_rootdn` -y .ldap_rootpw || true
	ldapadd -c -x -D `cat .ldap_rootdn` -y .ldap_rootpw -f cdedb/database/init.ldif || true
	sed -e 's/{LDAP_ORGANIZATION}/personas/' test/ancillary_files/sample_data.ldif | ldapadd -c -x -D `cat .ldap_rootdn` -y .ldap_rootpw || true
	sed -e 's/{LDAP_ORGANIZATION}/personas-test/' test/ancillary_files/sample_data.ldif | ldapadd -c -x -D `cat .ldap_rootdn` -y .ldap_rootpw || true

ldap-test:
	echo 'ou=personas-test,dc=cde-ev,dc=de' | ldapdelete -c -r -x -D `cat .ldap_rootdn` -y .ldap_rootpw || true
	ldapadd -c -x -D `cat .ldap_rootdn` -y .ldap_rootpw -f cdedb/database/init.ldif || true
	sed -e 's/{LDAP_ORGANIZATION}/personas-test/' test/ancillary_files/sample_data.ldif | ldapadd -c -x -D `cat .ldap_rootdn` -y .ldap_rootpw || true

sql:
	sudo -u postgres psql -U postgres -f cdedb/database/cdedb-users.sql
	sudo -u postgres psql -U postgres -f cdedb/database/cdedb-db.sql -v cdb_database_name=cdb
	sudo -u postgres psql -U postgres -f cdedb/database/cdedb-db.sql -v cdb_database_name=cdb_test
	sudo -u cdb psql -U cdb -d cdb -f cdedb/database/cdedb-tables.sql
	sudo -u cdb psql -U cdb -d cdb_test -f cdedb/database/cdedb-tables.sql
	sudo -u cdb psql -U cdb -d cdb -f test/ancillary_files/sample_data.sql
	sudo -u cdb psql -U cdb -d cdb_test -f test/ancillary_files/sample_data.sql

sql-test:
	sudo -u postgres psql -U postgres -f cdedb/database/cdedb-db.sql -v cdb_database_name=cdb_test
	sudo -u cdb psql -U cdb -d cdb_test -f cdedb/database/cdedb-tables.sql
	make sql-test-shallow

sql-test-shallow:
	sudo -u cdb psql -U cdb -d cdb_test -f test/ancillary_files/clean_data.sql
	sudo -u cdb psql -U cdb -d cdb_test -f test/ancillary_files/sample_data.sql

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
	make sample-data-test &> /dev/null
	[ -f cdedb/testconfig.py.off ] && mv cdedb/testconfig.py.off cdedb/testconfig.py || true
	${PYTHONBIN} -m test.main ${TESTPATTERN}
	[ -f cdedb/testconfig.py ] && mv cdedb/testconfig.py cdedb/testconfig.py.off || true

single-check:
	make quit-test-backends
	make sample-data-test &> /dev/null
	[ -f cdedb/testconfig.py.off ] && mv cdedb/testconfig.py.off cdedb/testconfig.py || true
	${PYTHONBIN} -m unittest ${TESTPATTERN}
	[ -f cdedb/testconfig.py ] && mv cdedb/testconfig.py cdedb/testconfig.py.off || true

.coverage: $(wildcard cdedb/*.py) $(wildcard cdedb/database/*.py) $(wildcard cdedb/frontend/*.py) $(wildcard cdedb/backend/*.py) $(wildcard test/*.py)
	/usr/lib/python-exec/python3.4/coverage run -m test.main

coverage: .coverage
	coverage report -m --omit='test/*,related/*'

.PHONY: help pyro-nameserver run-core quit-core run-cde quit-cde run-event quit-event run-session quit-session quit-all quit-test-backends doc sample-data sample-data-test sample-data-test-shallow ldap ldap-test sql sql-test sql-test-shallow lint check single-check .coverage coverage
