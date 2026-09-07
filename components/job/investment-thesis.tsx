import type { SerializedJob, ThesisPoint } from "@/lib/job/types";
import { formatConfidence, formatGrounding, safeSourceHref } from "@/lib/ui/thesis";

const GROUNDING_TONE: Record<string, string> = {
  up: "text-af-secondary",
  neutral: "text-af-signal-hold",
  muted: "text-af-on-surface-variant",
};

function ThesisPointItem({ point }: { point: ThesisPoint }) {
  const href = safeSourceHref(point.source_url);
  return (
    <li className="space-y-1">
      <p className="text-sm font-semibold text-af-on-surface">{point.claim}</p>
      <p className="text-sm text-af-on-surface-variant leading-relaxed">{point.evidence}</p>
      {href && (
        <a
          href={href}
          target="_blank"
          rel="noreferrer"
          className="text-af-secondary text-[12px] font-medium inline-flex items-center gap-1 hover:underline"
        >
          Source
          <span className="material-symbols-outlined text-[14px]">open_in_new</span>
        </a>
      )}
    </li>
  );
}

function ThesisSection({ title, points, accent }: { title: string; points: ThesisPoint[]; accent: string }) {
  return (
    <div className="bg-af-surface-container-lowest p-6 rounded-xl border border-af-outline-variant">
      <h5 className={`text-sm font-semibold uppercase mb-4 ${accent}`}>{title}</h5>
      {points.length === 0 ? (
        <p className="text-sm text-af-on-surface-variant">None provided.</p>
      ) : (
        <ul className="space-y-4">
          {points.map((p, i) => (
            <ThesisPointItem key={i} point={p} />
          ))}
        </ul>
      )}
    </div>
  );
}

export function InvestmentThesis({
  result,
  lastUpdatedLabel,
}: {
  result: SerializedJob["result"];
  lastUpdatedLabel: string;
}) {
  const confidence = formatConfidence(result?.confidence ?? null);
  const grounding = formatGrounding(result?.grounding ?? null);
  const bull = result?.bull_case ?? [];
  const bear = result?.bear_case ?? [];
  const risks = result?.key_risks ?? [];
  const researcherFindings = result?.researcher_findings;
  const fundamentalsAnalysis = result?.fundamentals_analysis;
  const riskAnalysis = result?.risk_analysis;

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h4 className="text-2xl font-semibold text-af-on-surface">Investment Thesis</h4>
          {confidence && (
            <span className="text-[12px] font-medium text-af-on-surface-variant border border-af-outline-variant rounded-full px-3 py-1">
              Confidence: {confidence}
            </span>
          )}
          {grounding && (
            <span
              className={`text-[12px] font-medium border border-af-outline-variant rounded-full px-3 py-1 ${GROUNDING_TONE[grounding.tone]}`}
            >
              {grounding.label}
            </span>
          )}
        </div>
        <span className="text-sm text-af-on-surface-variant">Last updated: {lastUpdatedLabel}</span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <ThesisSection title="Bull Case" points={bull} accent="text-af-secondary" />
        <ThesisSection title="Bear Case" points={bear} accent="text-af-error" />
      </div>
      {researcherFindings && (
        <ThesisSection title="Researcher Findings" points={researcherFindings} accent="text-af-secondary" />
      )}
      {fundamentalsAnalysis && (
        <ThesisSection title="Fundamentals Analysis" points={fundamentalsAnalysis} accent="text-af-secondary" />
      )}
      {riskAnalysis && (
        <ThesisSection title="Risk Analysis" points={riskAnalysis} accent="text-af-signal-hold" />
      )}
      <ThesisSection title="Key Risks" points={risks} accent="text-af-signal-hold" />
    </section>
  );
}
