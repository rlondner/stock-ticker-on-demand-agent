.PHONY: dev test seed snapshot smoke clean

dev:
	pnpm dev

test:
	pnpm test
	cd agent && .venv/bin/pytest

seed:
	pnpm exec tsx scripts/apply_migration.ts

snapshot:
	./scripts/build_snapshot.sh

smoke:
	./scripts/smoke.sh
