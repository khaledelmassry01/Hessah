import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { RoiBarChart } from "@/components/charts/RoiBarChart";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAuth } from "@/contexts/AuthContext";
import { mapApiError, runBacktest } from "@/lib/api";
import { formatCurrencyEGP } from "@/lib/format";

const backtestSchema = z.object({
  budgetEgp: z.coerce.number().positive("Budget must be positive"),
  historicalDate: z.string().min(1, "Historical date is required"),
  riskLevel: z.enum(["LOW", "MEDIUM", "HIGH"]),
});

type BacktestFormValues = z.infer<typeof backtestSchema>;

export function BacktestPage() {
  const { isPremium, user, tokens } = useAuth();
  const userId = user?.userId ?? tokens?.userId;

  const form = useForm<BacktestFormValues>({
    resolver: zodResolver(backtestSchema),
    defaultValues: {
      budgetEgp: 500000,
      historicalDate: new Date().toISOString().slice(0, 10),
      riskLevel: "HIGH",
    },
  });

  const backtestMutation = useMutation({
    mutationFn: async (values: BacktestFormValues) =>
      runBacktest({
        userId: userId as number,
        budgetEgp: values.budgetEgp,
        historicalDate: values.historicalDate,
        riskLevel: values.riskLevel,
        maxSectorWeight: 0.4,
        maxAdv30Participation: 0.05,
        excludeSuspended: true,
        allowFractionalShares: false,
      }),
  });

  async function onSubmit(values: BacktestFormValues) {
    await backtestMutation.mutateAsync(values);
  }

  if (!isPremium) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Premium Feature</CardTitle>
          <CardDescription>
            Backtesting is available only for PREMIUM users.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Badge variant="warning">Upgrade required</Badge>
        </CardContent>
      </Card>
    );
  }

  const result = backtestMutation.data;

  return (
    <div className="space-y-5">
      <section>
        <h2 className="text-2xl font-semibold tracking-tight">Backtest Simulator</h2>
        <p className="text-sm text-muted-foreground">
          Replay historical performance to validate allocation strategy behavior.
        </p>
      </section>

      <Card>
        <CardHeader>
          <CardTitle>Backtest Input</CardTitle>
          <CardDescription>
            Simulations can run for several seconds based on AI workload.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={form.handleSubmit(onSubmit)} className="grid gap-4 md:grid-cols-4">
            <div className="space-y-2">
              <Label htmlFor="budgetEgp">Budget (EGP)</Label>
              <Input id="budgetEgp" type="number" step="1000" {...form.register("budgetEgp")} />
            </div>

            <div className="space-y-2">
              <Label htmlFor="historicalDate">Historical Date</Label>
              <Input id="historicalDate" type="date" {...form.register("historicalDate")} />
            </div>

            <div className="space-y-2">
              <Label htmlFor="riskLevel">Risk Level</Label>
              <Select
                id="riskLevel"
                options={[
                  { value: "LOW", label: "LOW" },
                  { value: "MEDIUM", label: "MEDIUM" },
                  { value: "HIGH", label: "HIGH" },
                ]}
                {...form.register("riskLevel")}
              />
            </div>

            <div className="flex items-end">
              <Button type="submit" className="w-full" disabled={backtestMutation.isPending || !userId}>
                {backtestMutation.isPending ? "Running backtest..." : "Run Backtest"}
              </Button>
            </div>
          </form>

          {backtestMutation.error ? (
            <p className="mt-3 text-sm text-destructive">{mapApiError(backtestMutation.error)}</p>
          ) : null}
        </CardContent>
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Performance Snapshot</CardTitle>
            <CardDescription>ROI and valuation summary</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Status</span>
              <span className="font-medium">{result?.status || "-"}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Original Value</span>
              <span className="font-medium">{formatCurrencyEGP(result?.originalValueEgp)}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Current Value</span>
              <span className="font-medium">{formatCurrencyEGP(result?.currentValueEgp)}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">ROI %</span>
              <span className="font-medium">
                {typeof result?.roiPct === "number" ? `${result.roiPct.toFixed(2)}%` : "-"}
              </span>
            </div>
          </CardContent>
        </Card>

        <RoiBarChart
          expectedReturn={result?.expectedReturn}
          expectedVolatility={result?.expectedVolatility}
          title="Expected Metrics"
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Historical Allocations</CardTitle>
          <CardDescription>Portfolio composition in the selected historical scenario</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Symbol</TableHead>
                <TableHead>Weight</TableHead>
                <TableHead>Shares</TableHead>
                <TableHead>Current Value</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {result?.historicalAllocations?.length ? (
                result.historicalAllocations.map((item) => (
                  <TableRow key={`${item.symbol}-${item.weight || 0}`}>
                    <TableCell className="font-medium">{item.symbol}</TableCell>
                    <TableCell>
                      {typeof item.weight === "number"
                        ? `${(item.weight * 100).toFixed(2)}%`
                        : "-"}
                    </TableCell>
                    <TableCell>{item.shares ?? "-"}</TableCell>
                    <TableCell>{formatCurrencyEGP(item.currentValueEgp)}</TableCell>
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell colSpan={4} className="text-center text-muted-foreground">
                    No backtest data yet.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
