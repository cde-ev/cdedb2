SHELL := /bin/bash

.PHONY: help doc sample-data sample-data-test sample-data-test-shallow sql \
	sql-test sql-test-shallow lint check single-check .coverage coverage \
	dump-html validate-html \
	i18n-extract i18n-update i18n-compile i18n-refresh

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
	@echo "single-check -- run some tests from the test suite"
	@echo "                (PATTERNS specifies globs to match against the testnames like"
	@echo "                tests.test_frontend_event.TestEventFrontend.test_create_event)"
	@echo "coverage -- run coverage to determine test suite coverage"

PYTHONBIN ?= python3
PYLINTBIN ?= pylint3
COVERAGEBIN ?= python3-coverage
MYPYBIN ?= mypy
TESTPREPARATION ?= automatic
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
	msgmerge --sort-by-file --lang=de --update \
		$(I18NDIR)/de/LC_MESSAGES/cdedb.po $(I18NDIR)/cdedb.pot
	msgmerge --sort-by-file --lang=en --update \
		$(I18NDIR)/en/LC_MESSAGES/cdedb.po $(I18NDIR)/cdedb.pot
	msgattrib --no-obsolete -o $(I18NDIR)/de/LC_MESSAGES/cdedb.po \
		$(I18NDIR)/de/LC_MESSAGES/cdedb.po
	msgattrib --no-obsolete -o $(I18NDIR)/en/LC_MESSAGES/cdedb.po \
		$(I18NDIR)/en/LC_MESSAGES/cdedb.po
	# TODO: do we want to use msgattribs --indent option for prettier po files?

i18n-compile:
	msgfmt --verbose --check --statistics -o $(I18NDIR)/de/LC_MESSAGES/cdedb.mo \
		$(I18NDIR)/de/LC_MESSAGES/cdedb.po
	msgfmt --verbose --check --statistics -o $(I18NDIR)/en/LC_MESSAGES/cdedb.mo \
		$(I18NDIR)/en/LC_MESSAGES/cdedb.po

sample-data:
	$(MAKE) storage > /dev/null
	$(MAKE) sql > /dev/null
	cp -f related/auto-build/files/stage3/localconfig.py \
		cdedb/localconfig.py

sample-data-test:
	$(MAKE) storage-test
	$(MAKE) sql-test

sample-data-test-shallow:
	$(MAKE) storage-test
	$(MAKE) sql-test-shallow

sample-data-xss:
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
		,TestAka_partial_export_event.json

storage-test:
	rm -rf -- /tmp/cdedb-store/*
	mkdir -p /tmp/cdedb-store/foto/
	cp tests/ancillary_files/$(TESTFOTONAME) /tmp/cdedb-store/foto/
	mkdir -p /tmp/cdedb-store/minor_form/
	mkdir -p /tmp/cdedb-store/event_logo/
	mkdir -p /tmp/cdedb-store/course_logo/
	mkdir -p /tmp/cdedb-store/ballot_result/
	mkdir -p /tmp/cdedb-store/assembly_attachment/
	mkdir -p /tmp/cdedb-store/genesis_attachment/
	mkdir -p /tmp/cdedb-store/mailman_templates/
	mkdir -p /tmp/cdedb-store/testfiles/
	cp tests/ancillary_files/rechen.pdf \
		/tmp/cdedb-store/assembly_attachment/1_v1
	cp tests/ancillary_files/kassen.pdf \
		/tmp/cdedb-store/assembly_attachment/2_v1
	cp tests/ancillary_files/kassen2.pdf \
		/tmp/cdedb-store/assembly_attachment/2_v3
	cp tests/ancillary_files/kandidaten.pdf \
		/tmp/cdedb-store/assembly_attachment/3_v1
	cp -t /tmp/cdedb-store/testfiles/ tests/ancillary_files/{$(TESTFILES)}

sql: tests/ancillary_files/sample_data.sql
ifeq ($(wildcard /PRODUCTIONVM),/PRODUCTIONVM)
	$(error Refusing to touch live instance)
endif
ifeq ($(wildcard /OFFLINEVM),/OFFLINEVM)
	$(error Refusing to touch orga instance)
endif
ifeq ($(wildcard /CONTAINER),/CONTAINER)
	psql postgresql://postgres:passwd@cdb -f cdedb/database/cdedb-users.sql
	psql postgresql://postgres:passwd@cdb -f cdedb/database/cdedb-db.sql -v cdb_database_name=cdb
	psql postgresql://postgres:passwd@cdb -f cdedb/database/cdedb-db.sql -v cdb_database_name=cdb_test
else
	sudo systemctl stop pgbouncer
	sudo -u postgres psql -f cdedb/database/cdedb-users.sql
	sudo -u postgres psql -f cdedb/database/cdedb-db.sql -v cdb_database_name=cdb
	sudo -u postgres psql -f cdedb/database/cdedb-db.sql -v cdb_database_name=cdb_test
	sudo systemctl start pgbouncer
endif
	$(PYTHONBIN) bin/execute_sql_script.py -f cdedb/database/cdedb-tables.sql --dbname=cdb
	$(PYTHONBIN) bin/execute_sql_script.py -f cdedb/database/cdedb-tables.sql --dbname=cdb_test
	$(PYTHONBIN) bin/execute_sql_script.py -f tests/ancillary_files/sample_data.sql --dbname=cdb
	$(PYTHONBIN) bin/execute_sql_script.py -f tests/ancillary_files/sample_data.sql --dbname=cdb_test

sql-test:
ifeq ($(wildcard /CONTAINER),/CONTAINER)
	psql postgresql://postgres:passwd@cdb -f cdedb/database/cdedb-db.sql -v cdb_database_name=cdb_test
else
	sudo systemctl stop pgbouncer
	sudo -u postgres psql -f cdedb/database/cdedb-db.sql -v cdb_database_name=cdb_test
	sudo systemctl start pgbouncer
endif
	$(PYTHONBIN) bin/execute_sql_script.py -f cdedb/database/cdedb-tables.sql --dbname=cdb_test 
	$(MAKE) sql-test-shallow

sql-test-shallow: tests/ancillary_files/sample_data.sql
	$(PYTHONBIN) bin/execute_sql_script.py -f tests/ancillary_files/clean_data.sql --dbname=cdb_test 
	$(PYTHONBIN) bin/execute_sql_script.py -f tests/ancillary_files/sample_data.sql --dbname=cdb_test 

sql-xss: tests/ancillary_files/sample_data_escaping.sql
ifeq ($(wildcard /PRODUCTIONVM),/PRODUCTIONVM)
	$(error Refusing to touch live instance)
endif
ifeq ($(wildcard /OFFLINEVM),/OFFLINEVM)
	$(error Refusing to touch orga instance)
endif
	$(MAKE) sql
	$(PYTHONBIN) bin/execute_sql_script.py -f tests/ancillary_files/sample_data_escaping.sql --dbname=cdb
	$(PYTHONBIN) bin/execute_sql_script.py -f tests/ancillary_files/sample_data_escaping.sql --dbname=cdb_test

cron:
	sudo -u www-data /cdedb2/bin/cron_execute.py

BANNERLINE := "============================================================$\
		===================="
lint:
	@echo ""
	@echo $(BANNERLINE)
	@echo "Lines too long in templates"
	@echo $(BANNERLINE)
	@echo ""
	grep -E -R '^.{121,}' cdedb/frontend/templates/ | grep 'tmpl:'
	@echo ""
	@echo $(BANNERLINE)
	@echo "All of pylint"
	@echo $(BANNERLINE)
	@echo ""
	${PYLINTBIN} --rcfile='./lint.rc' cdedb || true
	@echo ""
	@echo $(BANNERLINE)
	@echo "And now only errors and warnings"
	@echo $(BANNERLINE)
	@echo ""
	$(PYLINTBIN) --rcfile='./lint.rc' --output-format=text cdedb \
		| grep -E '^(\*\*\*\*|E:|W:)'


prepare-check:
ifneq ($(TESTPREPARATION), manual)
	$(MAKE) i18n-compile
	$(MAKE) sample-data-test &> /dev/null
	sudo rm -f /tmp/test-cdedb* /tmp/cdedb-timing.log /tmp/cdedb-mail-* \
		|| true
else
	@echo "Omitting test preparation."
endif

check: export CDEDB_TEST=True
check:
	$(MAKE) prepare-check
	$(PYTHONBIN) -m tests.main "$${TESTPATTERN}"

single-check: export CDEDB_TEST=True
single-check:
	$(MAKE) prepare-check
	$(PYTHONBIN) -m tests.singular "$${PATTERNS}"

xss-check: export CDEDB_TEST=True
xss-check:
	$(MAKE) prepare-check
	sudo -u cdb psql -U cdb -d cdb_test \
		-f tests/ancillary_files/clean_data.sql &>/dev/null
	sudo -u cdb psql -U cdb -d cdb_test \
		-f tests/ancillary_files/sample_data_escaping.sql &>/dev/null
	$(PYTHONBIN) -m bin.escape_fuzzing 2>/dev/null

dump-html: export SCRAP_ENCOUNTERED_PAGES=1 TESTPATTERN=test_frontend
dump-html:
	$(MAKE) check


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


.coverage: export CDEDB_TEST=True
.coverage: $(wildcard cdedb/*.py) $(wildcard cdedb/database/*.py) \
		$(wildcard cdedb/frontend/*.py) \
		$(wildcard cdedb/backend/*.py) $(wildcard tests/*.py)
	$(MAKE) prepare-check
	$(COVERAGEBIN) run -m tests.main

coverage: .coverage
	$(COVERAGEBIN) report --include 'cdedb/*' --show-missing
	$(COVERAGEBIN) html --include 'cdedb/*'
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

mypy-backend:
	${MYPYBIN} cdedb/backend/

mypy-frontend:
	${MYPYBIN} cdedb/frontend/

mypy-test:
	${MYPYBIN} tests/__init__.py tests/common.py \
		tests/create_sample_data_json.py tests/create_sample_data_sql.py \
		tests/main.py tests/singular.py

mypy:
	${MYPYBIN} cdedb tests/common.py
