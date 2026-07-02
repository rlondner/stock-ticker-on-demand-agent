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
