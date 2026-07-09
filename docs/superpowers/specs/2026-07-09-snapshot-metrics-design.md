# Design: Snapshot (yfinance) metrics

**Date:** 2026-07-09
**Status:** Approved (design), pending implementation plan
**Scope:** Agent (`agent/`). Instrument `fetch_snapshot` (the yfinance market-data
fetch in `agent/lib/finance.py`) with custom metrics, using the unified
metrics facade (`agent/lib/metrics.py`).

## Background

`agent/lib/finance.py::fetch_snapshot` fetches a per-ticker market-data snapshot
from yfinance (price, previous close, market cap, 52-week range, analyst
recommendation, etc.) and is the source of the "Current Price" shown on the
analysis page. It currently emits **traces** (span attributes `snapshot.fetched`,
`snapshot.close`, `snapshot.change_pct`) and **logs** (`snapshot.missing` on
failure) but **no metrics** — and yfinance's HTTP calls are not captured by
`agent.http.*` (those only wrap the OpenAI client). This design closes that gap.

`fetch_snapshot` has three outcome branches, all preserved:
1. exception → returns `None` (outcome **error**)
2. empty `info` → returns `None` (outcome **missing**)
3. success → returns the `Snapshot` (outcome **success**)

The unified observability transport (OTLP + Sentry, vendor-agnostic) is already in
place; this design adds only new instruments and emit call sites — no transport
changes.

## Metric inventory

All metrics are `ticker`-tagged; `job_id` is never a tag (unbounded cardinality).

| Metric | Type | Tags | Emitted |
|---|---|---|---|
| `agent.snapshot.fetch` | counter | `outcome` (`success`/`missing`/`error`), `ticker` | every fetch |
| `agent.snapshot.fetch.duration_ms` | histogram (ms) | `outcome`, `ticker` | every fetch |
| `agent.snapshot.backfilled` | counter | `ticker` | success where close/previous came from the 5-day history fallback |
| `agent.snapshot.field_missing` | counter | `field`, `ticker` | once per null key-field, on success only |
| `agent.snapshot.completeness` | histogram | `ticker` | populated key-field count (0–12), on success only |

**Duration** is measured over the whole `fetch_snapshot` call (including tenacity
retries) — the user-facing latency — not per attempt.

**Key fields** (the 12 nullable yfinance-sourced fields on `Snapshot`):
`company_name, sector, industry, close, previous_close, market_cap,
fifty_two_week_high, fifty_two_week_low, average_volume, analyst_recommendation,
analyst_opinion_count, business_summary`.
`currency`, `as_of`, and derived `change_pct` are excluded (always set / derived).
`field` is a bounded tag (~12 values) → safe Datadog custom-metric cardinality.

## Components & data flow

### `agent/lib/metrics.py` (new facade functions)

Follow the existing `record_*` pattern (each fans out to an OTel instrument via
`_add`/`_hist` **and** the Sentry mirror via `_sentry_incr`/`_sentry_dist`; all
guarded so a metrics failure never propagates). Add four instruments in
`init_metrics` and four functions:

- `record_snapshot_fetch(outcome: str, ticker: str, duration_ms: float)` — emits
  the `agent.snapshot.fetch` counter (attrs `{outcome, ticker}`) **and** the
  `agent.snapshot.fetch.duration_ms` histogram (attrs `{outcome, ticker}`).
- `record_snapshot_backfilled(ticker: str)` — counter `agent.snapshot.backfilled`
  (attrs `{ticker}`).
- `record_snapshot_field_missing(field: str, ticker: str)` — counter
  `agent.snapshot.field_missing` (attrs `{field, ticker}`).
- `record_snapshot_completeness(populated: int, ticker: str)` — histogram
  `agent.snapshot.completeness` (attrs `{ticker}`).

`metrics.py` stays generic — it does NOT know the `Snapshot` shape; the key-field
list and iteration live in `finance.py`.

### `agent/lib/finance.py`

- Add `from . import metrics` and a module-level `_SNAPSHOT_KEY_FIELDS` tuple (the
  12 fields above).
- `_fetch_snapshot_once` return type changes from `Snapshot | None` to
  `tuple[Snapshot | None, bool]` — the bool is `backfilled` (True when the 5-day
  history fallback supplied close or previous_close). This lets `fetch_snapshot`
  (the orchestrator) own **all** metric emission and know whether the fallback ran.
- `fetch_snapshot` wraps the call in a `time.monotonic()` timer and, in each of its
  three existing branches, emits `record_snapshot_fetch(outcome, ticker, dur_ms)`
  (keeping the existing span annotations and `emit_log` calls). On success it also:
  - emits `record_snapshot_backfilled(ticker)` if `backfilled`;
  - iterates `_SNAPSHOT_KEY_FIELDS`, calling `record_snapshot_field_missing(field,
    ticker)` for each `None` field and counting populated fields, then emits
    `record_snapshot_completeness(populated, ticker)`.

Ticker is passed explicitly to every `record_snapshot_*` call (no reliance on the
metrics contextvar, since `fetch_snapshot` runs before the LLM sets it).

## Error handling

- Every `record_snapshot_*` path is guarded by the facade (no-op when metrics are
  unconfigured), so snapshot metrics can never break the price fetch —
  `fetch_snapshot`'s "never raises / returns None on total failure" contract is
  preserved.
- No transport changes: reuses the unified OTLP + Sentry pipeline.

## Testing (TDD)

- **`metrics.py`** (`agent/tests/test_metrics.py`): `InMemoryMetricReader` asserts
  each new instrument records the expected value + attributes; extend the
  `job_id`-never-a-tag guard to cover the four new metrics.
- **`finance.py`** (`agent/tests/test_finance.py`), with `yfinance` mocked:
  - exception path → `outcome=error`, duration recorded, returns `None`;
  - empty `info` → `outcome=missing`, returns `None`;
  - success → `outcome=success` + duration;
  - success where close came from the history fallback → `backfilled` emitted;
  - a partial snapshot (some key fields `None`) → `field_missing` for exactly the
    null fields and `completeness` = 12 − (missing count);
  - a fully-populated snapshot → no `field_missing`, `completeness` = 12.
- **Cardinality guard:** a test asserting `job_id` is absent from every new metric.

## Out of scope

- No change to the traces or logs `fetch_snapshot` already emits, beyond keeping
  them intact.
- No change to the Next.js frontend (the price render is unaffected).
- No new yfinance data fields or product behavior — instrumentation only.

## Risks

- Changing `_fetch_snapshot_once`'s return shape touches its existing tests; the
  plan updates them alongside the change.
- `field` tag cardinality is bounded by the fixed key-field list; adding fields
  later grows it by at most one value each — acceptable.
