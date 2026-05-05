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
import { Info, Lock } from "lucide-react";
import { Link } from "react-router-dom";
import type { StopRule } from "@/types/api";

export function MarketWatchPage() {
  const { isPremium, isPro } = useAuth();
  const isFreeUser = !isPro; // Show FOMO UI for non-pro users

  const rulesQuery = useQuery({
    queryKey: ["market-watch-rules"],
    queryFn: fetchStopRules,
    enabled: isPremium,
  });

  // FOMO: Sample data for free users (shows blur effect on premium columns)
  const sampleData = useMemo(
    () => [
      { id: 1, symbol: "COMI.CA", confidenceScore: 0.85, predictedReturn5d: 0.042, action: "BUY" },
      { id: 2, symbol: "HRHO.CA", confidenceScore: 0.72, predictedReturn5d: 0.031, action: "HOLD" },
      { id: 3, symbol: "SWDY.CA", confidenceScore: 0.91, predictedReturn5d: 0.058, action: "BUY" },
    ],
    [],
  );


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
        <div className="flex items-center gap-2">
          {isFreeUser && (
            <Button asChild className="bg-amber-500 hover:bg-amber-600 text-white">
              <Link to="/upgrade">
                <Lock className="mr-2 h-4 w-4" />
                Upgrade to Pro
              </Link>
            </Button>
          )}
          <Button variant="outline" onClick={() => rulesQuery.refetch()} disabled={isFreeUser}>
            Refresh
          </Button>
        </div>
      </section>
      <Card>
        <CardHeader>
          <CardTitle>
            Active Stop Rules & AI Insights
            {isFreeUser && (
              <Badge variant="warning" className="ml-2 align-middle">
                PRO Preview
              </Badge>
            )}
          </CardTitle>
          <CardDescription>
            {isFreeUser
              ? "Sample preview of AI-powered market insights. Upgrade to unlock full data."
              : "Live XAI metrics and guardrails from backend"}
          </CardDescription>
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
                {isFreeUser
                  ? // FOMO: Sample data for free users with blur effect on premium columns
                    sampleData.map((rec) => (
                      <TableRow key={rec.id}>
                        <TableCell className="font-medium">{rec.symbol}</TableCell>
                        {/* Blurred premium columns with lock overlay */}
                        <TableCell className="relative">
                          <div className="blur-sm select-none">
                            <Badge variant="success">{(rec.confidenceScore * 100).toFixed(2)}%</Badge>
                          </div>
                          <div className="absolute inset-0 flex items-center justify-center">
                            <Lock className="h-4 w-4 text-amber-500" />
                          </div>
                        </TableCell>
                        <TableCell className="relative">
                          <div className="blur-sm select-none">
                            {(rec.predictedReturn5d * 100).toFixed(2)}%
                          </div>
                          <div className="absolute inset-0 flex items-center justify-center">
                            <Lock className="h-4 w-4 text-amber-500" />
                          </div>
                        </TableCell>
                        <TableCell className="relative">
                          <div className="blur-sm select-none">
                            <Badge variant={rec.action === "BUY" ? "success" : "warning"}>
                              {rec.action}
                            </Badge>
                          </div>
                          <div className="absolute inset-0 flex items-center justify-center">
                            <Lock className="h-4 w-4 text-amber-500" />
                          </div>
                        </TableCell>
                        <TableCell className="relative">
                          <div className="blur-sm select-none max-w-[150px]">
                            AI analysis unavailable in preview mode
                          </div>
                          <div className="absolute inset-0 flex items-center justify-center">
                            <Lock className="h-4 w-4 text-amber-500" />
                          </div>
                        </TableCell>
                        <TableCell>-</TableCell>
                        <TableCell>-</TableCell>
                        <TableCell>-</TableCell>
                      </TableRow>
                    ))
                  : recommendations.length
                    ? recommendations.map((rec, idx) => {
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
                            <TableCell className="whitespace-normal break-words">
                              {rec.xaiReasons && rec.xaiReasons.length ? (
                                <ul className="list-disc pl-4 space-y-1">
                                  {rec.xaiReasons.map((reason, reasonIdx) => (
                                    <li key={`${rec.id || idx}-reason-${reasonIdx}`}>{reason}</li>
                                  ))}
                                </ul>
                              ) : (
                                <span>No explainability reasons available.</span>
                              )}
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
                    : (
                      <TableRow>
                        <TableCell colSpan={8} className="text-center text-muted-foreground">
                          No stop rules found.
                        </TableCell>
                      </TableRow>
                    )}
              </TableBody>
            </Table>
          )}
          {isFreeUser && (
            <div className="mt-4 flex items-center justify-center gap-2 text-sm text-muted-foreground">
              <Lock className="h-4 w-4" />
              <span>Upgrade to PRO to unlock real-time AI insights and stop-loss guardrails.</span>
              <Link to="/upgrade" className="text-amber-600 hover:underline font-medium">
                Learn more
              </Link>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
