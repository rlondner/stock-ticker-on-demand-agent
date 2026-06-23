.PHONY: dev test seed snapshot smoke clean

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
