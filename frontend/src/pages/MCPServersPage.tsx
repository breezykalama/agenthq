import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link } from "react-router-dom";

import { api, gatewayApi, getErrorMessage, getGatewayErrorMessage } from "../api/client";
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
import type {
  MCPGatewayCallResponse,
  MCPGatewayTokenCreated,
  MCPGatewayTool,
  MCPServer,
  MCPServerSyncResponse
} from "../types/api";

const actionLinkClass =
  "rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50";

function formatDate(value: string | null) {
  return value ? new Date(value).toLocaleString() : "Never";
}

export function MCPServersPage() {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const isAdmin = getEffectiveRole(user) === "admin";
  const [authType, setAuthType] = useState("none");
  const [syncResult, setSyncResult] = useState<MCPServerSyncResponse | null>(null);
  const [copiedAgentId, setCopiedAgentId] = useState<string | null>(null);
  const [gatewayServer, setGatewayServer] = useState<MCPServer | null>(null);
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
    const authSecretRef = String(form.get("auth_secret_ref") ?? "");
    createServer.mutate({
      name: String(form.get("name") ?? ""),
      description: String(form.get("description") ?? "") || null,
      server_url: String(form.get("server_url") ?? ""),
      transport_type: String(form.get("transport_type") ?? "streamable_http"),
      auth_type: String(form.get("auth_type") ?? "none"),
      ...(authSecretRef ? { auth_secret_ref: authSecretRef } : {}),
      request_timeout_seconds: Number(form.get("request_timeout_seconds") ?? 30),
      connect_timeout_seconds: Number(form.get("connect_timeout_seconds") ?? 10)
    });
    event.currentTarget.reset();
    setAuthType("none");
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
                          <div>
                            <dt className="text-xs font-medium uppercase text-slate-500">Transport</dt>
                            <dd className="mt-1 text-slate-700">{server.transport_type}</dd>
                          </div>
                          <div>
                            <dt className="text-xs font-medium uppercase text-slate-500">Authentication</dt>
                            <dd className="mt-1 text-slate-700">{server.auth_type}</dd>
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
                          <SecondaryButton onClick={() => setGatewayServer(server)}>
                            Manage Gateway
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
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Transport">
                  <select name="transport_type" className={inputClass} defaultValue="streamable_http">
                    <option value="streamable_http">Streamable HTTP</option>
                    <option value="sse">SSE</option>
                  </select>
                </Field>
                <Field label="Authentication">
                  <select
                    name="auth_type"
                    className={inputClass}
                    value={authType}
                    onChange={(event) => setAuthType(event.target.value)}
                  >
                    <option value="none">None</option>
                    <option value="bearer">Bearer token</option>
                    <option value="api_key">API key</option>
                  </select>
                </Field>
              </div>
              {authType !== "none" ? (
                <Field label="Credential environment reference">
                  <input
                    name="auth_secret_ref"
                    className={inputClass}
                    placeholder="MCP_AUTH_CUSTOMER_OPERATIONS"
                    pattern="MCP_AUTH_[A-Z0-9_]+"
                    required
                  />
                </Field>
              ) : null}
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Request timeout (seconds)">
                  <input
                    name="request_timeout_seconds"
                    type="number"
                    min={1}
                    max={120}
                    defaultValue={30}
                    className={inputClass}
                    required
                  />
                </Field>
                <Field label="Connect timeout (seconds)">
                  <input
                    name="connect_timeout_seconds"
                    type="number"
                    min={1}
                    max={30}
                    defaultValue={10}
                    className={inputClass}
                    required
                  />
                </Field>
              </div>
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
      {isAdmin && gatewayServer ? (
        <GatewayPanel server={gatewayServer} onClose={() => setGatewayServer(null)} />
      ) : null}
    </>
  );
}

function GatewayPanel({ server, onClose }: { server: MCPServer; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [rawToken, setRawToken] = useState("");
  const [copied, setCopied] = useState(false);
  const [tools, setTools] = useState<MCPGatewayTool[]>([]);
  const [callResult, setCallResult] = useState<MCPGatewayCallResponse | null>(null);
  const tokens = useQuery({
    queryKey: ["mcp-gateway-tokens", server.id],
    queryFn: () => endpoints.mcpGatewayTokens(server.id)
  });
  const createToken = useMutation({
    mutationFn: (name: string) =>
      api
        .post<MCPGatewayTokenCreated>("/api/v1/mcp-gateway-tokens", {
          mcp_server_id: server.id,
          name
        })
        .then((response) => response.data),
    onSuccess: (created) => {
      setRawToken(created.token);
      void queryClient.invalidateQueries({ queryKey: ["mcp-gateway-tokens", server.id] });
    }
  });
  const rotateToken = useMutation({
    mutationFn: (tokenId: string) =>
      api
        .post<MCPGatewayTokenCreated>(`/api/v1/mcp-gateway-tokens/${tokenId}/rotate`)
        .then((response) => response.data),
    onSuccess: (rotated) => {
      setRawToken(rotated.token);
      void queryClient.invalidateQueries({ queryKey: ["mcp-gateway-tokens", server.id] });
    }
  });
  const revokeToken = useMutation({
    mutationFn: (tokenId: string) => api.post(`/api/v1/mcp-gateway-tokens/${tokenId}/revoke`),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["mcp-gateway-tokens", server.id] })
  });
  const loadTools = useMutation({
    mutationFn: () =>
      gatewayApi
        .get<{ items: MCPGatewayTool[] }>(`/api/v1/mcp-gateway/${server.id}/tools`, {
          headers: { Authorization: `Bearer ${rawToken}` }
        })
        .then((response) => response.data.items),
    onSuccess: setTools
  });
  const callTool = useMutation({
    mutationFn: ({
      toolId,
      payload,
      approvalId
    }: {
      toolId: string;
      payload: Record<string, unknown>;
      approvalId: string | null;
    }) =>
      gatewayApi
        .post<MCPGatewayCallResponse>(
          `/api/v1/mcp-gateway/${server.id}/tools/${toolId}/call`,
          { input_payload: payload, approval_id: approvalId },
          { headers: { Authorization: `Bearer ${rawToken}` } }
        )
        .then((response) => response.data),
    onSuccess: setCallResult
  });
  const gatewayEndpoint = `${String(gatewayApi.defaults.baseURL ?? "").replace(/\/$/, "")}/api/v1/mcp-gateway/${server.id}`;

  function submitToken(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    createToken.mutate(String(new FormData(event.currentTarget).get("gateway_name") ?? ""));
    event.currentTarget.reset();
  }

  function submitCall(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      callTool.mutate({
        toolId: String(form.get("tool_id") ?? ""),
        payload: JSON.parse(String(form.get("input_payload") ?? "{}")) as Record<string, unknown>,
        approvalId: String(form.get("approval_id") ?? "") || null
      });
    } catch {
      setCallResult(null);
    }
  }

  return (
    <Card className="mt-4 border-emerald-200">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold text-slate-950">AgentHQ Gateway · {server.name}</h3>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">
            Configure agents to connect to AgentHQ Gateway instead of the upstream MCP server.
            AgentHQ enforces policies, approvals, audit logging, and compliance controls before
            forwarding allowed calls.
          </p>
        </div>
        <SecondaryButton onClick={onClose}>Close</SecondaryButton>
      </div>
      <div className="mt-4 rounded-md bg-slate-50 p-3">
        <div className="text-xs font-medium uppercase text-slate-500">Gateway endpoint</div>
        <div className="mt-1 break-all font-mono text-xs text-slate-800">{gatewayEndpoint}</div>
      </div>
      <div className="mt-5 grid gap-5 xl:grid-cols-2">
        <div>
          <h4 className="font-medium">Gateway Tokens</h4>
          <form className="mt-3 flex flex-col gap-2 sm:flex-row" onSubmit={submitToken}>
            <input
              name="gateway_name"
              className={inputClass}
              placeholder="Production agent client"
              required
            />
            <PrimaryButton disabled={createToken.isPending}>Create token</PrimaryButton>
          </form>
          {rawToken ? (
            <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm">
              <div className="font-medium text-amber-950">Copy this token now. It is shown once.</div>
              <div className="mt-2 break-all font-mono text-xs text-amber-900">{rawToken}</div>
              <SecondaryButton
                onClick={() => {
                  void navigator.clipboard.writeText(rawToken);
                  setCopied(true);
                }}
              >
                {copied ? "Copied" : "Copy token"}
              </SecondaryButton>
            </div>
          ) : null}
          <DataState isLoading={tokens.isLoading} error={tokens.error}>
            <div className="mt-3 space-y-2">
              {tokens.data?.items.map((token) => (
                <div key={token.id} className="flex flex-wrap items-center justify-between gap-2 border-b py-2 text-sm">
                  <div>
                    <span className="font-medium">{token.name}</span> <Badge>{token.status}</Badge>
                    <div className="text-xs text-slate-500">Last used: {formatDate(token.last_used_at)}</div>
                  </div>
                  <div className="flex gap-2">
                    <SecondaryButton onClick={() => rotateToken.mutate(token.id)}>Rotate</SecondaryButton>
                    {token.status === "active" ? <SecondaryButton onClick={() => revokeToken.mutate(token.id)}>Revoke</SecondaryButton> : null}
                  </div>
                </div>
              ))}
            </div>
          </DataState>
        </div>
        <div>
          <h4 className="font-medium">Gateway Call Test</h4>
          <p className="mt-1 text-sm text-slate-500">
            Use the one-time token above to load governed tools and test policy enforcement.
          </p>
          <SecondaryButton disabled={!rawToken || loadTools.isPending} onClick={() => loadTools.mutate()}>
            {loadTools.isPending ? "Loading..." : "Load governed tools"}
          </SecondaryButton>
          <form className="mt-3 space-y-3" onSubmit={submitCall}>
            <Field label="Tool">
              <select name="tool_id" className={inputClass} required>
                <option value="">Select governed tool</option>
                {tools.map((tool) => <option key={tool.id} value={tool.id}>{tool.name}</option>)}
              </select>
            </Field>
            <Field label="JSON input">
              <textarea name="input_payload" className={inputClass} defaultValue="{}" rows={4} />
            </Field>
            <Field label="Approved approval ID (optional)">
              <input name="approval_id" className={inputClass} placeholder="Required when policy requires approval" />
            </Field>
            <PrimaryButton disabled={!rawToken || callTool.isPending}>
              {callTool.isPending ? "Calling..." : "Call through gateway"}
            </PrimaryButton>
          </form>
          {loadTools.error || callTool.error ? <p className="mt-3 text-sm text-red-700">{getGatewayErrorMessage(loadTools.error ?? callTool.error)}</p> : null}
          {callResult ? <pre className="mt-3 max-h-80 overflow-auto rounded-md bg-slate-950 p-3 text-xs text-slate-100">{JSON.stringify(callResult, null, 2)}</pre> : null}
        </div>
      </div>
      <p className="mt-5 text-xs text-amber-800">
        Strict enforcement requires upstream MCP servers to reject direct client access. Traffic
        sent directly to the upstream server bypasses AgentHQ.
      </p>
    </Card>
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
