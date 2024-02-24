SHELL := /bin/bash

.PHONY: help
help:
	@echo "Default Variables:"
	@echo "I18NDIR             -- directory of the translation files. Default: ./i18n"
	@echo ""
	@echo "General:"
	@echo "cron                -- trigger cronjob execution (as user www-cde)"
	@echo "doc                 -- build documentation"
	@echo "reload              -- re-compile GNU gettext data and trigger WSGI worker reload"
	@echo ""
	@echo "Translations"
	@echo "i18n-refresh        -- extract translatable strings from code and update translation catalogs in I18NDIR"
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
	@echo "sample-data-dump    -- shortcut to dump current database state into json file in tests directory"
	@echo "sample-data         -- shortcut to reset the whole application via the python cli"


###############
# Executables #
###############

PYTHONBIN ?= python3
ISORT ?= $(PYTHONBIN) -m isort --settings pyproject.toml
FLAKE8 ?= $(PYTHONBIN) -m flake8
PYLINT ?= $(PYTHONBIN) -m pylint
RUFF ?= sudo -u cdedb $(PYTHONBIN) -m ruff --config /cdedb2/pyproject.toml
COVERAGE ?= $(PYTHONBIN) -m coverage
MYPY ?= $(PYTHONBIN) -m mypy


#####################
# Default Variables #
#####################

# Use makes command-line arguments to override the following default variables
# Directory where the translation input files are stored.
# Especially used by the i18n-targets.
I18NDIR = ./i18n
# Directory where the translation output files are stored.
# Especially used by the i18n-targets.
I18NOUTDIR = ./i18n-output
# Available languages, by default detected as subdirectories of the translation targets.
I18N_LANGUAGES = $(patsubst $(I18NDIR)/%/LC_MESSAGES, %, $(wildcard $(I18NDIR)/*/LC_MESSAGES))

###########
# General #
###########

.PHONY: cron
cron:
	sudo -u www-cde /cdedb2/bin/cron_execute.py

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

.PHONY: i18n-output-dirs
i18n-output-dirs:
	for lang in $(I18N_LANGUAGES) ; do \
		mkdir -p $(I18NOUTDIR)/$$lang/LC_MESSAGES ; \
	done

.PHONY: i18n-refresh
i18n-refresh: i18n-extract i18n-update

.PHONY: i18n-extract
i18n-extract: i18n-output-dirs
	pybabel extract --msgid-bugs-address="cdedb@lists.cde-ev.de" \
		--mapping=./babel.cfg --keywords="rs.gettext rs.ngettext n_" \
		--output=$(I18NOUTDIR)/cdedb.pot --input-dirs="bin,cdedb"

i18n-update: $(foreach lang, $(I18N_LANGUAGES), $(I18NDIR)/$(lang)/LC_MESSAGES/cdedb.po)

$(I18NDIR)/%/LC_MESSAGES/cdedb.po: $(I18NOUTDIR)/cdedb.pot
	msgmerge --lang=$* --update $@ $<
	msgattrib --no-obsolete --sort-by-file -o $@ $@

i18n-compile: i18n-output-dirs
i18n-compile: $(foreach lang, $(I18N_LANGUAGES), $(I18NOUTDIR)/$(lang)/LC_MESSAGES/cdedb.mo)

$(I18NOUTDIR)/%/LC_MESSAGES/cdedb.mo: $(I18NDIR)/%/LC_MESSAGES/cdedb.po
	msgfmt --verbose --check --statistics -o $@ $<


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
	$(ISORT) --check-only bin/*.py cdedb tests
	@echo ""

.PHONY: flake8
flake8:
	@echo $(BANNERLINE)
	@echo "All of flake8"
	@echo $(BANNERLINE)
	$(FLAKE8) cdedb tests
	@echo ""

.PHONY: pylint
pylint:
	@echo $(BANNERLINE)
	@echo "All of pylint"
	@echo $(BANNERLINE)
	$(PYLINT) cdedb tests
	@echo ""

.PHONY: ruff
ruff:
	@echo $(BANNERLINE)
	@echo "All of ruff"
	@echo $(BANNERLINE)
	sudo mkdir .ruff_cache -p
	sudo chown cdedb -R .ruff_cache
	$(RUFF) cdedb tests
	@echo ""

.PHONY: template-line-length
template-line-length:
	@echo $(BANNERLINE)
	@echo "Lines too long in templates"
	@echo $(BANNERLINE)
	grep -E -R '^.{121,}' cdedb/frontend/templates/ | grep 'tmpl:'
	@echo ""

.PHONY: lint
lint: ruff isort flake8 pylint


################
# Code testing #
################

.PHONY: check
check:
	$(PYTHONBIN) bin/check.py --verbose

.PHONY: xss-check
xss-check:
	$(PYTHONBIN) bin/check.py --verbose --parts xss

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
	python3 -m cdedb dev compile-sample-data-json \
		--outfile /cdedb2/tests/ancillary_files/sample_data.json

.PHONY: sample-data
sample-data:
	sudo python3 -m cdedb dev apply-sample-data --owner www-cde
