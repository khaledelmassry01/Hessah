import { AllocationPieChart } from "@/components/charts/AllocationPieChart";
import type { PortfolioAllocation } from "@/types/api";

type PortfolioPieChartProps = {
  allocations: PortfolioAllocation[];
  title?: string;
};

export function PortfolioPieChart({
  allocations,
  title = "Portfolio Allocation",
}: PortfolioPieChartProps) {
  return <AllocationPieChart allocations={allocations} title={title} />;
}
