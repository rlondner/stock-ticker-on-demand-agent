import type { SerializedJob } from "@/lib/job/types";

type Result = NonNullable<SerializedJob["result"]>;

const TOKEN_RE = /("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g;

function highlight(json: string) {
  const parts: Array<{ text: string; className?: string }> = [];
  let lastIndex = 0;
  for (const match of json.matchAll(TOKEN_RE)) {
    const start = match.index ?? 0;
    if (start > lastIndex) parts.push({ text: json.slice(lastIndex, start) });
    const [full, str, colon, keyword] = match;
    if (str && colon) {
      parts.push({ text: str, className: "text-af-primary" });
      parts.push({ text: colon });
    } else if (str) {
      parts.push({ text: str, className: "text-af-secondary" });
    } else if (keyword) {
      parts.push({ text: full, className: "text-af-signal-hold" });
    } else {
      parts.push({ text: full, className: "text-af-on-primary-container" });
    }
    lastIndex = start + full.length;
  }
  if (lastIndex < json.length) parts.push({ text: json.slice(lastIndex) });
  return parts;
}

export function RawLLMResponse({ result }: { result: Result | null }) {
  const json = JSON.stringify(result ?? {}, null, 2);
  const tokens = highlight(json);
  return (
    <div className="col-span-12 lg:col-span-8 bg-af-surface-container-lowest p-8 rounded-xl border border-af-outline-variant">
      <div className="flex items-center justify-between mb-6">
        <h4 className="text-2xl font-semibold text-af-on-surface">Raw LLM Response</h4>
        <span className="px-3 py-1 bg-af-surface-container-low rounded text-[12px] font-medium text-af-on-surface-variant">
          JSON
        </span>
      </div>
      <pre className="max-h-[32rem] overflow-auto bg-af-surface-container-low rounded-lg p-6 text-[13px] leading-relaxed font-mono text-af-on-surface-variant whitespace-pre">
        <code>
          {tokens.map((t, i) =>
            t.className ? (
              <span key={i} className={t.className}>{t.text}</span>
            ) : (
              <span key={i}>{t.text}</span>
            ),
          )}
        </code>
      </pre>
    </div>
  );
}
