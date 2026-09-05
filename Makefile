# pips — task entry points (ADR-0007: plain Make, no `just`, no GitHub Actions).
# Every target is a thin wrapper over the real command so that Jenkins, the research
# container and a laptop all run the identical ladder.

SHELL := /bin/bash
.DEFAULT_GOAL := help
UV ?= uv
RUN ?= $(UV) run
PY ?= $(RUN) python
BASE ?= main
PAST_DIR ?= ../past
PIPS_DATA_ROOT ?= /srv/pips
DAY ?=

.PHONY: help setup lint typecheck test tdd-check ledger-check salvage-verify authority-check determinism ci \
        fixtures s1-smoke backtest-smoke parity qc rust-test refs-extract clean

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[1m%-16s\033[0m %s\n", $$1, $$2}'

setup: ## Create the virtualenv and install dev dependencies
	$(UV) sync --group dev

lint: ## ruff (lint + format check)
	$(RUN) ruff check python tests
	$(RUN) ruff format --check python tests

typecheck: ## mypy --strict over core/ + schemas/
	$(RUN) mypy

test: ## pytest (unit + property + integration)
	$(RUN) pytest

sweep: ## Mutation-sweep every production module changed against BASE, by its committed spec
	uv run python ops/mutate/sweep.py --base $(BASE)

tdd-check: ## Refuse production code committed ahead of its test [G-TDD-01]
	$(PY) -m pips.cli tdd check $(BASE) .

ledger-check: ## Verify prose <-> ledger <-> code <-> tests (§8.2)
	$(PY) -m pips.cli ledger check .

salvage-verify: ## Resolve every harvest-map donor SHA against ../past (§1.2, read-only)
	$(PY) -m pips.cli salvage verify $(PAST_DIR)

authority-check: ## Report GATE-0 data-use authority status [G-AUTH-0]
	$(PY) -m pips.cli authority check

determinism: ## Run the smoke pipeline twice and diff hashes (constitution rule 1)
	$(PY) -m pips.cli determinism .

fixtures: ## Regenerate the seeded smoke fixtures
	$(PY) -m pips.cli fixtures generate fixtures

rust-test: ## cargo clippy -D warnings + cargo test
	cargo clippy --workspace --all-targets -- -D warnings
	cargo test --workspace

provenance: ## Refuse to run the ladder against code that is not the code under test
	$(PY) -m pips.cli provenance

ci: provenance lint typecheck tdd-check test sweep rust-test determinism ledger-check ## The full ladder Jenkins runs
	@echo "ci: green"

# Dirtiness is probed with `git status --porcelain`, which reports UNTRACKED files too. The
# image build is COPY . . and .dockerignore excludes only caches, so a module that has not been
# added yet goes into the image -- and a probe blind to it would stamp the build clean, leaving
# the image naming a commit it does not contain. That is the hole ops/provenance.py exists for.
ci-container: ## The documented verify: build the image FROM the working tree, then run the ladder
	@mkdir -p $(CURDIR)/.devdata
	@sha=$$(git rev-parse HEAD); \
	 dirty=$$(test -z "$$(git status --porcelain)" && echo 0 || echo 1); \
	 echo "ci-container: building $$sha (dirty=$$dirty)"; \
	 PIPS_SHA=$$sha PIPS_DIRTY=$$dirty PIPS_EXPECTED_SHA=$$sha \
	 PIPS_DATA_DIR=$${PIPS_DATA_DIR:-$(CURDIR)/.devdata} \
	 docker compose build research && \
	 PIPS_SHA=$$sha PIPS_EXPECTED_SHA=$$sha \
	 PIPS_DATA_DIR=$${PIPS_DATA_DIR:-$(CURDIR)/.devdata} \
	 docker compose run --rm research make ci

refs-extract: ## Cache pandoc extractions of docs/reference/*.docx (needs pandoc)
	@mkdir -p docs/reference/_extracted
	@for f in docs/reference/*.docx; do \
	  out="docs/reference/_extracted/$$(basename "$$f" .docx).md"; \
	  echo "  $$f -> $$out"; \
	  pandoc -t markdown --wrap=none "$$f" -o "$$out"; \
	done

qc: ## Quality-check bronze and quarantine failures (§6 M5)
	$(PY) -m pips.cli qc $(PIPS_DATA_ROOT)

promote: ## Promote bronze to silver, consulting QC's verdicts [C-SILVER-01]
	$(PY) -m pips.cli promote $(PIPS_DATA_ROOT) --known-on $(shell date -u +%F)

s1-smoke: ## Stage-1 screening smoke run on fixtures (§6 M12 Verify)
	$(PY) -m pips.cli s1-smoke fixtures

s1-search: ## Run successive halving over A01 variants and RECORD every trial [C-TRIAL-01]
	$(PY) -m pips.cli s1-search fixtures $(CURDIR)/build/s1-search/registry.db

s5-smoke: ## Search every alpha family, promote the winners, and run S5 across them [C-S5-01]
# Fresh registry, for the reason spelled out under certify-smoke: an append-only registry
# reused across invocations reports a multiplicity that counts how often somebody ran the demo.
	rm -rf $(CURDIR)/build/s5-smoke
	$(PY) -m pips.cli s5-smoke fixtures $(CURDIR)/build/s5-smoke/registry.db

s5-smoke-wide: ## s5-smoke on a wider cross-section (8 symbols), generated on demand
	rm -rf $(CURDIR)/build/s5-wide
	$(PY) -m pips.cli fixtures generate --wide $(CURDIR)/build/fixtures-wide
	$(PY) -m pips.cli s5-smoke $(CURDIR)/build/fixtures-wide $(CURDIR)/build/s5-wide/registry.db

certify-smoke: ## Nominate, screen, and report the distance to a certified bundle (§6 M20 Verify)
# FRESH REGISTRY EVERY RUN. The registry is append-only, so reusing the path accumulates trials
# across invocations: the multiplicity climbs with the number of times somebody ran the demo,
# and S5 can select a row written by an OLDER VERSION OF THE CODE. A smoke run must describe
# the run, not the history of the directory. (Rule 4 is about a research cycle's ledger, which
# lives on the VM -- not about a scratch path under build/.)
	rm -rf $(CURDIR)/build/certify-smoke
	$(PY) -m pips.cli certify-smoke fixtures $(CURDIR)/build/certify-smoke/registry.db

backtest-smoke: ## Event-engine backtest smoke run on fixtures (M14)
	@echo "backtest-smoke: not implemented until M14"; exit 1

parity: ## Python/Rust byte-equality replay for DAY=<day> (M24)
	@test -n "$(DAY)" || { echo "usage: make parity DAY=2026-06-01"; exit 2; }
	@echo "parity: not implemented until M24"; exit 1

clean: ## Remove build and test caches
	rm -rf .pytest_cache .mypy_cache .ruff_cache target
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

# ---- CI controller (ADR-0007). Infrastructure for the repo, never an arb-vm service. ----
JENKINS_COMPOSE := docker compose -f ops/jenkins/docker-compose.yml
JENKINS_URL ?= http://127.0.0.1:8081
REF ?= main

.PHONY: provenance ci-container s1-search s5-smoke s5-smoke-wide
.PHONY: jenkins-up jenkins-down jenkins-logs jenkins-build install-hooks

jenkins-up: ## Build and start the pips Jenkins controller (loopback :8081)
	PIPS_REPO=$(CURDIR) $(JENKINS_COMPOSE) up -d --build
	@echo "pips Jenkins starting at $(JENKINS_URL) (user: pips)"

jenkins-down: ## Stop the controller (keeps its home volume)
	$(JENKINS_COMPOSE) down

jenkins-logs: ## Tail controller logs
	$(JENKINS_COMPOSE) logs -f --tail=100

jenkins-build: ## Trigger the pips-ci job for REF=<branch> and wait for the verdict
	@ops/jenkins/trigger.sh "$(REF)"

install-hooks: ## Install the pre-push gate (Jenkins must be green before a push leaves)
	@git config core.hooksPath ops/git-hooks
	@echo "hooksPath -> ops/git-hooks; pre-push now runs pips-ci for the current branch"
