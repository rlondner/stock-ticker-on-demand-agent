# Final review fix report

## SDK inspection results

### Node — `@sentry/nextjs` (via `node_modules/@sentry/core/build/types/metrics/public-api.d.ts`)
Real API:
```ts
count(name: string, value?: number, options?: MetricOptions): void;
distribution(name: string, value: number, options?: MetricOptions): void;
gauge(name: string, value: number, options?: MetricOptions): void;
```
`MetricOptions` has `attributes?: Metric['attributes']`. NO `increment`, NO `incr`, NO `tags` key.

### Python — `sentry_sdk.metrics` (via `agent/.venv/bin/python -c "import sentry_sdk, inspect; ..."`)
```
dir(sentry_sdk.metrics) → [..., 'count', 'distribution', 'gauge', ...]
inspect.signature(sentry_sdk.metrics.count)       → (name, value, unit=None, attributes=None) -> None
inspect.signature(sentry_sdk.metrics.distribution) → (name, value, unit=None, attributes=None) -> None
```
NO `incr` method. NO `tags=` parameter. Correct params are `attributes=`.

---

## C1 — Sentry API bug (Node + Python)

### Node `lib/observability/metrics.ts`
Changed `sentryIncr` to call `Sentry?.metrics?.count?.(key, value, { attributes: tags })`.
Was: `Sentry?.metrics?.increment?.(key, value, { tags })` — `increment` does not exist.

### Python `agent/lib/metrics.py`
- `_sentry_incr`: changed `hasattr(m, "incr") / m.incr(key, value, tags=tags)` → `hasattr(m, "count") / m.count(key, value, attributes=tags)`.
- `_sentry_dist`: changed `m.distribution(key, value, tags=tags)` → `m.distribution(key, value, attributes=tags)`.

### Node test `tests/observability.metrics.test.ts`
Dropped `vi.mock("@sentry/nextjs", ...)` (discovered it does NOT intercept CJS `require()` in
vitest 4.1.10 — only ESM imports are intercepted; `require()` returns the real module).
Instead: import `* as SentryNextjs from "@sentry/nextjs"` and use `vi.spyOn(SentryNextjs.metrics, "count")`,
which spies on the same object the CJS `require()` returns (same cached module instance).
Also set `SENTRY_DSN_NEXTJS` at file scope (above the `import { initMetrics }`) so
`sentryEnabled=true` from the first `initMetrics()` call.
Added assertion: `count` is called with `("jobs.submitted", 1, { attributes: { outcome, ticker } })`.

### Python test `agent/tests/test_metrics.py` — new test `test_sentry_mirror_calls_count_with_attributes`
Reloads `lib.metrics`, sets `SENTRY_DSN_AGENT`, inits metrics, then monkeypatches
`sentry_sdk.metrics.count` and `sentry_sdk.metrics.distribution` with capturing lambdas.
Asserts: `record_job_completed` → `count("jobs.completed", 1, attributes={"final_status":..., "ticker":"AAPL"})`.
Asserts: `record_agent_run_duration` → `distribution("agent.run.duration_ms", ..., attributes=...)`.
Asserts `job_id` never appears in attributes.

---

## #7 — OTEL.md doc drift

`OTEL.md` line 42: `sentry-sdk[opentelemetry]>=2.15.0` → `>=2.44.0` (matches `agent/requirements.txt`).

---

## I1 — `llm.web_search.used` moved to success path

`agent/lib/llm.py`: removed `metrics.record_llm_web_search(api, ticker)` from before the
`responses.create(...)` call. Added it after `parse_response(text)` succeeds, inside the
`if self._use_responses_api:` branch, before `record_llm_call(..., "ok", ...)`.
Effect: the metric is emitted only on a successful, non-empty responses-API call (not on
retry/failure), still never on the chat.completions branch.

---

## I2 — New tests in `agent/tests/test_llm.py`

### `test_chat_completions_branch_emits_tokens_and_call`
Uses a fake client with `_use_responses_api=False`. Asserts:
- `record_llm_tokens` called with `api="chat.completions"`, correct token counts.
- `record_llm_call` called with `api="chat.completions"`, `outcome="ok"`.
- `record_llm_web_search` NOT called (list remains empty).

### `test_empty_response_emits_record_llm_empty_response`
Calls `_require_nonempty("", ...)` directly with `api="chat.completions"`, asserts
`record_llm_empty_response("gpt-4.1-mini", "chat.completions", "NVDA")` is invoked
and `EmptyLLMResponseError` is raised.

---

## Test results

```
cd agent && .venv/bin/python -m pytest tests/test_metrics.py tests/test_llm.py -v
============================= 36 passed in 10.83s ==============================

npx vitest run tests/observability.metrics.test.ts tests/api.jobs.test.ts
 Test Files  2 passed (2)
      Tests  7 passed (7)
```

---

## Deviations from findings guidance

- **Node Sentry test mock strategy**: The findings suggested mocking `{ count, distribution, gauge }` via `vi.mock`. Discovered that `vi.mock` does NOT intercept CJS `require()` calls in Vitest 4.1.10 (only ESM imports are intercepted). Used `vi.spyOn` on the real `SentryNextjs.metrics` object imported via ESM (`import * as SentryNextjs from "@sentry/nextjs"`), which shares the same cached instance as the CJS `require()`. This is more robust: it proves the actual runtime code path calls the correct method.
- All other changes match findings guidance exactly.
