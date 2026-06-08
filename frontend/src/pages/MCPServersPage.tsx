import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { api, getErrorMessage } from "../api/client";
import { endpoints } from "../api/queries";
import { useAuth } from "../auth/context";
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
import type { MCPServerSyncResponse } from "../types/api";

export function MCPServersPage() {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const [message, setMessage] = useState("");
  const servers = useQuery({ queryKey: ["mcp-servers"], queryFn: endpoints.mcpServers });
  const createServer = useMutation({
    mutationFn: (payload: unknown) => api.post("/api/v1/mcp-servers", payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["mcp-servers"] })
  });
  const syncServer = useMutation({
    mutationFn: (serverId: string) =>
      api
        .post<MCPServerSyncResponse>(`/api/v1/mcp-servers/${serverId}/sync`)
        .then((response) => response.data),
    onSuccess: (result) => {
      setMessage(
        `Sync complete: ${result.created_tools_count} tools created and ${result.updated_tools_count} updated.`
      );
      void queryClient.invalidateQueries({ queryKey: ["mcp-servers"] });
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] });
    }
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    createServer.mutate({
      name: String(form.get("name") ?? ""),
      description: String(form.get("description") ?? "") || null,
      server_url: String(form.get("server_url") ?? "")
    });
    event.currentTarget.reset();
  }

  return (
    <>
      <PageHeader
        title="MCP Servers"
        subtitle="Register tool providers and sync discovered tools into governed agents."
      />
      <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <Card>
          <h3 className="mb-3 font-semibold">Server Registry</h3>
          <DataState isLoading={servers.isLoading} error={servers.error}>
            <div className="space-y-3">
              {servers.data?.items.map((server) => (
                <div
                  key={server.id}
                  className="flex flex-col gap-3 border-b border-slate-200 py-3 last:border-0 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <div className="font-medium text-slate-950">{server.name}</div>
                      <Badge>{server.status}</Badge>
                    </div>
                    <div className="mt-1 truncate text-sm text-slate-500">{server.server_url}</div>
                    {server.last_error ? (
                      <div className="mt-1 text-sm text-red-700">{server.last_error}</div>
                    ) : null}
                  </div>
                  <SecondaryButton onClick={() => syncServer.mutate(server.id)}>
                    {syncServer.isPending ? "Syncing..." : "Sync tools"}
                  </SecondaryButton>
                </div>
              ))}
            </div>
            {servers.data?.total === 0 ? (
              <div className="mt-4">
                <EmptyState
                  title="No MCP servers registered"
                  message="Register your first MCP server to discover tools."
                />
              </div>
            ) : null}
          </DataState>
          {message ? (
            <div className="mt-4 rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">
              {message}
            </div>
          ) : null}
          {syncServer.error ? (
            <div className="mt-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
              {getErrorMessage(syncServer.error)}
            </div>
          ) : null}
        </Card>
        {user?.role === "admin" ? (
          <Card>
            <h3 className="mb-1 font-semibold">Register MCP Server</h3>
            <p className="mb-4 text-sm text-slate-500">
              Registration stores connection details. Syncing creates or reuses a linked agent.
            </p>
            <form className="space-y-4" onSubmit={submit}>
              <Field label="Name">
                <input
                  name="name"
                  className={inputClass}
                  placeholder="Customer Operations MCP"
                  required
                />
              </Field>
              <Field label="Server URL">
                <input
                  name="server_url"
                  type="url"
                  className={inputClass}
                  placeholder="https://mcp.example.com/server"
                  required
                />
              </Field>
              <Field label="Description">
                <textarea
                  name="description"
                  className={inputClass}
                  placeholder="Tools provided by this MCP server"
                  rows={3}
                />
              </Field>
              {createServer.error ? (
                <div className="text-sm text-red-700">{getErrorMessage(createServer.error)}</div>
              ) : null}
              <PrimaryButton disabled={createServer.isPending}>
                {createServer.isPending ? "Registering..." : "Register server"}
              </PrimaryButton>
            </form>
          </Card>
        ) : (
          <Card className="bg-slate-50">
            <h3 className="font-semibold text-slate-900">Admin access required</h3>
            <p className="mt-2 text-sm leading-6 text-slate-600">
              MCP server registration and sync are available to administrators.
            </p>
          </Card>
        )}
      </div>
    </>
  );
}
