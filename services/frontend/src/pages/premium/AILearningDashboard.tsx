import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import {
  CartesianGrid,
  Line,
  LineChart,
  PolarAngleAxis,
  RadialBar,
  RadialBarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/contexts/AuthContext";
import { fetchAiPerformanceSummary, mapApiError, runBacktest } from "@/lib/api";
import { formatCurrencyEGP } from "@/lib/format";

const triggerSchema = z.object({
  historicalDate: z.string().min(1, "Historical date is required"),
  budgetEgp: z.coerce.number().positive("Budget must be positive"),
});

type TriggerFormValues = z.infer<typeof triggerSchema>;

type ChartPoint = {
  testDate: string;
  dateLabel: string;
  predictedReturnPct: number;
  actualReturnPct: number;
  accuracyPct: number;
  riskFreeRatePct: number;
  covarianceShrinkage: number;
};

function formatPercentage(value: number, digits = 2) {
  return `${value.toFixed(digits)}%`;
}

export function AILearningDashboard() {
  const { isPremium, user, tokens } = useAuth();
  const userId = user?.userId ?? tokens?.userId;

  const form = useForm<TriggerFormValues>({
    resolver: zodResolver(triggerSchema),
    defaultValues: {
      historicalDate: new Date().toISOString().slice(0, 10),
      budgetEgp: 500000,
    },
  });

  const performanceQuery = useQuery({
    queryKey: ["ai-performance-summary"],
    queryFn: async () => fetchAiPerformanceSummary(15),
    enabled: isPremium,
  });

  const backtestMutation = useMutation({
    mutationFn: async (values: TriggerFormValues) => {
      if (!userId) {
        throw new Error("User context is missing. Please login again.");
      }

      return runBacktest({
        userId,
        budgetEgp: values.budgetEgp,
        historicalDate: values.historicalDate,
        riskLevel: "MEDIUM",
        maxSectorWeight: 0.4,
        maxAdv30Participation: 0.05,
        excludeSuspended: true,
        allowFractionalShares: false,
      });
    },
    onSuccess: async () => {
      await performanceQuery.refetch();
    },
  });

  async function onSubmit(values: TriggerFormValues) {
    await backtestMutation.mutateAsync(values);
  }

  const chartData = useMemo<ChartPoint[]>(() => {
    return [...(performanceQuery.data ?? [])]
      .sort((a, b) => new Date(a.testDate).getTime() - new Date(b.testDate).getTime())
      .map((entry) => {
        const testDate = entry.testDate;
        const parsedDate = new Date(`${testDate}T00:00:00`);
        const dateLabel = Number.isNaN(parsedDate.getTime())
          ? testDate
          : parsedDate.toLocaleDateString("en-EG", {
              month: "short",
              day: "2-digit",
            });

        return {
          testDate,
          dateLabel,
          predictedReturnPct: (entry.predictedReturn ?? 0) * 100,
          actualReturnPct: (entry.actualReturn ?? 0) * 100,
          accuracyPct: Math.min(100, Math.max(0, (entry.accuracyScore ?? 0) * 100)),
          riskFreeRatePct: (entry.optimizedParameters?.riskFreeRate ?? 0) * 100,
          covarianceShrinkage: entry.optimizedParameters?.covarianceShrinkage ?? 0,
        };
      });
  }, [performanceQuery.data]);

  const averageAccuracy = useMemo(() => {
    if (!chartData.length) {
      return 0;
    }

    const total = chartData.reduce((sum, point) => sum + point.accuracyPct, 0);
    return total / chartData.length;
  }, [chartData]);

  const averageGap = useMemo(() => {
    if (!chartData.length) {
      return 0;
    }

    const totalGap = chartData.reduce(
      (sum, point) => sum + Math.abs(point.predictedReturnPct - point.actualReturnPct),
      0,
    );

    return totalGap / chartData.length;
  }, [chartData]);

  const latestPoint = chartData[chartData.length - 1];

  const gaugeColor =
    averageAccuracy >= 80
      ? "#34d399"
      : averageAccuracy >= 60
        ? "#f59e0b"
        : "#fb7185";

  if (!isPremium) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Premium Feature</CardTitle>
          <CardDescription>
            AI performance analytics is available only for PREMIUM users.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Badge variant="warning">Upgrade required</Badge>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-5">
      <section className="relative overflow-hidden rounded-2xl border border-cyan-500/25 bg-slate-950/80 p-5 text-slate-100 shadow-[0_0_80px_-45px_rgba(8,145,178,0.95)]">
        <div className="pointer-events-none absolute -right-16 -top-20 h-56 w-56 rounded-full bg-cyan-500/20 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-24 left-0 h-52 w-52 rounded-full bg-emerald-500/20 blur-3xl" />

        <div className="relative flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-[0.26em] text-cyan-300/85">AI Learning Module</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight">Prediction Trust Console</h2>
            <p className="mt-1 max-w-2xl text-sm text-slate-300/85">
              Compare predicted performance against real outcomes, monitor confidence drift,
              and trigger fresh historical backtests on demand.
            </p>
          </div>
          <Badge className="border border-cyan-400/45 bg-cyan-500/20 text-cyan-100">Live model telemetry</Badge>
        </div>

        <div className="relative mt-5 grid gap-3 sm:grid-cols-3">
          <div className="rounded-xl border border-slate-700/70 bg-slate-900/75 p-3">
            <p className="text-[11px] uppercase tracking-[0.16em] text-slate-400">Backtests visualized</p>
            <p className="mt-1 text-2xl font-semibold text-slate-100">{chartData.length}</p>
          </div>
          <div className="rounded-xl border border-slate-700/70 bg-slate-900/75 p-3">
            <p className="text-[11px] uppercase tracking-[0.16em] text-slate-400">Average reality gap</p>
            <p className="mt-1 text-2xl font-semibold text-amber-300">{formatPercentage(averageGap)}</p>
          </div>
          <div className="rounded-xl border border-slate-700/70 bg-slate-900/75 p-3">
            <p className="text-[11px] uppercase tracking-[0.16em] text-slate-400">Latest test date</p>
            <p className="mt-1 text-2xl font-semibold text-emerald-300">{latestPoint?.dateLabel || "-"}</p>
          </div>
        </div>
      </section>

      {(performanceQuery.error || backtestMutation.error) ? (
        <Card className="border-destructive/40 bg-destructive/10">
          <CardContent className="pt-6 text-sm text-destructive">
            {performanceQuery.error
              ? mapApiError(performanceQuery.error)
              : backtestMutation.error
                ? mapApiError(backtestMutation.error)
                : "An unknown error occurred."}
          </CardContent>
        </Card>
      ) : null}

      <section className="grid gap-4 xl:grid-cols-[2fr_1fr]">
        <Card className="border-cyan-500/20 bg-slate-950/80 text-slate-100">
          <CardHeader>
            <CardTitle className="text-base text-cyan-200">ROI Comparison: Predicted vs Actual</CardTitle>
            <CardDescription className="text-slate-400">
              Last 10-20 model evaluations with predicted versus actual ROI.
            </CardDescription>
          </CardHeader>
          <CardContent className="h-[340px]">
            {performanceQuery.isLoading ? (
              <div className="flex h-full items-center justify-center text-sm text-slate-400">
                Loading AI performance history...
              </div>
            ) : chartData.length === 0 ? (
              <div className="flex h-full items-center justify-center text-sm text-slate-400">
                No performance logs available yet. Trigger a backtest to start tracking.
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData} margin={{ top: 8, right: 18, left: 0, bottom: 10 }}>
                  <CartesianGrid strokeDasharray="4 4" stroke="rgba(148,163,184,0.28)" />
                  <XAxis dataKey="dateLabel" stroke="rgba(203,213,225,0.78)" tick={{ fontSize: 12 }} />
                  <YAxis
                    stroke="rgba(203,213,225,0.78)"
                    tick={{ fontSize: 12 }}
                    tickFormatter={(value) => `${value.toFixed(0)}%`}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "rgba(2, 6, 23, 0.95)",
                      border: "1px solid rgba(56, 189, 248, 0.35)",
                      borderRadius: "0.65rem",
                    }}
                    formatter={(value: number, name: string) => [
                      formatPercentage(value),
                      name,
                    ]}
                    labelFormatter={(label) => `Backtest: ${label}`}
                  />
                  <Line
                    type="monotone"
                    dataKey="predictedReturnPct"
                    name="Predicted ROI"
                    stroke="#22d3ee"
                    strokeWidth={2.2}
                    dot={{ r: 2 }}
                    activeDot={{ r: 4 }}
                  />
                  <Line
                    type="monotone"
                    dataKey="actualReturnPct"
                    name="Actual ROI"
                    stroke="#f59e0b"
                    strokeWidth={2.2}
                    dot={{ r: 2 }}
                    activeDot={{ r: 4 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        <Card className="border-cyan-500/20 bg-slate-950/80 text-slate-100">
          <CardHeader>
            <CardTitle className="text-base text-cyan-200">Confidence Metric</CardTitle>
            <CardDescription className="text-slate-400">Average model accuracy score.</CardDescription>
          </CardHeader>
          <CardContent className="flex h-[340px] flex-col items-center justify-between gap-3">
            <div className="h-[210px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <RadialBarChart
                  cx="50%"
                  cy="58%"
                  innerRadius="70%"
                  outerRadius="100%"
                  barSize={24}
                  data={[{ name: "Accuracy", value: averageAccuracy, fill: gaugeColor }]}
                  startAngle={205}
                  endAngle={-25}
                >
                  <PolarAngleAxis type="number" domain={[0, 100]} tick={false} />
                  <RadialBar
                    dataKey="value"
                    background={{ fill: "rgba(148,163,184,0.20)" }}
                    cornerRadius={16}
                  />
                </RadialBarChart>
              </ResponsiveContainer>
            </div>

            <div className="text-center">
              <p className="text-4xl font-semibold" style={{ color: gaugeColor }}>
                {formatPercentage(averageAccuracy, 1)}
              </p>
              <p className="text-[11px] uppercase tracking-[0.24em] text-slate-400">Average Model Accuracy</p>
            </div>

            <div className="w-full space-y-2 rounded-lg border border-slate-700/70 bg-slate-900/70 p-3 text-xs">
              <div className="flex items-center justify-between text-slate-300">
                <span>Latest Risk-Free Rate</span>
                <span className="font-medium text-slate-100">
                  {latestPoint ? formatPercentage(latestPoint.riskFreeRatePct, 2) : "-"}
                </span>
              </div>
              <div className="flex items-center justify-between text-slate-300">
                <span>Latest Covariance Shrinkage</span>
                <span className="font-medium text-slate-100">
                  {latestPoint ? latestPoint.covarianceShrinkage.toFixed(4) : "-"}
                </span>
              </div>
            </div>
          </CardContent>
        </Card>
      </section>

      <Card className="border-cyan-500/20 bg-slate-950/80 text-slate-100">
        <CardHeader>
          <CardTitle className="text-base text-cyan-200">Manual Backtest Trigger</CardTitle>
          <CardDescription className="text-slate-400">
            Run an AI backtest for a chosen historical date and budget.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <form onSubmit={form.handleSubmit(onSubmit)} className="grid gap-4 md:grid-cols-3">
            <div className="space-y-2">
              <Label htmlFor="historicalDate" className="text-slate-300">
                Historical Date
              </Label>
              <Input
                id="historicalDate"
                type="date"
                className="border-slate-700 bg-slate-900/80 text-slate-100"
                {...form.register("historicalDate")}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="budgetEgp" className="text-slate-300">
                Budget (EGP)
              </Label>
              <Input
                id="budgetEgp"
                type="number"
                step="1000"
                className="border-slate-700 bg-slate-900/80 text-slate-100"
                {...form.register("budgetEgp")}
              />
            </div>

            <div className="flex items-end">
              <Button
                type="submit"
                className="w-full bg-cyan-500 text-slate-950 hover:bg-cyan-400"
                disabled={backtestMutation.isPending || !userId}
              >
                {backtestMutation.isPending ? "Running backtest..." : "Trigger Backtest"}
              </Button>
            </div>
          </form>

          {backtestMutation.data ? (
            <div className="grid gap-3 rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm md:grid-cols-4">
              <div>
                <p className="text-xs uppercase tracking-wide text-emerald-200/80">Status</p>
                <p className="font-medium text-emerald-100">{backtestMutation.data.status || "-"}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-emerald-200/80">Request ID</p>
                <p className="truncate font-medium text-emerald-100">{backtestMutation.data.requestId || "-"}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-emerald-200/80">Current Value</p>
                <p className="font-medium text-emerald-100">
                  {formatCurrencyEGP(backtestMutation.data.currentValueEgp)}
                </p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-emerald-200/80">ROI</p>
                <p className="font-medium text-emerald-100">
                  {typeof backtestMutation.data.roiPct === "number"
                    ? `${backtestMutation.data.roiPct.toFixed(2)}%`
                    : "-"}
                </p>
              </div>
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
