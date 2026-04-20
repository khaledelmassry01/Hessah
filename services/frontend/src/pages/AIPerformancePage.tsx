import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, BrainCircuit, ChartSpline, DatabaseBackup } from "lucide-react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchAiPerformanceSummary, mapApiError } from "@/lib/api";

type ChartPoint = {
  testDate: string;
  dateLabel: string;
  predictedReturnPct: number;
  actualReturnPct: number;
};

function asPercent(value?: number) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return 0;
  }

  if (Math.abs(value) > 1) {
    return value;
  }

  return value * 100;
}

function formatPercent(value: number, digits = 2) {
  return `${value.toFixed(digits)}%`;
}

export function AIPerformancePage() {
  const performanceQuery = useQuery({
    queryKey: ["ai-performance-summary", 30],
    queryFn: () => fetchAiPerformanceSummary(20),
    retry: 1,
  });

  const chartData = useMemo<ChartPoint[]>(() => {
    return [...(performanceQuery.data ?? [])]
      .sort((a, b) => new Date(a.testDate).getTime() - new Date(b.testDate).getTime())
      .map((entry) => {
        const parsedDate = new Date(`${entry.testDate}T00:00:00`);
        const dateLabel = Number.isNaN(parsedDate.getTime())
          ? entry.testDate
          : parsedDate.toLocaleDateString("en-EG", {
              month: "short",
              day: "2-digit",
            });

        return {
          testDate: entry.testDate,
          dateLabel,
          predictedReturnPct: asPercent(entry.predictedReturn),
          actualReturnPct: asPercent(entry.actualReturn),
        };
      });
  }, [performanceQuery.data]);

  const averagePrecisionScore = useMemo(() => {
    const scores = (performanceQuery.data ?? [])
      .map((entry) => asPercent(entry.accuracyScore))
      .filter((value) => Number.isFinite(value) && value > 0);

    if (scores.length === 0) {
      return 0;
    }

    return scores.reduce((sum, value) => sum + value, 0) / scores.length;
  }, [performanceQuery.data]);

  const bestSectorPrediction = useMemo(() => {
    const counts = new Map<string, number>();

    (performanceQuery.data ?? []).forEach((entry) => {
      if (!entry.bestSectorPrediction) {
        return;
      }

      const key = entry.bestSectorPrediction.trim();
      if (!key) {
        return;
      }

      counts.set(key, (counts.get(key) ?? 0) + 1);
    });

    if (counts.size === 0) {
      return "No sector signal yet";
    }

    return [...counts.entries()].sort((a, b) => b[1] - a[1])[0][0];
  }, [performanceQuery.data]);

  const totalBacktestsRun = chartData.length;

  if (performanceQuery.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-12 w-72" />
        <div className="grid gap-4 md:grid-cols-3">
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
        </div>
        <Skeleton className="h-[380px]" />
      </div>
    );
  }

  if (performanceQuery.error) {
    return (
      <Card className="border-destructive/40 bg-destructive/10">
        <CardHeader>
          <CardTitle>Performance Feed Unavailable</CardTitle>
          <CardDescription>
            {mapApiError(performanceQuery.error)}
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  if (!chartData.length) {
    return (
      <Card className="border-cyan-500/25 bg-slate-950/80 text-slate-100">
        <CardHeader>
          <CardTitle className="text-cyan-200">No Backtests Recorded Yet</CardTitle>
          <CardDescription className="text-slate-400">
            Start your first learning cycle to unlock predictive analytics and precision tracking.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button asChild className="bg-cyan-500 text-slate-950 hover:bg-cyan-400">
            <Link to="/premium/backtest">Run Initial Training</Link>
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <section className="relative overflow-hidden rounded-2xl border border-cyan-500/25 bg-slate-950/80 p-5 text-slate-100 shadow-[0_0_80px_-44px_rgba(8,145,178,0.95)]">
        <div className="pointer-events-none absolute -right-16 -top-20 h-56 w-56 rounded-full bg-cyan-500/20 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-24 left-0 h-52 w-52 rounded-full bg-emerald-500/20 blur-3xl" />

        <div className="relative">
          <p className="text-xs uppercase tracking-[0.26em] text-cyan-300/85">ModelPerformanceLog</p>
          <h2 className="mt-2 text-2xl font-semibold tracking-tight">AI Performance</h2>
          <p className="mt-1 max-w-2xl text-sm text-slate-300/85">
            Compare predicted returns against actual market outcomes and monitor model confidence trends.
          </p>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-3">
        <Card className="border-cyan-500/25 bg-slate-950/80 text-slate-100">
          <CardHeader className="pb-2">
            <CardDescription className="text-slate-400">Average Precision Score</CardDescription>
            <CardTitle className="text-3xl text-cyan-200">{formatPercent(averagePrecisionScore, 1)}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2 text-xs text-slate-400">
              <BrainCircuit className="h-4 w-4 text-cyan-300" />
              Rolling mean of model accuracy scores.
            </div>
          </CardContent>
        </Card>

        <Card className="border-cyan-500/25 bg-slate-950/80 text-slate-100">
          <CardHeader className="pb-2">
            <CardDescription className="text-slate-400">Best Sector Prediction</CardDescription>
            <CardTitle className="text-2xl text-emerald-300">{bestSectorPrediction}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2 text-xs text-slate-400">
              <ChartSpline className="h-4 w-4 text-emerald-300" />
              Most frequently top-ranked sector in logged runs.
            </div>
          </CardContent>
        </Card>

        <Card className="border-cyan-500/25 bg-slate-950/80 text-slate-100">
          <CardHeader className="pb-2">
            <CardDescription className="text-slate-400">Total Backtests Run</CardDescription>
            <CardTitle className="text-3xl text-amber-300">{totalBacktestsRun}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2 text-xs text-slate-400">
              <DatabaseBackup className="h-4 w-4 text-amber-300" />
              Logged historical evaluations in the model performance stream.
            </div>
          </CardContent>
        </Card>
      </section>

      <Card className="border-cyan-500/25 bg-slate-950/80 text-slate-100">
        <CardHeader>
          <CardTitle className="text-cyan-200">Predicted Return vs Actual Return</CardTitle>
          <CardDescription className="text-slate-400">
            Line chart view of model return forecasts against realized outcomes.
          </CardDescription>
        </CardHeader>
        <CardContent className="h-[420px]">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 12, right: 16, left: 0, bottom: 12 }}>
              <CartesianGrid strokeDasharray="4 4" stroke="rgba(148,163,184,0.28)" />
              <XAxis dataKey="dateLabel" stroke="rgba(203,213,225,0.75)" tick={{ fontSize: 12 }} />
              <YAxis
                stroke="rgba(203,213,225,0.75)"
                tick={{ fontSize: 12 }}
                tickFormatter={(value) => `${value.toFixed(0)}%`}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "rgba(2, 6, 23, 0.95)",
                  border: "1px solid rgba(56, 189, 248, 0.35)",
                  borderRadius: "0.65rem",
                }}
                formatter={(value: number, name: string) => [formatPercent(value), name]}
                labelFormatter={(label) => `Backtest: ${label}`}
              />
              <Line
                type="monotone"
                dataKey="predictedReturnPct"
                name="Predicted Return"
                stroke="#22d3ee"
                strokeWidth={2.4}
                dot={{ r: 2 }}
                activeDot={{ r: 4 }}
              />
              <Line
                type="monotone"
                dataKey="actualReturnPct"
                name="Actual Return"
                stroke="#f59e0b"
                strokeWidth={2.4}
                dot={{ r: 2 }}
                activeDot={{ r: 4 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>

      <div className="rounded-lg border border-slate-700/70 bg-slate-900/70 p-3 text-xs text-slate-400">
        <div className="inline-flex items-center gap-2">
          <Activity className="h-4 w-4 text-cyan-300" />
          Precision metrics are computed from available ModelPerformanceLog values and auto-refresh on revisit.
        </div>
      </div>
    </div>
  );
}

export default AIPerformancePage;
