SHELL := /bin/bash

.PHONY: help
help:
	@echo "Default Variables:"
	@echo "DATABASE_NAME       -- name of a postgres database. Default: cdb"
	@echo "STORAGE_DIR         -- location where the cdedb stores files. Default: /var/lib/cdedb"
	@echo "LOG_DIR             -- location of the logs. Default: /var/log/cdedb"
	@echo "DATA_USER           -- system user who will own STORAGE_DIR and LOG_DIR. Default: www-data"
	@echo "XSS_PAYLOAD         -- payload to insert in sample_data_xss.sql. Default: <script>abcdef</script>"
	@echo "I18NDIR             -- directory of the translation files. Default: ./i18n"
	@echo ""
	@echo "General:"
	@echo "cron                -- trigger cronjob execution (as user www-data)"
	@echo "doc                 -- build documentation"
	@echo "reload              -- re-compile GNU gettext data and trigger WSGI worker reload"
	@echo ""
	@echo "Translations"
	@echo "i18n-refresh        -- extract translatable strings from code and update translation catalogs in I18NDIR"
	@echo ""
	@echo "Storage:"
	@echo "storage             -- recreate STORAGE_DIR owned by DATA_USER and populate it with sample files"
	@echo "log                 -- recreate LOG_DIR owned by DATA_USER"
	@echo ""
	@echo "Database"
	@echo "sql-initial         -- Drops all databases and create default postgres users."
	@echo "sql-setup           -- Create new database DATABASE_NAME"
	@echo "sql                 -- populates database DATABASE_NAME with sample content (use sample-data instead)"
	@echo ""
	@echo "LDAP:"
	@echo "TODO add description"
	@echo ""
	@echo "Code formatting:"
	@echo "mypy                -- let mypy run over our codebase (bin, cdedb, tests)"
	@echo "lint                -- run linters (isort, flake8 and pylint)"
	@echo ""
	@echo "Code testing:"
	@echo "check               -- run (parts of the) test suite"
	@echo "xss-check           -- check for xss vulnerabilities"
	@echo "dump-html           -- run frontend tests and store all encountered pages inside /tmp/cdedb-dump/"
	@echo "validate-html       -- run html validator over the dumped frontend pages "
	@echo "                       (dump-html is executed before if they do not exist yet)"
	@echo "coverage            -- run coverage to determine test suite coverage"
	@echo ""
	@echo "Sample Data:"
	@echo "sample-data         -- initialize database structures (DESTROYS DATA!)"
	@echo "sample-data-dump    -- dump current database state into json file in tests directory"


###############
# Executables #
###############

PYTHONBIN ?= python3
ISORT ?= $(PYTHONBIN) -m isort
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


#####################
# Default Variables #
#####################

# Use makes command-line arguments to override the following default variables
# The database name on which we operate. This will be overridden in the test suite.
DATABASE_NAME = cdb
# Directory where the python application stores additional files. This will be overridden in the test suite.
STORAGE_DIR = /var/lib/cdedb
# Direcotry where the application stores its log files. This will be overriden in the test suite.
LOG_DIR = /var/log/cdedb
# User who runs the application and has access to storage and log dir. This will be overridden in the test suite.
DATA_USER = www-data
# Payload to be injected in the sample_data_xss.sql file.
XSS_PAYLOAD = <script>abcdef</script>
I18NDIR ?= ./i18n


###########
# General #
###########

.PHONY: cron
cron:
	sudo -u www-data /cdedb2/bin/cron_execute.py

.PHONY: doc
doc:
	bin/create_email_template_list.sh .
	$(MAKE) -C doc html

.PHONY: reload
reload: i18n-compile
ifeq ($(wildcard /CONTAINER),/CONTAINER)
	apachectl restart
else
	sudo systemctl restart apache2
endif

# ensure we do not modify a production or offline vm. Add as prerequisite to each target which could destroy data.
.PHONY: sanity-check
sanity-check:
  ifeq ($(wildcard /PRODUCTIONVM),/PRODUCTIONVM)
	$(error Refusing to touch live instance)
  endif
  ifeq ($(wildcard /OFFLINEVM),/OFFLINEVM)
	$(error Refusing to touch orga instance)
  endif


################
# Translations #
################

.PHONY: i18n-refresh
i18n-refresh: i18n-extract i18n-update

.PHONY: i18n-extract
i18n-extract:
	pybabel extract --msgid-bugs-address="cdedb@lists.cde-ev.de" \
		--mapping=./babel.cfg --keywords="rs.gettext rs.ngettext n_" \
		--output=$(I18NDIR)/cdedb.pot --input-dirs="bin,cdedb"

.PHONY: i18n-update
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

.PHONY: i18n-compile
i18n-compile:
	msgfmt --verbose --check --statistics -o $(I18NDIR)/de/LC_MESSAGES/cdedb.mo \
		$(I18NDIR)/de/LC_MESSAGES/cdedb.po
	msgfmt --verbose --check --statistics -o $(I18NDIR)/en/LC_MESSAGES/cdedb.mo \
		$(I18NDIR)/en/LC_MESSAGES/cdedb.po
	msgfmt --verbose --check --statistics -o $(I18NDIR)/la/LC_MESSAGES/cdedb.mo \
		$(I18NDIR)/la/LC_MESSAGES/cdedb.po


###########
# Storage #
###########

TESTFOTONAME := e83e5a2d36462d6810108d6a5fb556dcc6ae210a580bfe4f6211fe925e61ffbec03e425a3c06bea243$\
		33cc17797fc29b047c437ef5beb33ac0f570c6589d64f9

.PHONY: storage
storage: sanity-check
	sudo rm -rf -- $(STORAGE_DIR)/*
	# this takes care the DATA_USER also owns the directories containing STORAGE_DIR
	sudo -u $(DATA_USER) mkdir -p $(STORAGE_DIR)
	sudo mkdir -p $(STORAGE_DIR)/foto/
	sudo mkdir -p $(STORAGE_DIR)/minor_form/
	sudo mkdir -p $(STORAGE_DIR)/event_logo/
	sudo mkdir -p $(STORAGE_DIR)/course_logo/
	sudo mkdir -p $(STORAGE_DIR)/ballot_result/
	sudo mkdir -p $(STORAGE_DIR)/assembly_attachment/
	sudo mkdir -p $(STORAGE_DIR)/genesis_attachment/
	sudo mkdir -p $(STORAGE_DIR)/mailman_templates/
	sudo mkdir -p $(STORAGE_DIR)/testfiles/
	sudo cp tests/ancillary_files/$(TESTFOTONAME) $(STORAGE_DIR)/foto/
	sudo cp tests/ancillary_files/rechen.pdf $(STORAGE_DIR)/assembly_attachment/1_v1
	sudo cp tests/ancillary_files/kassen.pdf $(STORAGE_DIR)/assembly_attachment/2_v1
	sudo cp tests/ancillary_files/kassen2.pdf $(STORAGE_DIR)/assembly_attachment/2_v3
	sudo cp tests/ancillary_files/kandidaten.pdf $(STORAGE_DIR)/assembly_attachment/3_v1
	sudo cp -t $(STORAGE_DIR)/testfiles/ tests/ancillary_files/{$(TESTFILES)}
	sudo chown --recursive $(DATA_USER):$(DATA_USER) $(STORAGE_DIR)

TESTFILES := picture.pdf,picture.png,picture.jpg,form.pdf,rechen.pdf,ballot_result.json,sepapain.xml$\
		,event_export.json,batch_admission.csv,money_transfers.csv,money_transfers_valid.csv$\
		,partial_event_import.json,TestAka_partial_export_event.json,statement.csv$\
		,questionnaire_import.json

.PHONY: log
log: sanity-check
	sudo rm -rf -- $(LOG_DIR)/*
	# this takes care the DATA_USER also owns the directories containing LOG_DIR
	sudo -u $(DATA_USER) mkdir -p $(LOG_DIR)
	sudo chown $(DATA_USER):$(DATA_USER) $(LOG_DIR)


############
# Database #
############

# drop all existent databases and add the database users. Acts globally and is idempotent.
.PHONY: sql-initial
sql-initial: sanity-check
  # we cannot use systemctl in docker
  ifneq ($(wildcard /CONTAINER),/CONTAINER)
	sudo systemctl stop pgbouncer
	sudo systemctl stop slapd
  endif
	$(PSQL_ADMIN) -f cdedb/database/cdedb-users.sql
  ifneq ($(wildcard /CONTAINER),/CONTAINER)
	sudo systemctl start pgbouncer
	# we need actual data before we can restart slapd, so we deferr this to later
	# sudo systemctl start slapd
  endif

# setup a new database, specified by DATABASE_NAME. Does not yet populate it with actual data.
.PHONY: sql-setup
sql-setup: sanity-check
  # we cannot use systemctl in docker
  ifneq ($(wildcard /CONTAINER),/CONTAINER)
	sudo systemctl stop pgbouncer
	sudo systemctl stop slapd
  endif
	$(PSQL_ADMIN) -f cdedb/database/cdedb-db.sql -v cdb_database_name=$(DATABASE_NAME)
  ifneq ($(wildcard /CONTAINER),/CONTAINER)
	sudo systemctl start pgbouncer
	# we need actual data before we can restart slapd, so we deferr this to later
	# sudo systemctl start slapd
  endif
	$(PSQL) -f cdedb/database/cdedb-tables.sql --dbname=$(DATABASE_NAME)
	$(PSQL) -f cdedb/database/cdedb-ldap.sql --dbname=$(DATABASE_NAME)

# setup a new database and populate it with the sample data.
.PHONY: sql
sql: sql-setup tests/ancillary_files/sample_data.sql
	$(PSQL) -f tests/ancillary_files/sample_data.sql --dbname=$(DATABASE_NAME)
  # finally restart slapd
  ifneq ($(wildcard /CONTAINER),/CONTAINER)
	sudo systemctl restart slapd
  endif

# setup a new database and populate it with special sample data to perform xss checks.
.PHONY: sql-xss
sql-xss: sql-setup tests/ancillary_files/sample_data_xss.sql
	$(PSQL) -f tests/ancillary_files/sample_data_xss.sql --dbname=$(DATABASE_NAME)


########
# LDAP #
########

ldap-create:
	sudo SCRIPT_DRY_RUN="" $(PYTHONBIN) ldap/create-ldap.py

ldap-update:
	sudo SCRIPT_DRY_RUN="" $(PYTHONBIN) ldap/update-ldap.py

ldap-remove:
	sudo SCRIPT_DRY_RUN="" $(PYTHONBIN) ldap/remove-ldap.py

###################
# Code formatting #
###################

.PHONY: format
format:
	$(ISORT) bin/*.py cdedb tests

.PHONY: mypy
mypy:
	$(MYPY) bin/*.py cdedb tests

BANNERLINE := "================================================================================"

.PHONY: isort
isort:
	@echo $(BANNERLINE)
	@echo "All of isort"
	@echo $(BANNERLINE)
	@echo ""
	$(ISORT) --check-only bin/*.py cdedb tests

.PHONY: flake8
flake8:
	@echo $(BANNERLINE)
	@echo "All of flake8"
	@echo $(BANNERLINE)
	@echo ""
	$(FLAKE8) cdedb tests

.PHONY: pylint
pylint:
	@echo $(BANNERLINE)
	@echo "All of pylint"
	@echo $(BANNERLINE)
	@echo ""
	$(PYLINT) cdedb tests

.PHONY: template-line-length
template-line-length:
	@echo $(BANNERLINE)
	@echo "Lines too long in templates"
	@echo $(BANNERLINE)
	@echo ""
	grep -E -R '^.{121,}' cdedb/frontend/templates/ | grep 'tmpl:'

.PHONY: lint
lint: isort flake8 pylint


################
# Code testing #
################

.PHONY: check
check:
	$(PYTHONBIN) bin/check.py --verbose $(or $(TESTPATTERNS), )

.PHONY: xss-check
xss-check:
	$(PYTHONBIN) bin/check.py --xss-check --verbose

.PHONY: dump-html
dump-html:
	$(MAKE) -B /tmp/cdedb-dump/

/tmp/cdedb-dump/: export CDEDB_TEST_DUMP_DIR=/tmp/cdedb-dump/
/tmp/cdedb-dump/:
	$(PYTHONBIN) -m bin.check --verbose tests.test_frontend*

.PHONY: validate-html
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

.PHONY: coverage
coverage: .coverage
	$(COVERAGE) report --include 'cdedb/*' --show-missing
	$(COVERAGE) html --include 'cdedb/*'
	@echo "HTML reports for easier inspection are in ./htmlcov"


##########################
# Sample Data Generation #
##########################

.PHONY: sample-data
sample-data: storage sql-initial sql
	cp -f related/auto-build/files/stage3/localconfig.py cdedb/localconfig.py

.PHONY: sample-data-dump
sample-data-dump:
	JSONTEMPFILE=`sudo -u www-data mktemp` \
		&& sudo -u www-data chmod +r "$${JSONTEMPFILE}" \
		&& sudo -u www-data $(PYTHONBIN) bin/create_sample_data_json.py -o "$${JSONTEMPFILE}" \
		&& cp "$${JSONTEMPFILE}" tests/ancillary_files/sample_data.json \
		&& sudo -u www-data rm "$${JSONTEMPFILE}"

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
