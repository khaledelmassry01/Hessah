import { useMemo } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import {
  Bot,
  Gauge,
  LineChart,
  LogOut,
  Moon,
  Shield,
  ShieldCheck,
  Sparkles,
  SunMedium,
  UserCircle2,
} from "lucide-react";

import { useAuth } from "@/contexts/AuthContext";
import { useTheme } from "@/contexts/ThemeContext";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type NavItem = {
  to: string;
  label: string;
  icon: React.ReactNode;
  premium?: boolean;
};

const navItems: NavItem[] = [
  { to: "/", label: "Dashboard", icon: <Gauge className="h-4 w-4" /> },
  { to: "/optimizer", label: "Optimizer", icon: <Sparkles className="h-4 w-4" /> },
  {
    to: "/premium/backtest",
    label: "Backtest",
    icon: <Bot className="h-4 w-4" />,
    premium: true,
  },
  {
    to: "/performance",
    label: "AI Performance",
    icon: <LineChart className="h-4 w-4" />,
    premium: true,
  },
  {
    to: "/premium/market-watch",
    label: "Market Watch",
    icon: <ShieldCheck className="h-4 w-4" />,
    premium: true,
  },
  {
    to: "/settings/profile",
    label: "Profile & Security",
    icon: <UserCircle2 className="h-4 w-4" />,
  },
];

export function AppShell() {
  const { user, logout, roles, isPro, isAdmin } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const location = useLocation();

  // Display role badges based on all user roles
  const getRoleBadgeVariant = (role: string) => {
    switch (role) {
      case "ADMIN":
        return "success" as const;
      case "PRO":
        return "warning" as const;
      default:
        return "secondary" as const;
    }
  };

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top_right,_hsl(var(--primary)/0.18),transparent_42%),radial-gradient(circle_at_bottom_left,_hsl(var(--accent)/0.16),transparent_36%)]">
      <div className="mx-auto grid min-h-screen max-w-[1440px] grid-cols-1 lg:grid-cols-[260px_1fr]">
        <aside className="border-b border-border/70 bg-background/80 px-5 py-6 backdrop-blur-md lg:border-b-0 lg:border-r">
          <Link to="/" className="mb-8 inline-flex items-center gap-3">
            <span className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-primary/90 text-primary-foreground shadow-lg shadow-primary/30">
              EGX
            </span>
            <div>
              <p className="text-sm font-semibold">Portfolio Optimizer</p>
              <p className="text-xs text-muted-foreground">Frontend Console</p>
            </div>
          </Link>

          <nav className="space-y-2">
            {navItems.map((item) => {
              const active =
                item.to === "/"
                  ? location.pathname === "/"
                  : location.pathname.startsWith(item.to);

              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={cn(
                    "flex items-center justify-between rounded-md px-3 py-2 text-sm font-medium transition",
                    active
                      ? "bg-primary/10 text-primary"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground",
                  )}
                >
                  <span className="inline-flex items-center gap-2">
                    {item.icon}
                    {item.label}
                  </span>
                  {item.premium ? (
                    <Badge variant="warning" className="px-2 py-0 text-[10px]">
                      PRO
                    </Badge>
                  ) : null}
                </NavLink>
              );
            })}

            {isAdmin && (
              <>
                <div className="my-4 border-t border-border/70" />
                <p className="mb-2 px-3 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                  Administration
                </p>
                <NavLink
                  to="/admin/dashboard"
                  className={cn(
                    "flex items-center justify-between rounded-md px-3 py-2 text-sm font-medium transition",
                    location.pathname.startsWith("/admin")
                      ? "bg-primary/10 text-primary"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground",
                  )}
                >
                  <span className="inline-flex items-center gap-2">
                    <Shield className="h-4 w-4" />
                    Admin Dashboard
                  </span>
                  <Badge variant="success" className="px-2 py-0 text-[10px]">
                    ADMIN
                  </Badge>
                </NavLink>
              </>
            )}
          </nav>
        </aside>

        <div className="flex min-h-screen flex-col">
          <header className="sticky top-0 z-20 flex items-center justify-between border-b border-border/70 bg-background/85 px-4 py-3 backdrop-blur-md sm:px-6">
            <div>
              <p className="text-sm text-muted-foreground">Active workspace</p>
              <h1 className="text-base font-semibold tracking-tight sm:text-lg">
                EGX Portfolio Control Panel
              </h1>
            </div>

            <div className="flex items-center gap-2">
              {/* Show all user roles as badges */}
              {roles.map((role) => (
                <Badge key={role} variant={getRoleBadgeVariant(role)}>
                  {role}
                </Badge>
              ))}
              <Button variant="outline" size="icon" onClick={toggleTheme}>
                {theme === "dark" ? (
                  <SunMedium className="h-4 w-4" />
                ) : (
                  <Moon className="h-4 w-4" />
                )}
              </Button>
              <Button variant="ghost" onClick={logout}>
                <LogOut className="mr-2 h-4 w-4" />
                Logout
              </Button>
            </div>
          </header>

          <main className="flex-1 px-4 py-5 sm:px-6 sm:py-6">
            <Outlet />
          </main>
        </div>
      </div>
    </div>
  );
}
