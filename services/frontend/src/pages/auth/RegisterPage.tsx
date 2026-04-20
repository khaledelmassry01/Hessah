import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { Link, useNavigate } from "react-router-dom";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/contexts/AuthContext";

const registerSchema = z
  .object({
    fullName: z.string().min(2, "Full name is required"),
    email: z.string().email("Provide a valid email address"),
    phone: z.string().optional(),
    password: z
      .string()
      .min(8, "At least 8 characters")
      .regex(/[A-Z]/, "Include at least one uppercase letter")
      .regex(/[a-z]/, "Include at least one lowercase letter")
      .regex(/\d/, "Include at least one number")
      .regex(/[^A-Za-z\d]/, "Include at least one special character"),
    confirmPassword: z.string().min(8),
  })
  .refine((values) => values.password === values.confirmPassword, {
    path: ["confirmPassword"],
    message: "Passwords do not match",
  });

type RegisterFormValues = z.infer<typeof registerSchema>;

export function RegisterPage() {
  const navigate = useNavigate();
  const { register } = useAuth();
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const form = useForm<RegisterFormValues>({
    resolver: zodResolver(registerSchema),
    defaultValues: {
      fullName: "",
      email: "",
      phone: "",
      password: "",
      confirmPassword: "",
    },
  });

  const registerMutation = useMutation({
    mutationFn: async (values: RegisterFormValues) => {
      await register({
        fullName: values.fullName,
        email: values.email,
        phone: values.phone,
        password: values.password,
      });
    },
    onSuccess: () => {
      navigate("/", { replace: true });
    },
    onError: (error: Error) => {
      setErrorMessage(error.message);
    },
  });

  async function onSubmit(values: RegisterFormValues) {
    setErrorMessage(null);
    await registerMutation.mutateAsync(values);
  }

  return (
    <div className="grid min-h-screen place-items-center bg-[radial-gradient(circle_at_top_left,_hsl(var(--primary)/0.2),transparent_44%),radial-gradient(circle_at_bottom_right,_hsl(var(--accent)/0.2),transparent_40%)] px-4 py-8">
      <Card className="w-full max-w-xl border-border/70 bg-background/90 backdrop-blur-sm">
        <CardHeader className="space-y-1">
          <CardTitle className="text-2xl">Create your account</CardTitle>
          <CardDescription>
            Start optimizing EGX portfolios with real-time AI insights.
          </CardDescription>
        </CardHeader>

        <CardContent>
          <form onSubmit={form.handleSubmit(onSubmit)} className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2 sm:col-span-2">
              <Label htmlFor="fullName">Full Name</Label>
              <Input id="fullName" placeholder="Ahmed Salah" {...form.register("fullName")} />
              {form.formState.errors.fullName ? (
                <p className="text-xs text-destructive">{form.formState.errors.fullName.message}</p>
              ) : null}
            </div>

            <div className="space-y-2 sm:col-span-2">
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" placeholder="you@example.com" {...form.register("email")} />
              {form.formState.errors.email ? (
                <p className="text-xs text-destructive">{form.formState.errors.email.message}</p>
              ) : null}
            </div>

            <div className="space-y-2 sm:col-span-2">
              <Label htmlFor="phone">Phone (optional)</Label>
              <Input id="phone" placeholder="+2010..." {...form.register("phone")} />
            </div>

            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input id="password" type="password" {...form.register("password")} />
              {form.formState.errors.password ? (
                <p className="text-xs text-destructive">{form.formState.errors.password.message}</p>
              ) : null}
            </div>

            <div className="space-y-2">
              <Label htmlFor="confirmPassword">Confirm Password</Label>
              <Input id="confirmPassword" type="password" {...form.register("confirmPassword")} />
              {form.formState.errors.confirmPassword ? (
                <p className="text-xs text-destructive">{form.formState.errors.confirmPassword.message}</p>
              ) : null}
            </div>

            {errorMessage ? (
              <p className="sm:col-span-2 text-sm text-destructive">{errorMessage}</p>
            ) : null}

            <Button type="submit" className="sm:col-span-2" disabled={registerMutation.isPending}>
              {registerMutation.isPending ? "Creating account..." : "Create Account"}
            </Button>
          </form>

          <p className="mt-4 text-center text-sm text-muted-foreground">
            Already have an account?{" "}
            <Link to="/login" className="font-medium text-primary hover:underline">
              Login
            </Link>
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
