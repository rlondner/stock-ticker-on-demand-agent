import { Welcome } from "@/components/dashboard/welcome";
import { AiSentimentCard } from "@/components/dashboard/ai-sentiment-card";
import { TopGainersCard } from "@/components/dashboard/top-gainers-card";
import { MarketRiskCard } from "@/components/dashboard/market-risk-card";
import { RecentActivity } from "@/components/dashboard/recent-activity";

export const dynamic = "force-dynamic";

export default function Home() {
  return (
    <div className="grid grid-cols-12 gap-6">
      <Welcome />
      <AiSentimentCard />
      <div className="col-span-12 lg:col-span-4 grid grid-rows-2 gap-6">
        <TopGainersCard />
        <MarketRiskCard />
      </div>
      <RecentActivity />
    </div>
  );
}
