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

ci: lint typecheck tdd-check test rust-test determinism ledger-check ## The full ladder Jenkins runs
	@echo "ci: green"

refs-extract: ## Cache pandoc extractions of docs/reference/*.docx (needs pandoc)
	@mkdir -p docs/reference/_extracted
	@for f in docs/reference/*.docx; do \
	  out="docs/reference/_extracted/$$(basename "$$f" .docx).md"; \
	  echo "  $$f -> $$out"; \
	  pandoc -t markdown --wrap=none "$$f" -o "$$out"; \
	done

qc: ## Data quality control over the silver zone (M5)
	@echo "qc: not implemented until M5"; exit 1

s1-smoke: ## Stage-1 screening smoke run on fixtures (§6 M12 Verify)
	$(PY) -m pips.cli s1-smoke fixtures

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
