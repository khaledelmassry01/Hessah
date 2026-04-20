import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type RoiBarChartProps = {
  expectedReturn?: number;
  expectedVolatility?: number;
  title?: string;
};

export function RoiBarChart({
  expectedReturn,
  expectedVolatility,
  title = "Risk / Return Snapshot",
}: RoiBarChartProps) {
  const data = [
    { metric: "Expected Return", value: expectedReturn ? expectedReturn * 100 : 0 },
    {
      metric: "Expected Volatility",
      value: expectedVolatility ? expectedVolatility * 100 : 0,
    },
  ];

  const hasData = data.some((item) => item.value > 0);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
      </CardHeader>
      <CardContent className="h-[290px]">
        {!hasData ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            Run optimizer or backtest to visualize risk-return metrics.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} barSize={42}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="metric" tick={{ fontSize: 12 }} />
              <YAxis unit="%" tick={{ fontSize: 12 }} />
              <Tooltip formatter={(value: number) => `${value.toFixed(2)}%`} />
              <Bar dataKey="value" fill="#0f766e" radius={[8, 8, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}
