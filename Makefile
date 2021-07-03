SHELL := /bin/bash

.PHONY: help doc reload i18n-refresh i18n-extract i18n-update i18n-compile sample-data \
	sample-data-dump storage storage-test sql sql-test sql-test-shallow cron mypy flake8 pylint \
	template-line-length lint prepare-check check check-parallel sql-xss xss-check dump-html \
	validate-html .coverage coverage

help:
	@echo "General:"
	@echo "doc          -- build documentation"
	@echo "reload       -- re-compile GNU gettext data and trigger WSGI worker reload"
	@echo "i18n-refresh -- extract translatable strings from code and update translation catalogs"
	@echo ""
	@echo "Database and storage:"
	@echo "sample-data      -- initialize database structures (DESTROYS DATA!)"
	@echo "sample-data-dump -- dump current database state into json file in tests directory"
	@echo "sql              -- initialize postgres (use sample-data instead)"
	@echo "sql-test         -- initialize database structures for test suite"
	@echo "sql-test-shallow -- reset database structures for test suite"
	@echo "                    (this is a fast version of sql-test, can be substituted after that"
	@echo "                        was executed)"
	@echo "storage          -- (re)create storage directory in /var/lib/cdedb"
	@echo "storage-test     -- create storage directory inside /tmp for tests needing this for"
	@echo "                    attachments, photos etc."
	@echo "                    (this should not be called by hand, but every test needing this"
	@echo "                        should get the @storage decorator)"
	@echo "cron             -- trigger cronjob execution (as user www-data)"
	@echo ""
	@echo "Code testing:"
	@echo "mypy           -- let mypy run over our codebase (bin, cdedb, tests)"
	@echo "lint           -- run linters (flake8 and pylint)"
	@echo "check          -- run (parts of the) test suite"
	@echo "                  (TESTPATTERNS specifies globs to match against the testnames like"
	@echo "                      '404 500' or tests.test_frontend_event.TestEventFrontend.test_show_event"
	@echo "                      If TESTPATTERNS is empty, run full test suite)"
	@echo "check-parallel -- run full test suite using multiple CPU cores/threads"
	@echo "                  (beta, not stable yet!)"
	@echo "xss-check      -- check for xss vulnerabilities"
	@echo "dump-html      -- run frontend tests and store all encountered pages inside"
	@echo "                  /tmp/cdedb-dump/"
	@echo "validate-html  -- run html validator over the dumped frontend pages "
	@echo "                  (dump-html is executed before if they do not exist yet)"
	@echo "coverage       -- run coverage to determine test suite coverage"

# Executables
PYTHONBIN ?= python3
FLAKE8 ?= $(PYTHONBIN) -m flake8
PYLINT ?= $(PYTHONBIN) -m pylint
COVERAGE ?= $(PYTHONBIN) -m coverage
MYPY ?= $(PYTHONBIN) -m mypy
ifeq ($(wildcard /CONTAINER),/CONTAINER)
# We need to use psql directly as DROP DATABASE and variables are not supported by our helper
	PSQL_ADMIN ?= psql postgresql://postgres:passwd@cdb
	PSQL ?= $(PYTHONBIN) bin/execute_sql_script.py
else
	PSQL_ADMIN ?= sudo -u postgres psql
	PSQL ?= sudo -u cdb psql
endif
SAMPLE_DATA_SQL ?= bin/create_sample_data_sql.py

# Others
TESTPREPARATION ?= automatic
TESTDATABASENAME ?= $(or ${CDEDB_TEST_DATABASE}, cdb_test)
TESTTMPDIR ?= $(or ${CDEDB_TEST_TMP_DIR}, /tmp/cdedb-test-default )
TESTSTORAGEPATH ?= $(TESTTMPDIR)/storage
TESTLOGPATH ?= $(TESTTMPDIR)/logs
XSS_PAYLOAD ?= $(or ${CDEDB_TEST_XSS_PAYLOAD}, <script>abcdef</script>)
I18NDIR ?= ./i18n


###########
# General #
###########

doc:
	bin/create_email_template_list.sh .
	$(MAKE) -C doc html

ldap-reset-sql:
	systemctl stop slapd.service \
    && rm /etc/ldap/slapd.d/cn\=config/*Database*sql* \
    && systemctl start slapd.service

ldap-reset:
	apt remove --purge -y slapd \
    && apt install -y slapd

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
		--output=$(I18NDIR)/cdedb.pot --input-dirs="bin,cdedb"

i18n-update:
	msgmerge --lang=de --update $(I18NDIR)/de/LC_MESSAGES/cdedb.po $(I18NDIR)/cdedb.pot
	msgmerge --lang=en --update $(I18NDIR)/en/LC_MESSAGES/cdedb.po $(I18NDIR)/cdedb.pot
	msgmerge --lang=la --update $(I18NDIR)/la/LC_MESSAGES/cdedb.po $(I18NDIR)/cdedb.pot
	msgattrib --no-obsolete --sort-by-file -o $(I18NDIR)/de/LC_MESSAGES/cdedb.po \
		$(I18NDIR)/de/LC_MESSAGES/cdedb.po
	msgattrib --no-obsolete --sort-by-file -o $(I18NDIR)/en/LC_MESSAGES/cdedb.po \
		$(I18NDIR)/en/LC_MESSAGES/cdedb.po
	msgattrib --no-obsolete --sort-by-file -o $(I18NDIR)/la/LC_MESSAGES/cdedb.po \
		$(I18NDIR)/la/LC_MESSAGES/cdedb.po
	# TODO: do we want to use msgattribs --indent option for prettier po files?

i18n-compile:
	msgfmt --verbose --check --statistics -o $(I18NDIR)/de/LC_MESSAGES/cdedb.mo \
		$(I18NDIR)/de/LC_MESSAGES/cdedb.po
	msgfmt --verbose --check --statistics -o $(I18NDIR)/en/LC_MESSAGES/cdedb.mo \
		$(I18NDIR)/en/LC_MESSAGES/cdedb.po
	msgfmt --verbose --check --statistics -o $(I18NDIR)/la/LC_MESSAGES/cdedb.mo \
		$(I18NDIR)/la/LC_MESSAGES/cdedb.po


########################
# Database and storage #
########################

sample-data:
	cp -f related/auto-build/files/stage3/localconfig.py cdedb/localconfig.py
	$(MAKE) storage > /dev/null
	$(MAKE) sql > /dev/null

sample-data-dump:
	JSONTEMPFILE=`sudo -u www-data mktemp` \
		&& sudo -u www-data chmod +r "$${JSONTEMPFILE}" \
		&& sudo -u www-data $(PYTHONBIN) bin/create_sample_data_json.py -o "$${JSONTEMPFILE}" \
		&& cp "$${JSONTEMPFILE}" tests/ancillary_files/sample_data.json \
		&& sudo -u www-data rm "$${JSONTEMPFILE}"

TESTFOTONAME := e83e5a2d36462d6810108d6a5fb556dcc6ae210a580bfe4f6211fe925e61ffbec03e425a3c06bea243$\
		33cc17797fc29b047c437ef5beb33ac0f570c6589d64f9

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
	sudo cp tests/ancillary_files/rechen.pdf /var/lib/cdedb/assembly_attachment/1_v1
	sudo cp tests/ancillary_files/kassen.pdf /var/lib/cdedb/assembly_attachment/2_v1
	sudo cp tests/ancillary_files/kassen2.pdf /var/lib/cdedb/assembly_attachment/2_v3
	sudo cp tests/ancillary_files/kandidaten.pdf /var/lib/cdedb/assembly_attachment/3_v1
	sudo chown --recursive www-data:www-data /var/lib/cdedb

TESTFILES := picture.pdf,picture.png,picture.jpg,form.pdf,ballot_result.json,sepapain.xml$\
		,event_export.json,batch_admission.csv,money_transfers.csv,money_transfers_valid.csv$\
		,partial_event_import.json,TestAka_partial_export_event.json,statement.csv

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
ifneq ($(wildcard /CONTAINER),/CONTAINER)
	sudo systemctl stop pgbouncer
endif
	$(PSQL_ADMIN) -f cdedb/database/cdedb-users.sql
	$(PSQL_ADMIN) -f cdedb/database/cdedb-db.sql -v cdb_database_name=cdb
ifneq ($(wildcard /CONTAINER),/CONTAINER)
	sudo systemctl start pgbouncer
endif
	$(PSQL) -f cdedb/database/cdedb-tables.sql --dbname=cdb
	$(PSQL) -f cdedb/database/cdedb-ldap.sql --dbname=cdb
	$(PSQL) -f tests/ancillary_files/sample_data.sql --dbname=cdb

sql-test:
ifneq ($(wildcard /CONTAINER),/CONTAINER)
	sudo systemctl stop pgbouncer
endif
	$(PSQL_ADMIN) -f cdedb/database/cdedb-db.sql -v cdb_database_name=${TESTDATABASENAME}
ifneq ($(wildcard /CONTAINER),/CONTAINER)
	sudo systemctl start pgbouncer
endif
	$(PSQL) -f cdedb/database/cdedb-tables.sql --dbname=${TESTDATABASENAME}
	$(PSQL) -f cdedb/database/cdedb-ldap.sql --dbname=${TESTDATABASENAME}
	$(MAKE) sql-test-shallow

sql-test-shallow: tests/ancillary_files/sample_data.sql
	$(PSQL) -f tests/ancillary_files/clean_data.sql --dbname=${TESTDATABASENAME}
	$(PSQL) -f tests/ancillary_files/sample_data.sql --dbname=${TESTDATABASENAME}

cron:
	sudo -u www-data /cdedb2/bin/cron_execute.py


################
# Code testing #
################

mypy:
	$(MYPY) bin cdedb tests

BANNERLINE := "================================================================================"

flake8:
	@echo $(BANNERLINE)
	@echo "All of flake8"
	@echo $(BANNERLINE)
	@echo ""
	$(FLAKE8) cdedb

pylint:
	@echo $(BANNERLINE)
	@echo "All of pylint"
	@echo $(BANNERLINE)
	@echo ""
	$(PYLINT) cdedb --load-plugins=pylint.extensions.bad_builtin

template-line-length:
	@echo $(BANNERLINE)
	@echo "Lines too long in templates"
	@echo $(BANNERLINE)
	@echo ""
	grep -E -R '^.{121,}' cdedb/frontend/templates/ | grep 'tmpl:'

lint: flake8 pylint

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
	# TODO: move this logic into bin/check.py
	# TODO: using inverse regex arguments possible? Would be helpful for not overlooking some tests
	# sleeping is necessary here that the i18n-refresh runs at the very beginning to not interfere
	$(PYTHONBIN) -m bin.check \
		test_backend test_common test_config test_database test_offline test_script test_session \
		test_validation test_vote_verification & \
	sleep 0.5; \
	$(PYTHONBIN) -m bin.check \
		frontend_event frontend_ml frontend_privacy frontend_parse & \
	sleep 0.5; \
	$(PYTHONBIN) -m bin.check \
		frontend_application frontend_assembly frontend_common frontend_core frontend_cde \
		frontend_cron

check:
	$(PYTHONBIN) -m bin.check $(or $(TESTPATTERNS), )

sql-xss: tests/ancillary_files/sample_data_xss.sql
ifneq ($(wildcard /CONTAINER),/CONTAINER)
	sudo systemctl stop pgbouncer
endif
	$(PSQL_ADMIN) -f cdedb/database/cdedb-db.sql -v cdb_database_name=${TESTDATABASENAME}
ifneq ($(wildcard /CONTAINER),/CONTAINER)
	sudo systemctl start pgbouncer
endif
	$(PSQL) -f cdedb/database/cdedb-tables.sql --dbname=${TESTDATABASENAME}
	$(PSQL) -f cdedb/database/cdedb-ldap.sql --dbname=${TESTDATABASENAME}
	$(PSQL) -f tests/ancillary_files/sample_data_xss.sql --dbname=${TESTDATABASENAME}

xss-check:
	$(PYTHONBIN) -m bin.check --xss-check --verbose

dump-html:
	$(MAKE) -B /tmp/cdedb-dump/

/tmp/cdedb-dump/: export CDEDB_TEST_DUMP_DIR=/tmp/cdedb-dump/
/tmp/cdedb-dump/:
	$(PYTHONBIN) -m bin.check test_frontend

validate-html: /tmp/cdedb-dump/ /opt/validator/vnu-runtime-image/bin/vnu
	/opt/validator/vnu-runtime-image/bin/vnu --no-langdetect --stdout \
		--filterpattern '(.*)input type is not supported in all browsers(.*)' /tmp/cdedb-dump/* \
		> /cdedb2/validate-html.txt

/opt/validator/vnu-runtime-image/bin/vnu: /opt/validator/vnu.linux.zip
	unzip -DD /opt/validator/vnu.linux.zip -d /opt/validator

VALIDATORURL := "https://github.com/validator/validator/releases/download/20.6.30/vnu.linux.zip"
VALIDATORCHECKSUM := "f56d95448fba4015ec75cfc9546e3063e8d66390 /opt/validator/vnu.linux.zip"

/opt/validator/vnu.linux.zip: /opt/validator
	wget $(VALIDATORURL) -O /opt/validator/vnu.linux.zip
	echo $(VALIDATORCHECKSUM) | sha1sum -c -
	touch /opt/validator/vnu.linux.zip # refresh downloaded timestamp

/opt/validator:
	sudo mkdir /opt/validator
	sudo chown cdedb:cdedb /opt/validator


.coverage: $(wildcard cdedb/*.py) $(wildcard cdedb/database/*.py) $(wildcard cdedb/frontend/*.py) \
		$(wildcard cdedb/backend/*.py) $(wildcard tests/*.py)
	$(COVERAGE) run -m bin.check

coverage: .coverage
	$(COVERAGE) report --include 'cdedb/*' --show-missing
	$(COVERAGE) html --include 'cdedb/*'
	@echo "HTML reports for easier inspection are in ./htmlcov"

tests/ancillary_files/sample_data.sql: tests/ancillary_files/sample_data.json \
		$(SAMPLE_DATA_SQL) cdedb/database/cdedb-tables.sql cdedb/database/cdedb-ldap.sql
	SQLTEMPFILE=`sudo -u www-data mktemp` \
		&& sudo -u www-data chmod +r "$${SQLTEMPFILE}" \
		&& sudo rm -f /tmp/cdedb*log \
		&& sudo -u www-data $(PYTHONBIN) \
			$(SAMPLE_DATA_SQL) \
			-i tests/ancillary_files/sample_data.json \
			-o "$${SQLTEMPFILE}" \
		&& sudo rm -f /tmp/cdedb*log \
		&& cp "$${SQLTEMPFILE}" tests/ancillary_files/sample_data.sql \
		&& sudo -u www-data rm "$${SQLTEMPFILE}"

tests/ancillary_files/sample_data_xss.sql: tests/ancillary_files/sample_data.json \
		$(SAMPLE_DATA_SQL) cdedb/database/cdedb-tables.sql cdedb/database/cdedb-ldap.sql
	SQLTEMPFILE=`sudo -u www-data mktemp` \
		&& sudo -u www-data chmod +r "$${SQLTEMPFILE}" \
		&& sudo rm -f /tmp/cdedb*log \
		&& sudo -u www-data $(PYTHONBIN) \
			$(SAMPLE_DATA_SQL) \
			-i tests/ancillary_files/sample_data.json \
			-o "$${SQLTEMPFILE}" \
			--xss "${XSS_PAYLOAD}" \
		&& sudo rm -f /tmp/cdedb*log \
		&& cp "$${SQLTEMPFILE}" tests/ancillary_files/sample_data_xss.sql \
		&& sudo -u www-data rm "$${SQLTEMPFILE}"
