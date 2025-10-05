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
	@echo "Formatting and static analysis:"
	@echo "mypy                -- let mypy run over our codebase"
	@echo "lint                -- run linters (ruff)"
	@echo "format              -- automatically sort imports and reformat code"
	@echo "autoformat          -- automatically sort imports, reformat code and lint"
	@echo "format-diff         -- show the changes 'format' would make but do not apply them"
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
RUFF ?= $(PYTHONBIN) -m ruff --config pyproject.toml
ISORT ?= $(RUFF) check --select I
COVERAGE ?= $(PYTHONBIN) -m coverage
MYPY ?= $(PYTHONBIN) -m mypy

include .ruff_targets

MAKE_FORMAT_TARGETS ?= $(FORMAT_TARGETS)
MAKE_LINT_TARGETS ?= $(LINT_TARGETS)
MAKE_ISORT_TARGETS ?= $(ISORT_TARGETS)


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
	sudo -u www-cde -g www-data /cdedb2/bin/cron_execute.py

.PHONY: doc
doc:
	bin/create_email_template_list.sh .
	$(MAKE) -C doc html

.PHONY: reload
reload: i18n-compile
	python3 -m cdedb db remove-transactions
ifeq ($(wildcard /CONTAINER),/CONTAINER)
	sudo apachectl restart
	kill $$(pidof -x gunicorn) || true
	sudo /run-gunicorn.sh
else
	sudo systemctl restart apache2.service cdedb-app.service
endif


################
# Translations #
################

.PHONY: i18n-output-dirs
i18n-output-dirs:
	for lang in $(I18N_LANGUAGES) ; do \
		mkdir -p $(I18NOUTDIR)/$$lang/LC_MESSAGES ; \
	done
ifeq ($(wildcard /CONTAINER),/CONTAINER)
	sudo chown -R cdedb:cdedb $(I18NOUTDIR)
endif

.PHONY: i18n-refresh
i18n-refresh: i18n-extract i18n-update

.PHONY: i18n-extract
i18n-extract: i18n-output-dirs
	$(PYTHON) cdedb/i18n_additional.py > cdedb/.i18n_additional.py
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
	$(ISORT) --fix $(MAKE_ISORT_TARGETS)
	$(RUFF) format $(MAKE_FORMAT_TARGETS)

.PHONY: autoformat
autoformat: format
	$(RUFF) check --output-format full $(MAKE_LINT_TARGETS)

.PHONY: format-diff
format-diff:
	$(ISORT) $(MAKE_ISORT_TARGETS) --diff
	$(RUFF) format $(MAKE_FORMAT_TARGETS) --diff

.PHONY: mypy
mypy:
	$(MYPY) bin/*.py $(MAKE_LINT_TARGETS)

BANNERLINE := "================================================================================"

.PHONY: isort
isort:
	@echo $(BANNERLINE)
	@echo "All of isort"
	@echo $(BANNERLINE)
	$(ISORT) $(MAKE_ISORT_TARGETS)
	@echo ""

.PHONY: ruff
ruff:
	@echo $(BANNERLINE)
	@echo "All of ruff"
	@echo $(BANNERLINE)
	sudo mkdir .ruff_cache -p
	sudo chown cdedb -R .ruff_cache
ifeq ($(CI),true)
	# Use the grouped output format to make it easier to read in CI
	$(RUFF) check $(MAKE_LINT_TARGETS) --output-format=grouped
	$(RUFF) format $(MAKE_FORMAT_TARGETS) --check
else
	$(RUFF) check $(MAKE_LINT_TARGETS)
	$(RUFF) format $(MAKE_FORMAT_TARGETS) --check
endif
	@echo ""

.PHONY: ruff-fix
ruff-fix:
	$(RUFF) check $(MAKE_LINT_TARGETS) --fix

.PHONY: template-line-length
template-line-length:
	@echo $(BANNERLINE)
	@echo "Lines too long in templates"
	@echo $(BANNERLINE)
	grep -E -R '^.{121,}' cdedb/frontend/templates/ | grep 'tmpl:'
	@echo ""

.PHONY: lint
lint: ruff isort


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
	sudo python3 -m cdedb dev apply-sample-data --owner www-cde --group www-data
