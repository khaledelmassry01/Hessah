import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";

export function NotFoundPage() {
  return (
    <div className="grid min-h-screen place-items-center px-4">
      <div className="text-center">
        <p className="text-sm uppercase tracking-[0.2em] text-muted-foreground">404</p>
        <h1 className="mt-2 text-3xl font-semibold">Page Not Found</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          The requested route does not exist in the EGX optimizer frontend.
        </p>
        <Button className="mt-6" asChild>
          <Link to="/">Go to Dashboard</Link>
        </Button>
      </div>
    </div>
  );
}
