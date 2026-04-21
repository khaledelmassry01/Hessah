import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { PortfolioPieChart } from "@/components/charts/PortfolioPieChart";
import { StatCard } from "@/components/dashboard/StatCard";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAuth } from "@/contexts/AuthContext";
import {
  fetchAiPerformanceSummary,
  fetchInstruments,
  fetchLatestPortfolio,
  fetchWalletSummary,
  mapApiError,
} from "@/lib/api";
import { formatCurrencyEGP, formatPercent } from "@/lib/format";

function formatSignedPercent(value?: number) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "-";
  }

  const normalized = Math.abs(value) > 1 ? value / 100 : value;
  const prefix = normalized > 0 ? "+" : "";

  return `${prefix}${(normalized * 100).toFixed(2)}%`;
}

export function DashboardPage() {
  const { user, tokens, refreshProfile } = useAuth();
  const userId = user?.userId ?? tokens?.userId;

  const walletQuery = useQuery({
    queryKey: ["wallet", userId],
    queryFn: async () => fetchWalletSummary(userId as number),
    enabled: Boolean(userId),
  });

  const portfolioQuery = useQuery({
    queryKey: ["portfolio-latest", userId],
    queryFn: async () => fetchLatestPortfolio(userId as number),
    enabled: Boolean(userId),
    retry: 1,
  });

  const instrumentsQuery = useQuery({
    queryKey: ["instruments"],
    queryFn: fetchInstruments,
    retry: 1,
  });

  const performanceQuery = useQuery({
    queryKey: ["ai-performance-summary", 15],
    queryFn: () => fetchAiPerformanceSummary(15),
    retry: 1,
  });

  const allocations = portfolioQuery.data?.allocations ?? [];

  const totalInvested = useMemo(
    () => allocations.reduce((sum, row) => sum + (row.executedAmountEgp ?? 0), 0),
    [allocations],
  );

  const walletBalance = useMemo(() => {
    const available = walletQuery.data?.availableBalance ?? 0;
    const locked = walletQuery.data?.lockedBalance ?? 0;

    return available + locked;
  }, [walletQuery.data?.availableBalance, walletQuery.data?.lockedBalance]);

  const latestAccuracy = useMemo(() => {
    const ranked = [...(performanceQuery.data ?? [])].sort(
      (a, b) => new Date(b.testDate).getTime() - new Date(a.testDate).getTime(),
    );

    return ranked.find((entry) => typeof entry.accuracyScore === "number")?.accuracyScore;
  }, [performanceQuery.data]);

  const portfolioModelAccuracy = portfolioQuery.data?.modelAccuracy;
  const displayedModelAccuracy =
    typeof portfolioModelAccuracy === "number" ? portfolioModelAccuracy : latestAccuracy;

  const preventiveSellRecommendations = useMemo(
    () =>
      (portfolioQuery.data?.recommendations ?? []).filter(
        (item) => item.action?.toUpperCase() === "PREVENTIVE_SELL",
      ),
    [portfolioQuery.data?.recommendations],
  );

  const instruments = useMemo(
    () => [...(instrumentsQuery.data ?? [])].sort((a, b) => a.symbol.localeCompare(b.symbol)),
    [instrumentsQuery.data],
  );

  const isLoading = walletQuery.isLoading || portfolioQuery.isLoading || instrumentsQuery.isLoading;

  const hasError = walletQuery.error || portfolioQuery.error || instrumentsQuery.error;

  const errorMessage =
    walletQuery.error
      ? mapApiError(walletQuery.error)
      : portfolioQuery.error
        ? mapApiError(portfolioQuery.error)
        : instrumentsQuery.error
          ? mapApiError(instrumentsQuery.error)
          : null;

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-9 w-48" />
        <div className="grid gap-4 md:grid-cols-3">
          <Skeleton className="h-32" />
          <Skeleton className="h-32" />
          <Skeleton className="h-32" />
        </div>
        <div className="grid gap-4 xl:grid-cols-[1fr_1.3fr]">
          <Skeleton className="h-72" />
          <Skeleton className="h-72" />
        </div>
        <Skeleton className="h-[360px]" />
      </div>
    );
  }

  return (
    <div className="space-y-6 text-slate-100">
      <section className="relative overflow-hidden rounded-2xl border border-cyan-500/20 bg-slate-950/85 p-5 shadow-[0_0_70px_-45px_rgba(6,182,212,0.95)]">
        <div className="pointer-events-none absolute -right-12 -top-16 h-52 w-52 rounded-full bg-cyan-500/20 blur-3xl" />
        <div className="pointer-events-none absolute -left-10 bottom-0 h-44 w-44 rounded-full bg-emerald-500/15 blur-3xl" />
        <div className="relative flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.24em] text-cyan-300/85">Investor Platform</p>
          <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-100">Dashboard</h2>
          <p className="text-sm text-slate-300/80">
            Welcome {user?.fullName || "Investor"}. Track your wallet, AI model confidence, and EGX opportunities.
          </p>
        </div>

        <Button variant="outline" className="border-slate-600 bg-slate-900/80 text-slate-100 hover:bg-slate-800" onClick={refreshProfile}>
          Refresh Profile
        </Button>
        </div>
      </section>

      {hasError ? (
        <Card className="border-destructive/40 bg-destructive/10">
          <CardContent className="pt-6 text-sm text-destructive">
            {errorMessage || "Some widgets failed to load. Check API availability or token validity."}
          </CardContent>
        </Card>
      ) : null}

      <section className="grid gap-4 md:grid-cols-3">
        <StatCard
          title="Balance"
          value={formatCurrencyEGP(walletBalance)}
          subtitle={`Available ${formatCurrencyEGP(walletQuery.data?.availableBalance)}`}
          className="border-slate-700/70 bg-slate-950/80 text-slate-100"
        />
        <StatCard
          title="Total Investment"
          value={formatCurrencyEGP(totalInvested)}
          subtitle="Current allocated capital"
          className="border-slate-700/70 bg-slate-950/80 text-slate-100"
        />
        <StatCard
          title="Model Accuracy"
          value={formatPercent(displayedModelAccuracy)}
          subtitle="Current AI model accuracy score"
          trend={typeof displayedModelAccuracy === "number" && displayedModelAccuracy >= 0.7 ? "up" : undefined}
          className="border-slate-700/70 bg-slate-950/80 text-slate-100"
        />
      </section>

      <section className="grid gap-4 xl:grid-cols-[1fr_1.3fr]">
        <PortfolioPieChart allocations={allocations} />
        <Card className="border-slate-700/70 bg-slate-950/80 text-slate-100">
          <CardHeader>
            <CardTitle>Allocation Snapshot</CardTitle>
            <CardDescription className="text-slate-400">Latest optimizer run financial metrics</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="flex items-center justify-between text-slate-300">
              <span className="text-slate-400">Portfolio Run ID</span>
              <span className="font-medium">{portfolioQuery.data?.portfolioRunId ?? "-"}</span>
            </div>
            <div className="flex items-center justify-between text-slate-300">
              <span className="text-slate-400">Requested Amount</span>
              <span className="font-medium">{formatCurrencyEGP(portfolioQuery.data?.requestedAmount)}</span>
            </div>
            <div className="flex items-center justify-between text-slate-300">
              <span className="text-slate-400">Fee Buffer</span>
              <span className="font-medium">{formatCurrencyEGP(portfolioQuery.data?.feeBuffer)}</span>
            </div>
            <div className="flex items-center justify-between text-slate-300">
              <span className="text-slate-400">Total Invested</span>
              <span className="font-medium">{formatCurrencyEGP(totalInvested)}</span>
            </div>
            <div className="flex items-center justify-between text-slate-300">
              <span className="text-slate-400">Expected Return</span>
              <span className="font-medium">{formatPercent(portfolioQuery.data?.expectedReturn)}</span>
            </div>
            <div className="flex items-center justify-between text-slate-300">
              <span className="text-slate-400">Expected Volatility</span>
              <span className="font-medium">{formatPercent(portfolioQuery.data?.expectedVolatility)}</span>
            </div>
            <div className="flex items-center justify-between text-slate-300">
              <span className="text-slate-400">Predicted Return (5D)</span>
              <span className="font-medium">{formatSignedPercent(portfolioQuery.data?.predictedReturn)}</span>
            </div>
            <div className="flex items-center justify-between text-slate-300">
              <span className="text-slate-400">Confidence Score</span>
              <span className="font-medium">{formatPercent(portfolioQuery.data?.confidenceScore)}</span>
            </div>
          </CardContent>
        </Card>
      </section>

      {preventiveSellRecommendations.length > 0 ? (
        <section>
          <Card className="border-amber-400/40 bg-amber-500/10 text-amber-100">
            <CardHeader>
              <CardTitle>PREVENTIVE_SELL Recommendations</CardTitle>
              <CardDescription className="text-amber-100/80">
                AI model detected potential downside risk of at least 10% over the next 5 trading days.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {preventiveSellRecommendations.map((item, index) => (
                <div
                  key={`${item.symbol || "unknown"}-${index}`}
                  className="rounded-md border border-amber-300/30 bg-slate-950/50 p-3 text-sm"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-semibold">{item.symbol || "Unknown Symbol"}</span>
                    <span className="text-amber-300">{item.action || "PREVENTIVE_SELL"}</span>
                  </div>
                  <div className="mt-1 text-amber-100/85">{item.reason || "Downside risk detected"}</div>
                  <div className="mt-2 flex items-center justify-between text-xs text-amber-100/70">
                    <span>Predicted Return (5D): {formatSignedPercent(item.predictedReturn5d)}</span>
                    <span>Confidence: {formatPercent(item.confidenceScore)}</span>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        </section>
      ) : null}

      <section>
        <Card className="border-slate-700/70 bg-slate-950/80 text-slate-100">
          <CardHeader>
            <CardTitle>Instruments Table</CardTitle>
            <CardDescription className="text-slate-400">Live instruments feed from /api/core/instruments</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Name</TableHead>
                  <TableHead>Sector</TableHead>
                  <TableHead>Last Price</TableHead>
                  <TableHead>Day Change</TableHead>
                  <TableHead>Volume</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {instruments.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={6} className="text-center text-muted-foreground">
                      No instrument data is available.
                    </TableCell>
                  </TableRow>
                ) : (
                  instruments.map((instrument) => (
                    <TableRow key={`${instrument.symbol}-${instrument.id || "0"}`}>
                      <TableCell className="font-medium">{instrument.symbol}</TableCell>
                      <TableCell>{instrument.name || "-"}</TableCell>
                      <TableCell>{instrument.sector || "-"}</TableCell>
                      <TableCell>{formatCurrencyEGP(instrument.lastPrice)}</TableCell>
                      <TableCell
                        className={
                          typeof instrument.dayChangePct === "number"
                            ? instrument.dayChangePct >= 0
                              ? "text-emerald-600"
                              : "text-rose-600"
                            : undefined
                        }
                      >
                        {formatSignedPercent(instrument.dayChangePct)}
                      </TableCell>
                      <TableCell>
                        {typeof instrument.volume === "number"
                          ? instrument.volume.toLocaleString("en-EG")
                          : "-"}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
