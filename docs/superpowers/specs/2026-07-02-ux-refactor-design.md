---
title: UX Refactor — AlphaFlow Shell Across Home, New Analysis, Done Analysis
date: 2026-07-02
status: draft
purpose: Refactor the app's three user-facing screens to match the AlphaFlow terminal mocks, sharing a common sidebar+topbar shell and leaving unimplemented artifacts as visible no-op placeholders.
---

# UX Refactor — AlphaFlow Shell

## 1. Purpose

Reshape the three user-facing screens of the Daytona stock-agent demo to match the AlphaFlow mocks in `designs/`:

- `designs/dashboard.html` → Home (`/`)
- `designs/analysis_new.html` → New Analysis (`/analyze`, new route)
- `designs/analysis_done.html` → Done Analysis (`/jobs/[id]`, moved into the shell)

`designs/dashboard.html` is the authoritative source for the sidebar and topbar on **all three** screens. Elements in the mocks that aren't backed by real functionality (Account, Logout, top-nav tabs, search, notifications, settings, avatar, static market widgets, Analysis Depth buttons, "How it works", "View Report", "Upgrade Now", table pagination chevrons, more-vert row menu) are rendered for design fidelity but perform no action.

The API surface (`/api/jobs`, `/api/status/[jobId]`, `/api/cleanup`), the agent code, the database schema, and the runtime dispatcher are all untouched. This refactor is scoped to the NextJS presentation layer and one new component tree.

## 2. Decisions

| # | Decision | Choice | Why |
|---|---|---|---|
| D1 | Route for New Analysis | Dedicated route `/analyze` | Deep-linkable, shareable, matches the mock's full-page feel; sidebar "Analysis" link and Home "New Analysis" CTA both target it |
| D2 | Shared shell placement | Route group `app/(app)/` with shared `layout.tsx` | Idiomatic App Router; sidebar/topbar don't remount across navigations; the "which pages get chrome" question is a directory boundary, not a runtime check |
| D3 | Running status pill | Add a fourth "Running" pill (secondary-container green family) alongside Pending / Complete / Failed | Users can distinguish "queued" from "actively executing"; small honest divergence from the mock's three-state table |
| D4 | Done-page bento | Full visual fidelity, sample static data for widgets we don't produce (Current Price, Revenue Distribution, Analyst Sentiment) | Fastest to ship, closest to design; the header, summary, and Key Insights are wired to real payload |
| D5 | `/admin` scope | Unchanged; stays outside the `(app)` group | Not one of the mocked screens; useful for triage/QA; keeps refactor scope small |
| D6 | Analysis Depth (Quick/Deep/Full) | Rendered as a placeholder selector; visual selection only; default = Quick Scan; value is NOT sent to the API | Preserves the mock's UI; no plumbing changes needed to `/api/jobs` or the agent |
| D7 | Design tokens | Add Material-3-style AlphaFlow tokens as CSS custom properties in `globals.css` via a new `@theme` block; use as Tailwind classes (`bg-af-surface-container-low`, etc.) | Keeps shadcn primitives intact; token names document intent; no per-component hardcoded hex |
| D8 | Fonts / icons | Keep the existing `next/font` Geist Sans + Geist Mono; add Material Symbols Outlined via `<link>` in the `(app)` layout only; **drop Inter** even though the mock uses it | Avoids a second body font; Geist covers both display and body; Material Symbols is required for the mock's icon set |
| D9 | 500-with-jobId submit behavior | Route the user to the failed job page (`/jobs/[jobId]`) so they can inspect the error card, in addition to showing the inline error before redirect | Small deviation from today's "stay on the form" behavior; better failure discoverability |
| D10 | Company-name lookup on Done page | Out of scope; H3 line under the ticker reuses the ticker | We have no name-lookup source in the current schema; adding one is a separate feature |
| D11 | Fewer-than-4 signals on Done page | Render only the signals present; no filler cards; if `signals.length === 0`, show a single muted "no insights yet" line | Honest empty state; avoids fake content |
| D12 | Table pagination on Home | Show "Showing N of M" using `count(*)`; chevrons are inert; only the first 10 rows fetched | Matches the mock's chrome without introducing real pagination |
| D13 | Mobile behavior | Sidebar hidden below `md` (mirrors the mock's `hidden md:flex`); main content readable stand-alone; no hamburger menu | Matches the mocks; a real mobile pattern is a follow-up |
| D14 | Dark mode | Out of scope; mocks are light-only; existing shadcn dark tokens stay untouched | The mocks' dark variants are placeholder classes; a full dark palette is a separate design |
| D15 | `SubmitForm` on Home | Removed; the only entry point to a new analysis is the sidebar CTA or `/analyze` | Single source of truth for the flow; the redirect from `/analyze` remains `router.push("/jobs/[id]")` as today |

## 3. File layout

```
app/
├── layout.tsx                       (unchanged in structure; keeps next/font + globals.css)
├── globals.css                      (+ new @theme block with AlphaFlow tokens)
├── page.tsx                         DELETED
├── (app)/                           NEW route group; owns the AlphaFlow shell
│   ├── layout.tsx                   renders <Sidebar/> + <Topbar/> + main canvas
│   ├── page.tsx                     Home (dashboard)
│   ├── analyze/page.tsx             New Analysis
│   └── jobs/[id]/page.tsx           Done Analysis (moved from app/jobs/[id]/page.tsx)
├── jobs/[id]/page.tsx               DELETED (moved into (app)/jobs/[id])
├── admin/page.tsx                   unchanged; not inside (app)
└── api/                             unchanged

components/
├── app-shell/                       NEW
│   ├── sidebar.tsx                  server; renders links + CTA + footer
│   ├── sidebar-nav-link.tsx         client; usePathname() for active state
│   ├── topbar.tsx                   server; brand + placeholder tabs + inert search cluster
│   └── new-analysis-cta.tsx         client Link to /analyze
├── dashboard/                       NEW
│   ├── welcome.tsx                  Market Overview + Active Portfolios + Weekly Volume (static)
│   ├── ai-sentiment-card.tsx        primary-container hero card (static)
│   ├── top-gainers-card.tsx         (static)
│   ├── market-risk-card.tsx         (static)
│   └── recent-activity.tsx          real; server-fetched jobs; row → /jobs/[id]
├── analyze/                         NEW
│   ├── ticker-search.tsx            client; input + Enter-to-submit
│   ├── suggested-tickers.tsx        client; chips fill the input
│   ├── depth-selector.tsx           client; visual only; default Quick Scan
│   └── launch-form.tsx              client; owns state + submit path
├── job/                             NEW
│   ├── stock-header.tsx             ticker + status + rec + static current-price line
│   ├── key-insights.tsx             real; maps signals[] to icon cards
│   ├── revenue-distribution.tsx     static sample bento panel
│   ├── analyst-sentiment.tsx        static sample bento panel
│   └── job-live-poller.tsx          client; polls /api/status/[id]; swaps in done body
├── job-detail.tsx                   DELETED (replaced by components/job/*)
├── jobs-list.tsx                    DELETED (replaced by components/dashboard/recent-activity.tsx)
├── submit-form.tsx                  DELETED (replaced by components/analyze/launch-form.tsx)
└── ui/                              existing shadcn primitives unchanged
```

## 4. Shared shell

### 4.1 `(app)/layout.tsx`
```tsx
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <main className="flex-1 flex flex-col overflow-y-auto bg-af-surface">
        <Topbar />
        <div className="p-xl max-w-container-max mx-auto w-full">{children}</div>
      </main>
    </div>
  );
}
```
Material Symbols `<link>` is added in the `<head>` via this layout only, so `/admin` doesn't load it.

### 4.2 Sidebar
Server component. Renders the brand block, two real nav links (`Home` → `/`, `Analysis` → `/analyze`) using `<SidebarNavLink>` (client, `usePathname()` for the active-state left border and `bg-af-surface-container-low`), the `New Analysis` CTA button, and an inert footer group (Account, Logout). Icons use Material Symbols Outlined names from the mock (`dashboard`, `analytics`, `account_circle`, `logout`). The `PRO Access` upsell card that appears in `analysis_new.html`'s sidebar is intentionally **not** ported — `dashboard.html` is authoritative for sidebar contents.

### 4.3 Topbar
Server component. Brand wordmark on the left, five inert nav tabs (Dashboard/Market/Portfolio/Watchlist/Alerts) with Dashboard visually active, and on the right an inert search input, `notifications` and `settings` icon buttons, and an inert avatar image. The mock's search input is rendered but disabled and has no onChange; it does not filter or navigate.

### 4.4 Tokens (globals.css)
```css
@theme {
  --color-af-surface: #f8f9ff;
  --color-af-surface-container-lowest: #ffffff;
  --color-af-surface-container-low: #eff4ff;
  --color-af-surface-container: #e5eeff;
  --color-af-surface-container-high: #dce9ff;
  --color-af-on-surface: #0b1c30;
  --color-af-on-surface-variant: #45464d;
  --color-af-outline-variant: #c6c6cd;
  --color-af-primary: #000000;
  --color-af-on-primary: #ffffff;
  --color-af-primary-container: #131b2e;
  --color-af-on-primary-container: #7c839b;
  --color-af-secondary: #006c49;
  --color-af-secondary-container: #6cf8bb;
  --color-af-on-secondary-container: #00714d;
  --color-af-error: #ba1a1a;
  --color-af-error-container: #ffdad6;
  --color-af-on-error-container: #93000a;
  --color-af-signal-buy: #10b981;
  --color-af-signal-hold: #f59e0b;
  --color-af-signal-sell: #ef4444;

  --spacing-xs: 4px;
  --spacing-sm: 8px;
  --spacing-md: 16px;
  --spacing-lg: 24px;
  --spacing-xl: 32px;
  --spacing-container-max: 1280px;
}
```
Consumed as `bg-af-surface`, `text-af-on-surface-variant`, `p-xl`, `max-w-container-max`, etc. Existing shadcn tokens (`bg-background`, `text-foreground`, `border-border`) are untouched; new AlphaFlow surfaces use the new tokens.

## 5. Screen mappings

### 5.1 Home — `app/(app)/page.tsx`
Server component. Fetches:
```
db.select({id, ticker, status, recommendation, createdAt})
  .from(jobs)
  .where(eq(jobs.userId, "demo-user"))
  .orderBy(desc(jobs.createdAt))
  .limit(10)
```
and `db.select({count: sql`count(*)`}).from(jobs).where(...)` for the "Showing N of M" line.

Layout:
- Welcome section (real title, static portfolio/volume cards)
- Bento row: `AiSentimentCard` (col-span-8) + column of `TopGainersCard` + `MarketRiskCard` (col-span-4)
- `RecentActivity` table (col-span-12) with pagination footer

The mock's page-bottom footer ("© 2024 AlphaFlow Research. Market data delayed by 15 mins." + Privacy / Terms / Data Attribution links) is **not** ported — it's static disclaimer chrome, not part of the demo's story, and it doesn't appear on the other two mocked screens.

Row click target: `/jobs/[id]`. `more_vert` is an inert button on each row.

Status pill classes (used on Home rows and on the Done page header):
- `pending` → `bg-af-surface-container-high text-af-on-surface-variant` · "Pending"
- `running` → `bg-af-secondary-container text-af-on-secondary-container` · "Running"
- `complete` → `bg-af-primary-container text-af-on-primary` · "Complete"
- `failed` → `bg-af-error-container text-af-on-error-container` · "Failed"

Signal pill (only when `recommendation` is set):
- `buy` → `bg-af-signal-buy text-white` · "BUY"
- `hold` → `bg-af-signal-hold text-white` · "HOLD"
- `sell` → `bg-af-signal-sell text-white` · "SELL"

Timestamp format matches the mock: `Jun 14, 2024 · 09:12:04 EST`. Formatted server-side with `new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", … })` so there's no client hydration mismatch.

### 5.2 New — `app/(app)/analyze/page.tsx`
Server component wrapper; body is `<LaunchForm>` (client) containing `<TickerSearch>`, `<SuggestedTickers>`, `<DepthSelector>`, and footer actions.

- **Ticker input** — controlled, uppercase, `maxLength=5`, validated with `/^[A-Z]{1,5}$/`. Same validation as today's `SubmitForm`.
- **Suggested tickers** — chips NVDA / AAPL / MSFT / TSLA / AMD. Click fills the input and focuses it.
- **Analysis Depth** — three buttons (Quick Scan · Deep Dive · Full Report). Default selected: Quick Scan. Selection is local state only; NOT sent to the API.
- **Header close X** — inert (page is deep-linked; there's no modal to close).
- **"How it works"** — inert.
- **"Cancel"** — `<Link href="/">`.
- **"Launch AI Agent"** — `POST /api/jobs {ticker}`. Button shows "Launching…" and disables during the transition.
- **Bottom info cards** ("SEC Compliance", "Data Integrity") — static.

### 5.3 Done — `app/(app)/jobs/[id]/page.tsx`
Server component fetches the row exactly like today's `app/jobs/[id]/page.tsx`, serializes `Date`s to ISO strings, and hands `initialJob` to `<JobLivePoller>` (client). The poller keeps today's contract: `GET /api/status/[jobId]` every 2.5s until `status ∈ {complete, failed}`.

Sections rendered (top → bottom):
1. **Stock header** — H2 ticker + status pill + rec pill (if any); H3 line reuses the ticker (D10); `result.summary` paragraph; right-aligned static Current Price block ("$342.15 −1.24%").
2. **Key Insights** — 4-card grid populated from `result.signals[]`; icons cycle `psychology`, `trending_up`, `warning`, `groups` by index; each card shows label (uppercase), evidence, and — if `signal.source` is a valid URL — a `Source →` link that opens the URL in a new tab (`target="_blank" rel="noreferrer"`); when `signal.source` is null or unparseable, the link line is omitted. If `signals.length < 4`, render only the ones present. If `signals.length === 0`, render a single muted "No insights yet" line spanning the grid.
3. **Revenue Distribution bento** (col-span-8) — static sample bars (Atlas 66% / Enterprise 28% / Services 6%).
4. **Analyst Sentiment bento** (col-span-4) — static sample progress bars + quote.

State overlays:
- `pending` / `running` — same header layout with `[Pending]` or `[Running]` pill; a compact "Sandbox `{sandboxId ?? "spawning…"}` · Xs elapsed" hint under the header; skeleton placeholders (`bg-af-surface-container-low animate-pulse`) for Key Insights + bento.
- `failed` — header with `[Failed]` pill; an `bg-af-error-container` card with `<pre>{job.error}</pre>` (truncation is optional at this stage); Key Insights + bento hidden.
- `complete` — full render as above.

"Last updated" line above Key Insights: `job.completedAt` formatted like the mock ("Oct 24, 2023") if present; otherwise "Just now".

## 6. Data flow

- **Home** — single server render; two DB queries (rows + count). `export const dynamic = "force-dynamic"`. No client polling on Home; freshness comes from navigation.
- **New** — no data fetch on render. `POST /api/jobs { ticker }` on submit; `router.push(/jobs/${jobId})` on 200 or on 500-with-jobId (D9).
- **Done** — one DB fetch on the server; then 2.5s polling on the client until terminal state (same code path as today's `JobDetail`).

`/api/jobs/route.ts`, `/api/status/[jobId]/route.ts`, `lib/runtime/*`, `lib/daytona.ts`, and the agent are all unchanged by this refactor.

## 7. Error handling

| Scenario | Behavior |
|---|---|
| Ticker validation fails | Inline error line under the ticker input; button stays enabled; no request sent |
| `POST /api/jobs` → 400 | Inline error line from `body.error`; stay on `/analyze` |
| `POST /api/jobs` → 500 (with `jobId`) | Inline error line briefly; then `router.push(/jobs/${jobId})` so the user lands on the failed job page with the error card visible (D9) |
| `POST /api/jobs` → network error / no `jobId` | Inline error line "Submit failed"; stay on `/analyze` |
| Unknown job id on `/jobs/[id]` | `notFound()` (Next default 404); no custom art |
| `GET /api/status/[jobId]` non-200 | Silently retry on next 2.5s tick; unchanged from today |
| Job completes with empty `signals[]` | Key Insights grid shows single muted "No insights yet" line; bento unchanged |
| Job completes with missing `result.summary` | H3 area renders the ticker only (no summary paragraph); everything else renders |

## 8. Testing

**New unit tests (Vitest + Testing Library):**

- `tests/components/status-pill.test.tsx` — table of `[status, expectedLabel, expectedClasses]` for pending/running/complete/failed; catches token drift and the "running vs pending" mapping regression.
- `tests/components/signal-pill.test.tsx` — `buy` → BUY / green, `hold` → HOLD / amber, `sell` → SELL / red; null → not rendered.
- `tests/components/depth-selector.test.tsx` — clicking a button moves the "selected" ring; the submitted payload (spied via mock fetch on the parent) does NOT include `depth`.
- `tests/components/launch-form.test.tsx` — mock `fetch` and `useRouter`; assert POST body `{ticker: "AAPL"}` on submit; assert `router.push("/jobs/xyz")` on 200; assert inline error on 400; assert inline error AND `router.push("/jobs/xyz")` on 500-with-jobId.
- `tests/components/job-live-poller.test.tsx` — mocked fetch sequence pending → running → complete; interval clears on terminal state; failed shows error card; pending/running shows skeleton.
- `tests/components/recent-activity.test.tsx` — fixture of 4 jobs (one per status, one with recommendation, one without); assert row order, pill classes, and timestamp format.

**Existing tests kept green:**
- `tests/daytona.test.ts` — no change (API and lib unchanged)
- `tests/runtime.test.ts`, `tests/runtime.subprocess.test.ts`, `tests/runtime.subprocess.integration.test.ts` — no change

**Manual verification (PR description checklist):**
- [ ] Submit a ticker end-to-end (`AGENT_RUNTIME=subprocess` for speed) and confirm Done page moves through `Pending → Running → Complete`
- [ ] Refresh Home after a submit and confirm the new row appears in Recent Activity
- [ ] Confirm sidebar highlight moves between `/` and `/analyze`
- [ ] Confirm every placeholder is truly no-op: Account, Logout, topbar tabs, topbar search, notifications, settings, avatar, Analysis Depth buttons (visually select only), "How it works", "Cancel-X" close on `/analyze`, table `more_vert`, "View Report" on Market Risk, pagination chevrons, footer links
- [ ] Trigger a failure (bad ticker in subprocess mode or force `sandbox_spawn_failed`) and confirm the redirect-to-failed-job behavior lands on `/jobs/[id]` with the error card
- [ ] Verify sub-`md` viewport hides the sidebar and main content is readable

## 9. Out of scope

- Real Market / Portfolio / Watchlist / Alerts data
- Real avatar, notifications, settings, auth
- Depth-aware agent behavior (D6)
- Company-name lookup (D10)
- Table pagination beyond the first 10 (D12)
- `/admin` restyle (D5)
- Dark mode (D14)
- Mobile hamburger menu (D13)
- Toast system for errors (inline is sufficient)
- Real-time push (polling remains 2.5s)

## 10. Success criteria

- `pnpm dev` renders the three screens with the AlphaFlow shell and matches the mocks visually at ≥ `md` viewport.
- Submitting a ticker from `/analyze` navigates to the Done page and shows Pending → Running → Complete over the actual polling cycle.
- All new unit tests pass; existing suites pass without edits.
- No new dependencies beyond a Material Symbols `<link>` in the `(app)` layout head.
- `/admin` still renders unchanged.
- No `console.warn`/`error` on any of the three screens with fully-populated real data.
