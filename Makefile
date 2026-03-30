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
	@echo "shellcheck		   -- run shellcheck over all shell scripts"
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

UV ?= uv
PYTHONBIN ?= $(UV) run --all-groups python3
RUFF ?= $(UV) run ruff
ISORT ?= $(RUFF) check --select I
COVERAGE ?= $(PYTHONBIN) -m coverage
MYPY ?= $(UV) run --all-groups mypy
DMYPY ?= $(UV) run --all-groups dmypy


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

UV_PROJECT_ENVIRONMENT ?= .venv
UV_PYTHON_INSTALL_DIR ?= /var/cache/uv-python/

###########
# General #
###########

.PHONY: cron
cron: www-cde-venv
	sudo -u www-cde -g www-data UV_PROJECT_ENVIRONMENT=/home/www-cde/.venv $(UV) run --no-sync /cdedb2/bin/cron_execute.py

.PHONY: doc
doc:
	bin/create_email_template_list.sh .
	$(MAKE) -C doc html

.PHONY: reload
reload: i18n-compile venv
	$(PYTHONBIN) -m cdedb db remove-transactions
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
ifeq ($(wildcard /CONTAINER),/CONTAINER)
	sudo chown -R cdedb:cdedb $(I18NOUTDIR)
endif
	for lang in $(I18N_LANGUAGES) ; do \
		mkdir -p $(I18NOUTDIR)/$$lang/LC_MESSAGES ; \
	done

.PHONY: i18n-refresh
i18n-refresh: i18n-extract i18n-update

.PHONY: i18n-extract
i18n-extract: i18n-output-dirs venv
	$(PYTHONBIN) cdedb/i18n_additional.py > cdedb/.i18n_additional.py
	$(UV) run pybabel extract --msgid-bugs-address="cdedb@lists.cde-ev.de" \
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

.PHONY: venv
venv:
	if [ -d "/cdedb2" ]; then \
		sudo UV_PYTHON_INSTALL_DIR=$(UV_PYTHON_INSTALL_DIR) \
			$(UV) sync --all-groups; \
	fi

.PHONY: www-cde-venv
www-cde-venv:
	if [ -d "/cdedb2" ]; then \
		sudo UV_PYTHON_INSTALL_DIR=$(UV_PYTHON_INSTALL_DIR) \
			UV_PROJECT_ENVIRONMENT=/home/www-cde/.venv/ \
			$(UV) sync --no-dev --group ldap; \
	fi

.PHONY: format
format: venv
	$(ISORT) --fix
	$(RUFF) format

.PHONY: autoformat
autoformat: format
	$(RUFF) check

.PHONY: format-diff
format-diff: venv
	$(ISORT) --diff
	$(RUFF) format --diff

.PHONY: mypy
mypy: venv
	$(MYPY)

.PHONY: dmypy
dmypy: venv
	$(DMYPY) run

BANNERLINE := "================================================================================"

.PHONY: isort
isort: venv
	@echo $(BANNERLINE)
	@echo "All of isort"
	@echo $(BANNERLINE)
	$(ISORT)
	@echo ""

.PHONY: ruff
ruff: venv
	@echo $(BANNERLINE)
	@echo "All of ruff"
	@echo $(BANNERLINE)
ifeq ($(CI),true)
	# Use the grouped output format to make it easier to read in CI
	$(RUFF) check --output-format=grouped
	$(RUFF) format --check
else
	$(RUFF) check
	$(RUFF) format --check
endif
	@echo ""

.PHONY: ruff-fix
ruff-fix: venv
	$(RUFF) check --fix

.PHONY: shellcheck
shellcheck:
	@echo $(BANNERLINE)
	@echo "All of shellcheck"
	@echo $(BANNERLINE)
	shellcheck $$( \
		find bin/ i18n/ related/ \
			-type f \
			\( -name '*.sh' -or \( -executable -not -name '*.py' \) \) \
			-not \( -path bin/archive/'*' -or -path related/deploy/archive/'*' -or -path related/auto-build/bin/'*' \) \
	)

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
check: venv
	$(PYTHONBIN) bin/check.py --verbose

.PHONY: xss-check
xss-check: venv
	$(PYTHONBIN) bin/check.py --verbose --parts xss

.PHONY: dump-html
dump-html:
	$(MAKE) -B /tmp/cdedb-dump/

/tmp/cdedb-dump/: export CDEDB_TEST_DUMP_DIR=/tmp/cdedb-dump/
/tmp/cdedb-dump/: venv
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
		$(wildcard cdedb/backend/*.py) $(wildcard tests/*.py) venv
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
sample-data-dump: venv
	$(PYTHONBIN) -m cdedb dev compile-sample-data-json \
		--outfile /cdedb2/tests/ancillary_files/sample_data.json

.PHONY: sample-data
sample-data: venv
	sudo $(PYTHONBIN) -m cdedb dev apply-sample-data --owner www-cde --group www-data
