SHELL := /bin/bash

help:
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
	@echo "lint -- run linters (mainly pylint)"
	@echo "check -- run test suite"
	@echo "         (TESTPATTERN specifies files, e.g. 'test_common.py')"
	@echo "single-check -- run a single test from the test suite"
	@echo "                (specified via TESTPATTERN, e.g."
	@echo "                 'test.test_common.TestCommon.test_extract_roles')"
	@echo "coverage -- run coverage to determine test suite coverage"

PYTHONBIN ?= python3
TESTPATTERN ?=

ifeq ($(wildcard .ldap_rootpw_local), .ldap_rootpw_local)
LDAP_PASSWORDFILE = .ldap_rootpw_local
else
LDAP_PASSWORDFILE = .ldap_rootpw
endif

doc:
	make -C doc html

i18n-refresh:
	pybabel extract -F ./babel.cfg -k "rs.gettext","rs.ngettext" -o ./i18n/cdedb.pot .
	pybabel update -i ./i18n/cdedb.pot -d ./i18n/ -l de -D cdedb
	pybabel update -i ./i18n/cdedb.pot -d ./i18n/ -l en -D cdedb

i18n-compile:
	pybabel compile -d ./i18n/ -l de -D cdedb
	pybabel compile -d ./i18n/ -l en -D cdedb

sample-data:
	make sql
	make ldap

sample-data-test:
	make storage-test
	make sql-test
	make ldap-test

sample-data-test-shallow:
	make storage-test
	make sql-test-shallow
	make ldap-test

storage-test:
	rm -rf "/tmp/cdedb-store/"
	mkdir -p "/tmp/cdedb-store/foto/"
	cp test/ancillary_files/e83e5a2d36462d6810108d6a5fb556dcc6ae210a580bfe4f6211fe925e61ffbec03e425a3c06bea24333cc17797fc29b047c437ef5beb33ac0f570c6589d64f9 /tmp/cdedb-store/foto/
	mkdir -p "/tmp/cdedb-store/minor_form/"
	mkdir -p "/tmp/cdedb-store/ballot_result/"
	mkdir -p "/tmp/cdedb-store/assembly_attachment/"
	mkdir -p "/tmp/cdedb-store/testfiles/"
	cp test/ancillary_files/{picture.png,picture.jpg,form.pdf,ballot_result.json,sepapain.xml,event_export.json,batch_admission.csv,money_transfers.csv} /tmp/cdedb-store/testfiles/

ldap:
ifeq ($(wildcard /DBVM),/DBVM)
	$(error Refusing to touch live instance)
endif
	echo 'ou=personas,dc=cde-ev,dc=de' | ldapdelete -c -r -x -D `cat .ldap_rootdn` -y ${LDAP_PASSWORDFILE} || true
	echo 'ou=personas-test,dc=cde-ev,dc=de' | ldapdelete -c -r -x -D `cat .ldap_rootdn` -y ${LDAP_PASSWORDFILE} || true
	ldapadd -c -x -D `cat .ldap_rootdn` -y ${LDAP_PASSWORDFILE} -f cdedb/database/init.ldif || true
	sed -e 's/{LDAP_ORGANIZATION}/personas/' test/ancillary_files/sample_data.ldif | ldapadd -c -x -D `cat .ldap_rootdn` -y ${LDAP_PASSWORDFILE} || true
	sed -e 's/{LDAP_ORGANIZATION}/personas-test/' test/ancillary_files/sample_data.ldif | ldapadd -c -x -D `cat .ldap_rootdn` -y ${LDAP_PASSWORDFILE} || true

ldap-test:
	echo 'ou=personas-test,dc=cde-ev,dc=de' | ldapdelete -c -r -x -D `cat .ldap_rootdn` -y ${LDAP_PASSWORDFILE} || true
	ldapadd -c -x -D `cat .ldap_rootdn` -y ${LDAP_PASSWORDFILE} -f cdedb/database/init.ldif || true
	sed -e 's/{LDAP_ORGANIZATION}/personas-test/' test/ancillary_files/sample_data.ldif | ldapadd -c -x -D `cat .ldap_rootdn` -y ${LDAP_PASSWORDFILE} || true

sql:
ifeq ($(wildcard /DBVM),/DBVM)
	$(error Refusing to touch live instance)
endif
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
	@echo ""
	@echo "================================================================================"
	@echo "Lines too long in templates"
	@echo "================================================================================"
	@echo ""
	egrep -R '^.{121,}' cdedb/frontend/templates/ | grep 'tmpl:' | cat
	@echo ""
	@echo "================================================================================"
	@echo "All of pylint"
	@echo "================================================================================"
	@echo ""
	/usr/lib/python-exec/python3.5/pylint --rcfile='./lint.rc' cdedb || true
	@echo ""
	@echo "================================================================================"
	@echo "And now only errors and warnings"
	@echo "================================================================================"
	@echo ""
	/usr/lib/python-exec/python3.5/pylint --rcfile='./lint.rc' --output-format=text cdedb | egrep '^(\*\*\*\*|E:|W:)' | egrep -v "Module 'cdedb.validation' has no '[a-zA-Z_]*' member" | egrep -v "Instance of '[A-Za-z]*Config' has no '[a-zA-Z_]*' member"

check:
	make sample-data-test &> /dev/null
	rm -f /tmp/test-cdedb* /tmp/cdedb-timing.log /tmp/cdedb-mail-* || true
	[ -f cdedb/testconfig.py.off ] && mv cdedb/testconfig.py.off cdedb/testconfig.py || true
	${PYTHONBIN} -m test.main ${TESTPATTERN}
	[ -f cdedb/testconfig.py ] && mv cdedb/testconfig.py cdedb/testconfig.py.off || true

single-check:
	make sample-data-test &> /dev/null
	rm -f /tmp/test-cdedb* /tmp/cdedb-timing.log /tmp/cdedb-mail-* || true
	[ -f cdedb/testconfig.py.off ] && mv cdedb/testconfig.py.off cdedb/testconfig.py || true
	${PYTHONBIN} -m unittest ${TESTPATTERN}
	[ -f cdedb/testconfig.py ] && mv cdedb/testconfig.py cdedb/testconfig.py.off || true

quick-check:
	${PYTHONBIN} -c "from cdedb.frontend.application import Application ; Application(\"`pwd`/test/localconfig.py\")" > /dev/null

.coverage: $(wildcard cdedb/*.py) $(wildcard cdedb/database/*.py) $(wildcard cdedb/frontend/*.py) $(wildcard cdedb/backend/*.py) $(wildcard test/*.py)
	${PYTHONBIN} /usr/bin/coverage run -m test.main

coverage: .coverage
	${PYTHONBIN} /usr/bin/coverage report -m --omit='test/*,related/*'

.PHONY: help doc sample-data sample-data-test sample-data-test-shallow ldap ldap-test sql sql-test sql-test-shallow lint check single-check .coverage coverage
