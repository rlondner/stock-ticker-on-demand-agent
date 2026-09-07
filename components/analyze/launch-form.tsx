"use client";
import Link from "next/link";
import { useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { TickerSearch } from "./ticker-search";
import { SuggestedTickers } from "./suggested-tickers";
import { DepthSelector } from "./depth-selector";
import { NotifyPicker, validateDestination, type NotifyChannelOption } from "./notify-picker";
import { submitAnalysis } from "@/lib/analyze/submit-analysis";

export function LaunchForm() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [ticker, setTicker] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const [notifyChannel, setNotifyChannel] = useState<NotifyChannelOption>("none");
  const [notifyDestination, setNotifyDestination] = useState("");

  const onPickSuggestion = (t: string) => {
    setTicker(t);
    inputRef.current?.focus();
  };

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const destErr = validateDestination(notifyChannel, notifyDestination);
    if (destErr) {
      setError(destErr);
      return;
    }
    startTransition(async () => {
      const result = await submitAnalysis({
        ticker,
        ...(notifyChannel !== "none" ? { notifyChannel, notifyDestination } : {}),
        push: router.push,
      });
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
          <NotifyPicker
            channel={notifyChannel}
            destination={notifyDestination}
            onChannelChange={setNotifyChannel}
            onDestinationChange={setNotifyDestination}
          />
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
              className="px-8 py-4 bg-af-primary text-af-on-primary rounded-lg text-sm font-semibold hover:opacity-90 transition-colors flex items-center gap-2 shadow-md disabled:opacity-60 disabled:cursor-not-allowed"
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
          <div className="p-2 bg-af-tertiary-fixed rounded-lg">
            <span className="material-symbols-outlined text-af-on-tertiary-fixed-variant">hub</span>
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
