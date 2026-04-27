import { Link } from "react-router-dom";
import { Lock } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

export function UpgradePage() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <Card className="max-w-md w-full">
        <CardHeader className="text-center">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-amber-100 dark:bg-amber-900/30">
            <Lock className="h-8 w-8 text-amber-600 dark:text-amber-400" />
          </div>
          <CardTitle className="text-xl">Pro Feature</CardTitle>
          <CardDescription>
            This feature requires a PRO or ADMIN account.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col items-center gap-4">
          <Badge variant="warning" className="px-4 py-1 text-sm">
            Upgrade to Pro
          </Badge>
          <p className="text-sm text-muted-foreground text-center">
            Unlock AI-powered market insights, backtesting, stop-loss guardrails,
            and explainable AI signals with a PRO subscription.
          </p>
          <Button asChild variant="default">
            <Link to="/">Back to Dashboard</Link>
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
