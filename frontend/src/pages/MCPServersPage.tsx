import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link } from "react-router-dom";

import { api, getErrorMessage } from "../api/client";
import { endpoints } from "../api/queries";
import { useAuth } from "../auth/context";
import { getEffectiveRole } from "../auth/roles";
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

const actionLinkClass =
  "rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50";

function formatDate(value: string | null) {
  return value ? new Date(value).toLocaleString() : "Never";
}

export function MCPServersPage() {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const isAdmin = getEffectiveRole(user) === "admin";
  const [syncResult, setSyncResult] = useState<MCPServerSyncResponse | null>(null);
  const [copiedAgentId, setCopiedAgentId] = useState<string | null>(null);
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
    onMutate: () => setSyncResult(null),
    onSuccess: (result) => {
      setSyncResult(result);
      void queryClient.invalidateQueries({ queryKey: ["mcp-servers"] });
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] });
    }
  });

  async function copyAgentId(agentId: string) {
    await navigator.clipboard.writeText(agentId);
    setCopiedAgentId(agentId);
  }

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
        subtitle="MCP servers registered for this organization."
      />
      <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <Card>
          <h3 className="mb-3 font-semibold">Server Registry</h3>
          <DataState isLoading={servers.isLoading} error={servers.error}>
            <div className="space-y-3">
              {servers.data?.items.map((server) => {
                const isSyncing = syncServer.isPending && syncServer.variables === server.id;
                return (
                  <div key={server.id} className="border-b border-slate-200 py-4 last:border-0">
                    <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <div className="font-medium text-slate-950">{server.name}</div>
                          <Badge>{server.status}</Badge>
                        </div>
                        <dl className="mt-3 grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
                          <div>
                            <dt className="text-xs font-medium uppercase text-slate-500">Server URL</dt>
                            <dd className="mt-1 break-all text-slate-700">{server.server_url}</dd>
                          </div>
                          <div>
                            <dt className="text-xs font-medium uppercase text-slate-500">Last Sync</dt>
                            <dd className="mt-1 text-slate-700">{formatDate(server.last_sync_at)}</dd>
                          </div>
                          <div className="sm:col-span-2">
                            <dt className="text-xs font-medium uppercase text-slate-500">Linked Agent ID</dt>
                            <dd className="mt-1 break-all font-mono text-xs text-slate-700">
                              {server.agent_id ?? "Not linked yet"}
                            </dd>
                          </div>
                        </dl>
                        {server.last_error ? (
                          <div className="mt-3 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                            {server.last_error}
                          </div>
                        ) : null}
                      </div>
                      {isAdmin ? (
                        <div className="flex shrink-0 flex-wrap gap-2">
                          <SecondaryButton
                            disabled={isSyncing}
                            onClick={() => syncServer.mutate(server.id)}
                          >
                            {isSyncing ? "Syncing..." : "Sync Tools"}
                          </SecondaryButton>
                          {server.agent_id ? (
                            <>
                              <Link to={`/agents?agentId=${server.agent_id}`} className={actionLinkClass}>
                                View Linked Agent
                              </Link>
                              <SecondaryButton onClick={() => void copyAgentId(server.agent_id!)}>
                                {copiedAgentId === server.agent_id ? "Copied" : "Copy Agent ID"}
                              </SecondaryButton>
                            </>
                          ) : null}
                        </div>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
            {servers.data?.total === 0 ? (
              <div className="mt-4">
                <EmptyState
                  title="No MCP servers registered for this organization"
                  message="Register an MCP server to connect this organization workspace to governed agents and tools."
                  actions={
                    isAdmin ? (
                      <a href="#register-mcp-server" className={actionLinkClass}>
                        Register MCP Server
                      </a>
                    ) : undefined
                  }
                />
              </div>
            ) : null}
          </DataState>
          {syncServer.error ? (
            <div className="mt-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
              {getErrorMessage(syncServer.error)}
            </div>
          ) : null}
        </Card>
        {isAdmin ? (
          <Card className="scroll-mt-24">
            <div id="register-mcp-server" className="scroll-mt-24" />
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
      {syncResult ? (
        <Card className="mt-4 border-emerald-200 bg-emerald-50">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <h3 className="font-semibold text-emerald-950">MCP sync completed</h3>
              <p className="mt-1 text-sm text-emerald-800">
                The linked agent and discovered tools are ready for governance review.
              </p>
              <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
                <SyncMetric label="Discovered Tools" value={syncResult.discovered_tools_count} />
                <SyncMetric label="Created Tools" value={syncResult.created_tools_count} />
                <SyncMetric label="Updated Tools" value={syncResult.updated_tools_count} />
                <SyncMetric label="Status" value={syncResult.status} />
                <SyncMetric label="Last Sync" value={formatDate(syncResult.last_sync_at)} />
                <SyncMetric label="Linked Agent ID" value={syncResult.agent_id} mono />
              </dl>
            </div>
            <div className="flex shrink-0 flex-wrap gap-2">
              <Link to={`/agents?agentId=${syncResult.agent_id}`} className={actionLinkClass}>
                View Linked Agent
              </Link>
              <Link
                to={`/policy-decisions?agentId=${syncResult.agent_id}`}
                className={actionLinkClass}
              >
                Test Policy Decision
              </Link>
            </div>
          </div>
        </Card>
      ) : null}
    </>
  );
}

function SyncMetric({
  label,
  value,
  mono = false
}: {
  label: string;
  value: string | number;
  mono?: boolean;
}) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase text-emerald-700">{label}</dt>
      <dd className={`mt-1 break-all text-emerald-950 ${mono ? "font-mono text-xs" : ""}`}>
        {value}
      </dd>
    </div>
  );
}
