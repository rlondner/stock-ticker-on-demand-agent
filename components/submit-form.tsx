"use client";
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function SubmitForm() {
  const [ticker, setTicker] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const router = useRouter();

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const value = ticker.trim().toUpperCase();
    if (!/^[A-Z]{1,5}$/.test(value)) {
      setError("Ticker must be 1–5 uppercase letters.");
      return;
    }
    startTransition(async () => {
      const res = await fetch("/api/jobs", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ ticker: value }),
      });
      const body = await res.json();
      if (!res.ok) { setError(body.error ?? "Submit failed"); return; }
      router.push(`/jobs/${body.jobId}`);
    });
  }

  return (
    <form onSubmit={onSubmit} className="flex gap-2 items-start">
      <Input
        value={ticker}
        onChange={(e) => setTicker(e.target.value)}
        placeholder="AAPL"
        maxLength={5}
        aria-label="ticker"
        className="w-32 uppercase"
      />
      <Button type="submit" disabled={pending}>
        {pending ? "Analyzing…" : "Analyze"}
      </Button>
      {error && <p className="text-red-600 text-sm self-center">{error}</p>}
    </form>
  );
}
