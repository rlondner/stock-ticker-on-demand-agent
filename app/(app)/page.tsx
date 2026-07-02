import { RecentActivity } from "@/components/dashboard/recent-activity";

export const dynamic = "force-dynamic";

export default function Home() {
  return (
    <div className="grid grid-cols-12 gap-6">
      <RecentActivity />
    </div>
  );
}
