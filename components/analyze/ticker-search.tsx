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
