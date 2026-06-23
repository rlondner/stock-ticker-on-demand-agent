.PHONY: dev test seed snapshot smoke clean agent-local

AGENT_PY := $(if $(wildcard agent/.venv/Scripts/python.exe),.venv/Scripts/python.exe,.venv/bin/python)

dev:
	pnpm dev

test:
	pnpm test
	cd agent && .venv/bin/pytest

seed:
	pnpm exec tsx --env-file=.env scripts/apply_migration.mts

snapshot:
	bash ./scripts/build_snapshot.sh

smoke:
	bash ./scripts/smoke.sh

agent-local:
	cd agent && ./$(AGENT_PY) analyze.py $(TICKER)
