import { Suspense, lazy } from "react";
import { Route, Routes } from "react-router-dom";

import { ProtectedRoute, PublicOnlyRoute } from "@/routes/ProtectedRoute";

const DashboardLayout = lazy(() =>
  import("@/components/layout/AppShell").then((module) => ({
    default: module.AppShell,
  })),
);

const NotFoundPage = lazy(() =>
  import("@/pages/NotFoundPage").then((module) => ({
    default: module.NotFoundPage,
  })),
);

const LoginPage = lazy(() =>
  import("@/pages/auth/LoginPage").then((module) => ({
    default: module.LoginPage,
  })),
);

const RegisterPage = lazy(() =>
  import("@/pages/auth/RegisterPage").then((module) => ({
    default: module.RegisterPage,
  })),
);

const DashboardPage = lazy(() =>
  import("@/pages/Dashboard").then((module) => ({
    default: module.Dashboard,
  })),
);

const OptimizerPage = lazy(() =>
  import("@/pages/optimizer/OptimizerPage").then((module) => ({
    default: module.OptimizerPage,
  })),
);

const BacktestPage = lazy(() =>
  import("@/pages/premium/BacktestPage").then((module) => ({
    default: module.BacktestPage,
  })),
);

const AIPerformancePage = lazy(() =>
  import("@/pages/AIPerformancePage").then((module) => ({
    default: module.AIPerformancePage,
  })),
);

const AILearningDashboardPage = lazy(() =>
  import("@/pages/premium/AILearningDashboard").then((module) => ({
    default: module.AILearningDashboard,
  })),
);

const MarketWatchPage = lazy(() =>
  import("@/pages/premium/MarketWatchPage").then((module) => ({
    default: module.MarketWatchPage,
  })),
);

const ProfileSettingsPage = lazy(() =>
  import("@/pages/settings/ProfileSettingsPage").then((module) => ({
    default: module.ProfileSettingsPage,
  })),
);

function RouteFallback() {
  return (
    <div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">
      Loading screen...
    </div>
  );
}

export default function App() {
  return (
    <Suspense fallback={<RouteFallback />}>
      <Routes>
        <Route element={<PublicOnlyRoute />}>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
        </Route>

        <Route element={<ProtectedRoute />}>
          <Route element={<DashboardLayout />}>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/optimize" element={<OptimizerPage />} />
            <Route path="/optimizer" element={<OptimizerPage />} />
            <Route path="/performance" element={<AILearningDashboardPage />} />
            <Route path="/premium/backtest" element={<BacktestPage />} />
            <Route path="/premium/ai-learning" element={<AILearningDashboardPage />} />
            <Route path="/premium/ai-performance" element={<AIPerformancePage />} />
            <Route path="/premium/market-watch" element={<MarketWatchPage />} />
            <Route path="/settings/profile" element={<ProfileSettingsPage />} />
            <Route path="/profile-sessions" element={<ProfileSettingsPage />} />
            <Route path="/settings/profile-sessions" element={<ProfileSettingsPage />} />
          </Route>
        </Route>

        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </Suspense>
  );
}
