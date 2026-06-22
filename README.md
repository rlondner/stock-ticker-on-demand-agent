# Daytona Stock-Agent Demo

A demo showing short-lived AI agents hosted in Daytona sandboxes. A user submits
a stock ticker; an ephemeral Daytona VM runs an OpenAI agent that produces a
buy/hold/sell analysis; the NextJS app polls Neon Postgres until the result is ready.

See `docs/superpowers/specs/2026-06-22-daytona-stock-agent-design.md` for the design,
and `docs/superpowers/plans/2026-06-22-daytona-stock-agent.md` for the implementation plan.

## Quickstart

1. Copy `.env.example` to `.env` and fill in required vars.
2. `pnpm install`
3. `make seed` — applies migrations to Neon
4. `make snapshot` — builds and publishes the Daytona snapshot
5. `pnpm dev` — start NextJS at http://localhost:3000
