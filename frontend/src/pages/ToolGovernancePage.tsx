import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api, getErrorMessage } from "../api/client";
import { endpoints } from "../api/queries";
import {
  Badge,
  Card,
  DataState,
  EmptyState,
  Field,
  MetricCard,
  PageHeader,
  PrimaryButton,
  SecondaryButton,
  inputClass
} from "../components/Ui";
import type { ToolGovernanceItem } from "../types/api";

function JsonSchema({ value }: { value: Record<string, unknown> | null }) {
  return (
    <pre className="max-h-80 overflow-auto rounded-md bg-slate-950 p-3 text-xs text-slate-100">
      {value ? JSON.stringify(value, null, 2) : "Schema not provided by the MCP server."}
    </pre>
  );
}

export function ToolGovernancePage() {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<ToolGovernanceItem | null>(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [riskFilter, setRiskFilter] = useState("");
  const [serverFilter, setServerFilter] = useState("");
  const [agentFilter, setAgentFilter] = useState("");
  const tools = useQuery({ queryKey: ["tool-governance"], queryFn: endpoints.toolGovernance });
  const summary = useQuery({
    queryKey: ["tool-governance-summary"],
    queryFn: endpoints.toolGovernanceSummary
  });
  const review = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: unknown }) =>
      api.post<ToolGovernanceItem>(`/api/v1/tool-governance/${id}/review`, payload).then((r) => r.data),
    onSuccess: (item) => {
      setSelected(item);
      void queryClient.invalidateQueries({ queryKey: ["tool-governance"] });
      void queryClient.invalidateQueries({ queryKey: ["tool-governance-summary"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] });
    }
  });
  const filtered = useMemo(
    () =>
      (tools.data?.items ?? []).filter(
        (tool) =>
          (!statusFilter || tool.governance_status === statusFilter) &&
          (!riskFilter || tool.risk_level === riskFilter) &&
          (!serverFilter || tool.mcp_server_id === serverFilter) &&
          (!agentFilter || tool.agent_id === agentFilter)
      ),
    [tools.data, statusFilter, riskFilter, serverFilter, agentFilter]
  );
  const servers = useMemo(
    () => Array.from(new Map((tools.data?.items ?? []).map((tool) => [tool.mcp_server_id, tool.mcp_server_name]))),
    [tools.data]
  );
  const agents = useMemo(
    () => Array.from(new Map((tools.data?.items ?? []).map((tool) => [tool.agent_id, tool.agent_name]))),
    [tools.data]
  );

  function submitReview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) return;
    const form = new FormData(event.currentTarget);
    review.mutate({
      id: selected.id,
      payload: {
        risk_level: String(form.get("risk_level")),
        permission: String(form.get("permission"))
      }
    });
  }

  return (
    <>
      <PageHeader
        title="MCP Tool Governance"
        subtitle="Review discovered tool schemas, risk, permissions, and policy coverage."
      />
      <DataState isLoading={summary.isLoading} error={summary.error}>
        <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="Total Tools" value={summary.data?.total_tools ?? 0} />
          <MetricCard label="Unreviewed Tools" value={summary.data?.unreviewed_tools ?? 0} />
          <MetricCard label="Governed Tools" value={summary.data?.governed_tools ?? 0} />
          <MetricCard label="High Risk Tools" value={summary.data?.high_risk_tools ?? 0} />
        </div>
      </DataState>
      <Card>
        <div className="mb-4 flex flex-wrap gap-3">
          <Field label="Governance Status">
            <select className={inputClass} value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="">All statuses</option>
              <option value="unreviewed">unreviewed</option>
              <option value="reviewed">reviewed</option>
              <option value="governed">governed</option>
            </select>
          </Field>
          <Field label="Risk Level">
            <select className={inputClass} value={riskFilter} onChange={(e) => setRiskFilter(e.target.value)}>
              <option value="">All risks</option>
              <option value="low">low</option><option value="medium">medium</option>
              <option value="high">high</option><option value="critical">critical</option>
            </select>
          </Field>
          <Field label="MCP Server">
            <select className={inputClass} value={serverFilter} onChange={(e) => setServerFilter(e.target.value)}>
              <option value="">All servers</option>
              {servers.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
            </select>
          </Field>
          <Field label="Agent">
            <select className={inputClass} value={agentFilter} onChange={(e) => setAgentFilter(e.target.value)}>
              <option value="">All agents</option>
              {agents.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
            </select>
          </Field>
        </div>
        <DataState isLoading={tools.isLoading} error={tools.error} onRetry={() => void tools.refetch()}>
          {filtered.length === 0 ? (
            <EmptyState
              title="No discovered MCP tools"
              message="Discovered tools become the inventory AgentHQ can review, govern, and protect. Register and sync an MCP server to bring tools into this workspace."
              actions={<Link to="/mcp-servers" className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700">Register or sync MCP server</Link>}
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="border-b text-xs uppercase text-slate-500">
                  <tr><th className="py-2">Tool</th><th>Status</th><th>Risk</th><th>Permission</th><th>Policies</th><th>Alerts</th><th>Schema Change</th><th>Reviewed</th><th /></tr>
                </thead>
                <tbody>
                  {filtered.map((tool) => (
                    <tr key={tool.id} className="border-b last:border-0">
                      <td className="py-3"><div className="font-medium">{tool.name}</div><div className="text-xs text-slate-500">{tool.agent_name} · {tool.mcp_server_name}</div></td>
                      <td><Badge>{tool.governance_status}</Badge></td><td>{tool.risk_level}</td><td>{tool.permission}</td>
                      <td>{tool.policy_count}</td>
                      <td>{tool.active_alerts_count ? <Link className="text-blue-700 underline" to={`/governance-alerts?tool_id=${tool.id}`}>{tool.active_alerts_count} active</Link> : "None"}</td>
                      <td>{tool.schema_last_updated_at ? new Date(tool.schema_last_updated_at).toLocaleString() : "Never"}</td>
                      <td>{tool.reviewed_at ? new Date(tool.reviewed_at).toLocaleString() : "Not reviewed"}</td>
                      <td><SecondaryButton onClick={() => setSelected(tool)}>Review</SecondaryButton></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </DataState>
      </Card>
      {selected ? (
        <Card className="mt-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div><h3 className="font-semibold">{selected.name}</h3><p className="mt-1 text-sm text-slate-500">{selected.description ?? "No description provided."}</p></div>
            <SecondaryButton onClick={() => setSelected(null)}>Close</SecondaryButton>
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <details open><summary className="mb-2 cursor-pointer font-medium">Input Schema</summary><JsonSchema value={selected.input_schema} /></details>
            <details><summary className="mb-2 cursor-pointer font-medium">Output Schema</summary><JsonSchema value={selected.output_schema} /></details>
          </div>
          <div className="mt-4 text-sm text-slate-600">
            Schema version {selected.schema_version ?? "unknown"}. Governed by: {selected.governed_by.join(", ") || "No matching policies"}.
            {selected.policy_names.length ? ` Policies: ${selected.policy_names.join(", ")}.` : ""}
          </div>
          <form onSubmit={submitReview} className="mt-4 grid gap-3 sm:grid-cols-2 lg:max-w-xl">
            <Field label="Risk Level"><select name="risk_level" defaultValue={selected.risk_level} className={inputClass}><option value="low">low</option><option value="medium">medium</option><option value="high">high</option><option value="critical">critical</option></select></Field>
            <Field label="Permission"><select name="permission" defaultValue={selected.permission} className={inputClass}><option value="read">read</option><option value="write">write</option><option value="execute">execute</option><option value="admin">admin</option></select></Field>
            <div className="sm:col-span-2"><PrimaryButton disabled={review.isPending}>{review.isPending ? "Saving..." : "Mark Reviewed"}</PrimaryButton></div>
            {review.error ? <p className="text-sm text-red-600 sm:col-span-2">{getErrorMessage(review.error)}</p> : null}
          </form>
        </Card>
      ) : null}
    </>
  );
}
