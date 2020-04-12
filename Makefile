SHELL := /bin/bash

help:
	@echo "doc -- build documentation"
	@echo "reload -- re-compile GNU gettext data and trigger WSGI worker reload"
	@echo "sample-data -- initialize database structures (DESTROYES DATA!)"
	@echo "sample-data-test -- initialize database structures for test suite"
	@echo "sample-data-test-shallow -- initialize database structures for test suite"
	@echo "                            (this is a fast version of sample-data-test,"
	@echo "                             can be substituted after sample-data-test was"
	@echo "                             executed)"
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
PYLINTBIN ?= pylint3
TESTPATTERN ?=

doc:
	bin/create_email_template_list.sh .
	make -C doc html

reload:
	make i18n-compile
	sudo systemctl restart apache2

i18n-refresh:
	pybabel extract -F ./babel.cfg -k "rs.gettext" -k "rs.ngettext" -k "n_" -o ./i18n/cdedb.pot .
	pybabel update -i ./i18n/cdedb.pot -d ./i18n/ -l de -D cdedb
	pybabel update -i ./i18n/cdedb.pot -d ./i18n/ -l en -D cdedb

i18n-compile:
	pybabel compile -d ./i18n/ -l de -D cdedb
	pybabel compile -d ./i18n/ -l en -D cdedb

sample-data:
	make storage > /dev/null
	make sql > /dev/null
	cp -f related/auto-build/files/stage3/localconfig.py cdedb/localconfig.py

sample-data-test:
	make storage-test
	make sql-test

sample-data-test-shallow:
	make storage-test
	make sql-test-shallow

sample-data-xss:
	make sql-xss

storage:
ifeq ($(wildcard /PRODUCTIONVM),/PRODUCTIONVM)
	$(error Refusing to touch live instance)
endif
ifeq ($(wildcard /OFFLINEVM),/OFFLINEVM)
	$(error Refusing to touch orga instance)
endif
	sudo rm -rf "/var/lib/cdedb/"
	sudo mkdir -p "/var/lib/cdedb/foto/"
	sudo mkdir -p "/var/lib/cdedb/minor_form/"
	sudo mkdir -p "/var/lib/cdedb/event_logo/"
	sudo mkdir -p "/var/lib/cdedb/course_logo/"
	sudo mkdir -p "/var/lib/cdedb/ballot_result/"
	sudo mkdir -p "/var/lib/cdedb/assembly_attachment/"
	sudo mkdir -p "/var/lib/cdedb/mailman_templates/"
	sudo mkdir -p "/var/lib/cdedb/genesis_attachment/"
	sudo cp test/ancillary_files/e83e5a2d36462d6810108d6a5fb556dcc6ae210a580bfe4f6211fe925e61ffbec03e425a3c06bea24333cc17797fc29b047c437ef5beb33ac0f570c6589d64f9 /var/lib/cdedb/foto/
	sudo chown --recursive www-data:www-data /var/lib/cdedb

storage-test:
	rm -rf "/tmp/cdedb-store/"
	mkdir -p "/tmp/cdedb-store/foto/"
	cp test/ancillary_files/e83e5a2d36462d6810108d6a5fb556dcc6ae210a580bfe4f6211fe925e61ffbec03e425a3c06bea24333cc17797fc29b047c437ef5beb33ac0f570c6589d64f9 /tmp/cdedb-store/foto/
	mkdir -p "/tmp/cdedb-store/minor_form/"
	mkdir -p "/tmp/cdedb-store/event_logo/"
	mkdir -p "/tmp/cdedb-store/course_logo/"
	mkdir -p "/tmp/cdedb-store/ballot_result/"
	mkdir -p "/tmp/cdedb-store/assembly_attachment/"
	mkdir -p "/tmp/cdedb-store/genesis_attachment/"
	mkdir -p "/tmp/cdedb-store/mailman_templates/"
	mkdir -p "/tmp/cdedb-store/testfiles/"
	cp test/ancillary_files/{picture.pdf,picture.png,picture.jpg,form.pdf,ballot_result.json,sepapain.xml,event_export.json,batch_admission.csv,money_transfers.csv,money_transfers_valid.csv,partial_event_import.json} /tmp/cdedb-store/testfiles/

sql: test/ancillary_files/sample_data.sql
ifeq ($(wildcard /PRODUCTIONVM),/PRODUCTIONVM)
	$(error Refusing to touch live instance)
endif
ifeq ($(wildcard /OFFLINEVM),/OFFLINEVM)
	$(error Refusing to touch orga instance)
endif
	sudo systemctl stop pgbouncer
	sudo -u postgres psql -U postgres -f cdedb/database/cdedb-users.sql
	sudo -u postgres psql -U postgres -f cdedb/database/cdedb-db.sql -v cdb_database_name=cdb
	sudo -u postgres psql -U postgres -f cdedb/database/cdedb-db.sql -v cdb_database_name=cdb_test
	sudo -u cdb psql -U cdb -d cdb -f cdedb/database/cdedb-tables.sql
	sudo -u cdb psql -U cdb -d cdb_test -f cdedb/database/cdedb-tables.sql
	sudo -u cdb psql -U cdb -d cdb -f test/ancillary_files/sample_data.sql
	sudo -u cdb psql -U cdb -d cdb_test -f test/ancillary_files/sample_data.sql
	sudo systemctl start pgbouncer

sql-test:
	sudo systemctl stop pgbouncer
	sudo -u postgres psql -U postgres -f cdedb/database/cdedb-db.sql -v cdb_database_name=cdb_test
	sudo -u cdb psql -U cdb -d cdb_test -f cdedb/database/cdedb-tables.sql
	make sql-test-shallow
	sudo systemctl start pgbouncer

sql-test-shallow: test/ancillary_files/sample_data.sql
	sudo -u cdb psql -U cdb -d cdb_test -f test/ancillary_files/clean_data.sql
	sudo -u cdb psql -U cdb -d cdb_test -f test/ancillary_files/sample_data.sql

sql-xss:
ifeq ($(wildcard /PRODUCTIONVM),/PRODUCTIONVM)
	$(error Refusing to touch live instance)
endif
ifeq ($(wildcard /OFFLINEVM),/OFFLINEVM)
	$(error Refusing to touch orga instance)
endif
	sudo systemctl stop pgbouncer
	sudo -u postgres psql -U postgres -f cdedb/database/cdedb-users.sql
	sudo -u postgres psql -U postgres -f cdedb/database/cdedb-db.sql -v cdb_database_name=cdb
	sudo -u postgres psql -U postgres -f cdedb/database/cdedb-db.sql -v cdb_database_name=cdb_test
	sudo -u cdb psql -U cdb -d cdb -f cdedb/database/cdedb-tables.sql
	sudo -u cdb psql -U cdb -d cdb_test -f cdedb/database/cdedb-tables.sql
	sudo -u cdb psql -U cdb -d cdb -f test/ancillary_files/sample_data_escaping.sql
	sudo -u cdb psql -U cdb -d cdb_test -f test/ancillary_files/sample_data_escaping.sql
	sudo systemctl start pgbouncer

cron:
	sudo -u www-data /cdedb2/bin/cron_execute.py

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
	${PYLINTBIN} --rcfile='./lint.rc' cdedb || true
	@echo ""
	@echo "================================================================================"
	@echo "And now only errors and warnings"
	@echo "================================================================================"
	@echo ""
	${PYLINTBIN} --rcfile='./lint.rc' --output-format=text cdedb | egrep '^(\*\*\*\*|E:|W:)' | egrep -v "Module 'cdedb.validation' has no '[a-zA-Z_]*' member" | egrep -v "Instance of '[A-Za-z]*Config' has no '[a-zA-Z_]*' member"

check:
	make i18n-compile
	make sample-data-test &> /dev/null
	sudo rm -f /tmp/test-cdedb* /tmp/cdedb-timing.log /tmp/cdedb-mail-* || true
	[ -f cdedb/testconfig.py.off ] && mv cdedb/testconfig.py.off cdedb/testconfig.py || true
	${PYTHONBIN} -m test.main ${TESTPATTERN}
	[ -f cdedb/testconfig.py ] && mv cdedb/testconfig.py cdedb/testconfig.py.off || true

single-check:
	make i18n-compile
	make sample-data-test &> /dev/null
	sudo rm -f /tmp/test-cdedb* /tmp/cdedb-timing.log /tmp/cdedb-mail-* || true
	[ -f cdedb/testconfig.py.off ] && mv cdedb/testconfig.py.off cdedb/testconfig.py || true
	${PYTHONBIN} -m unittest ${TESTPATTERN}
	[ -f cdedb/testconfig.py ] && mv cdedb/testconfig.py cdedb/testconfig.py.off || true

new-single-check:
	make i18n-compile
	make sample-data-test &> /dev/null
	sudo rm -f /tmp/test-cdedb* /tmp/cdedb-timing.log /tmp/cdedb-mail-* || true
	[ -f cdedb/testconfig.py.off ] && mv cdedb/testconfig.py.off cdedb/testconfig.py || true
	${PYTHONBIN} -m test.singular "${TESTNAME}" "${TESTFILE}"
	[ -f cdedb/testconfig.py ] && mv cdedb/testconfig.py cdedb/testconfig.py.off || true

xss-check:
	make sample-data-test &>/dev/null
	sudo -u cdb psql -U cdb -d cdb_test -f test/ancillary_files/clean_data.sql &>/dev/null
	sudo -u cdb psql -U cdb -d cdb_test -f test/ancillary_files/sample_data_escaping.sql &>/dev/null
	[ -f cdedb/testconfig.py.off ] && mv cdedb/testconfig.py.off cdedb/testconfig.py || true
	${PYTHONBIN} -m bin.escape_fuzzing 2>/dev/null
	[ -f cdedb/testconfig.py ] && mv cdedb/testconfig.py cdedb/testconfig.py.off || true

dump-html:
	var SCRAP_ENCOUNTERED_PAGES=1 TESTPATTERN=test_frontend make check

validate-html: /opt/validator/vnu-runtime-image/bin/vnu
	/opt/validator/vnu-runtime-image/bin/vnu /tmp/tmp* 2>&1 \
		| grep -v -F 'This document appears to be written in English' \
		| grep -v -F 'input type is not supported in all browsers' \

/opt/validator/vnu-runtime-image/bin/vnu: /opt/validator/vnu.linux.zip
	unzip -D /opt/validator/vnu.linux.zip -d /opt/validator

/opt/validator/vnu.linux.zip: /opt/validator
	wget 'https://github.com/validator/validator/releases/download/20.3.16/vnu.linux.zip' -O /opt/validator/vnu.linux.zip
	echo "c7d8d7c925dbd64fd5270f7b81a56f526e6bbef0 /opt/validator/vnu.linux.zip" | sha1sum -c -
	touch /opt/validator/vnu.linux.zip # refresh downloaded timestamp

/opt/validator:
	sudo mkdir /opt/validator
	sudo chown cdedb:cdedb /opt/validator

quick-check:
	${PYTHONBIN} -c "from cdedb.frontend.application import Application ; Application(\"`pwd`/test/localconfig.py\")" > /dev/null

.coverage: $(wildcard cdedb/*.py) $(wildcard cdedb/database/*.py) $(wildcard cdedb/frontend/*.py) $(wildcard cdedb/backend/*.py) $(wildcard test/*.py)
	${PYTHONBIN} /usr/bin/coverage run -m test.main

coverage: .coverage
	${PYTHONBIN} /usr/bin/coverage report -m --omit='test/*,related/*'

.PHONY: help doc sample-data sample-data-test sample-data-test-shallow sql sql-test sql-test-shallow lint \
	check single-check .coverage coverage dump-html validate-html

test/ancillary_files/sample_data.sql: test/ancillary_files/sample_data.json test/create_sample_data_sql.py
	SQLTEMPFILE=`sudo -u www-data mktemp` \
		&& sudo -u www-data chmod +r "$${SQLTEMPFILE}" \
		&& sudo -u www-data ${PYTHONBIN} test/create_sample_data_sql.py \
			-i test/ancillary_files/sample_data.json -o "$${SQLTEMPFILE}" \
		&& cp "$${SQLTEMPFILE}" test/ancillary_files/sample_data.sql \
		&& sudo -u www-data rm "$${SQLTEMPFILE}"
