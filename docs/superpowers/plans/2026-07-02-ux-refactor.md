# UX Refactor — AlphaFlow Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wrap the app's three user-facing screens (Home, New Analysis, Done Analysis) in a shared AlphaFlow sidebar+topbar shell that matches `designs/dashboard.html`, `designs/analysis_new.html`, and `designs/analysis_done.html`, keeping unimplemented mock artifacts as visible no-op placeholders.

**Architecture:** New route group `app/(app)/` owns the shared `<Sidebar />` + `<Topbar />` layout. `/admin` stays outside, unchanged. Pure logic (status-pill classes, signal-pill classes, timestamp formatting, submit orchestration, signal→insight mapping) lives in `lib/**` and is unit-tested with the existing Vitest node runner. Components render markup only.

**Tech Stack:** Next 16 (App Router) · React 19 · Tailwind CSS v4 (via shadcn) · TypeScript · Drizzle ORM · Vitest (node env) · pnpm

**Testing note:** Vitest is configured `environment: "node"`, `include: ["tests/**/*.test.ts"]`. No jsdom / RTL. This plan tests pure logic as `.test.ts` files and verifies component composition via a manual smoke pass at the end.

**Reference spec:** [`docs/superpowers/specs/2026-07-02-ux-refactor-design.md`](../specs/2026-07-02-ux-refactor-design.md)

---

## Prerequisites

Working directory: repo root. Node/pnpm installed. `pnpm install` already run.

Run `pnpm test` and `pnpm build` at the start of the plan to confirm the baseline is green:

```bash
pnpm test
pnpm build
```

Expected: `pnpm test` prints all-green; `pnpm build` compiles without new errors (the pre-existing `lib/runtime/subprocess.ts` tsc warnings are OK and unrelated).

If either fails for reasons unrelated to this plan, stop and investigate before continuing.

---

## Task 1: Add AlphaFlow design tokens to globals.css

**Files:**
- Modify: `app/globals.css`

- [ ] **Step 1: Add the `@theme` block with AlphaFlow tokens**

Open `app/globals.css`. After the existing `:root { ... }` block (after line 84, before the `.dark { ... }` block), insert a new Tailwind v4 `@theme` block. Tailwind v4 CSS-first config makes these tokens available as Tailwind utility classes automatically.

Add exactly this block:

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

  --spacing-af-xs: 4px;
  --spacing-af-sm: 8px;
  --spacing-af-md: 16px;
  --spacing-af-lg: 24px;
  --spacing-af-xl: 32px;

  --container-af-max: 1280px;
}
```

**Why prefix everything with `af-`:** avoids clashes with the existing shadcn `--color-primary`, `--color-secondary`, etc. Tailwind v4's `@theme` merges token names into utility classes, so `--color-af-surface` becomes `bg-af-surface`, `text-af-surface`, etc.

- [ ] **Step 2: Verify Tailwind picks up the tokens**

```bash
pnpm build 2>&1 | tail -20
```

Expected: the build compiles. If Tailwind reports an unknown class later in the plan (`bg-af-surface`, etc.), it means the token wasn't picked up — check the `@theme` block's location and syntax.

- [ ] **Step 3: Commit**

```bash
git add app/globals.css
git commit -m "$(cat <<'EOF'
feat(styles): add AlphaFlow design tokens for Home/New/Done shells

Adds a @theme block with Material-3-style surface/on-surface/container/
error/signal tokens under an af- prefix so they don't collide with the
existing shadcn palette. Tailwind v4 exposes these as utility classes
(bg-af-surface, text-af-on-surface-variant, ...).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Move existing pages into the (app) route group

**Files:**
- Create: `app/(app)/layout.tsx` (thin wrapper — full shell wired in Task 3)
- Create: `app/(app)/page.tsx` (moved from `app/page.tsx`)
- Create: `app/(app)/jobs/[id]/page.tsx` (moved from `app/jobs/[id]/page.tsx`)
- Create: `app/(app)/analyze/page.tsx` (temporary placeholder body)
- Delete: `app/page.tsx`
- Delete: `app/jobs/[id]/page.tsx` (whole `app/jobs/` folder removed)

- [ ] **Step 1: Create the (app) layout with a temporary body wrapper**

Create `app/(app)/layout.tsx`:

```tsx
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return <div className="min-h-screen bg-af-surface">{children}</div>;
}
```

This is intentionally minimal in Task 2 — full sidebar+topbar comes in Task 3.

- [ ] **Step 2: Move Home into (app)**

Copy `app/page.tsx` content to `app/(app)/page.tsx`, then delete the original.

```bash
mkdir -p 'app/(app)'
git mv app/page.tsx 'app/(app)/page.tsx'
```

Note: on some shells the parentheses in `app/(app)/` need quoting. If `git mv` complains, do it in two steps: `mv` with quotes, then `git add -A`.

- [ ] **Step 3: Move Job detail into (app)**

```bash
mkdir -p 'app/(app)/jobs/[id]'
git mv app/jobs/[id]/page.tsx 'app/(app)/jobs/[id]/page.tsx'
rmdir app/jobs/[id] app/jobs
```

- [ ] **Step 4: Create the placeholder /analyze page**

Create `app/(app)/analyze/page.tsx`:

```tsx
export default function AnalyzePage() {
  return (
    <main className="p-8 max-w-3xl mx-auto">
      <h1 className="text-2xl font-bold">Analyze</h1>
      <p className="text-sm text-slate-500">Full form wired up in Task 11.</p>
    </main>
  );
}
```

- [ ] **Step 5: Smoke-test the routing**

```bash
pnpm dev
```

In a browser, hit:
- `http://localhost:3000/` → renders today's dashboard (SubmitForm + JobsList)
- `http://localhost:3000/analyze` → renders "Analyze / Full form wired up in Task 11."
- `http://localhost:3000/jobs/00000000-0000-0000-0000-000000000000` → 404 for unknown id (expected)
- `http://localhost:3000/admin` → unchanged (raw table)

Kill dev server (Ctrl+C).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
refactor(app): move Home and Job pages into (app) route group

Introduces the app/(app)/ route group with a thin layout wrapper so the
shared AlphaFlow shell (Task 3) can own sidebar+topbar without touching
/admin. Adds a placeholder /analyze route stub. No visual changes yet.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Build the sidebar + topbar shell and wire into (app) layout

**Files:**
- Create: `components/app-shell/sidebar-nav-link.tsx`
- Create: `components/app-shell/new-analysis-cta.tsx`
- Create: `components/app-shell/sidebar.tsx`
- Create: `components/app-shell/topbar.tsx`
- Modify: `app/(app)/layout.tsx`

- [ ] **Step 1: Create the active-link client helper**

Create `components/app-shell/sidebar-nav-link.tsx`:

```tsx
"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

export function SidebarNavLink({
  href,
  icon,
  label,
}: {
  href: string;
  icon: string;
  label: string;
}) {
  const pathname = usePathname();
  const isActive = href === "/" ? pathname === "/" : pathname.startsWith(href);
  const baseClasses =
    "flex items-center gap-4 px-4 py-2 rounded-lg font-semibold text-sm transition-all";
  const activeClasses =
    "text-af-on-surface bg-af-surface-container-low border-l-2 border-af-primary";
  const inactiveClasses =
    "text-af-on-surface-variant hover:bg-af-surface-container-low";
  return (
    <Link href={href} className={`${baseClasses} ${isActive ? activeClasses : inactiveClasses}`}>
      <span className="material-symbols-outlined">{icon}</span>
      <span>{label}</span>
    </Link>
  );
}
```

- [ ] **Step 2: Create the New Analysis CTA**

Create `components/app-shell/new-analysis-cta.tsx`:

```tsx
import Link from "next/link";

export function NewAnalysisCta() {
  return (
    <Link
      href="/analyze"
      className="mt-8 mb-8 w-full block text-center bg-af-primary-container text-af-on-primary py-3 px-6 rounded-lg font-semibold text-sm hover:opacity-90 transition-opacity"
    >
      New Analysis
    </Link>
  );
}
```

- [ ] **Step 3: Create the sidebar (server component)**

Create `components/app-shell/sidebar.tsx`:

```tsx
import { SidebarNavLink } from "./sidebar-nav-link";
import { NewAnalysisCta } from "./new-analysis-cta";

export function Sidebar() {
  return (
    <aside className="hidden md:flex flex-col h-screen w-64 bg-af-surface-container-lowest border-r border-af-outline-variant px-4 py-6">
      {/* Brand block */}
      <div className="flex items-center gap-4 mb-8">
        <div className="w-10 h-10 rounded-full bg-af-primary flex items-center justify-center text-af-on-primary">
          <span className="material-symbols-outlined">monitoring</span>
        </div>
        <div>
          <h1 className="text-2xl font-extrabold text-af-on-surface tracking-tight">AlphaFlow</h1>
          <p className="text-[12px] text-af-on-surface-variant uppercase tracking-widest">
            Research Terminal
          </p>
        </div>
      </div>

      {/* Real nav links */}
      <nav className="flex-1 space-y-2">
        <SidebarNavLink href="/" icon="dashboard" label="Home" />
        <SidebarNavLink href="/analyze" icon="analytics" label="Analysis" />
      </nav>

      <NewAnalysisCta />

      {/* Inert footer group */}
      <div className="pt-8 border-t border-af-outline-variant space-y-2">
        <button
          type="button"
          className="flex items-center gap-4 px-4 py-2 w-full text-af-on-surface-variant hover:bg-af-surface-container-low transition-all rounded-lg font-semibold text-sm"
        >
          <span className="material-symbols-outlined">account_circle</span>
          <span>Account</span>
        </button>
        <button
          type="button"
          className="flex items-center gap-4 px-4 py-2 w-full text-af-error hover:bg-af-surface-container-low transition-all rounded-lg font-semibold text-sm"
        >
          <span className="material-symbols-outlined">logout</span>
          <span>Logout</span>
        </button>
      </div>
    </aside>
  );
}
```

Note: Account and Logout are `<button>` elements without an onClick handler — they render but perform no action, matching the spec's placeholder rule.

- [ ] **Step 4: Create the topbar (server component)**

Create `components/app-shell/topbar.tsx`:

```tsx
export function Topbar() {
  return (
    <header className="sticky top-0 z-10 bg-af-surface-container-lowest border-b border-af-outline-variant px-4 h-16 flex justify-between items-center w-full max-w-af-max mx-auto">
      <div className="flex items-center gap-8">
        <span className="text-2xl font-extrabold text-af-on-surface tracking-tight">AlphaFlow</span>
        <nav className="hidden lg:flex items-center gap-6">
          <span className="text-af-on-surface font-bold border-b-2 border-af-primary pb-1 text-sm">
            Dashboard
          </span>
          {["Market", "Portfolio", "Watchlist", "Alerts"].map((tab) => (
            <button
              key={tab}
              type="button"
              className="text-af-on-surface-variant pb-1 text-sm hover:text-af-on-surface transition-colors"
            >
              {tab}
            </button>
          ))}
        </nav>
      </div>
      <div className="flex items-center gap-6">
        <div className="relative">
          <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-af-on-surface-variant pointer-events-none">
            search
          </span>
          <input
            type="text"
            placeholder="Analyze tickers (e.g. NVDA)..."
            disabled
            className="pl-10 pr-4 py-2 bg-af-surface-container-low border border-af-outline-variant rounded-full text-sm w-64 outline-none cursor-not-allowed"
          />
        </div>
        <div className="flex items-center gap-4">
          <button type="button" className="text-af-on-surface-variant hover:text-af-on-surface transition-colors">
            <span className="material-symbols-outlined">notifications</span>
          </button>
          <button type="button" className="text-af-on-surface-variant hover:text-af-on-surface transition-colors">
            <span className="material-symbols-outlined">settings</span>
          </button>
          <div className="w-8 h-8 rounded-full bg-af-surface-container-high border border-af-outline-variant" aria-hidden />
        </div>
      </div>
    </header>
  );
}
```

Avatar image is intentionally a plain div — no external image dependency, and it's a placeholder anyway.

- [ ] **Step 5: Wire Sidebar + Topbar + Material Symbols into the (app) layout**

Rewrite `app/(app)/layout.tsx` to:

```tsx
import { Sidebar } from "@/components/app-shell/sidebar";
import { Topbar } from "@/components/app-shell/topbar";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      {/* Material Symbols only loaded for AlphaFlow-shell pages; /admin doesn't get it */}
      <link
        rel="stylesheet"
        href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap"
      />
      <div className="flex h-screen overflow-hidden">
        <Sidebar />
        <main className="flex-1 flex flex-col overflow-y-auto bg-af-surface">
          <Topbar />
          <div className="p-8 max-w-af-max mx-auto w-full">{children}</div>
        </main>
      </div>
    </>
  );
}
```

- [ ] **Step 6: Smoke-test the shell**

```bash
pnpm dev
```

Visit `/`, `/analyze`, `/jobs/<any>`. In all three, the sidebar and topbar should render. Sidebar highlight should follow the current path (Home active on `/`, Analysis active on `/analyze`). Click sidebar Home / Analysis and confirm navigation without page reload. Confirm `/admin` still renders with NO shell.

Kill dev server.

- [ ] **Step 7: Commit**

```bash
git add app/'(app)'/layout.tsx components/app-shell
git commit -m "$(cat <<'EOF'
feat(app-shell): add sidebar + topbar to (app) route group

Sidebar has real Home and Analysis links plus a New Analysis CTA that
routes to /analyze. Account, Logout, topbar tabs, topbar search,
notifications, settings, and avatar render as visible no-op placeholders
per the spec. Material Symbols is loaded via <link> in the (app) layout
only, so /admin does not fetch it.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Status pill (pure mapper + component) with TDD

**Files:**
- Create: `tests/components/status-pill.test.ts`
- Create: `lib/ui/status-pill.ts`
- Create: `components/ui/status-pill.tsx`

- [ ] **Step 1: Write the failing test**

Create `tests/components/status-pill.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { statusPillProps } from "@/lib/ui/status-pill";

describe("statusPillProps", () => {
  it("maps pending to a neutral pill", () => {
    expect(statusPillProps("pending")).toEqual({
      label: "Pending",
      className: "bg-af-surface-container-high text-af-on-surface-variant",
    });
  });

  it("maps running to the green secondary pill", () => {
    expect(statusPillProps("running")).toEqual({
      label: "Running",
      className: "bg-af-secondary-container text-af-on-secondary-container",
    });
  });

  it("maps complete to the primary-container dark pill", () => {
    expect(statusPillProps("complete")).toEqual({
      label: "Complete",
      className: "bg-af-primary-container text-af-on-primary",
    });
  });

  it("maps failed to the error-container pill", () => {
    expect(statusPillProps("failed")).toEqual({
      label: "Failed",
      className: "bg-af-error-container text-af-on-error-container",
    });
  });

  it("throws on an unknown status", () => {
    // @ts-expect-error — deliberately invalid
    expect(() => statusPillProps("weird")).toThrow(/unknown status/i);
  });
});
```

- [ ] **Step 2: Run the test and confirm it fails**

```bash
pnpm test tests/components/status-pill.test.ts 2>&1 | tail -20
```

Expected: fails with a module-not-found error for `@/lib/ui/status-pill`.

- [ ] **Step 3: Implement the mapper**

Create `lib/ui/status-pill.ts`:

```ts
export type JobStatus = "pending" | "running" | "complete" | "failed";

export function statusPillProps(status: JobStatus): { label: string; className: string } {
  switch (status) {
    case "pending":
      return { label: "Pending", className: "bg-af-surface-container-high text-af-on-surface-variant" };
    case "running":
      return { label: "Running", className: "bg-af-secondary-container text-af-on-secondary-container" };
    case "complete":
      return { label: "Complete", className: "bg-af-primary-container text-af-on-primary" };
    case "failed":
      return { label: "Failed", className: "bg-af-error-container text-af-on-error-container" };
    default: {
      const _exhaustive: never = status;
      throw new Error(`unknown status: ${String(_exhaustive)}`);
    }
  }
}
```

- [ ] **Step 4: Run the test and confirm it passes**

```bash
pnpm test tests/components/status-pill.test.ts 2>&1 | tail -10
```

Expected: 5 tests pass.

- [ ] **Step 5: Add the component**

Create `components/ui/status-pill.tsx`:

```tsx
import { statusPillProps, type JobStatus } from "@/lib/ui/status-pill";

export function StatusPill({ status }: { status: JobStatus }) {
  const { label, className } = statusPillProps(status);
  return (
    <span className={`inline-block px-3 py-1 rounded-full text-[12px] font-medium ${className}`}>
      {label}
    </span>
  );
}
```

- [ ] **Step 6: Commit**

```bash
git add tests/components/status-pill.test.ts lib/ui/status-pill.ts components/ui/status-pill.tsx
git commit -m "$(cat <<'EOF'
feat(ui): add StatusPill for the four job statuses

Pure statusPillProps() mapper covers the four states with token-based
classes. Component composes the mapper output into a pill span. Adds a
fourth 'Running' pill so the queued vs executing distinction is visible,
per spec D3.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Signal pill (pure mapper + component) with TDD

**Files:**
- Create: `tests/components/signal-pill.test.ts`
- Create: `lib/ui/signal-pill.ts`
- Create: `components/ui/signal-pill.tsx`

- [ ] **Step 1: Write the failing test**

Create `tests/components/signal-pill.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { signalPillProps } from "@/lib/ui/signal-pill";

describe("signalPillProps", () => {
  it("maps buy to green BUY pill", () => {
    expect(signalPillProps("buy")).toEqual({
      label: "BUY",
      className: "bg-af-signal-buy text-white",
    });
  });

  it("maps hold to amber HOLD pill", () => {
    expect(signalPillProps("hold")).toEqual({
      label: "HOLD",
      className: "bg-af-signal-hold text-white",
    });
  });

  it("maps sell to red SELL pill", () => {
    expect(signalPillProps("sell")).toEqual({
      label: "SELL",
      className: "bg-af-signal-sell text-white",
    });
  });

  it("returns null when no recommendation", () => {
    expect(signalPillProps(null)).toBeNull();
  });
});
```

- [ ] **Step 2: Run the test and confirm it fails**

```bash
pnpm test tests/components/signal-pill.test.ts 2>&1 | tail -10
```

Expected: fails with module-not-found.

- [ ] **Step 3: Implement the mapper**

Create `lib/ui/signal-pill.ts`:

```ts
export type Recommendation = "buy" | "hold" | "sell";

export function signalPillProps(
  recommendation: Recommendation | null,
): { label: string; className: string } | null {
  if (recommendation === null) return null;
  switch (recommendation) {
    case "buy":
      return { label: "BUY", className: "bg-af-signal-buy text-white" };
    case "hold":
      return { label: "HOLD", className: "bg-af-signal-hold text-white" };
    case "sell":
      return { label: "SELL", className: "bg-af-signal-sell text-white" };
  }
}
```

- [ ] **Step 4: Run the test and confirm it passes**

```bash
pnpm test tests/components/signal-pill.test.ts 2>&1 | tail -10
```

Expected: 4 tests pass.

- [ ] **Step 5: Add the component**

Create `components/ui/signal-pill.tsx`:

```tsx
import { signalPillProps, type Recommendation } from "@/lib/ui/signal-pill";

export function SignalPill({ recommendation }: { recommendation: Recommendation | null }) {
  const props = signalPillProps(recommendation);
  if (!props) return null;
  return (
    <span className={`inline-block px-6 py-1 rounded-full text-[12px] font-bold ${props.className}`}>
      {props.label}
    </span>
  );
}
```

- [ ] **Step 6: Commit**

```bash
git add tests/components/signal-pill.test.ts lib/ui/signal-pill.ts components/ui/signal-pill.tsx
git commit -m "$(cat <<'EOF'
feat(ui): add SignalPill for BUY/HOLD/SELL

Pure signalPillProps() returns null when no recommendation is set, so
consumers can render conditionally. Component composes the mapper output.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Timestamp formatter with TDD

**Files:**
- Create: `tests/components/format-timestamp.test.ts`
- Create: `lib/ui/format-timestamp.ts`

- [ ] **Step 1: Write the failing test**

Create `tests/components/format-timestamp.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { formatMockTimestamp, formatCompactDate } from "@/lib/ui/format-timestamp";

describe("formatMockTimestamp", () => {
  it("renders the mock's 'Jun 14, 2024 · 09:12:04 EST' shape (ET)", () => {
    // 2024-06-14T13:12:04Z is 09:12:04 EDT (America/New_York).
    // ET-region output shows 'EDT' or 'EST' depending on DST; assert the
    // structural shape rather than the exact abbreviation.
    const out = formatMockTimestamp(new Date("2024-06-14T13:12:04Z"));
    expect(out).toMatch(/^Jun 14, 2024 · 09:12:04 E[SD]T$/);
  });

  it("is stable regardless of the process's local timezone", () => {
    // Same instant as above; confirms the formatter forces America/New_York
    const out = formatMockTimestamp(new Date(Date.UTC(2024, 5, 14, 13, 12, 4)));
    expect(out).toMatch(/^Jun 14, 2024 ·/);
  });
});

describe("formatCompactDate", () => {
  it("renders the mock's 'Oct 24, 2023' shape (no time)", () => {
    expect(formatCompactDate(new Date("2023-10-24T18:00:00Z"))).toBe("Oct 24, 2023");
  });
});
```

- [ ] **Step 2: Run the test and confirm it fails**

```bash
pnpm test tests/components/format-timestamp.test.ts 2>&1 | tail -10
```

Expected: fails with module-not-found.

- [ ] **Step 3: Implement the formatter**

Create `lib/ui/format-timestamp.ts`:

```ts
const MOCK_FMT = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  year: "numeric",
  month: "short",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
  timeZoneName: "short",
});

/** Format like the AlphaFlow mock: "Jun 14, 2024 · 09:12:04 EST". */
export function formatMockTimestamp(date: Date): string {
  const parts = MOCK_FMT.formatToParts(date);
  const p = (t: string) => parts.find((x) => x.type === t)?.value ?? "";
  const month = p("month");
  const day = p("day");
  const year = p("year");
  const hour = p("hour");
  const minute = p("minute");
  const second = p("second");
  const tz = p("timeZoneName");
  return `${month} ${day}, ${year} · ${hour}:${minute}:${second} ${tz}`;
}

const COMPACT_FMT = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  year: "numeric",
  month: "short",
  day: "2-digit",
});

/** Format like "Oct 24, 2023" — no time component. */
export function formatCompactDate(date: Date): string {
  return COMPACT_FMT.format(date);
}
```

- [ ] **Step 4: Run the test and confirm it passes**

```bash
pnpm test tests/components/format-timestamp.test.ts 2>&1 | tail -10
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/components/format-timestamp.test.ts lib/ui/format-timestamp.ts
git commit -m "$(cat <<'EOF'
feat(ui): add timezone-stable timestamp formatters

formatMockTimestamp() renders the 'Jun 14, 2024 · 09:12:04 EST' shape
used in Recent Activity; formatCompactDate() renders the 'Oct 24, 2023'
shape used on the Done page. Both force America/New_York so server
rendering matches the client and there's no hydration mismatch.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Recent Activity component (real data)

**Files:**
- Create: `components/dashboard/recent-activity.tsx`
- Delete: `components/jobs-list.tsx`

- [ ] **Step 1: Peek at the jobs schema for the exact column shape**

Read `lib/db/client.ts` and confirm the columns available on `jobs`: `id`, `ticker`, `status`, `recommendation`, `createdAt`, `userId`, plus the ones we don't need here (`sandboxId`, `result`, `error`, `startedAt`, `completedAt`). This informs the Drizzle select.

```bash
grep -E "id:|ticker:|status:|recommendation:|createdAt:|userId:" lib/db/client.ts
```

Expected: confirms the fields exist.

- [ ] **Step 2: Create RecentActivity**

Create `components/dashboard/recent-activity.tsx`:

```tsx
import Link from "next/link";
import { desc, eq, sql } from "drizzle-orm";
import { db, jobs } from "@/lib/db/client";
import { StatusPill } from "@/components/ui/status-pill";
import { SignalPill } from "@/components/ui/signal-pill";
import { formatMockTimestamp } from "@/lib/ui/format-timestamp";
import type { JobStatus } from "@/lib/ui/status-pill";
import type { Recommendation } from "@/lib/ui/signal-pill";

const PAGE_SIZE = 10;

export async function RecentActivity() {
  const rows = await db
    .select({
      id: jobs.id,
      ticker: jobs.ticker,
      status: jobs.status,
      recommendation: jobs.recommendation,
      createdAt: jobs.createdAt,
    })
    .from(jobs)
    .where(eq(jobs.userId, "demo-user"))
    .orderBy(desc(jobs.createdAt))
    .limit(PAGE_SIZE);

  const totalRows = await db
    .select({ count: sql<number>`count(*)::int` })
    .from(jobs)
    .where(eq(jobs.userId, "demo-user"));
  const total = totalRows[0]?.count ?? rows.length;

  return (
    <section className="col-span-12">
      <div className="bg-af-surface-container-lowest border border-af-outline-variant rounded-xl overflow-hidden">
        <div className="px-8 py-6 border-b border-af-outline-variant">
          <h3 className="text-2xl font-semibold text-af-on-surface">Recent Activity</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-af-surface-container-low">
                <th className="px-8 py-4 text-[12px] font-semibold text-af-on-surface-variant uppercase tracking-wider">Ticker</th>
                <th className="px-8 py-4 text-[12px] font-semibold text-af-on-surface-variant uppercase tracking-wider">Analysis Status</th>
                <th className="px-8 py-4 text-[12px] font-semibold text-af-on-surface-variant uppercase tracking-wider">Signal</th>
                <th className="px-8 py-4 text-[12px] font-semibold text-af-on-surface-variant uppercase tracking-wider">Timestamp</th>
                <th className="px-8 py-4 text-[12px] font-semibold text-af-on-surface-variant uppercase tracking-wider text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-af-outline-variant">
              {rows.length === 0 && (
                <tr>
                  <td className="px-8 py-8 text-af-on-surface-variant text-sm" colSpan={5}>
                    No analyses yet. Click "New Analysis" to start.
                  </td>
                </tr>
              )}
              {rows.map((r) => (
                <tr key={r.id} className="hover:bg-af-surface-container-low transition-colors">
                  <td className="px-8 py-6">
                    <Link href={`/jobs/${r.id}`} className="flex items-center gap-4">
                      <div className="w-8 h-8 rounded bg-af-surface-container-high flex items-center justify-center font-bold text-af-on-surface">
                        {r.ticker.charAt(0)}
                      </div>
                      <span className="font-bold text-af-on-surface">{r.ticker}</span>
                    </Link>
                  </td>
                  <td className="px-8 py-6">
                    <StatusPill status={r.status as JobStatus} />
                  </td>
                  <td className="px-8 py-6">
                    <SignalPill recommendation={r.recommendation as Recommendation | null} />
                  </td>
                  <td className="px-8 py-6 text-sm text-af-on-surface-variant">
                    {formatMockTimestamp(r.createdAt)}
                  </td>
                  <td className="px-8 py-6 text-right">
                    <button
                      type="button"
                      aria-label="row actions"
                      className="p-2 text-af-on-surface-variant hover:text-af-on-surface rounded-full hover:bg-af-surface-container transition-all"
                    >
                      <span className="material-symbols-outlined">more_vert</span>
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="px-8 py-4 bg-af-surface-container-low flex items-center justify-between">
          <p className="text-[12px] text-af-on-surface-variant">
            Showing {rows.length} of {total} analysis jobs
          </p>
          <div className="flex gap-2">
            <button type="button" aria-label="previous page" className="p-1 text-af-on-surface-variant hover:text-af-on-surface">
              <span className="material-symbols-outlined">chevron_left</span>
            </button>
            <button type="button" aria-label="next page" className="p-1 text-af-on-surface-variant hover:text-af-on-surface">
              <span className="material-symbols-outlined">chevron_right</span>
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
```

Note: pagination chevrons are inert per spec D12. The row click target is the whole ticker cell; making the row a `<tr>` link inside is illegal HTML.

- [ ] **Step 3: Temporarily wire RecentActivity into the (app) Home so it renders**

Modify `app/(app)/page.tsx` to import and render RecentActivity ONLY (the rest of the dashboard comes in Task 8). Replace the current file with:

```tsx
import { RecentActivity } from "@/components/dashboard/recent-activity";

export const dynamic = "force-dynamic";

export default function Home() {
  return (
    <div className="grid grid-cols-12 gap-6">
      <RecentActivity />
    </div>
  );
}
```

- [ ] **Step 4: Smoke-test**

```bash
pnpm dev
```

Visit `/`. Confirm the Recent Activity table renders with the correct pills and timestamps. Submit a ticker via `/analyze` (still the placeholder form) — no, that won't submit yet. Alternative: use the existing subprocess runtime and hit the API directly:

```bash
curl -X POST -H "content-type: application/json" -d '{"ticker":"AAPL"}' http://localhost:3000/api/jobs
```

Refresh `/`. The row should appear with a Pending or Running pill. Wait ~30s and refresh again; it should transition to Complete or Failed.

Kill dev server.

- [ ] **Step 5: Delete the old JobsList**

```bash
git rm components/jobs-list.tsx
```

- [ ] **Step 6: Commit**

```bash
git add components/dashboard/recent-activity.tsx app/'(app)'/page.tsx
git commit -m "$(cat <<'EOF'
feat(dashboard): add Recent Activity table backed by real jobs

Server-fetches the last 10 jobs for user 'demo-user', renders StatusPill /
SignalPill / formatMockTimestamp for each row, links the ticker cell to
/jobs/[id]. Pagination chevrons and the row action menu are inert per
spec D12. Replaces the legacy JobsList component; Home is temporarily
just the table until Task 8 adds the bento widgets.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Static dashboard widgets + full Home composition

**Files:**
- Create: `components/dashboard/welcome.tsx`
- Create: `components/dashboard/ai-sentiment-card.tsx`
- Create: `components/dashboard/top-gainers-card.tsx`
- Create: `components/dashboard/market-risk-card.tsx`
- Modify: `app/(app)/page.tsx`

- [ ] **Step 1: Create Welcome**

Create `components/dashboard/welcome.tsx`:

```tsx
export function Welcome() {
  return (
    <section className="col-span-12 mb-8">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <p className="text-sm font-semibold text-af-on-surface-variant uppercase tracking-widest mb-1">
            Equity Research Terminal
          </p>
          <h2 className="text-5xl font-bold text-af-on-surface tracking-tight">Market Overview</h2>
        </div>
        <div className="flex gap-4">
          <div className="px-6 py-4 bg-af-surface-container-lowest border border-af-outline-variant rounded-xl">
            <p className="text-sm text-af-on-surface-variant">Active Portfolios</p>
            <p className="text-2xl font-semibold text-af-on-surface">
              12 <span className="text-af-secondary text-sm">▲ 4.2%</span>
            </p>
          </div>
          <div className="px-6 py-4 bg-af-surface-container-lowest border border-af-outline-variant rounded-xl">
            <p className="text-sm text-af-on-surface-variant">Weekly Volume</p>
            <p className="text-2xl font-semibold text-af-on-surface">
              $1.2M <span className="text-af-error text-sm">▼ 1.8%</span>
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
```

- [ ] **Step 2: Create AiSentimentCard**

Create `components/dashboard/ai-sentiment-card.tsx`:

```tsx
const KPIS = [
  { label: "Volatility Index", value: "14.22" },
  { label: "S&P 500 Peak", value: "5,432" },
  { label: "Yield Curve", value: "4.12%" },
  { label: "Fear/Greed", value: "68/100" },
];

export function AiSentimentCard() {
  return (
    <div className="col-span-12 lg:col-span-8 relative overflow-hidden rounded-xl bg-af-primary-container min-h-[400px] flex flex-col p-8">
      <div className="relative z-10 h-full flex flex-col justify-between">
        <div>
          <h3 className="text-3xl font-semibold text-af-on-primary mb-2">AI Sentiment Score</h3>
          <p className="text-lg text-af-on-primary-container max-w-md">
            Proprietary deep learning analysis of global markets suggests a bullish trend for tech-heavy portfolios over the next quarter.
          </p>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-6 mt-8">
          {KPIS.map((k) => (
            <div key={k.label}>
              <p className="text-[12px] text-af-on-primary-container uppercase">{k.label}</p>
              <p className="text-2xl font-semibold text-af-on-primary">{k.value}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Create TopGainersCard**

Create `components/dashboard/top-gainers-card.tsx`:

```tsx
const GAINERS = [
  { ticker: "TSLA", pct: "+12.4%" },
  { ticker: "NVDA", pct: "+8.2%" },
  { ticker: "PLTR", pct: "+7.1%" },
];

export function TopGainersCard() {
  return (
    <div className="bg-af-surface-container-lowest border border-af-outline-variant rounded-xl p-6 flex flex-col">
      <div className="flex justify-between items-center mb-4">
        <h4 className="text-sm font-semibold text-af-on-surface">Top Gainers</h4>
        <span className="material-symbols-outlined text-af-secondary">trending_up</span>
      </div>
      <div className="space-y-2">
        {GAINERS.map((g) => (
          <div key={g.ticker} className="flex justify-between items-center text-sm">
            <span className="font-bold">{g.ticker}</span>
            <span className="text-af-secondary font-medium">{g.pct}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Create MarketRiskCard**

Create `components/dashboard/market-risk-card.tsx`:

```tsx
export function MarketRiskCard() {
  return (
    <div className="bg-af-surface-container-lowest border border-af-outline-variant rounded-xl p-6 flex flex-col">
      <div className="flex justify-between items-center mb-4">
        <h4 className="text-sm font-semibold text-af-on-surface">Market Risk</h4>
        <span className="material-symbols-outlined text-af-error">warning</span>
      </div>
      <p className="text-sm text-af-on-surface-variant mb-4">
        Exposure to geopolitical tensions in energy sectors has increased significantly this morning.
      </p>
      <button
        type="button"
        className="mt-auto text-af-on-surface font-semibold text-sm flex items-center gap-1 hover:gap-2 transition-all"
      >
        View Report <span className="material-symbols-outlined text-sm">arrow_forward</span>
      </button>
    </div>
  );
}
```

`View Report` button is inert per spec.

- [ ] **Step 5: Compose the Home page**

Rewrite `app/(app)/page.tsx`:

```tsx
import { Welcome } from "@/components/dashboard/welcome";
import { AiSentimentCard } from "@/components/dashboard/ai-sentiment-card";
import { TopGainersCard } from "@/components/dashboard/top-gainers-card";
import { MarketRiskCard } from "@/components/dashboard/market-risk-card";
import { RecentActivity } from "@/components/dashboard/recent-activity";

export const dynamic = "force-dynamic";

export default function Home() {
  return (
    <div className="grid grid-cols-12 gap-6">
      <Welcome />
      <AiSentimentCard />
      <div className="col-span-12 lg:col-span-4 grid grid-rows-2 gap-6">
        <TopGainersCard />
        <MarketRiskCard />
      </div>
      <RecentActivity />
    </div>
  );
}
```

- [ ] **Step 6: Smoke-test**

```bash
pnpm dev
```

Visit `/`. Confirm:
- Welcome section shows Market Overview + Active Portfolios + Weekly Volume
- AI Sentiment hero (col-span-8) + Top Gainers/Market Risk column (col-span-4) render side by side ≥ `lg`
- Recent Activity table below

Kill dev server.

- [ ] **Step 7: Commit**

```bash
git add components/dashboard/ app/'(app)'/page.tsx
git commit -m "$(cat <<'EOF'
feat(dashboard): compose Welcome + bento + Recent Activity on Home

Adds the four static dashboard widgets (Welcome, AiSentimentCard,
TopGainersCard, MarketRiskCard) matching designs/dashboard.html and
composes them on / above the real Recent Activity table. View Report on
Market Risk is inert per the spec's placeholder rule.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Analyze subcomponents (DepthSelector, SuggestedTickers, TickerSearch)

**Files:**
- Create: `components/analyze/depth-selector.tsx`
- Create: `components/analyze/suggested-tickers.tsx`
- Create: `components/analyze/ticker-search.tsx`

These three components are visual + state helpers with no pure logic worth unit-testing. Correctness is verified in Task 11's end-to-end smoke test.

- [ ] **Step 1: Create DepthSelector**

Create `components/analyze/depth-selector.tsx`:

```tsx
"use client";
import { useState } from "react";

const DEPTHS = [
  { key: "quick", icon: "speed", label: "Quick Scan", eta: "~2 mins" },
  { key: "deep", icon: "query_stats", label: "Deep Dive", eta: "~8 mins" },
  { key: "full", icon: "description", label: "Full Report", eta: "~20 mins" },
] as const;

export function DepthSelector() {
  const [selected, setSelected] = useState<(typeof DEPTHS)[number]["key"]>("quick");
  return (
    <div className="space-y-2">
      <label className="text-sm font-semibold text-af-on-surface">Analysis Depth</label>
      <div className="grid grid-cols-3 gap-4">
        {DEPTHS.map((d) => {
          const isSelected = selected === d.key;
          return (
            <button
              key={d.key}
              type="button"
              onClick={() => setSelected(d.key)}
              className={`flex flex-col items-center gap-2 p-6 border-2 rounded-xl text-center transition-all ${
                isSelected
                  ? "border-af-primary bg-af-surface-container-low"
                  : "border-af-outline-variant hover:border-af-primary"
              }`}
            >
              <span
                className={`material-symbols-outlined ${
                  isSelected ? "text-af-on-surface" : "text-af-on-surface-variant"
                }`}
                style={{ fontVariationSettings: isSelected ? "'FILL' 1" : "'FILL' 0" }}
              >
                {d.icon}
              </span>
              <span className={`text-sm font-semibold ${isSelected ? "text-af-on-surface" : "text-af-on-surface-variant"}`}>
                {d.label}
              </span>
              <span className="text-[10px] text-af-on-surface-variant">{d.eta}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
```

Note: `selected` is local state only. Value is never sent to the API — LaunchForm (Task 11) submits only `{ ticker }`. Per spec D6.

- [ ] **Step 2: Create SuggestedTickers**

Create `components/analyze/suggested-tickers.tsx`:

```tsx
"use client";

const SUGGESTED = [
  { ticker: "NVDA", icon: "trending_up" },
  { ticker: "AAPL", icon: "trending_up" },
  { ticker: "MSFT", icon: "trending_up" },
  { ticker: "TSLA", icon: "history" },
  { ticker: "AMD", icon: "history" },
] as const;

export function SuggestedTickers({ onPick }: { onPick: (ticker: string) => void }) {
  return (
    <div className="space-y-2">
      <p className="text-[12px] text-af-on-surface-variant">Suggested Tickers</p>
      <div className="flex flex-wrap gap-2">
        {SUGGESTED.map((s) => (
          <button
            key={s.ticker}
            type="button"
            onClick={() => onPick(s.ticker)}
            className="px-4 py-1 border border-af-outline-variant rounded-full text-sm font-semibold text-af-on-surface-variant transition-all flex items-center gap-1 hover:border-af-on-surface hover:bg-af-surface-container-low"
          >
            <span className="material-symbols-outlined text-[16px]">{s.icon}</span>
            {s.ticker}
          </button>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Create TickerSearch**

Create `components/analyze/ticker-search.tsx`:

```tsx
"use client";
import { forwardRef } from "react";

type Props = {
  value: string;
  onChange: (v: string) => void;
};

export const TickerSearch = forwardRef<HTMLInputElement, Props>(function TickerSearch(
  { value, onChange },
  ref,
) {
  return (
    <div className="space-y-2">
      <label className="text-sm font-semibold text-af-on-surface" htmlFor="ticker-input">
        Stock Ticker
      </label>
      <div className="relative">
        <span className="absolute left-4 top-1/2 -translate-y-1/2 material-symbols-outlined text-af-on-surface-variant">
          search
        </span>
        <input
          ref={ref}
          id="ticker-input"
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value.toUpperCase())}
          maxLength={5}
          placeholder="Enter symbol like TSLA or NVDA"
          className="w-full pl-12 pr-4 py-6 bg-af-surface-container-lowest border border-af-outline-variant rounded-lg focus:ring-2 focus:ring-af-primary focus:border-transparent outline-none transition-all text-base uppercase"
        />
      </div>
    </div>
  );
});
```

`forwardRef` so `LaunchForm` can focus the input after a chip click.

- [ ] **Step 4: Commit**

```bash
git add components/analyze/depth-selector.tsx components/analyze/suggested-tickers.tsx components/analyze/ticker-search.tsx
git commit -m "$(cat <<'EOF'
feat(analyze): add DepthSelector, SuggestedTickers, TickerSearch

Three client subcomponents used by LaunchForm. DepthSelector is purely
visual state (never submitted to the API, per spec D6). SuggestedTickers
calls back into the parent to fill the input. TickerSearch forwards its
ref so the parent can focus the input after a chip pick.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: submitAnalysis orchestrator (pure) with TDD

**Files:**
- Create: `tests/components/submit-analysis.test.ts`
- Create: `lib/analyze/submit-analysis.ts`

This is the load-bearing test in the plan — it covers the four submit branches (200, 400, 500-with-jobId, 500-without-jobId).

- [ ] **Step 1: Write the failing test**

Create `tests/components/submit-analysis.test.ts`:

```ts
import { describe, it, expect, vi } from "vitest";
import { submitAnalysis } from "@/lib/analyze/submit-analysis";

function makeFetch(status: number, body: unknown): typeof fetch {
  return vi.fn(async () => ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  }) as unknown as Response);
}

describe("submitAnalysis", () => {
  it("validates the ticker before hitting the network", async () => {
    const fetchSpy = vi.fn();
    const pushSpy = vi.fn();
    const result = await submitAnalysis({
      ticker: "aaaaaa", // >5 chars — invalid
      fetchImpl: fetchSpy as unknown as typeof fetch,
      push: pushSpy,
    });
    expect(result).toEqual({ ok: false, error: expect.stringMatching(/1[–-]5 uppercase/) });
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(pushSpy).not.toHaveBeenCalled();
  });

  it("posts the uppercased ticker and pushes to /jobs/[id] on 200", async () => {
    const fetchImpl = makeFetch(200, { jobId: "job-1" });
    const push = vi.fn();
    const result = await submitAnalysis({ ticker: "aapl", fetchImpl, push });
    expect(fetchImpl).toHaveBeenCalledWith("/api/jobs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ ticker: "AAPL" }),
    });
    expect(push).toHaveBeenCalledWith("/jobs/job-1");
    expect(result).toEqual({ ok: true, jobId: "job-1" });
  });

  it("returns the server error on 400 and does NOT navigate", async () => {
    const fetchImpl = makeFetch(400, { error: "ticker must be 1-5 uppercase letters" });
    const push = vi.fn();
    const result = await submitAnalysis({ ticker: "AAPL", fetchImpl, push });
    expect(push).not.toHaveBeenCalled();
    expect(result).toEqual({ ok: false, error: "ticker must be 1-5 uppercase letters" });
  });

  it("on 500 with jobId, returns the error AND navigates to the failed job", async () => {
    const fetchImpl = makeFetch(500, { error: "spawn_failed", jobId: "job-x" });
    const push = vi.fn();
    const result = await submitAnalysis({ ticker: "AAPL", fetchImpl, push });
    expect(push).toHaveBeenCalledWith("/jobs/job-x");
    expect(result).toEqual({ ok: false, error: "spawn_failed", jobId: "job-x" });
  });

  it("on 500 without jobId, returns the error and stays on the form", async () => {
    const fetchImpl = makeFetch(500, { error: "internal" });
    const push = vi.fn();
    const result = await submitAnalysis({ ticker: "AAPL", fetchImpl, push });
    expect(push).not.toHaveBeenCalled();
    expect(result).toEqual({ ok: false, error: "internal" });
  });

  it("handles a fetch reject as 'Submit failed'", async () => {
    const fetchImpl = vi.fn(async () => {
      throw new Error("network");
    }) as unknown as typeof fetch;
    const push = vi.fn();
    const result = await submitAnalysis({ ticker: "AAPL", fetchImpl, push });
    expect(push).not.toHaveBeenCalled();
    expect(result).toEqual({ ok: false, error: "Submit failed" });
  });
});
```

- [ ] **Step 2: Run the test and confirm it fails**

```bash
pnpm test tests/components/submit-analysis.test.ts 2>&1 | tail -20
```

Expected: module-not-found.

- [ ] **Step 3: Implement the orchestrator**

Create `lib/analyze/submit-analysis.ts`:

```ts
export type SubmitResult =
  | { ok: true; jobId: string }
  | { ok: false; error: string; jobId?: string };

export type SubmitParams = {
  ticker: string;
  fetchImpl?: typeof fetch;
  push: (path: string) => void;
};

const TICKER_RE = /^[A-Z]{1,5}$/;

export async function submitAnalysis({ ticker, fetchImpl, push }: SubmitParams): Promise<SubmitResult> {
  const doFetch: typeof fetch = fetchImpl ?? fetch;
  const value = ticker.trim().toUpperCase();
  if (!TICKER_RE.test(value)) {
    return { ok: false, error: "Ticker must be 1–5 uppercase letters." };
  }

  let res: Response;
  try {
    res = await doFetch("/api/jobs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ ticker: value }),
    });
  } catch {
    return { ok: false, error: "Submit failed" };
  }

  const body = (await res.json().catch(() => ({}))) as { jobId?: string; error?: string };

  if (res.ok && body.jobId) {
    push(`/jobs/${body.jobId}`);
    return { ok: true, jobId: body.jobId };
  }

  // Non-2xx. If the server still returned a jobId (spawn failure path — see
  // /api/jobs/route.ts D9), route the user to the failed job so they can
  // inspect the error card.
  if (body.jobId) {
    push(`/jobs/${body.jobId}`);
    return { ok: false, error: body.error ?? "Submit failed", jobId: body.jobId };
  }
  return { ok: false, error: body.error ?? "Submit failed" };
}
```

- [ ] **Step 4: Run the test and confirm it passes**

```bash
pnpm test tests/components/submit-analysis.test.ts 2>&1 | tail -10
```

Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/components/submit-analysis.test.ts lib/analyze/submit-analysis.ts
git commit -m "$(cat <<'EOF'
feat(analyze): add submitAnalysis orchestrator with 500-with-jobId path

Pure fn takes fetch + router.push as deps for testability. Validates
locally before hitting the network, uppercases the ticker, navigates to
/jobs/[id] on both 200 and on 500-when-a-jobId-is-returned per spec D9,
and returns a structured result the form can render inline.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Launch form + analyze page assembly

**Files:**
- Create: `components/analyze/launch-form.tsx`
- Modify: `app/(app)/analyze/page.tsx`
- Delete: `components/submit-form.tsx`

- [ ] **Step 1: Create LaunchForm**

Create `components/analyze/launch-form.tsx`:

```tsx
"use client";
import Link from "next/link";
import { useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { TickerSearch } from "./ticker-search";
import { SuggestedTickers } from "./suggested-tickers";
import { DepthSelector } from "./depth-selector";
import { submitAnalysis } from "@/lib/analyze/submit-analysis";

export function LaunchForm() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [ticker, setTicker] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const onPickSuggestion = (t: string) => {
    setTicker(t);
    inputRef.current?.focus();
  };

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    startTransition(async () => {
      const result = await submitAnalysis({ ticker, push: router.push });
      if (!result.ok) setError(result.error);
    });
  };

  return (
    <section className="relative z-10 w-full max-w-2xl mx-auto">
      <form onSubmit={onSubmit} className="bg-af-surface-container-lowest border border-af-outline-variant rounded-xl shadow-lg p-8 space-y-8">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-af-outline-variant pb-6">
          <div>
            <h2 className="text-3xl font-semibold text-af-on-surface">Start New Analysis</h2>
            <p className="text-base text-af-on-surface-variant">
              Configure your research parameters for AI-driven insights.
            </p>
          </div>
          <button
            type="button"
            aria-label="close"
            className="text-af-on-surface-variant hover:text-af-on-surface transition-colors p-2"
          >
            <span className="material-symbols-outlined">close</span>
          </button>
        </div>

        {/* Input section */}
        <div className="space-y-6">
          <TickerSearch ref={inputRef} value={ticker} onChange={setTicker} />
          <SuggestedTickers onPick={onPickSuggestion} />
          <DepthSelector />
        </div>

        {/* Footer actions */}
        <div className="pt-6 border-t border-af-outline-variant flex items-center justify-between gap-4">
          <button
            type="button"
            className="flex items-center gap-2 text-af-on-surface-variant hover:text-af-on-surface transition-colors text-sm font-semibold"
          >
            <span className="material-symbols-outlined">help_outline</span>
            How it works
          </button>
          <div className="flex gap-4">
            <Link
              href="/"
              className="px-8 py-4 border border-af-outline-variant rounded-lg text-sm font-semibold text-af-on-surface hover:bg-af-surface-container-low transition-colors"
            >
              Cancel
            </Link>
            <button
              type="submit"
              disabled={pending}
              className="px-8 py-4 bg-af-primary-container text-af-on-primary rounded-lg text-sm font-semibold hover:opacity-90 transition-colors flex items-center gap-2 shadow-md disabled:opacity-60 disabled:cursor-not-allowed"
            >
              <span className="material-symbols-outlined" style={{ fontVariationSettings: "'FILL' 1" }}>
                smart_toy
              </span>
              {pending ? "Launching…" : "Launch AI Agent"}
            </button>
          </div>
        </div>

        {error && <p className="text-af-error text-sm">{error}</p>}
      </form>

      {/* Info cards */}
      <div className="grid grid-cols-2 gap-6 mt-6">
        <div className="bg-af-surface-container-lowest bg-opacity-80 border border-af-outline-variant p-4 rounded-xl flex items-start gap-4">
          <div className="p-2 bg-af-secondary-container rounded-lg">
            <span className="material-symbols-outlined text-af-on-secondary-container">verified_user</span>
          </div>
          <div>
            <p className="text-sm font-semibold text-af-on-surface">SEC Compliance</p>
            <p className="text-sm text-af-on-surface-variant">
              All agents utilize real-time Edgar filings.
            </p>
          </div>
        </div>
        <div className="bg-af-surface-container-lowest bg-opacity-80 border border-af-outline-variant p-4 rounded-xl flex items-start gap-4">
          <div className="p-2 bg-af-surface-container rounded-lg">
            <span className="material-symbols-outlined text-af-on-surface">hub</span>
          </div>
          <div>
            <p className="text-sm font-semibold text-af-on-surface">Data Integrity</p>
            <p className="text-sm text-af-on-surface-variant">
              Multi-source verification from terminal feeds.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
```

- [ ] **Step 2: Rewrite /analyze to render LaunchForm**

Replace `app/(app)/analyze/page.tsx` with:

```tsx
import { LaunchForm } from "@/components/analyze/launch-form";

export default function AnalyzePage() {
  return (
    <div className="flex items-center justify-center min-h-[70vh]">
      <LaunchForm />
    </div>
  );
}
```

- [ ] **Step 3: Delete the old SubmitForm**

```bash
git rm components/submit-form.tsx
```

- [ ] **Step 4: Smoke-test the submit flow**

Set the local runtime for speed:

```bash
export AGENT_RUNTIME=subprocess  # cmd.exe: set AGENT_RUNTIME=subprocess ; PowerShell: $env:AGENT_RUNTIME='subprocess'
pnpm dev
```

Visit `/analyze`. Confirm:
- Card renders with header, ticker input, chips, depth selector (Quick Scan selected by default), Cancel + Launch buttons, and two info cards below.
- Click NVDA chip → input becomes NVDA, focus moves to input.
- Click Deep Dive → visual selection moves; input value unchanged; page state doesn't otherwise mutate.
- Type "aapl" → input uppercases to AAPL live.
- Click Launch → button reads "Launching…", disables, then navigates to `/jobs/<newId>`.
- Type "aaaaaa" (6 chars, invalid), click Launch → inline error "Ticker must be 1–5 uppercase letters." shows below the form; no navigation.
- Click Cancel → navigates back to `/`.

Kill dev server.

- [ ] **Step 5: Commit**

```bash
git add components/analyze/launch-form.tsx app/'(app)'/analyze/page.tsx
git commit -m "$(cat <<'EOF'
feat(analyze): wire LaunchForm on /analyze with the shared shell

Composes TickerSearch, SuggestedTickers, DepthSelector, footer actions,
and the two info cards from analysis_new.html. Submit uses the tested
submitAnalysis orchestrator, so the 500-with-jobId path lands the user
on the failed job page per spec D9. Cancel is a Link to /. The close X
and How-it-works button are inert placeholders.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Stock header (Done page)

**Files:**
- Create: `components/job/stock-header.tsx`

- [ ] **Step 1: Create StockHeader**

Create `components/job/stock-header.tsx`:

```tsx
import { StatusPill } from "@/components/ui/status-pill";
import { SignalPill } from "@/components/ui/signal-pill";
import type { JobStatus } from "@/lib/ui/status-pill";
import type { Recommendation } from "@/lib/ui/signal-pill";

type Props = {
  ticker: string;
  status: JobStatus;
  recommendation: Recommendation | null;
  summary: string | null;
};

export function StockHeader({ ticker, status, recommendation, summary }: Props) {
  return (
    <section className="flex flex-col md:flex-row md:items-end justify-between gap-6 bg-af-surface-container-lowest p-8 rounded-xl border border-af-outline-variant">
      <div className="space-y-2">
        <div className="flex items-center gap-4">
          <h2 className="text-5xl font-bold text-af-on-surface tracking-tight">{ticker}</h2>
          <StatusPill status={status} />
          <SignalPill recommendation={recommendation} />
        </div>
        <div>
          {/* Spec D10: no company-name lookup; H3 reuses the ticker */}
          <h3 className="text-2xl font-semibold text-af-on-surface">{ticker}</h3>
          {summary && (
            <p className="text-af-on-surface-variant text-base max-w-2xl mt-4">{summary}</p>
          )}
        </div>
      </div>
      <div className="flex flex-col items-end gap-2">
        {/* Static sample per spec D4 */}
        <div className="text-right">
          <p className="text-[12px] text-af-on-surface-variant uppercase tracking-wider">Current Price</p>
          <p className="text-3xl font-semibold text-af-on-surface">
            $342.15 <span className="text-sm text-af-error font-medium">-1.24%</span>
          </p>
        </div>
      </div>
    </section>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add components/job/stock-header.tsx
git commit -m "$(cat <<'EOF'
feat(job): add StockHeader for the Done page

Composes ticker + StatusPill + SignalPill, reuses ticker as H3 per spec
D10 (no company-name lookup), and renders the static Current Price sample
per D4.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Key Insights mapper + component (TDD)

**Files:**
- Create: `tests/components/map-insights.test.ts`
- Create: `lib/job/map-insights.ts`
- Create: `components/job/key-insights.tsx`

- [ ] **Step 1: Write the failing test**

Create `tests/components/map-insights.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { mapSignalsToInsights } from "@/lib/job/map-insights";

describe("mapSignalsToInsights", () => {
  it("returns [] for an empty input", () => {
    expect(mapSignalsToInsights([])).toEqual([]);
  });

  it("returns [] for null input (missing signals array)", () => {
    expect(mapSignalsToInsights(null)).toEqual([]);
  });

  it("cycles through the four icon names by index", () => {
    const signals = [
      { label: "s1", evidence: "e1", source: null },
      { label: "s2", evidence: "e2", source: null },
      { label: "s3", evidence: "e3", source: null },
      { label: "s4", evidence: "e4", source: null },
    ];
    const out = mapSignalsToInsights(signals);
    expect(out.map((s) => s.icon)).toEqual(["psychology", "trending_up", "warning", "groups"]);
  });

  it("renders label uppercase", () => {
    const out = mapSignalsToInsights([{ label: "AI Momentum", evidence: "e", source: null }]);
    expect(out[0].label).toBe("AI MOMENTUM");
  });

  it("keeps the source when it parses as an http(s) URL", () => {
    const out = mapSignalsToInsights([{ label: "s", evidence: "e", source: "https://example.com/q3-call" }]);
    expect(out[0].sourceHref).toBe("https://example.com/q3-call");
  });

  it("drops the source when it is not a URL", () => {
    const out = mapSignalsToInsights([{ label: "s", evidence: "e", source: "Q3 Earnings Call" }]);
    expect(out[0].sourceHref).toBeNull();
  });

  it("drops the source when it is null", () => {
    const out = mapSignalsToInsights([{ label: "s", evidence: "e", source: null }]);
    expect(out[0].sourceHref).toBeNull();
  });

  it("wraps around after 4 signals (5th uses psychology again)", () => {
    const signals = Array.from({ length: 5 }, (_, i) => ({
      label: `s${i}`,
      evidence: `e${i}`,
      source: null,
    }));
    const out = mapSignalsToInsights(signals);
    expect(out[4].icon).toBe("psychology");
  });
});
```

- [ ] **Step 2: Run the test and confirm it fails**

```bash
pnpm test tests/components/map-insights.test.ts 2>&1 | tail -20
```

Expected: module-not-found.

- [ ] **Step 3: Implement the mapper**

Create `lib/job/map-insights.ts`:

```ts
export type RawSignal = { label: string; evidence: string; source: string | null };

export type Insight = {
  icon: "psychology" | "trending_up" | "warning" | "groups";
  label: string;
  evidence: string;
  sourceHref: string | null;
};

const ICONS = ["psychology", "trending_up", "warning", "groups"] as const;

function parseHttpUrl(s: string | null): string | null {
  if (!s) return null;
  try {
    const u = new URL(s);
    return u.protocol === "http:" || u.protocol === "https:" ? u.toString() : null;
  } catch {
    return null;
  }
}

export function mapSignalsToInsights(signals: RawSignal[] | null | undefined): Insight[] {
  if (!signals) return [];
  return signals.map((s, i) => ({
    icon: ICONS[i % ICONS.length],
    label: s.label.toUpperCase(),
    evidence: s.evidence,
    sourceHref: parseHttpUrl(s.source),
  }));
}
```

- [ ] **Step 4: Run the test and confirm it passes**

```bash
pnpm test tests/components/map-insights.test.ts 2>&1 | tail -10
```

Expected: 8 tests pass.

- [ ] **Step 5: Create KeyInsights**

Create `components/job/key-insights.tsx`:

```tsx
import { mapSignalsToInsights, type RawSignal } from "@/lib/job/map-insights";

const ICON_BG: Record<string, string> = {
  psychology: "bg-af-primary-container text-af-on-primary",
  trending_up: "bg-af-secondary-container text-af-on-secondary-container",
  warning: "bg-af-error-container text-af-on-error-container",
  groups: "bg-af-surface-container text-af-on-surface",
};

export function KeyInsights({ signals, lastUpdatedLabel }: { signals: RawSignal[] | null; lastUpdatedLabel: string }) {
  const insights = mapSignalsToInsights(signals);

  return (
    <section className="space-y-6">
      <div className="flex items-center justify-between">
        <h4 className="text-2xl font-semibold text-af-on-surface">Key Insights</h4>
        <span className="text-sm text-af-on-surface-variant">Last updated: {lastUpdatedLabel}</span>
      </div>
      {insights.length === 0 ? (
        <p className="text-sm text-af-on-surface-variant">No insights yet.</p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          {insights.map((s, i) => (
            <div
              key={i}
              className="bg-af-surface-container-lowest p-6 rounded-xl border border-af-outline-variant flex flex-col justify-between h-full"
            >
              <div className="space-y-4">
                <div className={`w-12 h-12 rounded-lg flex items-center justify-center ${ICON_BG[s.icon]}`}>
                  <span className="material-symbols-outlined">{s.icon}</span>
                </div>
                <h5 className="text-sm font-semibold text-af-on-surface uppercase">{s.label}</h5>
                <p className="text-sm text-af-on-surface-variant leading-relaxed">{s.evidence}</p>
              </div>
              {s.sourceHref && (
                <div className="mt-6 pt-4 border-t border-af-outline-variant">
                  <a
                    href={s.sourceHref}
                    target="_blank"
                    rel="noreferrer"
                    className="text-af-secondary text-[12px] font-medium flex items-center gap-1 hover:underline"
                  >
                    Source
                    <span className="material-symbols-outlined text-[14px]">open_in_new</span>
                  </a>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
```

- [ ] **Step 6: Commit**

```bash
git add tests/components/map-insights.test.ts lib/job/map-insights.ts components/job/key-insights.tsx
git commit -m "$(cat <<'EOF'
feat(job): add KeyInsights driven by signals[]

Pure mapSignalsToInsights() cycles the four mock icons by index,
uppercases labels, and only keeps source when it's a valid http(s) URL —
so the render treats it as a link (open in new tab) with no fallback
plain-text label. Empty signals list renders 'No insights yet.' per spec
D11.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: Static bento panels (Revenue Distribution + Analyst Sentiment)

**Files:**
- Create: `components/job/revenue-distribution.tsx`
- Create: `components/job/analyst-sentiment.tsx`

- [ ] **Step 1: Create RevenueDistribution**

Create `components/job/revenue-distribution.tsx`:

```tsx
export function RevenueDistribution() {
  return (
    <div className="col-span-12 lg:col-span-8 bg-af-surface-container-lowest p-8 rounded-xl border border-af-outline-variant">
      <div className="flex items-center justify-between mb-8">
        <h4 className="text-2xl font-semibold text-af-on-surface">Revenue Distribution</h4>
        <div className="flex gap-2">
          <span className="px-3 py-1 bg-af-surface-container-low rounded text-[12px] font-medium">FY 2023</span>
          <span className="px-3 py-1 text-af-on-surface-variant text-[12px] font-medium">FY 2022</span>
        </div>
      </div>
      <div className="h-64 flex items-end justify-between gap-6 px-8">
        <div className="flex-1 bg-af-primary-container h-[80%] rounded-t-lg" title="Atlas: 66%" />
        <div className="flex-1 bg-af-on-primary-container h-[45%] rounded-t-lg" title="Enterprise: 28%" />
        <div className="flex-1 bg-af-outline-variant h-[15%] rounded-t-lg" title="Services: 6%" />
      </div>
      <div className="flex justify-between mt-4 px-8 text-[12px] text-af-on-surface-variant">
        <span>MongoDB Atlas</span>
        <span>Enterprise Advanced</span>
        <span>Professional Services</span>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create AnalystSentiment**

Create `components/job/analyst-sentiment.tsx`:

```tsx
type Row = { label: string; pct: number; color: string; textColor: string };

const ROWS: Row[] = [
  { label: "BUY RECOMMENDATION", pct: 62, color: "bg-af-secondary", textColor: "text-af-secondary" },
  { label: "HOLD RECOMMENDATION", pct: 31, color: "bg-af-signal-hold", textColor: "text-af-signal-hold" },
  { label: "SELL RECOMMENDATION", pct: 7, color: "bg-af-error", textColor: "text-af-error" },
];

export function AnalystSentiment() {
  return (
    <div className="col-span-12 lg:col-span-4 bg-af-surface-container-lowest p-8 rounded-xl border border-af-outline-variant">
      <h4 className="text-2xl font-semibold text-af-on-surface mb-8">Analyst Sentiment</h4>
      <div className="space-y-6">
        {ROWS.map((r) => (
          <div key={r.label}>
            <div className={`flex justify-between text-[12px] mb-2 font-medium ${r.textColor}`}>
              <span>{r.label}</span>
              <span>{r.pct}%</span>
            </div>
            <div className="w-full h-2 bg-af-surface-container-low rounded-full overflow-hidden">
              <div className={`h-full ${r.color}`} style={{ width: `${r.pct}%` }} />
            </div>
          </div>
        ))}
      </div>
      <div className="mt-8 p-4 bg-af-surface-container-low rounded-lg">
        <p className="text-sm italic text-af-on-surface">
          "The expansion of Atlas into multi-cloud environments provides a unique moat that hyperscalers struggle to replicate."
        </p>
        <p className="text-[12px] font-medium text-af-on-surface-variant mt-2">— Tier 1 Investment Bank</p>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add components/job/revenue-distribution.tsx components/job/analyst-sentiment.tsx
git commit -m "$(cat <<'EOF'
feat(job): add static Revenue Distribution + Analyst Sentiment bento

Static panels rendered on the Done page per spec D4 — no data source
today; the numbers match analysis_done.html exactly.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: JobLivePoller + Done page assembly

**Files:**
- Create: `components/job/job-live-poller.tsx`
- Modify: `app/(app)/jobs/[id]/page.tsx`
- Delete: `components/job-detail.tsx`

- [ ] **Step 1: Create the shared Job type module**

Because both server (`page.tsx`) and client (`job-live-poller.tsx`) need the same shape, extract it to `lib/job/types.ts`.

Create `lib/job/types.ts`:

```ts
import type { JobStatus } from "@/lib/ui/status-pill";
import type { Recommendation } from "@/lib/ui/signal-pill";
import type { RawSignal } from "@/lib/job/map-insights";

export type SerializedJob = {
  id: string;
  ticker: string;
  status: JobStatus;
  recommendation: Recommendation | null;
  result: { summary?: string; signals?: RawSignal[] } | null;
  error: string | null;
  sandboxId: string | null;
  createdAt: string; // ISO
  startedAt: string | null; // ISO
  completedAt: string | null; // ISO
};
```

- [ ] **Step 2: Create JobLivePoller**

Create `components/job/job-live-poller.tsx`:

```tsx
"use client";
import { useEffect, useState } from "react";
import { StockHeader } from "./stock-header";
import { KeyInsights } from "./key-insights";
import { RevenueDistribution } from "./revenue-distribution";
import { AnalystSentiment } from "./analyst-sentiment";
import { formatCompactDate } from "@/lib/ui/format-timestamp";
import type { SerializedJob } from "@/lib/job/types";

export function JobLivePoller({ initialJob }: { initialJob: SerializedJob }) {
  const [job, setJob] = useState<SerializedJob>(initialJob);

  useEffect(() => {
    if (job.status === "complete" || job.status === "failed") return;
    const id = setInterval(async () => {
      const res = await fetch(`/api/status/${job.id}`);
      if (!res.ok) return;
      const next: SerializedJob = await res.json();
      setJob(next);
      if (next.status === "complete" || next.status === "failed") clearInterval(id);
    }, 2500);
    return () => clearInterval(id);
  }, [job.id, job.status]);

  const elapsedSeconds = Math.round(
    ((job.completedAt ? new Date(job.completedAt).getTime() : Date.now()) -
      new Date(job.createdAt).getTime()) /
      1000,
  );

  const lastUpdatedLabel = job.completedAt
    ? formatCompactDate(new Date(job.completedAt))
    : "Just now";

  return (
    <div className="space-y-8">
      <StockHeader
        ticker={job.ticker}
        status={job.status}
        recommendation={job.recommendation}
        summary={job.result?.summary ?? null}
      />

      {(job.status === "pending" || job.status === "running") && (
        <>
          <p className="text-sm text-af-on-surface-variant">
            Sandbox {job.sandboxId ?? "spawning…"} · {elapsedSeconds}s elapsed
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            {Array.from({ length: 4 }, (_, i) => (
              <div key={i} className="bg-af-surface-container-low animate-pulse rounded-xl h-56" />
            ))}
          </div>
          <div className="grid grid-cols-12 gap-6">
            <div className="col-span-12 lg:col-span-8 bg-af-surface-container-low animate-pulse rounded-xl h-96" />
            <div className="col-span-12 lg:col-span-4 bg-af-surface-container-low animate-pulse rounded-xl h-96" />
          </div>
        </>
      )}

      {job.status === "failed" && (
        <div className="bg-af-error-container rounded-xl p-6">
          <pre className="text-xs whitespace-pre-wrap text-af-on-error-container">{job.error}</pre>
        </div>
      )}

      {job.status === "complete" && (
        <>
          <KeyInsights signals={job.result?.signals ?? null} lastUpdatedLabel={lastUpdatedLabel} />
          <section className="grid grid-cols-12 gap-6">
            <RevenueDistribution />
            <AnalystSentiment />
          </section>
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Rewrite the Done page**

Replace `app/(app)/jobs/[id]/page.tsx` with:

```tsx
import { notFound } from "next/navigation";
import { eq } from "drizzle-orm";
import { db, jobs } from "@/lib/db/client";
import { JobLivePoller } from "@/components/job/job-live-poller";
import type { SerializedJob } from "@/lib/job/types";

export const dynamic = "force-dynamic";

export default async function JobPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const rows = await db.select().from(jobs).where(eq(jobs.id, id)).limit(1);
  if (rows.length === 0) notFound();
  const row = rows[0];
  const initial: SerializedJob = {
    id: row.id,
    ticker: row.ticker,
    status: row.status as SerializedJob["status"],
    recommendation: row.recommendation as SerializedJob["recommendation"],
    result: (row.result as SerializedJob["result"]) ?? null,
    error: row.error ?? null,
    sandboxId: row.sandboxId ?? null,
    createdAt: row.createdAt.toISOString(),
    startedAt: row.startedAt ? row.startedAt.toISOString() : null,
    completedAt: row.completedAt ? row.completedAt.toISOString() : null,
  };
  return <JobLivePoller initialJob={initial} />;
}
```

Note: the old page had `<main className="p-8 max-w-3xl mx-auto">` wrapping the detail. Now that wrapper lives in `(app)/layout.tsx`; this page renders the poller directly.

- [ ] **Step 4: Delete the old JobDetail component**

```bash
git rm components/job-detail.tsx
```

- [ ] **Step 5: Smoke-test the full flow**

```bash
$env:AGENT_RUNTIME='subprocess'   # PowerShell; on bash/zsh: export AGENT_RUNTIME=subprocess
pnpm dev
```

- Visit `/analyze`, submit "AAPL", confirm redirect to `/jobs/<id>`.
- On `/jobs/<id>`: Pending → Running (with skeleton grids) → Complete (with header, insights, bento). If the agent completes with no signals, "No insights yet." shows.
- Submit again with an invalid input to trigger the 500-with-jobId path only if you can force a spawn failure; otherwise skip and rely on the unit test coverage from Task 10.
- Return to `/`; the new row appears at the top of Recent Activity with the right status.

Kill dev server.

- [ ] **Step 6: Commit**

```bash
git add components/job/job-live-poller.tsx lib/job/types.ts app/'(app)'/jobs/'[id]'/page.tsx
git commit -m "$(cat <<'EOF'
feat(job): rebuild the Done page with the AlphaFlow bento layout

Server page fetches the row and hands a SerializedJob to JobLivePoller,
which keeps today's 2.5s /api/status polling contract. During
pending/running, header + skeleton grids render; failed shows the error
card; complete renders the full StockHeader + KeyInsights +
RevenueDistribution + AnalystSentiment layout. Replaces the legacy
JobDetail component.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 16: Manual verification pass + cleanup

**Files:** none by default; only fixes if the checklist reveals issues.

- [ ] **Step 1: Run the full test suite**

```bash
pnpm test 2>&1 | tail -30
```

Expected: all tests pass — 6 new pure-logic tests + 8 pre-existing daytona test file + all runtime tests.

- [ ] **Step 2: Run the type checker**

```bash
pnpm exec tsc --noEmit 2>&1 | tail -30
```

Expected: the pre-existing errors in `lib/runtime/subprocess.ts` (`ProcessEnv` NODE_ENV, `unref`) remain. **No new errors** from any new file in this refactor. If new errors appear, fix them before continuing.

- [ ] **Step 3: Run the linter**

```bash
pnpm lint 2>&1 | tail -30
```

Expected: green, or at most the pre-existing warnings.

- [ ] **Step 4: End-to-end smoke checklist**

Start `pnpm dev` (with `AGENT_RUNTIME=subprocess` for speed) and walk this list:

- [ ] `/` renders the shell + Welcome + AI Sentiment hero + Top Gainers + Market Risk + Recent Activity.
- [ ] `/analyze` renders the shell + LaunchForm card + info cards.
- [ ] Sidebar highlight follows the route (Home active on `/`, Analysis active on `/analyze` and `/jobs/[id]`).
- [ ] Sidebar `New Analysis` CTA navigates to `/analyze`.
- [ ] `/admin` still renders unchanged — no shell, no Material Symbols loaded, raw table intact.
- [ ] Submit AAPL from `/analyze` → redirect to `/jobs/[id]`.
- [ ] `/jobs/[id]` cycles Pending → Running (skeleton) → Complete (header + insights + bento).
- [ ] `/jobs/<unknown-id>` returns 404 (default Next 404 page).
- [ ] Placeholders confirmed inert: Account, Logout, Dashboard/Market/Portfolio/Watchlist/Alerts topbar tabs, topbar search input, notifications button, settings button, avatar div, Analysis Depth buttons (visual only), Close X on `/analyze`, How-it-works button, `more_vert` row buttons, View Report on Market Risk, pagination chevrons.
- [ ] Sub-`md` viewport hides the sidebar; main content is readable stand-alone.

- [ ] **Step 5: Fix any issues, commit fixes**

For each visual bug found, make the smallest change and commit with a descriptive message referencing the issue.

- [ ] **Step 6: Final housekeeping — delete `tsconfig.tsbuildinfo` if it was created by mistake and is not already ignored**

```bash
git check-ignore tsconfig.tsbuildinfo && echo "already ignored" || echo "check .gitignore"
```

If not ignored, leave `.gitignore` handling out of this refactor (unrelated concern).

- [ ] **Step 7: Confirm the branch is clean**

```bash
git status --short
```

Expected: no unstaged/uncommitted changes from this refactor's touched files.

---

## Self-review checklist

- Spec §1 Purpose (shell across three screens, unimplemented artifacts inert) → Tasks 3, 8, 11, 15.
- Spec §2 D1 (`/analyze` route) → Task 2 stub + Task 11 wire-up.
- Spec §2 D2 ((app) route group) → Task 2.
- Spec §2 D3 (Running pill) → Task 4.
- Spec §2 D4 (Done bento fidelity, static widgets) → Tasks 12, 14.
- Spec §2 D5 (/admin unchanged) → Task 2 leaves `app/admin/page.tsx` alone; Task 3 sidebar excludes `/admin` from shell.
- Spec §2 D6 (Depth visual-only, default Quick) → Task 9 DepthSelector; Task 10 orchestrator asserts payload is `{ticker}` only.
- Spec §2 D7 (design tokens) → Task 1.
- Spec §2 D8 (fonts/icons) → Task 3 layout adds Material Symbols `<link>`; Geist Sans/Mono stay; no Inter.
- Spec §2 D9 (500-with-jobId redirect) → Task 10 test + implementation.
- Spec §2 D10 (no company-name lookup) → Task 12 StockHeader reuses ticker.
- Spec §2 D11 (fewer-than-4 signals, empty state) → Task 13 tests + KeyInsights markup.
- Spec §2 D12 (pagination text + inert chevrons) → Task 7 RecentActivity.
- Spec §2 D13 (mobile behavior — sidebar `hidden md:flex`) → Task 3 sidebar class.
- Spec §2 D14 (no dark mode) → Nothing in this plan touches the shadcn `.dark {}` block.
- Spec §2 D15 (SubmitForm removed) → Task 11.
- Spec §7 Error handling table → Task 10 covers submit paths; Task 15 covers the poller / failed card / empty signals.
- Spec §8 Manual verification checklist → Task 16 Step 4.

No placeholders (TBD/TODO), no vague steps, no missing code blocks. Every file path is exact.

Type consistency: `JobStatus` and `Recommendation` are defined once (Tasks 4, 5) and re-used by every downstream component. `SerializedJob` is defined once (Task 15) and used by both server page and poller. `RawSignal` is defined in Task 13 and re-used by `SerializedJob`.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-02-ux-refactor.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints.

Which approach?
