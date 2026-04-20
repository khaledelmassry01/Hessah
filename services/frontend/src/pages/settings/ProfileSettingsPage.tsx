import { useEffect } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAuth } from "@/contexts/AuthContext";
import {
  fetchCurrentUser,
  fetchUserSessions,
  mapApiError,
  revokeOtherSessions,
  revokeSession,
  updateCurrentUser,
} from "@/lib/api";
import { formatDateTime } from "@/lib/format";

const profileSchema = z.object({
  fullName: z.string().min(2, "Full name is required"),
  phone: z.string().optional(),
});

type ProfileFormValues = z.infer<typeof profileSchema>;

export function ProfileSettingsPage() {
  const queryClient = useQueryClient();
  const { refreshProfile } = useAuth();

  const profileQuery = useQuery({
    queryKey: ["me"],
    queryFn: fetchCurrentUser,
  });

  const sessionsQuery = useQuery({
    queryKey: ["sessions"],
    queryFn: fetchUserSessions,
  });

  const form = useForm<ProfileFormValues>({
    resolver: zodResolver(profileSchema),
    defaultValues: {
      fullName: "",
      phone: "",
    },
  });

  useEffect(() => {
    if (!profileQuery.data) {
      return;
    }

    form.reset({
      fullName: profileQuery.data.fullName || "",
      phone: profileQuery.data.phone || "",
    });
  }, [form, profileQuery.data]);

  const updateProfileMutation = useMutation({
    mutationFn: (values: ProfileFormValues) =>
      updateCurrentUser({ fullName: values.fullName, phone: values.phone }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["me"] }),
        refreshProfile(),
      ]);
    },
  });

  const revokeSessionMutation = useMutation({
    mutationFn: async (sessionId: number) => revokeSession(sessionId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["sessions"] });
    },
  });

  const revokeOthersMutation = useMutation({
    mutationFn: revokeOtherSessions,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["sessions"] });
    },
  });

  async function onSubmit(values: ProfileFormValues) {
    await updateProfileMutation.mutateAsync(values);
  }

  return (
    <div className="space-y-5 text-slate-100">
      <section className="relative overflow-hidden rounded-2xl border border-cyan-500/25 bg-slate-950/85 p-5 shadow-[0_0_70px_-45px_rgba(6,182,212,0.95)]">
        <div className="pointer-events-none absolute -right-12 -top-14 h-48 w-48 rounded-full bg-cyan-500/20 blur-3xl" />
        <div className="relative">
          <p className="text-xs uppercase tracking-[0.22em] text-cyan-300/85">Profile Settings</p>
          <h2 className="mt-2 text-2xl font-semibold tracking-tight">Profile & Session Security</h2>
          <p className="mt-1 text-sm text-slate-300/80">
            Update your account details and manage active sessions across devices.
          </p>
        </div>
      </section>

      {(profileQuery.error || sessionsQuery.error) ? (
        <Card className="border-destructive/40 bg-destructive/10">
          <CardContent className="pt-6 text-sm text-destructive">
            {profileQuery.error ? mapApiError(profileQuery.error) : mapApiError(sessionsQuery.error)}
          </CardContent>
        </Card>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-2">
        <Card className="border-slate-700/70 bg-slate-950/80 text-slate-100">
          <CardHeader>
            <CardTitle>Profile</CardTitle>
            <CardDescription className="text-slate-400">Identity and tier metadata</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="rounded-md border border-slate-700/70 bg-slate-900/70 p-3 text-sm">
              <p className="text-slate-400">Email</p>
              <p className="font-medium text-slate-100">{profileQuery.data?.email || "-"}</p>
              <div className="mt-2">
                <Badge variant="secondary" className="border-slate-600 bg-slate-800 text-slate-100">
                  {profileQuery.data?.tier || "FREE"}
                </Badge>
              </div>
            </div>

            <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-3">
              <div className="space-y-2">
                <Label htmlFor="fullName" className="text-slate-300">Full Name</Label>
                <Input id="fullName" className="border-slate-700 bg-slate-900/80 text-slate-100" {...form.register("fullName")} />
                {form.formState.errors.fullName ? (
                  <p className="text-xs text-destructive">{form.formState.errors.fullName.message}</p>
                ) : null}
              </div>

              <div className="space-y-2">
                <Label htmlFor="phone" className="text-slate-300">Phone</Label>
                <Input id="phone" className="border-slate-700 bg-slate-900/80 text-slate-100" {...form.register("phone")} />
              </div>

              <Button type="submit" className="bg-cyan-500 text-slate-950 hover:bg-cyan-400" disabled={updateProfileMutation.isPending}>
                {updateProfileMutation.isPending ? "Saving..." : "Save Profile"}
              </Button>
            </form>
          </CardContent>
        </Card>

        <Card className="border-slate-700/70 bg-slate-950/80 text-slate-100">
          <CardHeader>
            <CardTitle>Active Sessions</CardTitle>
            <CardDescription className="text-slate-400">Manage currently authenticated devices</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex justify-end">
              <Button
                variant="outline"
                className="border-slate-600 bg-slate-900/80 text-slate-100 hover:bg-slate-800"
                onClick={() => revokeOthersMutation.mutate()}
                disabled={revokeOthersMutation.isPending}
              >
                Revoke Other Sessions
              </Button>
            </div>

            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Device</TableHead>
                  <TableHead>IP</TableHead>
                  <TableHead>Last Active</TableHead>
                  <TableHead>Expires</TableHead>
                  <TableHead>Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sessionsQuery.data?.length ? (
                  sessionsQuery.data.map((session) => (
                    <TableRow key={session.sessionId}>
                      <TableCell>
                        <div className="flex max-w-[260px] flex-col gap-1">
                          <span className="truncate">{session.userAgent}</span>
                          {session.current ? <Badge variant="success">Current</Badge> : null}
                        </div>
                      </TableCell>
                      <TableCell>{session.ipAddress}</TableCell>
                      <TableCell>{formatDateTime(session.lastActive)}</TableCell>
                      <TableCell>{formatDateTime(session.expiresAt)}</TableCell>
                      <TableCell>
                        <Button
                          size="sm"
                          variant="outline"
                          className="border-slate-600 bg-slate-900/70 text-slate-100 hover:bg-slate-800"
                          disabled={session.current || revokeSessionMutation.isPending}
                          onClick={() => revokeSessionMutation.mutate(session.sessionId)}
                        >
                          Revoke
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))
                ) : (
                  <TableRow>
                    <TableCell colSpan={5} className="text-center text-slate-400">
                      No active sessions found.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export default ProfileSettingsPage;
