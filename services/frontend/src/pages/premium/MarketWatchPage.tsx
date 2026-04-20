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

  return (
    <div className="space-y-5">
      <section className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">Market Watch</h2>
          <p className="text-sm text-muted-foreground">
            Monitor active stop-loss and take-profit guardrails.
          </p>
        </div>
        <Button variant="outline" onClick={() => rulesQuery.refetch()}>
          Refresh
        </Button>
      </section>

      <Card>
        <CardHeader>
          <CardTitle>Active Stop Rules</CardTitle>
          <CardDescription>Rule state synchronized with premium backend endpoints</CardDescription>
        </CardHeader>
        <CardContent>
          {rulesQuery.isLoading ? (
            <p className="text-sm text-muted-foreground">Loading market watch...</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Rule ID</TableHead>
                  <TableHead>Portfolio Run</TableHead>
                  <TableHead>Stop Loss</TableHead>
                  <TableHead>Take Profit</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rulesQuery.data?.length ? (
                  rulesQuery.data.map((rule) => (
                    <TableRow key={rule.id}>
                      <TableCell className="font-medium">{rule.id}</TableCell>
                      <TableCell>{rule.portfolioRunId ?? "-"}</TableCell>
                      <TableCell>
                        {typeof rule.stopLossPct === "number"
                          ? `${(rule.stopLossPct * 100).toFixed(2)}%`
                          : "-"}
                      </TableCell>
                      <TableCell>
                        {typeof rule.takeProfitPct === "number"
                          ? `${(rule.takeProfitPct * 100).toFixed(2)}%`
                          : "-"}
                      </TableCell>
                      <TableCell>
                        {rule.isActive ? (
                          <Badge variant="success">Active</Badge>
                        ) : (
                          <Badge variant="secondary">Inactive</Badge>
                        )}
                      </TableCell>
                    </TableRow>
                  ))
                ) : (
                  <TableRow>
                    <TableCell colSpan={5} className="text-center text-muted-foreground">
                      No active rules found. If this endpoint is not enabled yet, the table stays empty.
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
