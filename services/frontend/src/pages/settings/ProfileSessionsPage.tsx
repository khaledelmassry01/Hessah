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

export function ProfileSessionsPage() {
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
    if (profileQuery.data) {
      form.reset({
        fullName: profileQuery.data.fullName || "",
        phone: profileQuery.data.phone || "",
      });
    }
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
    <div className="space-y-5">
      <section>
        <h2 className="text-2xl font-semibold tracking-tight">Profile & Sessions</h2>
        <p className="text-sm text-muted-foreground">
          Update profile details and revoke active login sessions.
        </p>
      </section>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Profile</CardTitle>
            <CardDescription>Account identity and subscription metadata</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="rounded-md border border-border/70 p-3 text-sm">
              <p className="text-muted-foreground">Email</p>
              <p className="font-medium">{profileQuery.data?.email || "-"}</p>
              <div className="mt-2">
                <Badge variant="secondary">{profileQuery.data?.tier || "FREE"}</Badge>
              </div>
            </div>

            <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-3">
              <div className="space-y-2">
                <Label htmlFor="fullName">Full Name</Label>
                <Input id="fullName" {...form.register("fullName")} />
                {form.formState.errors.fullName ? (
                  <p className="text-xs text-destructive">{form.formState.errors.fullName.message}</p>
                ) : null}
              </div>

              <div className="space-y-2">
                <Label htmlFor="phone">Phone</Label>
                <Input id="phone" {...form.register("phone")} />
              </div>

              <Button type="submit" disabled={updateProfileMutation.isPending}>
                {updateProfileMutation.isPending ? "Saving..." : "Save Profile"}
              </Button>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Active Sessions</CardTitle>
            <CardDescription>Manage currently authenticated devices</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex justify-end">
              <Button
                variant="outline"
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
                        <div className="flex flex-col gap-1">
                          <span className="truncate max-w-[240px]">{session.userAgent}</span>
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
                    <TableCell colSpan={5} className="text-center text-muted-foreground">
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
