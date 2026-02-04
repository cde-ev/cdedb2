# This is sourced by ~/.bash_aliases but synced via repo.
# If you want to change these locally, simply place a different alias later in ~/.bash_aliases

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
alias dmypy-cdedb="uv run --directory=/cdedb2 dmypy"

alias app-logs="sudo journalctl --no-hostname -u cdedb-app"
alias ldap-logs="sudo journalctl --no-hostname -u cde-ldap"
alias all-logs="sudo journalctl --no-hostname -u cdedb-app -u cde-ldap"

alias test-logs="sudo journalctl --no-hostname -t cdedb-test"
alias test-logs-ldap="sudo journalctl --no-hostname -u cde-ldap-test"
