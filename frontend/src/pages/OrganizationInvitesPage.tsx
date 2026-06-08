import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { getErrorMessage } from "../api/client";
import {
  type CreateOrganizationInvitePayload,
  organizationInvitesApi
} from "../api/organizationInvites";
import {
  Badge,
  Card,
  DataState,
  EmptyState,
  Field,
  PageHeader,
  PrimaryButton,
  SecondaryButton,
  inputClass
} from "../components/Ui";
import { useAuth } from "../auth/context";
import type { OrganizationInviteCreateResponse, UserRole } from "../types/api";

const roles: UserRole[] = ["admin", "auditor", "operator", "agent_owner"];

export function OrganizationInvitesPage() {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const organizationName =
    user?.organization_membership?.organization.name ?? "your current organization";
  const [createdInvite, setCreatedInvite] = useState<OrganizationInviteCreateResponse | null>(null);
  const [copyFeedback, setCopyFeedback] = useState("");
  const invites = useQuery({
    queryKey: ["organization-invites"],
    queryFn: () => organizationInvitesApi.list()
  });
  const createInvite = useMutation({
    mutationFn: organizationInvitesApi.create,
    onSuccess: (invite) => {
      setCreatedInvite(invite);
      setCopyFeedback("");
      void queryClient.invalidateQueries({ queryKey: ["organization-invites"] });
    }
  });
  const revokeInvite = useMutation({
    mutationFn: organizationInvitesApi.revoke,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["organization-invites"] })
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const payload: CreateOrganizationInvitePayload = {
      email: String(form.get("email") ?? ""),
      full_name: String(form.get("full_name") ?? "") || null,
      role: String(form.get("role") ?? "agent_owner") as UserRole,
      expires_in_days: Number(form.get("expires_in_days") ?? 7)
    };
    createInvite.mutate(payload);
    event.currentTarget.reset();
  }

  async function copyInviteLink() {
    if (!createdInvite) return;
    try {
      await navigator.clipboard.writeText(toPublicInviteUrl(createdInvite.invite_url));
      setCopyFeedback("Invite link copied");
    } catch {
      setCopyFeedback("Copy failed. Select the link and copy it manually.");
    }
  }

  return (
    <>
      <PageHeader
        title="Organization Invites"
        subtitle={`Invite people to join ${organizationName} and assign their organization role.`}
      />
      <Card className="mb-4 bg-slate-50">
        <h3 className="text-sm font-semibold text-slate-900">Current organization</h3>
        <p className="mt-1 text-sm leading-6 text-slate-600">
          Invited users will join <span className="font-medium">{organizationName}</span>. Only
          organization admins can create, review, and revoke invitations.
        </p>
      </Card>
      {createdInvite ? (
        <Card className="mb-4 border-emerald-200 bg-emerald-50">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="min-w-0">
              <h3 className="font-semibold text-emerald-950">Invite ready to share</h3>
              <p className="mt-1 text-sm text-emerald-800">
                Send this secure link to {createdInvite.email}. It expires{" "}
                {formatDate(createdInvite.expires_at)}.
              </p>
              <div className="mt-3 break-all rounded-md border border-emerald-200 bg-white p-3 font-mono text-xs text-slate-700">
                {toPublicInviteUrl(createdInvite.invite_url)}
              </div>
              {copyFeedback ? <p className="mt-2 text-sm text-emerald-800">{copyFeedback}</p> : null}
            </div>
            <SecondaryButton onClick={() => void copyInviteLink()}>Copy invite link</SecondaryButton>
          </div>
        </Card>
      ) : null}
      <div className="grid gap-4 xl:grid-cols-[1.35fr_0.65fr]">
        <Card>
          <h3 className="mb-3 font-semibold text-slate-950">Current Invites</h3>
          <DataState
            isLoading={invites.isLoading}
            error={invites.error}
            onRetry={() => void invites.refetch()}
          >
            <div className="overflow-x-auto">
              <table className="w-full min-w-[820px] text-left text-sm">
                <thead className="border-b border-slate-200 text-xs uppercase text-slate-500">
                  <tr>
                    <th className="py-2 pr-4">Person</th>
                    <th className="pr-4">Role</th>
                    <th className="pr-4">Status</th>
                    <th className="pr-4">Expires</th>
                    <th className="pr-4">Created</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {invites.data?.items.map((invite) => {
                    const isRevoking =
                      revokeInvite.isPending && revokeInvite.variables === invite.id;
                    return (
                      <tr key={invite.id} className="border-b border-slate-100 last:border-0">
                        <td className="py-3 pr-4">
                          <div className="font-medium text-slate-900">
                            {invite.full_name ?? "Name provided on acceptance"}
                          </div>
                          <div className="text-slate-500">{invite.email}</div>
                        </td>
                        <td className="pr-4">{formatRole(invite.role)}</td>
                        <td className="pr-4">
                          <Badge>{invite.status}</Badge>
                        </td>
                        <td className="pr-4 whitespace-nowrap">{formatDate(invite.expires_at)}</td>
                        <td className="pr-4 whitespace-nowrap">{formatDate(invite.created_at)}</td>
                        <td>
                          {invite.status === "pending" ? (
                            <SecondaryButton
                              disabled={isRevoking}
                              onClick={() => revokeInvite.mutate(invite.id)}
                            >
                              {isRevoking ? "Revoking..." : "Revoke"}
                            </SecondaryButton>
                          ) : (
                            <span className="text-slate-400">No action</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {invites.data?.total === 0 ? (
              <div className="mt-4">
                <EmptyState
                  title="No organization invites"
                  message={`Invite teammates to give them governed access to ${organizationName}.`}
                />
              </div>
            ) : null}
          </DataState>
          {revokeInvite.error ? (
            <p className="mt-3 text-sm text-red-700">{getErrorMessage(revokeInvite.error)}</p>
          ) : null}
        </Card>
        <Card>
          <h3 className="mb-1 font-semibold text-slate-950">Invite a User</h3>
          <p className="mb-4 text-sm text-slate-500">
            The generated link is shown once for you to share directly. The recipient will join{" "}
            {organizationName}.
          </p>
          <form className="space-y-4" onSubmit={submit}>
            <Field label="Email">
              <input
                name="email"
                className={inputClass}
                type="email"
                placeholder="colleague@company.com"
                required
              />
            </Field>
            <Field label="Full name (optional)">
              <input name="full_name" className={inputClass} placeholder="Alex Morgan" />
            </Field>
            <Field label="Organization role">
              <select name="role" className={inputClass} defaultValue="agent_owner">
                {roles.map((role) => (
                  <option key={role} value={role}>
                    {formatRole(role)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Expires in days">
              <input
                name="expires_in_days"
                className={inputClass}
                type="number"
                min={1}
                max={30}
                defaultValue={7}
                required
              />
            </Field>
            {createInvite.error ? (
              <p className="text-sm text-red-700">{getErrorMessage(createInvite.error)}</p>
            ) : null}
            <PrimaryButton disabled={createInvite.isPending}>
              {createInvite.isPending ? "Creating invite..." : "Create invite"}
            </PrimaryButton>
          </form>
        </Card>
      </div>
    </>
  );
}

function toPublicInviteUrl(inviteUrl: string): string {
  return new URL(inviteUrl, window.location.origin).toString();
}

function formatDate(value: string): string {
  return new Date(value).toLocaleString();
}

function formatRole(role: UserRole): string {
  return role
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}
