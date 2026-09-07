# One (withone.ai) Completion Notifications — Design

**Date:** 2026-09-07
**Status:** approved, pending implementation plan

## 1. Motivation

The README lists "Real authentication (schema is multi-user-ready; auth provider
is not wired)" as intentionally out of scope, and the hackathon brief calls for
leveraging One (withone.ai) — "managed auth and integrations behind a
four-command CLI." One is **not** an end-user login provider (no Auth0/Clerk-style
signup/session flow); it's a managed-credential layer that gives an application
authenticated access to third-party platforms (Slack, Gmail, Stripe, etc.) via
its CLI or an MCP server — there is no documented plain REST API.

This design uses One for what it actually is: when a stock analysis job
completes, the app notifies the requester via a One-connected Slack channel or
Gmail address, configured per submission. It does not add end-user login (that
remains a separate, unaddressed gap) and does not add a new CrewAI research
tool (that was considered and explicitly deferred — see §7).

## 2. Scope

**In scope:**
- Per-job notification configuration (`none` / `slack` / `gmail` + a
  destination) submitted alongside the ticker/depth.
- A NextJS-side integration with the One CLI (`@withone/cli`), triggered from
  the existing job-status polling mechanism when a job is first observed as
  `complete`.
- A `notified_at` column preventing duplicate sends across repeated polls.
- A small "Notified via Slack/Gmail" UI badge once sent.

**Out of scope:**
- End-user login/auth for the app itself (unrelated to One; a separate,
  still-unaddressed gap).
- Using One as a new research tool for the CrewAI crew (considered, deferred —
  smaller, more certain payoff to start with delivery rather than research).
- Retrying a failed notification send (see §4's explicit tradeoff).
- Any UI/API for the operator to manage/rotate their One connection — that
  remains a one-time manual `one connect` step per the CLI's own docs.

## 3. Architecture & data flow

```
LaunchForm: "Notify me when done" → none | slack | gmail + destination
   │
   ▼
POST /api/jobs { ticker, depth, notifyChannel?, notifyDestination? }
   │  insert jobs row (notify_channel, notify_destination, notified_at=NULL)
   ▼
... existing job flow unchanged (Daytona/subprocess → agent.py → mark_complete) ...
   ▼
Browser polls GET /api/status/[jobId] every 2.5s (existing mechanism, unchanged cadence)
   │  when status=='complete' AND notify_channel IS NOT NULL AND notified_at IS NULL:
   │    1. atomically claim: UPDATE jobs SET notified_at=now()
   │       WHERE id=$1 AND notified_at IS NULL RETURNING id
   │    2. if claimed: call lib/notify/one.ts, which shells out to the One CLI
   │       (npx --no-install @withone/cli actions execute ...)
   │    3. return the row with notified_at populated in the same response
   ▼
JobLivePoller (client) sees notifiedAt set on the same tick status turns
"complete" (polling stops once status is terminal) → renders a badge
```

No changes to the Python agent or the Daytona snapshot image: the One CLI
requires Node 18+, and the Daytona sandbox is a bare `python:3.12-slim` image.
NextJS is already Node, so the trigger lives entirely on that side.

**Claim-before-send tradeoff (explicit):** the atomic `UPDATE ... WHERE
notified_at IS NULL RETURNING id` guarantees at-most-one delivery attempt even
under concurrent polls, at the cost of no automatic retry if the One CLI call
itself fails (bad connection key, One API outage, transient network error).
This mirrors the existing `mark_complete`/`mark_failed` "claim via SQL guard"
idiom already used in `agent/lib/db.py`. A failed send is logged
(`notify.one.failed`) but the job stays permanently "notified" from the app's
perspective — acceptable for a best-effort demo notification, not something
acceptable for a billing receipt.

## 4. Schema & API changes

### DB migration (`db/migrations/0003_add_notify.sql`)

```sql
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS notify_channel TEXT
  CHECK (notify_channel IN ('slack','gmail') OR notify_channel IS NULL);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS notify_destination TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS notified_at TIMESTAMPTZ;
```

All three nullable, no default — old rows have no notification configured and
are never eligible for the claim check (`notify_channel IS NULL` short-circuits
it in application code before any UPDATE is attempted).

### Drizzle schema (`lib/db/schema.ts`)

```ts
notifyChannel: text("notify_channel"),       // "slack" | "gmail" | null
notifyDestination: text("notify_destination"),
notifiedAt: timestamp("notified_at", { withTimezone: true }),
```
```ts
export type NotifyChannel = "slack" | "gmail";
```

### API (`app/api/jobs/route.ts`)

Extend the zod `Body`:
```ts
notifyChannel: z.enum(["slack", "gmail"]).optional(),
notifyDestination: z.string().optional(),
```
with refinements:
- `notifyChannel` set ⇒ `notifyDestination` required.
- `notifyChannel === "gmail"` ⇒ `notifyDestination` matches a basic email
  regex (`/^[^\s@]+@[^\s@]+\.[^\s@]+$/`).
- `notifyChannel === "slack"` ⇒ `notifyDestination` matches
  `/^[#@][\w-]+$/` (a channel starting with `#` or a user starting with `@`).
- If `notifyChannel` is set but `ONE_SECRET` is unset on the server, reject
  with 400 (`"notifications are not configured on this server"`) — no
  separate feature-availability endpoint; the existing `LaunchForm` error
  banner already surfaces submit errors.

### `GET /api/status/[jobId]`

After fetching the row: if `status === "complete" && notify_channel &&
!notified_at`, attempt the atomic claim; on success, call
`sendCompletionNotification(...)` (awaited, for logging, but its failure never
changes the HTTP response) and return the row with `notifiedAt` set to the
claimed timestamp in the same response (no second DB round-trip needed to
reflect it to the client).

## 5. One CLI invocation (`lib/notify/one.ts`)

### Operator-level config (`.env.example`)

```
# One (withone.ai) — completion notifications. Leave ONE_SECRET unset to
# disable the feature entirely (submit requests with notifyChannel set are
# rejected with 400).
ONE_SECRET=
# Run `one connect slack` / `one connect gmail` once as the operator, then
# `one actions search slack "send message"` / `one actions search gmail
# "send email"` to find the actionId + connectionKey for the two pairs below.
ONE_SLACK_CONNECTION_KEY=
ONE_SLACK_SEND_ACTION_ID=
ONE_GMAIL_CONNECTION_KEY=
ONE_GMAIL_SEND_ACTION_ID=
```

The `actionId`s are opaque per-account identifiers from One's own action
catalog — not something to hardcode without a live account. This is the same
"verify against the real system" pattern already used for the Daytona SDK and
CrewAI's API surface in the prior feature, just at config-time instead of
code-time.

### The helper

```ts
export async function sendCompletionNotification(job: {
  ticker: string;
  recommendation: string | null;
  summary: string | undefined;
  notifyChannel: "slack" | "gmail";
  notifyDestination: string;
}): Promise<void>
```

Builds the channel-specific payload (`{channel, text}` for Slack;
`{to, subject, body}` for Gmail), resolves the matching `actionId`/
`connectionKey` pair from env, and runs:
```ts
execFile("npx", [
  "--no-install", "@withone/cli", "actions", "execute",
  app, actionId, connectionKey, "-d", JSON.stringify(payload), "--agent",
], { env: { ...process.env, ONE_SECRET: process.env.ONE_SECRET } })
```
`@withone/cli` is added as a regular `package.json` dependency (not solely
relied upon via `npx`'s auto-install) so `--no-install` always resolves it
locally — no network fetch or version drift on every job completion. Never
throws to its caller: logs `notify.one.sent`/`notify.one.failed` (mirroring
the existing `Sentry.logger`/`ddLog` dual-sink pattern already used in
`lib/daytona.ts`) and swallows all errors.

## 6. Frontend

- **New component** `components/analyze/notify-picker.tsx`: a controlled
  component (same pattern as `DepthSelector`) — a channel select (`None` /
  `Slack` / `Gmail`) plus a conditionally-shown destination text input, with
  client-side validation mirroring the API's two regexes (fail fast, same
  error text as the server would give).
- **`LaunchForm`**: adds `notifyChannel`/`notifyDestination` state, renders
  `<NotifyPicker>` alongside `<DepthSelector>`, passes both into
  `submitAnalysis`.
- **`submitAnalysis`/`SubmitParams`** (`lib/analyze/submit-analysis.ts`):
  gains optional `notifyChannel`/`notifyDestination`, included in the POST
  body only when a channel is actually selected (not `"none"`).
- **`SerializedJob`** (`lib/job/types.ts`): gains `notifyChannel:
  NotifyChannel | null`, `notifyDestination: string | null`, `notifiedAt:
  string | null` — documents the existing raw-row pass-through from
  `/api/status/[jobId]`, not new serialization logic.
- **`JobLivePoller`**: in the `job.status === "complete"` branch, renders a
  small pill (styled like the existing `status-pill`/`signal-pill`
  components) reading `"Notified via Slack"` / `"Notified via Gmail"` when
  `job.notifiedAt` is set; renders nothing when it isn't (no notification
  configured, or the send failed silently per §3's tradeoff).

## 7. Alternatives considered

- **One as a new CrewAI research tool** (e.g. a Gmail-search tool for the
  Researcher/Risk Analyst agents) — considered and explicitly deferred.
  Smaller, more certain payoff to ship notification delivery first; a
  research-tool integration touches the crew's prompt design and adds a sixth
  external dependency to the already-complex deep-analysis tier.
- **Triggering from the Python agent** (adding Node.js to the Daytona
  snapshot so `agent.py` could call the One CLI directly after
  `mark_complete`) — rejected: grows the snapshot image and boot time to add
  a second language runtime to what's currently a pure-Python sandbox, for no
  benefit over triggering from the already-Node NextJS side via the existing
  polling mechanism.
- **A direct One REST API call from Python** (avoiding both of the above) —
  investigated and ruled out: One does not document a plain HTTP/REST API:
  only the CLI and an MCP server are supported integration surfaces.
- **Operator-level (not per-job) destination config** — considered as the
  simpler MVP, but the user chose per-job configuration for flexibility
  (different tickers/analyses can notify different channels/people).

## 8. Testing plan

- **NextJS:**
  - `tests/api.jobs.test.ts` extended: notify-field validation (missing
    destination when channel set, malformed email/Slack destination,
    `ONE_SECRET` unset → 400).
  - `tests/api.status.notify.test.ts` (new): mocks the One helper —
    claim-then-send fires exactly once across two rapid polls, never fires
    when `notify_channel` is null or `notified_at` is already set, a thrown
    error from the CLI call doesn't affect the HTTP response or propagate.
  - `tests/lib/notify-one.test.ts` (new): payload shape per channel, env-var
    resolution per channel, swallows CLI failures (mocked `execFile`).
  - `NotifyPicker` has no automated render test — same test-infrastructure
    gap as `DepthSelector` (no jsdom/`@testing-library/react` in this repo);
    verified manually via `pnpm dev`, consistent with the prior feature's
    precedent.
- **Manual/e2e:** requires a real `ONE_SECRET` plus one connected Slack/Gmail
  account (not available in a sandboxed build environment) — submit a job
  with notification configured, confirm exactly one message/email arrives
  once the job completes, and confirm a second poll after completion does
  not send a duplicate.
