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
	pybabel extract \
		-F ./babel.cfg  --sort-by-file -o $(I18NDIR)/cdedb.pot \
		-k "rs.gettext" -k "rs.ngettext" -k "n_" .

i18n-update:
	pybabel update -i $(I18NDIR)/cdedb.pot -d $(I18NDIR)/ -l de -D cdedb \
		--ignore-obsolete
	pybabel update -i $(I18NDIR)/cdedb.pot -d $(I18NDIR)/ -l en -D cdedb \
		--ignore-obsolete

i18n-compile:
	pybabel compile -d $(I18NDIR)/ -l de -D cdedb
	pybabel compile -d $(I18NDIR)/ -l en -D cdedb

i18n-check:
	msgfmt -c $(I18NDIR)/de/LC_MESSAGES/cdedb.po --statistics \
		--output /dev/null
	msgfmt -c $(I18NDIR)/en/LC_MESSAGES/cdedb.po --statistics \
		--output /dev/null

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

sql-schema:
ifeq ($(wildcard /PRODUCTIONVM),/PRODUCTIONVM)
	$(error Refusing to touch live instance)
endif
ifeq ($(wildcard /OFFLINEVM),/OFFLINEVM)
	$(error Refusing to touch orga instance)
endif
ifeq ($(wildcard /CONTAINER),/CONTAINER)
	$(error This needs to be run inside the postgres container)
endif
	sudo systemctl stop pgbouncer
	sudo -u postgres psql -U postgres -f cdedb/database/cdedb-users.sql
	sudo -u postgres psql -U postgres -f cdedb/database/cdedb-db.sql \
		-v cdb_database_name=cdb
	sudo -u postgres psql -U postgres -f cdedb/database/cdedb-db.sql \
		-v cdb_database_name=cdb_test
	sudo -u cdb psql -U cdb -d cdb -f cdedb/database/cdedb-tables.sql
	sudo -u cdb psql -U cdb -d cdb_test -f cdedb/database/cdedb-tables.sql
	sudo systemctl start pgbouncer

sql-seed-database: tests/ancillary_files/sample_data.sql
ifeq ($(wildcard /PRODUCTIONVM),/PRODUCTIONVM)
	$(error Refusing to touch live instance)
endif
ifeq ($(wildcard /OFFLINEVM),/OFFLINEVM)
	$(error Refusing to touch orga instance)
endif
	$(PYTHONBIN) bin/execute_sql_script.py --dbname cdb \
		-f tests/ancillary_files/sample_data.sql
	$(PYTHONBIN) bin/execute_sql_script.py --dbname cdb_test \
		-f tests/ancillary_files/sample_data.sql

sql:
	$(MAKE) sql-schema
	$(MAKE) sql-seed-database

# This does not recurse to sql-schema, so in the very rare circumstance that
# you want to completely reset the test database it has to be executed
# explicitly. This is due to the restrictions of the docker environment.
sql-test:
	$(PYTHONBIN) bin/execute_sql_script.py --dbname=cdb_test \
		-f cdedb/database/cdedb-tables.sql
	$(MAKE) sql-test-shallow

sql-test-shallow: tests/ancillary_files/sample_data.sql
	$(PYTHONBIN) bin/execute_sql_script.py --dbname=cdb_test \
		-f tests/ancillary_files/clean_data.sql
	$(PYTHONBIN) bin/execute_sql_script.py --dbname=cdb_test\
		-f tests/ancillary_files/sample_data.sql

sql-xss:
ifeq ($(wildcard /PRODUCTIONVM),/PRODUCTIONVM)
	$(error Refusing to touch live instance)
endif
ifeq ($(wildcard /OFFLINEVM),/OFFLINEVM)
	$(error Refusing to touch orga instance)
endif
	$(MAKE) sql-schema
	$(PYTHONBIN) bin/execute_sql_script.py --dbname=cdb \
		-f tests/ancillary_files/sample_data_escaping.sql
	$(PYTHONBIN) bin/execute_sql_script.py --dbname=cdb_test\
		-f tests/ancillary_files/sample_data_escaping.sql

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
		| grep -E '^(\*\*\*\*|E:|W:)' \
		| grep -E -v "'cdedb.validation' has no '[a-zA-Z_]*' member"


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
	$(COVERAGEBIN) run -m test.main

coverage: .coverage
	$(COVERAGEBIN) report --include 'cdedb/*' --show-missing

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

.PHONY: help doc sample-data sample-data-test sample-data-test-shallow sql \
	sql-test sql-test-shallow lint check single-check .coverage coverage \
	dump-html validate-html

mypy-backend:
	${MYPYBIN} cdedb/backend/

mypy-frontend:
	${MYPYBIN} cdedb/frontend/

mypy-test:
	${MYPYBIN} tests/__init__.py tests/common.py \
		tests/create_sample_data_json.py tests/create_sample_data_sql.py \
		tests/main.py tests/singular.py

mypy:
	# Do not provide cdedb/validation.py on purpose.
	${MYPYBIN} cdedb/backend/ cdedb/frontend cdedb/__init__.py \
		cdedb/common.py cdedb/enums.py cdedb/i18n_additional.py \
		cdedb/ml_subscription_aux.py cdedb/ml_type_aux.py cdedb/query.py \
		cdedb/script.py cdedb/validationdata.py cdedb/validationtypes.py \
		tests/common.py
