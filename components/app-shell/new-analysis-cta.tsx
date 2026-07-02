import Link from "next/link";

export function NewAnalysisCta() {
  return (
    <Link
      href="/analyze"
      className="mt-8 mb-8 w-full block text-center bg-af-primary text-af-on-primary py-3 px-6 rounded-lg font-semibold text-sm hover:opacity-90 transition-opacity"
    >
      New Analysis
    </Link>
  );
}
