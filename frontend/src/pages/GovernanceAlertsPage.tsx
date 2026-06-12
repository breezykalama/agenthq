import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

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
  MetricCard,
  PageHeader,
  SecondaryButton,
  inputClass
} from "../components/Ui";
import type { GovernanceAlert } from "../types/api";

export function GovernanceAlertsPage() {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const role = getEffectiveRole(user);
  const canManage = role === "admin" || role === "operator";
  const [searchParams] = useSearchParams();
  const [status, setStatus] = useState("");
  const [severity, setSeverity] = useState("");
  const [type, setType] = useState("");
  const toolId = searchParams.get("tool_id") ?? "";
  const params = Object.fromEntries(
    Object.entries({ status, severity, alert_type: type, tool_id: toolId }).filter(([, value]) => value)
  );
  const alerts = useQuery({
    queryKey: ["governance-alerts", params],
    queryFn: () => endpoints.governanceAlerts(params)
  });
  const health = useQuery({ queryKey: ["governance-health"], queryFn: endpoints.governanceHealth });
  const transition = useMutation({
    mutationFn: ({ id, action }: { id: string; action: string }) =>
      api.post<GovernanceAlert>(`/api/v1/governance-alerts/${id}/${action}`).then((r) => r.data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["governance-alerts"] });
      void queryClient.invalidateQueries({ queryKey: ["governance-health"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] });
      void queryClient.invalidateQueries({ queryKey: ["tool-governance"] });
    }
  });

  return (
    <>
      <PageHeader
        title="Governance Alerts"
        subtitle="Monitor governance risks, MCP drift, and policy coverage gaps for this organization."
      />
      <DataState isLoading={health.isLoading} error={health.error}>
        <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="Governance Health" value={`${health.data?.score ?? 100}/100`} />
          <MetricCard label="Open Alerts" value={health.data?.open_alerts ?? 0} />
          <MetricCard label="Critical Alerts" value={health.data?.critical_alerts ?? 0} />
          <MetricCard label="Governance Gaps" value={health.data?.governance_gaps ?? 0} />
        </div>
      </DataState>
      <Card>
        <div className="mb-4 grid gap-3 sm:grid-cols-3">
          <Field label="Status"><select className={inputClass} value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All statuses</option><option value="open">open</option><option value="acknowledged">acknowledged</option><option value="resolved">resolved</option></select></Field>
          <Field label="Severity"><select className={inputClass} value={severity} onChange={(e) => setSeverity(e.target.value)}><option value="">All severities</option><option value="low">low</option><option value="medium">medium</option><option value="high">high</option><option value="critical">critical</option></select></Field>
          <Field label="Type"><select className={inputClass} value={type} onChange={(e) => setType(e.target.value)}><option value="">All types</option><option value="new_tool_discovered">new tool discovered</option><option value="tool_removed">tool removed</option><option value="schema_changed">schema changed</option><option value="description_changed">description changed</option><option value="high_risk_unreviewed">high-risk unreviewed</option><option value="ungoverned_tool">ungoverned tool</option><option value="policy_coverage_lost">policy coverage lost</option></select></Field>
        </div>
        <DataState isLoading={alerts.isLoading} error={alerts.error} onRetry={() => void alerts.refetch()}>
          {alerts.data?.items.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="border-b text-xs uppercase text-slate-500"><tr><th className="py-2">Alert</th><th>Severity</th><th>Type</th><th>Status</th><th>Tool</th><th>MCP Server</th><th>Created</th><th /></tr></thead>
                <tbody>
                  {alerts.data.items.map((alert) => (
                    <tr key={alert.id} className="border-b last:border-0">
                      <td className="max-w-sm py-3"><div className="font-medium">{alert.title}</div><div className="text-xs text-slate-500">{alert.description}</div></td>
                      <td><Badge>{alert.severity}</Badge></td><td>{alert.alert_type.replace(/_/g, " ")}</td><td>{alert.status}</td>
                      <td className="max-w-32 break-all text-xs">{alert.tool_id ?? "N/A"}</td><td className="max-w-32 break-all text-xs">{alert.mcp_server_id ?? "N/A"}</td>
                      <td>{new Date(alert.created_at).toLocaleString()}</td>
                      <td>{canManage ? <div className="flex gap-2">{alert.status === "open" ? <SecondaryButton onClick={() => transition.mutate({ id: alert.id, action: "acknowledge" })}>Acknowledge</SecondaryButton> : null}{alert.status !== "resolved" ? <SecondaryButton onClick={() => transition.mutate({ id: alert.id, action: "resolve" })}>Resolve</SecondaryButton> : <SecondaryButton onClick={() => transition.mutate({ id: alert.id, action: "reopen" })}>Reopen</SecondaryButton>}</div> : "Read only"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <EmptyState title="No governance alerts" message="No alerts match the current organization filters." />}
          {transition.error ? <p className="mt-3 text-sm text-red-600">{getErrorMessage(transition.error)}</p> : null}
        </DataState>
      </Card>
    </>
  );
}
