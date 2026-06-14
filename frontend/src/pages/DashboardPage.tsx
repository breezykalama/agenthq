import { useQueries } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { endpoints } from "../api/queries";
import { useAuth } from "../auth/context";
import { getEffectiveRole } from "../auth/roles";
import { Card, DataState, MetricCard, PageHeader } from "../components/Ui";
import type { CountMap, DashboardSummary } from "../types/api";

function CountList({ title, data }: { title: string; data?: CountMap }) {
  return (
    <Card>
      <h3 className="mb-3 text-sm font-semibold text-slate-900">{title}</h3>
      {Object.keys(data ?? {}).length === 0 ? (
        <p className="text-sm text-slate-500">No counts available.</p>
      ) : (
        <div className="space-y-2">
          {Object.entries(data ?? {}).map(([key, value]) => (
            <div key={key} className="flex items-center justify-between text-sm">
              <span className="capitalize text-slate-600">{key.replace(/_/g, " ")}</span>
              <span className="font-semibold text-slate-900">{value}</span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

export function DashboardPage() {
  const { user } = useAuth();
  const canViewAlerts = getEffectiveRole(user) !== "agent_owner";
  const canViewRisk = ["admin", "auditor"].includes(getEffectiveRole(user) ?? "");
  const [demoBannerDismissed, setDemoBannerDismissed] = useState(
    () => localStorage.getItem("agenthq_demo_banner_dismissed") === "true"
  );
  const [summary, agentsByRisk, executionsByStatus, approvalsByStatus, agents, recentAlerts, riskSummary] = useQueries({
    queries: [
      { queryKey: ["dashboard-summary"], queryFn: endpoints.dashboardSummary },
      { queryKey: ["agents-by-risk"], queryFn: endpoints.agentsByRisk },
      { queryKey: ["executions-by-status"], queryFn: endpoints.executionsByStatus },
      { queryKey: ["approvals-by-status"], queryFn: endpoints.approvalsByStatus },
      { queryKey: ["agents"], queryFn: endpoints.agents },
      {
        queryKey: ["governance-alerts", "recent"],
        queryFn: () => endpoints.governanceAlerts({ limit: 5 }),
        enabled: canViewAlerts
      },
      {
        queryKey: ["risk-summary"],
        queryFn: endpoints.riskSummary,
        enabled: canViewRisk
      }
    ]
  });

  const data = summary.data as DashboardSummary | undefined;
  const demoAgentNames = new Set([
    "Policy Knowledge Agent",
    "Customer Response Agent",
    "Payment Operations Agent",
    "Escalation Agent"
  ]);
  const isDemoMode = agents.data?.items.some((agent) => demoAgentNames.has(agent.name)) ?? false;
  const isEmptyWorkspace =
    !summary.isLoading &&
    (data?.total_mcp_servers ?? 0) === 0 &&
    (data?.discovered_tools ?? 0) === 0;
  return (
    <>
      <PageHeader title="Dashboard" subtitle="Your organization's agent governance overview." />
      <section className="mb-6 overflow-hidden rounded-md border border-slate-800 bg-slate-950 px-5 py-6 text-white shadow-sm sm:px-7">
        <div className="flex flex-col gap-6 xl:flex-row xl:items-end xl:justify-between">
          <div className="max-w-2xl">
            <div className="text-xs font-semibold uppercase text-emerald-300">Governance command center</div>
            <h2 className="mt-2 text-2xl font-semibold sm:text-3xl">
              See risk. Close governance gaps. Keep agents accountable.
            </h2>
            <p className="mt-3 text-sm leading-6 text-slate-300">
              AgentHQ brings discovery, policy, approvals, execution evidence, and compliance posture into one organization workspace.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {getEffectiveRole(user) === "admin" ? (
              <>
                <Link to="/mcp-servers" className="rounded-md bg-emerald-400 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-emerald-300">
                  Register MCP Server
                </Link>
                <Link to="/agents#create-agent" className="rounded-md border border-white/30 px-4 py-2 text-sm font-semibold text-white hover:bg-white/10">
                  Create Agent
                </Link>
                <Link to="/policy-rules" className="rounded-md border border-white/30 px-4 py-2 text-sm font-semibold text-white hover:bg-white/10">
                  Create Policy
                </Link>
              </>
            ) : null}
          </div>
        </div>
        <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <HeroMetric label="AI Risk Score" value={`${riskSummary.data?.risk_score ?? data?.governance_health ?? 100}/100`} />
          <HeroMetric label="Compliance Score" value={`${riskSummary.data?.compliance_score ?? 100}%`} />
          <HeroMetric label="Governed Tools" value={riskSummary.data?.governed_tools ?? data?.governed_tools ?? 0} />
          <HeroMetric label="Open Alerts" value={data?.open_governance_alerts ?? 0} />
        </div>
      </section>
      {isEmptyWorkspace ? (
        <Card className="mb-6 border-emerald-200 bg-emerald-50">
          <div className="grid gap-5 lg:grid-cols-[1fr_auto] lg:items-center">
            <div>
              <div className="text-xs font-semibold uppercase text-emerald-700">Welcome to AgentHQ</div>
              <h3 className="mt-2 text-xl font-semibold text-slate-950">Build your first governed agent connection</h3>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">
                Discover tools from an MCP server, govern their risk and permissions, enforce policy through the gateway, and measure the resulting risk posture.
              </p>
              <div className="mt-4 flex flex-wrap gap-2 text-xs font-semibold uppercase text-slate-600">
                <span>Discover</span><span aria-hidden="true">{"\u2192"}</span>
                <span>Govern</span><span aria-hidden="true">{"\u2192"}</span>
                <span>Enforce</span><span aria-hidden="true">{"\u2192"}</span>
                <span>Measure Risk</span>
              </div>
            </div>
            {getEffectiveRole(user) === "admin" ? (
              <Link to="/mcp-servers" className="rounded-md bg-slate-900 px-4 py-2 text-center text-sm font-semibold text-white hover:bg-slate-700">
                Register your first MCP server
              </Link>
            ) : null}
          </div>
        </Card>
      ) : null}
      {isDemoMode && !demoBannerDismissed ? (
        <div className="mb-4 flex flex-col gap-3 rounded-md border border-blue-200 bg-blue-50 p-4 text-blue-950 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm leading-6">
            This environment contains sample governance data so you can explore AgentHQ immediately.
          </p>
          <button
            type="button"
            onClick={() => {
              localStorage.setItem("agenthq_demo_banner_dismissed", "true");
              setDemoBannerDismissed(true);
            }}
            className="self-start rounded-md border border-blue-300 px-3 py-1.5 text-sm font-medium hover:bg-blue-100 sm:self-auto"
          >
            Dismiss
          </button>
        </div>
      ) : null}
      <DataState
        isLoading={summary.isLoading}
        error={summary.error}
        onRetry={() => void summary.refetch()}
      >
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="Total Agents" value={data?.total_agents ?? 0} />
          <MetricCard label="Executions Today" value={data?.executions_today ?? 0} />
          <MetricCard label="Pending Approvals" value={data?.pending_approvals ?? 0} />
          <MetricCard label="Open Incidents" value={data?.open_incidents ?? 0} />
          <MetricCard label="Blocked Executions" value={data?.blocked_executions ?? 0} />
          <MetricCard label="Requires Approval" value={data?.requires_approval_executions ?? 0} />
          <MetricCard label="MCP Servers" value={data?.total_mcp_servers ?? 0} />
          <MetricCard label="Discovered Tools" value={data?.discovered_tools ?? 0} />
          <MetricCard label="Governed Tools" value={data?.governed_tools ?? 0} />
          <MetricCard label="Unreviewed Tools" value={data?.unreviewed_tools ?? 0} />
          <MetricCard label="Schema Changes This Month" value={data?.schema_changes_this_month ?? 0} />
          <MetricCard label="Governance Health" value={`${data?.governance_health ?? 100}/100`} />
          <MetricCard label="Open Alerts" value={data?.open_governance_alerts ?? 0} />
          <MetricCard label="Critical Alerts" value={data?.critical_governance_alerts ?? 0} />
          <MetricCard label="Governance Gaps" value={data?.governance_gaps ?? 0} />
          <MetricCard label="Policy Coverage" value={`${data?.policy_coverage_percentage ?? 0}%`} />
          <MetricCard label="Active Users" value={data?.active_users ?? 0} />
          <MetricCard label="Total Cost" value={`$${data?.total_cost_usd ?? "0"}`} />
          <MetricCard label="Avg Latency" value={`${Math.round(data?.average_latency_ms ?? 0)} ms`} />
        </div>
      </DataState>
      {canViewRisk ? (
        <div className="mt-4">
          <DataState
            isLoading={riskSummary.isLoading}
            error={riskSummary.error}
            onRetry={() => void riskSummary.refetch()}
          >
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
              <MetricCard label="AI Risk Score" value={`${riskSummary.data?.risk_score ?? 100}/100`} />
              <MetricCard label="Compliance Score" value={`${riskSummary.data?.compliance_score ?? 100}%`} />
              <MetricCard label="Compliance Violations" value={riskSummary.data?.compliance_violations ?? 0} />
              <MetricCard label="Open Governance Risks" value={riskSummary.data?.open_governance_risks ?? 0} />
              <MetricCard label="High Risk Tools" value={riskSummary.data?.high_risk_tools ?? 0} />
            </div>
            <Card className="mt-4">
              <h3 className="mb-3 text-sm font-semibold text-slate-900">Risk Trend</h3>
              <div className="flex min-h-24 items-end gap-2 overflow-x-auto">
                {riskSummary.data?.risk_trend.map((snapshot) => (
                  <div key={snapshot.date} className="flex min-w-16 flex-col items-center gap-2">
                    <div
                      className="w-8 rounded-t bg-blue-600"
                      style={{ height: `${Math.max(8, snapshot.risk_score)}px` }}
                      title={`${snapshot.date}: ${snapshot.risk_score}/100`}
                    />
                    <span className="text-xs text-slate-500">{snapshot.date.slice(5)}</span>
                  </div>
                ))}
                {riskSummary.data?.risk_trend.length === 0 ? (
                  <p className="self-center text-sm text-slate-500">
                    Risk trend snapshots will appear as the organization is evaluated.
                  </p>
                ) : null}
              </div>
            </Card>
          </DataState>
        </div>
      ) : null}
      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        <DataState
          isLoading={agentsByRisk.isLoading}
          error={agentsByRisk.error}
          onRetry={() => void agentsByRisk.refetch()}
        >
          <CountList title="Agents by Risk" data={agentsByRisk.data} />
        </DataState>
        <DataState
          isLoading={executionsByStatus.isLoading}
          error={executionsByStatus.error}
          onRetry={() => void executionsByStatus.refetch()}
        >
          <CountList title="Executions by Status" data={executionsByStatus.data} />
        </DataState>
        <DataState
          isLoading={approvalsByStatus.isLoading}
          error={approvalsByStatus.error}
          onRetry={() => void approvalsByStatus.refetch()}
        >
          <CountList title="Approvals by Status" data={approvalsByStatus.data} />
        </DataState>
      </div>
      {canViewAlerts ? <div className="mt-6">
        <DataState isLoading={recentAlerts.isLoading} error={recentAlerts.error}>
          <Card>
            <h3 className="mb-3 text-sm font-semibold text-slate-900">Recent Governance Alerts</h3>
            {recentAlerts.data?.items.length ? (
              <div className="space-y-3">
                {recentAlerts.data.items.map((alert) => (
                  <div key={alert.id} className="flex flex-wrap justify-between gap-2 border-b pb-3 last:border-0 last:pb-0">
                    <div><div className="text-sm font-medium">{alert.title}</div><div className="text-xs text-slate-500">{alert.alert_type.replace(/_/g, " ")}</div></div>
                    <div className="text-xs text-slate-500">{alert.severity} · {alert.status}</div>
                  </div>
                ))}
              </div>
            ) : <p className="text-sm text-slate-500">No governance alerts have been recorded.</p>}
          </Card>
        </DataState>
      </div> : null}
    </>
  );
}

function HeroMetric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-md border border-white/15 bg-white/5 p-3">
      <div className="text-xs font-medium uppercase text-slate-400">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-white">{value}</div>
    </div>
  );
}
