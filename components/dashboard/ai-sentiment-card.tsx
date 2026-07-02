const KPIS = [
  { label: "Volatility Index", value: "14.22" },
  { label: "S&P 500 Peak", value: "5,432" },
  { label: "Yield Curve", value: "4.12%" },
  { label: "Fear/Greed", value: "68/100" },
];

export function AiSentimentCard() {
  return (
    <div className="col-span-12 lg:col-span-8 relative overflow-hidden rounded-xl bg-af-primary-container min-h-[400px] flex flex-col p-8">
      <div className="relative z-10 h-full flex flex-col justify-between">
        <div>
          <h3 className="text-3xl font-semibold text-af-on-primary mb-2">AI Sentiment Score</h3>
          <p className="text-lg text-af-on-primary-container max-w-md">
            Proprietary deep learning analysis of global markets suggests a bullish trend for tech-heavy portfolios over the next quarter.
          </p>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-6 mt-8">
          {KPIS.map((k) => (
            <div key={k.label}>
              <p className="text-[12px] text-af-on-primary-container uppercase">{k.label}</p>
              <p className="text-2xl font-semibold text-af-on-primary">{k.value}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
