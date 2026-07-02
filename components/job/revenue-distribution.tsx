export function RevenueDistribution() {
  return (
    <div className="col-span-12 lg:col-span-8 bg-af-surface-container-lowest p-8 rounded-xl border border-af-outline-variant">
      <div className="flex items-center justify-between mb-8">
        <h4 className="text-2xl font-semibold text-af-on-surface">Revenue Distribution</h4>
        <div className="flex gap-2">
          <span className="px-3 py-1 bg-af-surface-container-low rounded text-[12px] font-medium">FY 2023</span>
          <span className="px-3 py-1 text-af-on-surface-variant text-[12px] font-medium">FY 2022</span>
        </div>
      </div>
      <div className="h-64 flex items-end justify-between gap-6 px-8">
        <div className="flex-1 bg-af-primary-container h-[80%] rounded-t-lg" title="Atlas: 66%" />
        <div className="flex-1 bg-af-on-primary-container h-[45%] rounded-t-lg" title="Enterprise: 28%" />
        <div className="flex-1 bg-af-outline-variant h-[15%] rounded-t-lg" title="Services: 6%" />
      </div>
      <div className="flex justify-between mt-4 px-8 text-[12px] text-af-on-surface-variant">
        <span>MongoDB Atlas</span>
        <span>Enterprise Advanced</span>
        <span>Professional Services</span>
      </div>
    </div>
  );
}
