import { TrendingDown, TrendingUp } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type StatCardProps = {
  title: string;
  value: string;
  subtitle?: string;
  trend?: "up" | "down";
  className?: string;
};

export function StatCard({ title, value, subtitle, trend, className }: StatCardProps) {
  return (
    <Card className={cn("animate-fade-in-up", className)}>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex items-center justify-between gap-3">
          <p className="text-2xl font-semibold tracking-tight">{value}</p>
          {trend === "up" ? (
            <TrendingUp className="h-4 w-4 text-emerald-500" />
          ) : null}
          {trend === "down" ? (
            <TrendingDown className="h-4 w-4 text-rose-500" />
          ) : null}
        </div>
        {subtitle ? <p className="mt-1 text-xs text-muted-foreground">{subtitle}</p> : null}
      </CardContent>
    </Card>
  );
}
