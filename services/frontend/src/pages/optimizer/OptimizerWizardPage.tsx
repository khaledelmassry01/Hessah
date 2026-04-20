import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { AllocationPieChart } from "@/components/charts/AllocationPieChart";
import { RoiBarChart } from "@/components/charts/RoiBarChart";
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
import { generatePortfolio, mapApiError } from "@/lib/api";
import { formatCurrencyEGP } from "@/lib/format";

const optimizerSchema = z.object({
  amount: z.coerce
    .number({ invalid_type_error: "Amount is required" })
    .positive("Amount must be greater than zero")
    .min(1000, "Minimum amount is 1,000 EGP"),
  riskLevel: z.enum(["LOW", "MEDIUM", "HIGH"]),
});

type OptimizerFormValues = z.infer<typeof optimizerSchema>;

export function OptimizerWizardPage() {
  const { user, tokens } = useAuth();
  const userId = user?.userId ?? tokens?.userId;

  const form = useForm<OptimizerFormValues>({
    resolver: zodResolver(optimizerSchema),
    defaultValues: {
      amount: 50000,
      riskLevel: "LOW",
    },
  });

  const optimizeMutation = useMutation({
    mutationFn: async (values: OptimizerFormValues) =>
      generatePortfolio({
        userId: userId as number,
        amount: values.amount,
        riskLevel: values.riskLevel,
      }),
  });

  const result = optimizeMutation.data;

  async function onSubmit(values: OptimizerFormValues) {
    await optimizeMutation.mutateAsync(values);
  }

  return (
    <div className="space-y-5">
      <section>
        <h2 className="text-2xl font-semibold tracking-tight">Optimizer Wizard</h2>
        <p className="text-sm text-muted-foreground">
          Submit an investment amount and risk profile to generate a new EGX allocation.
        </p>
      </section>

      <Card>
        <CardHeader>
          <CardTitle>New Optimization Request</CardTitle>
          <CardDescription>Model runtime may take a few seconds depending on market constraints.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={form.handleSubmit(onSubmit)} className="grid gap-4 md:grid-cols-3">
            <div className="space-y-2">
              <Label htmlFor="amount">Amount (EGP)</Label>
              <Input id="amount" type="number" step="1000" {...form.register("amount")} />
              {form.formState.errors.amount ? (
                <p className="text-xs text-destructive">{form.formState.errors.amount.message}</p>
              ) : null}
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
              <Button type="submit" className="w-full" disabled={optimizeMutation.isPending || !userId}>
                {optimizeMutation.isPending ? "Running optimizer..." : "Generate Portfolio"}
              </Button>
            </div>
          </form>

          {optimizeMutation.error ? (
            <p className="mt-3 text-sm text-destructive">{mapApiError(optimizeMutation.error)}</p>
          ) : null}
        </CardContent>
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <AllocationPieChart allocations={result?.allocations ?? []} title="Generated Allocation" />
        <RoiBarChart
          expectedReturn={result?.expectedReturn}
          expectedVolatility={result?.expectedVolatility}
          title="Expected Risk / Return"
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Optimization Output</CardTitle>
          <CardDescription>
            Run ID: {result?.portfolioRunId ?? "-"} | Status: {result?.status ?? "-"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Symbol</TableHead>
                <TableHead>Sector</TableHead>
                <TableHead>Shares</TableHead>
                <TableHead>Amount</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {result?.allocations?.length ? (
                result.allocations.map((item) => (
                  <TableRow key={`${item.symbol}-${item.executedShares || 0}`}>
                    <TableCell className="font-medium">{item.symbol}</TableCell>
                    <TableCell>{item.sector || "-"}</TableCell>
                    <TableCell>{item.executedShares ?? "-"}</TableCell>
                    <TableCell>{formatCurrencyEGP(item.executedAmountEgp)}</TableCell>
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell colSpan={4} className="text-center text-muted-foreground">
                    Submit the form to see optimization results.
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
