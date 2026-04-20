import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/contexts/AuthContext";

const loginSchema = z.object({
  email: z.string().email("Provide a valid email address"),
  password: z.string().min(8, "Password must be at least 8 characters"),
});

type LoginFormValues = z.infer<typeof loginSchema>;

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { login } = useAuth();
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const from =
    (location.state as { from?: { pathname?: string } } | undefined)?.from
      ?.pathname || "/";

  const form = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: {
      email: "",
      password: "",
    },
  });

  const loginMutation = useMutation({
    mutationFn: async (values: LoginFormValues) => {
      await login(values);
    },
    onSuccess: () => {
      navigate(from, { replace: true });
    },
    onError: (error: Error) => {
      setErrorMessage(error.message);
    },
  });

  async function onSubmit(values: LoginFormValues) {
    setErrorMessage(null);
    await loginMutation.mutateAsync(values);
  }

  return (
    <div className="grid min-h-screen place-items-center bg-[radial-gradient(circle_at_top,_hsl(var(--primary)/0.22),transparent_48%),radial-gradient(circle_at_bottom,_hsl(var(--accent)/0.16),transparent_46%)] px-4 py-8">
      <Card className="w-full max-w-md border-border/70 bg-background/90 backdrop-blur-sm">
        <CardHeader className="space-y-1">
          <CardTitle className="text-2xl">Welcome back</CardTitle>
          <CardDescription>
            Sign in to monitor EGX allocations and run optimization jobs.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" placeholder="you@example.com" {...form.register("email")} />
              {form.formState.errors.email ? (
                <p className="text-xs text-destructive">{form.formState.errors.email.message}</p>
              ) : null}
            </div>

            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input id="password" type="password" placeholder="••••••••" {...form.register("password")} />
              {form.formState.errors.password ? (
                <p className="text-xs text-destructive">{form.formState.errors.password.message}</p>
              ) : null}
            </div>

            {errorMessage ? <p className="text-sm text-destructive">{errorMessage}</p> : null}

            <Button type="submit" className="w-full" disabled={loginMutation.isPending}>
              {loginMutation.isPending ? "Signing in..." : "Sign In"}
            </Button>
          </form>

          <p className="mt-4 text-center text-sm text-muted-foreground">
            New account?{" "}
            <Link to="/register" className="font-medium text-primary hover:underline">
              Register
            </Link>
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
