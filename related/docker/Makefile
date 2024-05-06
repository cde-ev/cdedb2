DOCKER-COMPOSE ?= docker compose

.PHONY: help
#: Show this help.
help:
	@awk '/^#:/{c=substr($$0,3);next}c&&/^[[:alpha:]][[:alnum:]_-]+:/'\
'{print substr($$1,1,index($$1,":")),c}1{c=0}' $(MAKEFILE_LIST) | column -s: -t
	@echo
	@echo "After starting the container point a browser at https://localhost:8443/db/"

.PHONY: build
#: Build docker image for development environment. (Note dep on build-runtime!)
build: build-runtime
	$(DOCKER-COMPOSE) --file docker-compose-dev.yaml build

.PHONY: clean
#: Reset state of development environment (deletes volumes).
clean:
	$(DOCKER-COMPOSE) --file docker-compose-dev.yaml --volumes down

.PHONY: start
#: Start up the development environment.
start:
	$(DOCKER-COMPOSE) --file docker-compose-dev.yaml up

.PHONY: shell
#: Open shell in development environment.
shell:
	$(DOCKER-COMPOSE) --file docker-compose-dev.yaml exec -u cdedb app bash

.PHONY: psql
#: Access postgres database directly.
psql:
	$(DOCKER-COMPOSE) exec cdb psql -U cdb -d cdb

.PHONY: build-runtime
#: Build docker image for runtime environment.
build-runtime:
	$(DOCKER-COMPOSE) --file docker-compose-run.yaml build

.PHONY: clean-runtime
#: Reset state of runtime environment (deletes volumes).
clean-runtime:
	$(DOCKER-COMPOSE) --file docker-compose-run.yaml --volumes down

.PHONY: start-runtime
#: Start up the runtime environment.
start-runtime:
	$(DOCKER-COMPOSE) --file docker-compose-run.yaml up

.PHONY: shell-runtime
#: Open shell in runtime environment.
shell-runtime:
	$(DOCKER-COMPOSE) --file docker-compose-run.yaml exec -u cdedb app bash

