import { useState } from "react";
import { Shield, Activity, Users, Zap } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { apiClient } from "@/lib/api-client";

export function AdminDashboard() {
  const [radarStatus, setRadarStatus] = useState<{
    loading: boolean;
    result: { status?: string; activeStopRules?: number; symbolsWithAiSignals?: number } | null;
  }>({ loading: false, result: null });

  async function triggerRadarScan() {
    setRadarStatus({ loading: true, result: null });
    try {
      const { data } = await apiClient.post("/admin/radar/trigger");
      setRadarStatus({ loading: false, result: data });
    } catch {
      setRadarStatus({ loading: false, result: { status: "ERROR" } });
    }
  }

  async function fetchRadarStatus() {
    setRadarStatus({ loading: true, result: null });
    try {
      const { data } = await apiClient.post("/admin/radar/status");
      setRadarStatus({ loading: false, result: data });
    } catch {
      setRadarStatus({ loading: false, result: { status: "ERROR" } });
    }
  }

  return (
    <div className="space-y-5">
      <section className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">Admin Dashboard</h2>
          <p className="text-sm text-muted-foreground">
            System administration and monitoring tools.
          </p>
        </div>
        <Badge variant="success" className="px-3 py-1">
          <Shield className="mr-1 h-3 w-3" />
          ADMIN
        </Badge>
      </section>

      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <Activity className="h-4 w-4" />
              System Status
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-emerald-600">OK</div>
            <p className="text-xs text-muted-foreground">All services operational</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <Zap className="h-4 w-4" />
              Market Radar
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {radarStatus.result?.activeStopRules ?? "-"}
            </div>
            <p className="text-xs text-muted-foreground">Active stop rules</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <Users className="h-4 w-4" />
              Users
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">-</div>
            <p className="text-xs text-muted-foreground">Total registered</p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Market Radar Controls</CardTitle>
          <CardDescription>
            Manually trigger or check status of the AI market radar scan.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex gap-2">
            <Button onClick={triggerRadarScan} disabled={radarStatus.loading}>
              <Zap className="mr-2 h-4 w-4" />
              Trigger Scan
            </Button>
            <Button variant="outline" onClick={fetchRadarStatus} disabled={radarStatus.loading}>
              <Activity className="mr-2 h-4 w-4" />
              Check Status
            </Button>
          </div>

          {radarStatus.loading && (
            <p className="text-sm text-muted-foreground">Loading...</p>
          )}

          {radarStatus.result && !radarStatus.loading && (
            <div className="rounded-md bg-muted p-3 text-sm">
              <pre className="whitespace-pre-wrap">
                {JSON.stringify(radarStatus.result, null, 2)}
              </pre>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
