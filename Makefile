SHELL := /bin/bash

.PHONY: help doc sample-data sql sql-test sql-test-shallow lint check single-check \
	.coverage coverage dump-html validate-html i18n-extract i18n-update i18n-compile i18n-refresh

help:
	@echo "doc -- build documentation"
	@echo "reload -- re-compile GNU gettext data and trigger WSGI worker reload"
	@echo "sample-data -- initialize database structures (DESTROYS DATA!)"
	@echo "sql -- initialize postgres (use sample-data instead)"
	@echo "sql-test -- initialize database structures for test suite"
	@echo "sql-test-shallow -- reset database structures for test suite"
	@echo "                    (this is a fast version of sql-test, can be substituted after that"
	@echo "                     was executed)"
	@echo "storage-test -- create STORAGE_DIR inside /tmp for tests needing this for attachments,"
	@echo "                photos etc."
	@echo "                (this should not be called by hand, but every test needing this should"
	@echo "                 get the @storage decorator)"
	@echo "lint -- run linters (mainly pylint)"
	@echo "check -- run test suite"
	@echo "         (TESTPATTERNS specifies globs to match against the testnames like '404 500' or "
	@echo "         tests.test_frontend_event.TestEventFrontend.test_create_event."
	@echo "         If TESTPATTERNS is empty, run full test suite)"
	@echo "coverage -- run coverage to determine test suite coverage"

# Binaries
PYTHONBIN ?= python3
FLAKE8 ?= $(PYTHONBIN) -m flake8
PYLINT ?= $(PYTHONBIN) -m pylint
COVERAGE ?= $(PYTHONBIN) -m coverage
MYPY ?= $(PYTHONBIN) -m mypy
ifeq ($(wildcard /CONTAINER),/CONTAINER)
	PSQL ?= $(PYTHONBIN) bin/execute_sql_script.py
else
	PSQL ?= sudo -u postgres psql
endif

# Others
TESTPREPARATION ?= automatic
TESTDATABASENAME ?= $(or ${CDEDB_TEST_DATABASE}, cdb_test)
TESTTMPDIR ?= ${CDEDB_TEST_TMP_DIR}
TESTSTORAGEPATH ?= $(TESTTMPDIR)/storage
TESTLOGPATH ?= $(TESTTMPDIR)/logs
THREADID ?= 1
I18NDIR ?= ./i18n

doc:
	bin/create_email_template_list.sh .
	$(MAKE) -C doc html

reload:
	$(MAKE) i18n-compile
ifeq ($(wildcard /CONTAINER),/CONTAINER)
	apachectl restart
else
	sudo systemctl restart apache2
endif

i18n-refresh:
	$(MAKE) i18n-extract
	$(MAKE) i18n-update

i18n-extract:
	pybabel extract --msgid-bugs-address="cdedb@lists.cde-ev.de" \
		--mapping=./babel.cfg --keywords="rs.gettext rs.ngettext n_" \
		--output=$(I18NDIR)/cdedb.pot --input-dirs=.

i18n-update:
	msgmerge --lang=de --update $(I18NDIR)/de/LC_MESSAGES/cdedb.po $(I18NDIR)/cdedb.pot
	msgmerge --lang=en --update $(I18NDIR)/en/LC_MESSAGES/cdedb.po $(I18NDIR)/cdedb.pot
	msgattrib --no-obsolete --sort-by-file -o $(I18NDIR)/de/LC_MESSAGES/cdedb.po \
		$(I18NDIR)/de/LC_MESSAGES/cdedb.po
	msgattrib --no-obsolete --sort-by-file -o $(I18NDIR)/en/LC_MESSAGES/cdedb.po \
		$(I18NDIR)/en/LC_MESSAGES/cdedb.po
	# TODO: do we want to use msgattribs --indent option for prettier po files?

i18n-compile:
	msgfmt --verbose --check --statistics -o $(I18NDIR)/de/LC_MESSAGES/cdedb.mo \
		$(I18NDIR)/de/LC_MESSAGES/cdedb.po
	msgfmt --verbose --check --statistics -o $(I18NDIR)/en/LC_MESSAGES/cdedb.mo \
		$(I18NDIR)/en/LC_MESSAGES/cdedb.po

sample-data:
	cp -f related/auto-build/files/stage3/localconfig.py cdedb/localconfig.py
	$(MAKE) storage > /dev/null
	$(MAKE) sql > /dev/null

sample-data-dump:
	JSONTEMPFILE=`sudo -u www-data mktemp` \
		&& sudo -u www-data chmod +r "$${JSONTEMPFILE}" \
		&& sudo -u www-data $(PYTHONBIN) tests/create_sample_data_json.py -o "$${JSONTEMPFILE}" \
		&& cp "$${JSONTEMPFILE}" tests/ancillary_files/sample_data.json \
		&& sudo -u www-data rm "$${JSONTEMPFILE}"

sample-data-xss:
	cp -f related/auto-build/files/stage3/localconfig.py cdedb/localconfig.py
	$(MAKE) storage
	$(MAKE) sql-xss

TESTFOTONAME := e83e5a2d36462d6810108d6a5fb556dcc6ae210a580bfe4f6211fe925e6$\
		1ffbec03e425a3c06bea24333cc17797fc29b047c437ef5beb33ac0f570$\
		c6589d64f9
storage:
ifeq ($(wildcard /PRODUCTIONVM),/PRODUCTIONVM)
	$(error Refusing to touch live instance)
endif
ifeq ($(wildcard /OFFLINEVM),/OFFLINEVM)
	$(error Refusing to touch orga instance)
endif
	sudo rm -rf -- /var/lib/cdedb/*
	sudo mkdir /var/lib/cdedb/foto/
	sudo mkdir /var/lib/cdedb/minor_form/
	sudo mkdir /var/lib/cdedb/event_logo/
	sudo mkdir /var/lib/cdedb/course_logo/
	sudo mkdir /var/lib/cdedb/ballot_result/
	sudo mkdir /var/lib/cdedb/assembly_attachment/
	sudo mkdir /var/lib/cdedb/mailman_templates/
	sudo mkdir /var/lib/cdedb/genesis_attachment/
	sudo cp tests/ancillary_files/$(TESTFOTONAME) /var/lib/cdedb/foto/
	sudo cp tests/ancillary_files/rechen.pdf \
		/var/lib/cdedb/assembly_attachment/1_v1
	sudo cp tests/ancillary_files/kassen.pdf \
		/var/lib/cdedb/assembly_attachment/2_v1
	sudo cp tests/ancillary_files/kassen2.pdf \
		/var/lib/cdedb/assembly_attachment/2_v3
	sudo cp tests/ancillary_files/kandidaten.pdf \
		/var/lib/cdedb/assembly_attachment/3_v1
	sudo chown --recursive www-data:www-data /var/lib/cdedb

TESTFILES := picture.pdf,picture.png,picture.jpg,form.pdf$\
		,ballot_result.json,sepapain.xml,event_export.json$\
		,batch_admission.csv,money_transfers.csv$\
		,money_transfers_valid.csv,partial_event_import.json$\
		,TestAka_partial_export_event.json,statement.csv

storage-test:
	rm -rf -- ${TESTSTORAGEPATH}/*
	mkdir -p ${TESTSTORAGEPATH}/foto/
	mkdir -p ${TESTSTORAGEPATH}/minor_form/
	mkdir -p ${TESTSTORAGEPATH}/event_logo/
	mkdir -p ${TESTSTORAGEPATH}/course_logo/
	mkdir -p ${TESTSTORAGEPATH}/ballot_result/
	mkdir -p ${TESTSTORAGEPATH}/assembly_attachment/
	mkdir -p ${TESTSTORAGEPATH}/genesis_attachment/
	mkdir -p ${TESTSTORAGEPATH}/mailman_templates/
	mkdir -p ${TESTSTORAGEPATH}/testfiles/
	cp tests/ancillary_files/$(TESTFOTONAME) ${TESTSTORAGEPATH}/foto/
	cp tests/ancillary_files/rechen.pdf ${TESTSTORAGEPATH}/assembly_attachment/1_v1
	cp tests/ancillary_files/kassen.pdf ${TESTSTORAGEPATH}/assembly_attachment/2_v1
	cp tests/ancillary_files/kassen2.pdf ${TESTSTORAGEPATH}/assembly_attachment/2_v3
	cp tests/ancillary_files/kandidaten.pdf ${TESTSTORAGEPATH}/assembly_attachment/3_v1
	cp -t ${TESTSTORAGEPATH}/testfiles/ tests/ancillary_files/{$(TESTFILES)}

sql: tests/ancillary_files/sample_data.sql
ifeq ($(wildcard /PRODUCTIONVM),/PRODUCTIONVM)
	$(error Refusing to touch live instance)
endif
ifeq ($(wildcard /OFFLINEVM),/OFFLINEVM)
	$(error Refusing to touch orga instance)
endif
ifeq ($(wildcard /CONTAINER),/CONTAINER)
	# We need to use psql directly as DROP DATABASE and variables are not supported by our helper
	psql postgresql://postgres:passwd@cdb -f cdedb/database/cdedb-users.sql
	psql postgresql://postgres:passwd@cdb -f cdedb/database/cdedb-db.sql -v cdb_database_name=cdb
	psql postgresql://postgres:passwd@cdb -f cdedb/database/cdedb-db.sql \
		-v cdb_database_name=${TESTDATABASENAME}
else
	sudo systemctl stop pgbouncer
	$(PSQL) -f cdedb/database/cdedb-users.sql
	$(PSQL) -f cdedb/database/cdedb-db.sql -v cdb_database_name=cdb
	$(PSQL) -f cdedb/database/cdedb-db.sql -v cdb_database_name=${TESTDATABASENAME}
	sudo systemctl start pgbouncer
endif
	$(PSQL) -f cdedb/database/cdedb-tables.sql --dbname=cdb
	$(PSQL) -f cdedb/database/cdedb-tables.sql --dbname=${TESTDATABASENAME}
	$(PSQL) -f tests/ancillary_files/sample_data.sql --dbname=cdb
	$(PSQL) -f tests/ancillary_files/sample_data.sql --dbname=${TESTDATABASENAME}

sql-test:
ifeq ($(wildcard /CONTAINER),/CONTAINER)
	psql postgresql://postgres:passwd@cdb -f cdedb/database/cdedb-db.sql \
		-v cdb_database_name=${TESTDATABASENAME}
else
	sudo systemctl stop pgbouncer
	$(PSQL) -f cdedb/database/cdedb-db.sql -v cdb_database_name=${TESTDATABASENAME}
	sudo systemctl start pgbouncer
endif
	$(PSQL) -f cdedb/database/cdedb-tables.sql --dbname=${TESTDATABASENAME}
	$(MAKE) sql-test-shallow

sql-test-shallow: tests/ancillary_files/sample_data.sql
	$(PSQL) -f tests/ancillary_files/clean_data.sql --dbname=${TESTDATABASENAME}
	$(PSQL) -f tests/ancillary_files/sample_data.sql --dbname=${TESTDATABASENAME}

sql-xss: tests/ancillary_files/sample_data_xss.sql
ifeq ($(wildcard /PRODUCTIONVM),/PRODUCTIONVM)
	$(error Refusing to touch live instance)
endif
ifeq ($(wildcard /OFFLINEVM),/OFFLINEVM)
	$(error Refusing to touch orga instance)
endif
ifeq ($(wildcard /CONTAINER),/CONTAINER)
	# We need to use psql directly as DROP DATABASE and variables are not supported by our helper
	psql postgresql://postgres:passwd@cdb -f cdedb/database/cdedb-db.sql -v cdb_database_name=cdb
	psql postgresql://postgres:passwd@cdb -f cdedb/database/cdedb-db.sql \
		-v cdb_database_name=${TESTDATABASENAME}
else
	sudo systemctl stop pgbouncer
	$(PSQL) -f cdedb/database/cdedb-db.sql -v cdb_database_name=cdb
	$(PSQL) -f cdedb/database/cdedb-db.sql -v cdb_database_name=${TESTDATABASENAME}
	sudo systemctl start pgbouncer
endif
	$(PSQL) -f cdedb/database/cdedb-tables.sql --dbname=cdb
	$(PSQL) -f cdedb/database/cdedb-tables.sql --dbname=${TESTDATABASENAME}
	$(PSQL) -f tests/ancillary_files/sample_data_xss.sql --dbname=cdb
	$(PSQL) -f tests/ancillary_files/sample_data_xss.sql --dbname=${TESTDATABASENAME}

cron:
	sudo -u www-data /cdedb2/bin/cron_execute.py

BANNERLINE := "============================================================$\
		===================="
lint:
	@echo $(BANNERLINE)
	@echo "Lines too long in templates"
	@echo $(BANNERLINE)
	@echo ""
	grep -E -R '^.{121,}' cdedb/frontend/templates/ | grep 'tmpl:'
	@echo ""
	@echo $(BANNERLINE)
	@echo "All of flake8"
	@echo $(BANNERLINE)
	@echo ""
	$(FLAKE8) cdedb
	@echo ""
	@echo $(BANNERLINE)
	@echo "All of pylint"
	@echo $(BANNERLINE)
	@echo ""
	$(PYLINT) cdedb


prepare-check:
ifneq ($(TESTPREPARATION), manual)
	mkdir -p $(TESTTMPDIR)
	sudo rm -rf $(TESTLOGPATH)  /tmp/cdedb-mail-* \
		|| true
	mkdir $(TESTLOGPATH)
	$(MAKE) i18n-compile
	$(MAKE) sql-test
else
	@echo "Omitting test preparation."
endif

check-parallel:
	# TODO: move this logic into tests/check.py
	# TODO: using inverse regex arguments possible? Would be helpful for not overlooking some tests
	# sleeping is necessary here that the i18n-refresh runs at the very beginning to not interfere
	$(PYTHONBIN) -m tests.check --thread_id 2 \
		test_backend test_common test_config test_database test_offline test_script test_session \
		test_validation test_vote_verification & \
	sleep 0.5; \
	$(PYTHONBIN) -m tests.check --thread_id 4 \
		frontend_event frontend_ml frontend_privacy frontend_parse & \
	sleep 0.5; \
	$(PYTHONBIN) -m tests.check --thread_id 3 \
		frontend_application frontend_assembly frontend_common frontend_core frontend_cde \
		frontend_cron

check:
	$(PYTHONBIN) -m tests.check --thread_id $(THREADID) $(or $(TESTPATTERNS), )

xss-check:
	$(PYTHONBIN) -m tests.check --thread_id $(THREADID) --xss-check

dump-html: export SCRAP_ENCOUNTERED_PAGES=1
dump-html:
	$(PYTHONBIN) -m tests.check --thread_id $(THREADID) test_frontend


validate-html: /opt/validator/vnu-runtime-image/bin/vnu
	/opt/validator/vnu-runtime-image/bin/vnu /tmp/tmp* 2>&1 \
		| grep -v -F 'This document appears to be written in English' \
		| grep -v -F 'input type is not supported in all browsers'

/opt/validator/vnu-runtime-image/bin/vnu: /opt/validator/vnu.linux.zip
	unzip -DD /opt/validator/vnu.linux.zip -d /opt/validator

VALIDATORURL := "https://github.com/validator/validator/releases/download/$\
		20.3.16/vnu.linux.zip"
VALIDATORCHECKSUM := "c7d8d7c925dbd64fd5270f7b81a56f526e6bbef0 $\
		/opt/validator/vnu.linux.zip"
/opt/validator/vnu.linux.zip: /opt/validator
	wget $(VALIDATORURL) -O /opt/validator/vnu.linux.zip
	echo $(VALIDATORCHECKSUM) | sha1sum -c -
	touch /opt/validator/vnu.linux.zip # refresh downloaded timestamp

/opt/validator:
	sudo mkdir /opt/validator
	sudo chown cdedb:cdedb /opt/validator


.coverage: $(wildcard cdedb/*.py) $(wildcard cdedb/database/*.py) \
		$(wildcard cdedb/frontend/*.py) \
		$(wildcard cdedb/backend/*.py) $(wildcard tests/*.py)
	$(COVERAGE) run -m tests.check --thread_id $(THREADID)

coverage: .coverage
	$(COVERAGE) report --include 'cdedb/*' --show-missing
	$(COVERAGE) html --include 'cdedb/*'
	@echo "HTML reports for easier inspection are in ./htmlcov"

tests/ancillary_files/sample_data.sql: tests/ancillary_files/sample_data.json \
		tests/create_sample_data_sql.py cdedb/database/cdedb-tables.sql
	SQLTEMPFILE=`sudo -u www-data mktemp` \
		&& sudo -u www-data chmod +r "$${SQLTEMPFILE}" \
		&& sudo -u www-data $(PYTHONBIN) \
			tests/create_sample_data_sql.py \
			-i tests/ancillary_files/sample_data.json \
			-o "$${SQLTEMPFILE}" \
		&& cp "$${SQLTEMPFILE}" tests/ancillary_files/sample_data.sql \
		&& sudo -u www-data rm "$${SQLTEMPFILE}"

tests/ancillary_files/sample_data_xss.sql: tests/ancillary_files/sample_data.json \
		tests/create_sample_data_sql.py cdedb/database/cdedb-tables.sql
	SQLTEMPFILE=`sudo -u www-data mktemp` \
		&& sudo -u www-data chmod +r "$${SQLTEMPFILE}" \
		&& sudo -u www-data $(PYTHONBIN) \
			tests/create_sample_data_sql.py \
			-i tests/ancillary_files/sample_data.json \
			-o "$${SQLTEMPFILE}" \
			--xss \
		&& cp "$${SQLTEMPFILE}" tests/ancillary_files/sample_data_xss.sql \
		&& sudo -u www-data rm "$${SQLTEMPFILE}"

mypy:
	$(MYPY) bin cdedb tests
