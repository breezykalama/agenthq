import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api, getErrorMessage } from "../api/client";
import { endpoints } from "../api/queries";
import { useAuth } from "../auth/context";
import { getEffectiveRole } from "../auth/roles";
import { markOnboardingStepComplete } from "../onboarding/progress";
import {
  Badge,
  Card,
  DataState,
  EmptyState,
  Field,
  PageHeader,
  PrimaryButton,
  inputClass
} from "../components/Ui";
import type { Agent, AgentTool, ListResponse } from "../types/api";

const actionLinkClass =
  "rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50";

function formString(form: FormData, key: string) {
  return String(form.get(key) ?? "");
}

export function AgentsPage() {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const [searchParams] = useSearchParams();
  const requestedAgentId = searchParams.get("agentId");
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(requestedAgentId);
  const agents = useQuery({ queryKey: ["agents"], queryFn: endpoints.agents });
  const selectedAgent = useMemo(
    () => agents.data?.items.find((agent) => agent.id === selectedAgentId) ?? agents.data?.items[0],
    [agents.data, selectedAgentId]
  );
  const tools = useQuery({
    queryKey: ["agent-tools", selectedAgent?.id],
    queryFn: () => endpoints.agentTools(selectedAgent?.id ?? ""),
    enabled: Boolean(selectedAgent?.id)
  });
  const isOrganizationAdmin = getEffectiveRole(user) === "admin";
  const mcpServers = useQuery({
    queryKey: ["mcp-servers"],
    queryFn: endpoints.mcpServers,
    enabled: isOrganizationAdmin
  });
  const selectedFromMcpSync = Boolean(requestedAgentId && selectedAgent?.id === requestedAgentId);

  useEffect(() => {
    if (requestedAgentId) setSelectedAgentId(requestedAgentId);
  }, [requestedAgentId]);

  useEffect(() => {
    if (!user || !selectedAgent) return;
    const selectedViaLinkedRoute = requestedAgentId === selectedAgent.id;
    const selectedLinkedAgent = mcpServers.data?.items.some(
      (server) => server.agent_id === selectedAgent.id
    );
    if (selectedViaLinkedRoute || selectedLinkedAgent) {
      markOnboardingStepComplete(user.id, "reviewLinkedAgent");
    }
  }, [mcpServers.data, requestedAgentId, selectedAgent, user]);

  const createAgent = useMutation({
    mutationFn: (payload: unknown) => api.post("/api/v1/agents", payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["agents"] })
  });
  const createTool = useMutation({
    mutationFn: ({ agentId, payload }: { agentId: string; payload: unknown }) =>
      api.post(`/api/v1/agents/${agentId}/tools`, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["agent-tools", selectedAgent?.id] })
  });

  function submitAgent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    createAgent.mutate({
      name: formString(form, "name"),
      description: formString(form, "description") || null,
      owner: formString(form, "owner"),
      department: formString(form, "department"),
      risk_level: formString(form, "risk_level"),
      status: formString(form, "status")
    });
    event.currentTarget.reset();
  }

  function submitTool(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedAgent) return;
    const form = new FormData(event.currentTarget);
    createTool.mutate({
      agentId: selectedAgent.id,
      payload: {
        name: formString(form, "name"),
        description: formString(form, "description") || null,
        permission: formString(form, "permission"),
        risk_level: formString(form, "risk_level"),
        is_enabled: true
      }
    });
    event.currentTarget.reset();
  }

  return (
    <>
      <PageHeader title="Agents" subtitle="Agents in this organization and their allowed tools." />
      <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <Card>
          <h3 className="mb-3 font-semibold">Agent Registry</h3>
          <DataState isLoading={agents.isLoading} error={agents.error}>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="border-b text-xs uppercase text-slate-500">
                  <tr>
                    <th className="py-2">Name</th>
                    <th>Status</th>
                    <th>Risk</th>
                    <th>Owner</th>
                  </tr>
                </thead>
                <tbody>
                  {(agents.data as ListResponse<Agent> | undefined)?.items.map((agent) => (
                    <tr
                      key={agent.id}
                      onClick={() => setSelectedAgentId(agent.id)}
                      className={`cursor-pointer border-b last:border-0 hover:bg-slate-50 ${
                        selectedAgent?.id === agent.id ? "bg-blue-50" : ""
                      }`}
                    >
                      <td className="py-3 font-medium">{agent.name}</td>
                      <td><Badge>{agent.status}</Badge></td>
                      <td>{agent.risk_level}</td>
                      <td>{agent.owner}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {agents.data?.total === 0 ? (
              <div className="mt-4">
                <EmptyState
                  title="No agents yet in this organization"
                  message="Register an MCP server for this organization to create a linked agent and discover its tools, or create an agent manually."
                  actions={
                    <>
                      {isOrganizationAdmin ? (
                        <Link to="/mcp-servers" className={actionLinkClass}>
                          Register MCP Server
                        </Link>
                      ) : null}
                      <a href="#create-agent" className={actionLinkClass}>
                        Create Agent Manually
                      </a>
                    </>
                  }
                />
              </div>
            ) : null}
          </DataState>
        </Card>
        <Card>
          <div id="create-agent" className="scroll-mt-24" />
          <h3 className="mb-3 font-semibold">Create Agent</h3>
          <form onSubmit={submitAgent} className="space-y-3">
            <Field label="Name"><input name="name" required className={inputClass} placeholder="Refund Review Agent" /></Field>
            <Field label="Description"><textarea name="description" className={inputClass} placeholder="What this agent is allowed to help with" /></Field>
            <Field label="Owner"><input name="owner" required className={inputClass} placeholder="payments-team" /></Field>
            <Field label="Department"><input name="department" required className={inputClass} placeholder="Finance" /></Field>
            <Field label="Risk Level">
              <select name="risk_level" className={inputClass} defaultValue="medium">
                <option value="low">low</option><option value="medium">medium</option><option value="high">high</option><option value="critical">critical</option>
              </select>
            </Field>
            <Field label="Status">
              <select name="status" className={inputClass} defaultValue="draft">
                <option value="draft">draft</option><option value="active">active</option><option value="disabled">disabled</option><option value="archived">archived</option>
              </select>
            </Field>
            <PrimaryButton>Create Agent</PrimaryButton>
            {createAgent.error ? <p className="text-sm text-red-600">{getErrorMessage(createAgent.error)}</p> : null}
          </form>
        </Card>
      </div>

      {selectedAgent ? (
        <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_0.8fr]">
          <Card>
            {selectedFromMcpSync ? (
              <div className="mb-4 rounded-md border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900">
                Linked agent selected from MCP sync. Review its discovered tools below.
              </div>
            ) : null}
            <div className="mb-2 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <h3 className="font-semibold">{selectedAgent.name}</h3>
              <Link
                to={`/policy-decisions?agentId=${selectedAgent.id}`}
                className={actionLinkClass}
              >
                Test Policy Decision
              </Link>
            </div>
            <p className="mb-4 text-sm text-slate-500">{selectedAgent.description ?? "No description"}</p>
            <DataState isLoading={tools.isLoading} error={tools.error}>
              <div className="grid gap-3 md:grid-cols-2">
                {(tools.data as ListResponse<AgentTool> | undefined)?.items.map((tool) => (
                  <div key={tool.id} className="rounded-md border border-slate-200 p-3">
                    <div className="font-medium">{tool.name}</div>
                    <div className="mt-1 text-sm text-slate-500">{tool.description}</div>
                    <div className="mt-3 flex gap-2"><Badge>{tool.permission}</Badge><Badge>{tool.risk_level}</Badge><Badge>{tool.is_enabled ? "enabled" : "disabled"}</Badge></div>
                    <Link
                      to={`/policy-decisions?agentId=${selectedAgent.id}&toolId=${tool.id}&action=${encodeURIComponent(tool.name)}`}
                      className={`${actionLinkClass} mt-3 inline-flex`}
                    >
                      Test This Tool
                    </Link>
                  </div>
                ))}
              </div>
              {tools.data?.total === 0 ? (
                <div className="mt-4">
                  <EmptyState title="No tools declared" message="Add a tool manually or sync tools from the linked MCP server." />
                </div>
              ) : null}
            </DataState>
          </Card>
          <Card>
            <h3 className="mb-3 font-semibold">Add Tool</h3>
            <form onSubmit={submitTool} className="space-y-3">
              <Field label="Name"><input name="name" required className={inputClass} placeholder="payment_lookup" /></Field>
              <Field label="Description"><textarea name="description" className={inputClass} placeholder="What this tool allows the agent to do" /></Field>
              <Field label="Permission">
                <select name="permission" className={inputClass} defaultValue="read">
                  <option value="read">read</option><option value="write">write</option><option value="execute">execute</option><option value="admin">admin</option>
                </select>
              </Field>
              <Field label="Risk Level">
                <select name="risk_level" className={inputClass} defaultValue="low">
                  <option value="low">low</option><option value="medium">medium</option><option value="high">high</option><option value="critical">critical</option>
                </select>
              </Field>
              <PrimaryButton>Add Tool</PrimaryButton>
              {createTool.error ? <p className="text-sm text-red-600">{getErrorMessage(createTool.error)}</p> : null}
            </form>
          </Card>
        </div>
      ) : null}
    </>
  );
}
