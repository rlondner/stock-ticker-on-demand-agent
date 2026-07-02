.PHONY: dev test seed snapshot smoke clean agent-local

ifeq ($(OS),Windows_NT)
  BASH := "C:/Program Files/Git/bin/bash.exe"
else
  BASH := bash
endif

AGENT_PY := $(if $(wildcard agent/.venv/Scripts/python.exe),.venv/Scripts/python.exe,.venv/bin/python)

dev:
	pnpm dev

test:
	pnpm test
	cd agent && .venv/bin/pytest

seed:
	pnpm exec tsx --env-file=.env scripts/apply_migration.mts

snapshot:
	$(BASH) ./scripts/build_snapshot.sh

smoke:
	$(BASH) ./scripts/smoke.sh

agent-local:
	cd agent && ./$(AGENT_PY) analyze.py $(TICKER)
