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
