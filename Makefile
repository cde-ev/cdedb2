SHELL := /bin/bash

.PHONY: help
help:
	@echo "Default Variables:"
	@echo "DATABASE_NAME       -- name of a postgres database. Default: cdb"
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
	@echo "sample-data-dump    -- dump current database state into json file in tests directory"
	@echo "sample-data         -- shortcut to reset the whole application via the python cli"


###############
# Executables #
###############

PYTHONBIN ?= python3
ISORT ?= $(PYTHONBIN) -m isort
FLAKE8 ?= $(PYTHONBIN) -m flake8
PYLINT ?= $(PYTHONBIN) -m pylint
COVERAGE ?= $(PYTHONBIN) -m coverage
MYPY ?= $(PYTHONBIN) -m mypy


#####################
# Default Variables #
#####################

# Use makes command-line arguments to override the following default variables
# The database name on which we operate. This will be overridden in the test suite.
DATABASE_NAME = cdb
# The host where the database is available. This is mostly needed to setup ldap correctly.
DATABASE_HOST = localhost
# The password of the cdb_admin user. This is currently needed to setup ldap correctly.
DATABASE_CDB_ADMIN_PASSWORD = 9876543210abcdefghijklmnopqrst
# Directory where the translation files are stored. Especially used by the i18n-targets.
I18NDIR = ./i18n
# Available languages, by default detected as subdirectories of the translation targets.
I18N_LANGUAGES = $(patsubst $(I18NDIR)/%/LC_MESSAGES, %, $(wildcard $(I18NDIR)/*/LC_MESSAGES))

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
	python3 -m cdedb db remove-transactions
ifeq ($(wildcard /CONTAINER),/CONTAINER)
	sudo apachectl restart
else
	sudo systemctl restart apache2
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

i18n-update: $(foreach lang, $(I18N_LANGUAGES), $(I18NDIR)/$(lang)/LC_MESSAGES/cdedb.po)

$(I18NDIR)/%/LC_MESSAGES/cdedb.po: $(I18NDIR)/cdedb.pot
	msgmerge --lang=$* --update $@ $<
	msgattrib --no-obsolete --sort-by-file -o $@ $@

i18n-compile: $(foreach lang, $(I18N_LANGUAGES), $(I18NDIR)/$(lang)/LC_MESSAGES/cdedb.mo)

$(I18NDIR)/%/LC_MESSAGES/cdedb.mo: $(I18NDIR)/%/LC_MESSAGES/cdedb.po
	msgfmt --verbose --check --statistics -o $@ $<


########
# LDAP #
########

.PHONY: ldap-prepare-odbc
ldap-prepare-odbc:
	# prepare odbc.ini file to enable database connection for ldap
	sudo cp -f ldap/odbc.ini /etc/odbc.ini \
		&& sudo sed -i -r -e "s/DATABASE_CDB_ADMIN_PASSWORD/${DATABASE_CDB_ADMIN_PASSWORD}/g" \
		                  -e "s/DATABASE_NAME/${DATABASE_NAME}/g" \
		                  -e "s/DATABASE_HOST/${DATABASE_HOST}/g" /etc/odbc.ini

.PHONY: ldap-prepare-ldif
ldap-prepare-ldif:
	# prepare the new cdedb-specific ldap configuration
	cp -f ldap/cdedb-ldap.ldif ldap/cdedb-ldap-applied.ldif \
		&& sed -i -r -e "s/DATABASE_CDB_ADMIN_PASSWORD/${DATABASE_CDB_ADMIN_PASSWORD}/g" \
		             -e "s/OLC_DB_NAME/${DATABASE_NAME}/g" \
		             -e "s/OLC_DB_HOST/${DATABASE_HOST}/g" ldap/cdedb-ldap-applied.ldif

.PHONY: ldap-create
ldap-create:
	# the only way to remove all ldap settings for sure is currently to uninstall it.
	# therefore, we need to re-install slapd here.
	sudo DEBIAN_FRONTEND=noninteractive apt-get install --yes slapd
	# remove the predefined mdb-database from ldap
	sudo systemctl stop slapd
	sudo rm -f /etc/ldap/slapd.d/cn=config/olcDatabase=\{1\}mdb.ldif
	sudo systemctl start slapd
	# Apply the overall ldap configuration (load modules, add backends etc)
	sudo ldapmodify -Y EXTERNAL -H ldapi:/// -f related/auto-build/files/stage3/ldap-config.ldif

.PHONY: ldap-update
ldap-update: ldap-prepare-odbc ldap-prepare-ldif
	# remove the old cdedb-specific configuration and apply the new one
	sudo systemctl stop slapd
	# TODO is there any nice solution to do this from within ldap?
	sudo rm -f /etc/ldap/slapd.d/cn=config/olcDatabase={1}sql.ldif
	sudo systemctl start slapd
	sudo ldapmodify -Y EXTERNAL -H ldapi:/// -f ldap/cdedb-ldap-applied.ldif

.PHONY: ldap-update-full
ldap-update-full: ldap-update
	sudo -u www-data $(PYTHONBIN) bin/ldap_add_duas.py

.PHONY: ldap-remove
ldap-remove:
	sudo apt-get remove --purge -y slapd

.PHONY: ldap-reset
ldap-reset: ldap-remove ldap-create ldap-update-full


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
	$(PYTHONBIN) -m bin.check --verbose tests.frontend_tests.*

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

.PHONY: sample-data-dump
sample-data-dump:
	JSONTEMPFILE=`sudo -u www-data mktemp` \
		&& sudo -u www-data chmod +r "$${JSONTEMPFILE}" \
		&& sudo -u www-data $(PYTHONBIN) bin/create_sample_data_json.py -o "$${JSONTEMPFILE}" \
		&& cp "$${JSONTEMPFILE}" tests/ancillary_files/sample_data.json \
		&& sudo -u www-data rm "$${JSONTEMPFILE}"

.PHONY: sample-data
sample-data:
	sudo python3 -m cdedb dev apply-sample-data --owner www-data
