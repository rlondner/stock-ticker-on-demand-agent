import { SubmitForm } from "@/components/submit-form";
import { JobsList } from "@/components/jobs-list";

export const dynamic = "force-dynamic";

export default function Home() {
  return (
    <main className="p-8 max-w-3xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold">Daytona Stock-Agent Demo</h1>
        <p className="text-sm text-slate-500">
          Submit a stock ticker; an ephemeral Daytona VM runs an AI agent and writes the result to Neon.
        </p>
      </div>
      <SubmitForm />
      <section>
        <h2 className="text-lg font-semibold mb-2">Recent jobs</h2>
        <JobsList />
      </section>
      <p className="text-xs text-slate-400">Demo only — not financial advice.</p>
    </main>
  );
}
