# This is sourced by ~/.bash_aliases but synced via repo.
# If you want to change these locally, simply place a different alias later in ~/.bash_aliases

alias reload-aliases=". ~/.bashrc"

alias py="uv run --project=/cdedb2 python"

alias check="uv run --project=/cdedb2 /cdedb2/bin/check.py -v"
alias c="check"
alias offline="uv run --project=/cdedb2 /cdedb2/bin/make_offline_vm.py --not-interactive --no-extra-packages --dev --no-offline-flag"

alias cdb="sudo -u cdb psql -U cdb -d cdb"

alias reload="make -C /cdedb2 reload"
alias sample-data="make -C /cdedb2 sample-data"

alias lint="uv run --directory=/cdedb2 ruff format --check; uv run --directory=/cdedb2 ruff check"
alias format="uv run --directory=/cdedb2 ruff format"
alias ruff-cdedb="uv run --directory=/cdedb2 ruff check"
alias mypy-cdedb="uv run --directory=/cdedb2 mypy"
alias dmypy-cdedb="uv run --directory=/cdedb2 dmypy run"
alias pyrefly-cdedb="uv run --directory=/cdedb2 pyrefly check"

alias app-logs="sudo journalctl --no-hostname -u cdedb-app -p info"
alias ldap-logs="sudo journalctl --no-hostname -u cde-ldap -p info"
alias all-logs="sudo journalctl --no-hostname -u cdedb-app -u cde-ldap -p info"

alias test-logs="sudo journalctl --no-hostname -t cdedb-test -p info"
alias test-logs-ldap="sudo journalctl --no-hostname -u cde-ldap-test -p info"

alias doctest="uv run --directory=/cdedb2 --with pytest pytest --doctest-modules cdedb --ignore cdedb/database/evolutions --ignore cdedb/.i18n_additional.py"
