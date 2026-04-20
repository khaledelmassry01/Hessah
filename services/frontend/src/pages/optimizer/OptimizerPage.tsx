import { useCallback, useMemo, useState } from "react";
import axios from "axios";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { AlertTriangle, CheckCircle2, LoaderCircle, Sparkles, X } from "lucide-react";

import { AllocationPieChart } from "@/components/charts/AllocationPieChart";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
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
  executePortfolioRebalance,
  fetchInstruments,
  generatePortfolio,
  mapApiError,
} from "@/lib/api";
import { formatCurrencyEGP } from "@/lib/format";
import type {
  GeneratePortfolioPayload,
  InstrumentSummary,
  PortfolioAllocation,
  RiskLevel,
} from "@/types/api";

const optimizerSchema = z.object({
  budget: z.coerce
    .number({ invalid_type_error: "Budget is required" })
    .positive("Budget must be greater than zero")
    .min(1000, "Minimum budget is 1,000 EGP"),
  riskLevel: z.enum(["LOW", "MEDIUM", "HIGH"]),
});

type OptimizerFormValues = z.infer<typeof optimizerSchema>;

type ToastTone = "error" | "success";

type ToastMessage = {
  id: number;
  title: string;
  message: string;
  tone: ToastTone;
};

type ExecutionPlanRow = {
  key: string;
  symbol: string;
  instrumentName: string;
  targetedShares?: number;
  currentPrice?: number;
  totalAllocationEgp?: number;
};

const FALLBACK_SECTORS = [
  "BANKS",
  "FINANCIAL_SERVICES",
  "INDUSTRIALS",
  "REAL_ESTATE",
  "CONSUMER",
  "ENERGY",
  "TELECOM",
] as const;

function resolveErrorToast(error: unknown) {
  if (axios.isAxiosError(error)) {
    const status = error.response?.status;

    if (status === 429) {
      return {
        title: "Rate Limited",
        message: "AI service is rate limited right now. Please retry in a few seconds.",
      };
    }

    if (status === 502 || status === 503 || status === 504) {
      return {
        title: "AI Engine Unavailable",
        message: "The AI engine is temporarily down. Try again shortly.",
      };
    }
  }

  return {
    title: "Optimization Failed",
    message: mapApiError(error),
  };
}

function toShares(value?: number) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "-";
  }

  return Math.round(value).toLocaleString("en-EG");
}

function inferCurrentPrice(
  row: {
    priceSnapshot?: number;
    executedAmountEgp?: number;
    executedShares?: number;
  },
  instrument?: InstrumentSummary,
) {
  if (typeof row.priceSnapshot === "number") {
    return row.priceSnapshot;
  }

  if (
    typeof row.executedAmountEgp === "number" &&
    typeof row.executedShares === "number" &&
    row.executedShares > 0
  ) {
    return row.executedAmountEgp / row.executedShares;
  }

  return instrument?.lastPrice;
}

export function OptimizerPage() {
  const { user, tokens } = useAuth();
  const userId = user?.userId ?? tokens?.userId;

  const [selectedSectors, setSelectedSectors] = useState<string[]>([]);
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const [lastPayload, setLastPayload] = useState<GeneratePortfolioPayload | null>(null);

  const form = useForm<OptimizerFormValues>({
    resolver: zodResolver(optimizerSchema),
    defaultValues: {
      budget: 50000,
      riskLevel: "MEDIUM",
    },
  });

  const instrumentsQuery = useQuery<InstrumentSummary[]>({
    queryKey: ["optimizer-instruments"],
    queryFn: fetchInstruments,
    retry: 1,
  });

  const instruments: InstrumentSummary[] = useMemo(
    () => (instrumentsQuery.data ?? []) as InstrumentSummary[],
    [instrumentsQuery.data],
  );

  const pushToast = useCallback((title: string, message: string, tone: ToastTone) => {
    const id = Date.now() + Math.floor(Math.random() * 1000);

    setToasts((current) => [...current, { id, title, message, tone }]);

    window.setTimeout(() => {
      setToasts((current) => current.filter((toast) => toast.id !== id));
    }, 6000);
  }, []);

  const previewMutation = useMutation({
    mutationFn: async (values: OptimizerFormValues) => {
      if (!userId) {
        throw new Error("User session is missing. Please login again.");
      }

      const payload: GeneratePortfolioPayload = {
        userId,
        amount: values.budget,
        riskLevel: values.riskLevel as RiskLevel,
        sectorConstraints: selectedSectors,
      };

      const response = await generatePortfolio(payload);
      setLastPayload(payload);
      return response;
    },
    onError: (error) => {
      const toast = resolveErrorToast(error);
      pushToast(toast.title, toast.message, "error");
    },
  });

  const executeMutation = useMutation({
    mutationFn: async () => {
      if (!lastPayload) {
        throw new Error("Generate a portfolio preview before executing.");
      }

      return executePortfolioRebalance(lastPayload);
    },
    onSuccess: () => {
      pushToast(
        "Execution Submitted",
        "Execute & Rebalance was accepted and sent to the portfolio engine.",
        "success",
      );
    },
    onError: (error) => {
      const toast = resolveErrorToast(error);
      pushToast(toast.title, toast.message, "error");
    },
  });

  const sectorOptions = useMemo(() => {
    const dynamicSectors = instruments
      .map((instrument) => instrument.sector)
      .filter((sector): sector is string => typeof sector === "string" && sector.length > 0);

    return [...new Set([...FALLBACK_SECTORS, ...dynamicSectors])];
  }, [instruments]);

  const instrumentsById = useMemo(() => {
    const index = new Map<number, InstrumentSummary>();

    instruments.forEach((instrument) => {
      if (typeof instrument.id === "number") {
        index.set(instrument.id, instrument);
      }
    });

    return index;
  }, [instruments]);

  const instrumentsBySymbol = useMemo(() => {
    const index = new Map<string, InstrumentSummary>();

    instruments.forEach((instrument) => {
      index.set(instrument.symbol.toUpperCase(), instrument);
    });

    return index;
  }, [instruments]);

  const executionPlanRows = useMemo<ExecutionPlanRow[]>(() => {
    const allocations = previewMutation.data?.allocations ?? [];

    return allocations
      .map((allocation, idx) => {
        const indexedInstrumentById =
          typeof allocation.stockId === "number"
            ? instrumentsById.get(allocation.stockId)
            : undefined;

        const indexedInstrumentBySymbol =
          allocation.symbol && allocation.symbol !== "N/A"
            ? instrumentsBySymbol.get(allocation.symbol.toUpperCase())
            : undefined;

        const instrument = indexedInstrumentById || indexedInstrumentBySymbol;

        const symbol =
          allocation.symbol !== "N/A"
            ? allocation.symbol
            : instrument?.symbol ||
              (typeof allocation.stockId === "number"
                ? `STK-${allocation.stockId}`
                : `ROW-${idx + 1}`);

        const currentPrice = inferCurrentPrice(allocation, instrument);

        const targetedShares =
          allocation.executedShares ??
          (typeof allocation.targetAmountEgp === "number" &&
          typeof currentPrice === "number" &&
          currentPrice > 0
            ? allocation.targetAmountEgp / currentPrice
            : undefined);

        const totalAllocationEgp =
          allocation.targetAmountEgp ??
          allocation.executedAmountEgp ??
          (typeof targetedShares === "number" && typeof currentPrice === "number"
            ? targetedShares * currentPrice
            : undefined);

        return {
          key: `${symbol}-${idx}`,
          symbol,
          instrumentName: allocation.name || instrument?.name || "Unknown instrument",
          targetedShares,
          currentPrice,
          totalAllocationEgp,
        };
      })
      .sort((a, b) => (b.totalAllocationEgp ?? 0) - (a.totalAllocationEgp ?? 0));
  }, [instrumentsById, instrumentsBySymbol, previewMutation.data?.allocations]);

  const hasPreview = executionPlanRows.length > 0;

  const chartAllocations = useMemo<PortfolioAllocation[]>(
    () =>
      executionPlanRows.map((row) => ({
        symbol: row.symbol,
        name: row.instrumentName,
        executedAmountEgp: row.totalAllocationEgp,
        targetAmountEgp: row.totalAllocationEgp,
      })),
    [executionPlanRows],
  );

  function toggleSector(sector: string) {
    setSelectedSectors((current) => {
      if (current.includes(sector)) {
        return current.filter((item) => item !== sector);
      }

      return [...current, sector];
    });
  }

  async function onSubmit(values: OptimizerFormValues) {
    await previewMutation.mutateAsync(values);
  }

  if (instrumentsQuery.isLoading && instruments.length === 0) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-12 w-64" />
        <Skeleton className="h-60" />
        <Skeleton className="h-80" />
      </div>
    );
  }

  return (
    <div className="relative space-y-6">
      <section className="relative overflow-hidden rounded-2xl border border-cyan-500/20 bg-slate-950/80 p-5 text-slate-100 shadow-[0_0_70px_-42px_rgba(6,182,212,0.95)]">
        <div className="pointer-events-none absolute -right-16 -top-20 h-52 w-52 rounded-full bg-cyan-500/20 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-16 left-2 h-52 w-52 rounded-full bg-emerald-500/20 blur-3xl" />

        <div className="relative flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-[0.22em] text-cyan-300/85">AI Portfolio Engine</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight">Optimizer Wizard</h2>
            <p className="mt-1 max-w-2xl text-sm text-slate-300/85">
              Build an AI preview, review the execution plan, then trigger Execute & Rebalance.
            </p>
          </div>
          <Badge className="border border-cyan-400/45 bg-cyan-500/20 text-cyan-100">
            Dark Fintech Workspace
          </Badge>
        </div>
      </section>

      <Card className="border-cyan-500/20 bg-slate-950/80 text-slate-100">
        <CardHeader>
          <CardTitle className="text-cyan-200">Optimization Inputs</CardTitle>
          <CardDescription className="text-slate-400">
            Budget and risk are required. Sector constraints are optional tags.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <div className="grid gap-4 md:grid-cols-3">
              <div className="space-y-2">
                <Label htmlFor="budget" className="text-slate-300">
                  Budget (EGP)
                </Label>
                <Input
                  id="budget"
                  type="number"
                  step="1000"
                  className="border-slate-700 bg-slate-900/75 text-slate-100"
                  {...form.register("budget")}
                />
                {form.formState.errors.budget ? (
                  <p className="text-xs text-rose-300">{form.formState.errors.budget.message}</p>
                ) : null}
              </div>

              <div className="space-y-2">
                <Label htmlFor="riskLevel" className="text-slate-300">
                  Risk Level
                </Label>
                <Select
                  id="riskLevel"
                  className="border-slate-700 bg-slate-900/75 text-slate-100"
                  options={[
                    { value: "LOW", label: "Low" },
                    { value: "MEDIUM", label: "Medium" },
                    { value: "HIGH", label: "High" },
                  ]}
                  {...form.register("riskLevel")}
                />
              </div>

              <div className="flex items-end">
                <Button
                  type="submit"
                  className="w-full bg-cyan-500 text-slate-950 hover:bg-cyan-400"
                  disabled={previewMutation.isPending || !userId}
                >
                  {previewMutation.isPending ? (
                    <>
                      <LoaderCircle className="h-4 w-4 animate-spin" />
                      Generating...
                    </>
                  ) : (
                    <>
                      <Sparkles className="h-4 w-4" />
                      Generate Portfolio
                    </>
                  )}
                </Button>
              </div>
            </div>

            <div className="space-y-2">
              <Label className="text-slate-300">Sector Constraints (Optional)</Label>
              <div className="flex flex-wrap gap-2">
                {sectorOptions.map((sector) => {
                  const selected = selectedSectors.includes(sector);

                  return (
                    <button
                      key={sector}
                      type="button"
                      onClick={() => toggleSector(sector)}
                      className={
                        selected
                          ? "rounded-full border border-cyan-400/80 bg-cyan-500/20 px-3 py-1 text-xs font-semibold text-cyan-100"
                          : "rounded-full border border-slate-600/70 bg-slate-900/70 px-3 py-1 text-xs text-slate-300 transition hover:border-cyan-500/60"
                      }
                    >
                      {sector}
                    </button>
                  );
                })}
              </div>
            </div>
          </form>
        </CardContent>
      </Card>

      {previewMutation.isPending ? (
        <Card className="border-cyan-500/20 bg-slate-950/80 text-slate-100">
          <CardContent className="pt-6">
            <div className="rounded-xl border border-cyan-500/30 bg-cyan-500/10 px-4 py-5">
              <div className="flex items-center gap-3">
                <div className="relative h-4 w-4">
                  <span className="absolute inset-0 rounded-full bg-cyan-300/80 animate-ping" />
                  <span className="absolute inset-0 rounded-full bg-cyan-300" />
                </div>
                <p className="text-sm text-cyan-100">
                  AI engine is computing your optimized allocation. Please wait...
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-[1.1fr_1.9fr]">
        <AllocationPieChart allocations={chartAllocations} title="Allocation Preview" />

        <Card className="border-cyan-500/20 bg-slate-950/80 text-slate-100">
          <CardHeader>
            <CardTitle className="text-cyan-200">Execution Plan</CardTitle>
            <CardDescription className="text-slate-400">
              Stock symbol and real name, targeted shares, current price, and total allocation.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Stock Symbol / Name</TableHead>
                  <TableHead>Targeted Shares</TableHead>
                  <TableHead>Current Price</TableHead>
                  <TableHead>Total Allocation</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {hasPreview ? (
                  executionPlanRows.map((row) => (
                    <TableRow key={row.key}>
                      <TableCell>
                        <div className="flex flex-col gap-1">
                          <span className="font-semibold text-slate-100">{row.symbol}</span>
                          <span className="text-xs text-slate-400">{row.instrumentName}</span>
                        </div>
                      </TableCell>
                      <TableCell>{toShares(row.targetedShares)}</TableCell>
                      <TableCell>{formatCurrencyEGP(row.currentPrice)}</TableCell>
                      <TableCell>{formatCurrencyEGP(row.totalAllocationEgp)}</TableCell>
                    </TableRow>
                  ))
                ) : (
                  <TableRow>
                    <TableCell colSpan={4} className="text-center text-slate-400">
                      Generate a preview to build the execution plan.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>

            <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-700/70 bg-slate-900/65 p-3">
              <div className="text-xs text-slate-400">
                {previewMutation.data?.portfolioRunId
                  ? `Preview Run ID: ${previewMutation.data.portfolioRunId}`
                  : "Preview run will appear after generation"}
              </div>
              <Button
                className="bg-emerald-500 text-slate-950 hover:bg-emerald-400"
                onClick={() => executeMutation.mutate()}
                disabled={!hasPreview || executeMutation.isPending}
              >
                {executeMutation.isPending ? (
                  <>
                    <LoaderCircle className="h-4 w-4 animate-spin" />
                    Executing...
                  </>
                ) : (
                  "Execute & Rebalance"
                )}
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>

      {toasts.length > 0 ? (
        <div className="fixed right-4 top-4 z-50 flex w-[340px] flex-col gap-2">
          {toasts.map((toast) => (
            <div
              key={toast.id}
              className={
                toast.tone === "success"
                  ? "rounded-lg border border-emerald-400/60 bg-emerald-500/20 p-3 text-emerald-100 shadow-xl backdrop-blur"
                  : "rounded-lg border border-rose-400/60 bg-rose-500/20 p-3 text-rose-100 shadow-xl backdrop-blur"
              }
            >
              <div className="flex items-start gap-2">
                {toast.tone === "success" ? (
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
                ) : (
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                )}
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold">{toast.title}</p>
                  <p className="mt-0.5 text-xs opacity-90">{toast.message}</p>
                </div>
                <button
                  type="button"
                  onClick={() => setToasts((current) => current.filter((item) => item.id !== toast.id))}
                  className="rounded p-0.5 opacity-80 transition hover:opacity-100"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
