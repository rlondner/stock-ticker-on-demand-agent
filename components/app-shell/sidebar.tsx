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
