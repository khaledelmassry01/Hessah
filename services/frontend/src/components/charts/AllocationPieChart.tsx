import {
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { PortfolioAllocation } from "@/types/api";

type AllocationPieChartProps = {
  allocations: PortfolioAllocation[];
  title?: string;
};

const COLORS = ["#0f766e", "#0369a1", "#b45309", "#1d4ed8", "#15803d", "#7c3aed"];

export function AllocationPieChart({
  allocations,
  title = "Allocation Breakdown",
}: AllocationPieChartProps) {
  const chartData = allocations
    .map((item) => ({
      name: item.symbol,
      value: item.executedAmountEgp ?? item.weight ?? 0,
    }))
    .filter((item) => item.value > 0)
    .slice(0, 8);

  return (
    <Card className="border-slate-700/70 bg-slate-950/80 text-slate-100">
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
      </CardHeader>
      <CardContent className="h-[290px]">
        {chartData.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-slate-400">
            Allocation data will appear after optimization.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={chartData}
                dataKey="value"
                nameKey="name"
                cx="50%"
                cy="48%"
                outerRadius={88}
                innerRadius={44}
                paddingAngle={2}
              >
                {chartData.map((entry, index) => (
                  <Cell
                    key={`${entry.name}-${entry.value}`}
                    fill={COLORS[index % COLORS.length]}
                  />
                ))}
              </Pie>
              <Tooltip formatter={(value: number) => value.toLocaleString("en-EG")} />
              <Legend verticalAlign="bottom" height={24} />
            </PieChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}
