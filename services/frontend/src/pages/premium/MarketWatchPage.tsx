import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAuth } from "@/contexts/AuthContext";
import { fetchStopRules } from "@/lib/api";
import { useMemo } from "react";
import { Info } from "lucide-react";
import type { StopRule } from "@/types/api";

export function MarketWatchPage() {
  const { isPremium } = useAuth();

  const rulesQuery = useQuery({
    queryKey: ["market-watch-rules"],
    queryFn: fetchStopRules,
    enabled: isPremium,
  });

  if (!isPremium) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Premium Feature</CardTitle>
          <CardDescription>
            Market Watch is available only for PREMIUM users.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Badge variant="warning">Upgrade required</Badge>
        </CardContent>
      </Card>
    );
  }

  // Market Watch: Display enriched Stop Rules with AI Market Radar signals
  // The backend now returns enriched StopRule objects with symbol, confidenceScore,
  // predictedReturn5d, action, and xaiReasons from the Daily AI Radar scan.
  const recommendations = useMemo(() => {
    return Array.isArray(rulesQuery.data)
      ? rulesQuery.data.map((item: StopRule) => ({
          id: item.id,
          stockId: item.stockId,
          symbol: item.symbol, // Use symbol directly from backend
          confidenceScore: item.confidenceScore ?? undefined,
          predictedReturn5d: item.predictedReturn5d ?? undefined,
          action: item.action ?? undefined,
          xaiReasons: item.xaiReasons ?? [],
          stopLossPct: item.stopLossPct ?? undefined,
          takeProfitPct: item.takeProfitPct ?? undefined,
          status: item.status ?? undefined,
          isActive: item.isActive ?? undefined,
        }))
      : [];
  }, [rulesQuery.data]);

  return (
    <div className="space-y-5">
      <section className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">Market Watch</h2>
          <p className="text-sm text-muted-foreground">
            Monitor active stop-loss and take-profit guardrails. Now with explainable AI insights.
          </p>
        </div>
        <Button variant="outline" onClick={() => rulesQuery.refetch()}>
          Refresh
        </Button>
      </section>
      <Card>
        <CardHeader>
          <CardTitle>Active Stop Rules & AI Insights</CardTitle>
          <CardDescription>Live XAI metrics and guardrails from backend</CardDescription>
        </CardHeader>
        <CardContent>
          {rulesQuery.isLoading ? (
            <p className="text-sm text-muted-foreground">Analyzing Market...</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Stock</TableHead>
                  <TableHead>Confidence</TableHead>
                  <TableHead>Pred. Return (5D)</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>XAI Reasons</TableHead>
                  <TableHead>Stop Loss</TableHead>
                  <TableHead>Take Profit</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {recommendations.length ? (
                  recommendations.map((rec, idx) => {
                    const confidence = rec.confidenceScore ?? 0;
                    const isHighConfidence = confidence > 0.6;
                    const badgeVariant = isHighConfidence ? "success" : "warning";
                    const action = rec.action || "HOLD";
                    const actionColor = action === "BUY" ? "success" : action === "HOLD" ? "secondary" : "warning";
                    return (
                      <TableRow key={rec.id || idx}>
                        <TableCell className="font-medium">{rec.symbol || "-"}</TableCell>
                        <TableCell>
                          {rec.confidenceScore !== undefined ? (
                            <Badge variant={badgeVariant}>{(confidence * 100).toFixed(2)}%</Badge>
                          ) : (
                            <span>-</span>
                          )}
                        </TableCell>
                        <TableCell>
                          {typeof rec.predictedReturn5d === "number"
                            ? `${(rec.predictedReturn5d * 100).toFixed(2)}%`
                            : "-"}
                        </TableCell>
                        <TableCell>
                          <Badge variant={actionColor}>{action}</Badge>
                        </TableCell>
                        <TableCell>
                          {rec.xaiReasons?.[0] || "No explainability reasons available."}
                        </TableCell>
                        <TableCell>
                          {typeof rec.stopLossPct === "number"
                            ? `${(rec.stopLossPct * 100).toFixed(2)}%`
                            : "-"}
                        </TableCell>
                        <TableCell>
                          {typeof rec.takeProfitPct === "number"
                            ? `${(rec.takeProfitPct * 100).toFixed(2)}%`
                            : "-"}
                        </TableCell>
                        <TableCell>{rec.status || (rec.isActive ? "ACTIVE" : "-")}</TableCell>
                      </TableRow>
                    );
                  })
                ) : (
                  <TableRow>
                    <TableCell colSpan={8} className="text-center text-muted-foreground">
                      No stop rules found.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
