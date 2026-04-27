import { Navigate, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "@/contexts/AuthContext";

export function ProtectedRoute() {
  const { isAuthenticated, isInitializing } = useAuth();
  const location = useLocation();

  if (isInitializing) {
    return (
      <div className="flex min-h-screen items-center justify-center text-muted-foreground">
        Initializing secure session...
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return <Outlet />;
}

type ProRouteProps = {
  fallbackPath?: string;
};

/**
 * Route that requires PRO or ADMIN role
 */
export function ProRoute({ fallbackPath = "/upgrade" }: ProRouteProps) {
  const { isAuthenticated, isInitializing, isPro } = useAuth();
  const location = useLocation();

  if (isInitializing) {
    return (
      <div className="flex min-h-screen items-center justify-center text-muted-foreground">
        Initializing secure session...
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  if (!isPro) {
    return <Navigate to={fallbackPath} replace state={{ from: location }} />;
  }

  return <Outlet />;
}

/**
 * Route that requires ADMIN role only
 */
export function AdminRoute({ fallbackPath = "/" }: ProRouteProps) {
  const { isAuthenticated, isInitializing, isAdmin } = useAuth();
  const location = useLocation();

  if (isInitializing) {
    return (
      <div className="flex min-h-screen items-center justify-center text-muted-foreground">
        Initializing secure session...
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  if (!isAdmin) {
    return <Navigate to={fallbackPath} replace state={{ from: location }} />;
  }

  return <Outlet />;
}

/**
 * Route wrapper that checks for requirePro prop
 * Can be used inline in routes: element={<ProtectedRoute requirePro />}
 */
export function ProtectedRouteWithPro({ 
  requirePro = false,
  requireAdmin = false,
  fallbackPath = "/upgrade" 
}: { 
  requirePro?: boolean;
  requireAdmin?: boolean;
  fallbackPath?: string;
}) {
  const { isAuthenticated, isInitializing, isPro, isAdmin } = useAuth();
  const location = useLocation();

  if (isInitializing) {
    return (
      <div className="flex min-h-screen items-center justify-center text-muted-foreground">
        Initializing secure session...
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  if (requireAdmin && !isAdmin) {
    return <Navigate to="/" replace state={{ from: location }} />;
  }

  if (requirePro && !isPro) {
    return <Navigate to={fallbackPath} replace state={{ from: location }} />;
  }

  return <Outlet />;
}

export function PublicOnlyRoute() {
  const { isAuthenticated, isInitializing } = useAuth();

  if (isInitializing) {
    return (
      <div className="flex min-h-screen items-center justify-center text-muted-foreground">
        Loading...
      </div>
    );
  }

  if (isAuthenticated) {
    return <Navigate to="/" replace />;
  }

  return <Outlet />;
}
