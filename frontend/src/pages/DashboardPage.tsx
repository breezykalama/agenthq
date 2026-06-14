import { useQueries } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { endpoints } from "../api/queries";
import { useAuth } from "../auth/context";
import { getEffectiveRole } from "../auth/roles";
import { TemporaryOnboarding } from "../components/Onboarding";
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
  const role = getEffectiveRole(user);
  const canViewAlerts = role !== "agent_owner";
  const canViewRisk = ["admin", "auditor"].includes(role ?? "");
  const [demoBannerDismissed, setDemoBannerDismissed] = useState(
    () => localStorage.getItem("agenthq_demo_banner_dismissed") === "true"
  );
  const [summary, agentsByRisk, executionsByStatus, approvalsByStatus, agents, recentAlerts, riskSummary] =
    useQueries({
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

  return (
    <>
      <PageHeader
        title="Dashboard"
        subtitle="Your organization's agent governance overview."
        actions={
          role === "admin" ? (
            <>
              <Link to="/mcp-servers" className="app-button app-button-primary">
                Register MCP Server
              </Link>
              <Link to="/agents#create-agent" className="app-button app-button-secondary">
                Create Agent
              </Link>
              <Link to="/policy-rules" className="app-button app-button-secondary">
                Create Policy
              </Link>
            </>
          ) : null
        }
      />

      <TemporaryOnboarding />

      <section className="mb-5 rounded-md border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="text-xs font-semibold uppercase text-slate-500">Executive summary</div>
            <p className="mt-1 text-sm text-slate-600">
              Current risk, compliance, tool governance, and alert posture.
            </p>
          </div>
          <div className="grid flex-1 gap-3 sm:grid-cols-2 lg:max-w-4xl lg:grid-cols-4">
            <HeroMetric
              label="AI Risk Score"
              value={`${riskSummary.data?.risk_score ?? data?.governance_health ?? 100}/100`}
            />
            <HeroMetric
              label="Compliance Score"
              value={`${riskSummary.data?.compliance_score ?? 100}%`}
            />
            <HeroMetric
              label="Governed Tools"
              value={riskSummary.data?.governed_tools ?? data?.governed_tools ?? 0}
            />
            <HeroMetric label="Open Alerts" value={data?.open_governance_alerts ?? 0} />
          </div>
        </div>
      </section>

      {isDemoMode && !demoBannerDismissed ? (
        <div className="mb-5 flex flex-col gap-3 rounded-md border border-blue-200 bg-blue-50 p-3 text-blue-950 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm">
            This environment contains sample governance data so you can explore AgentHQ immediately.
          </p>
          <button
            type="button"
            onClick={() => {
              localStorage.setItem("agenthq_demo_banner_dismissed", "true");
              setDemoBannerDismissed(true);
            }}
            className="self-start text-sm font-medium text-blue-700 hover:text-blue-950 sm:self-auto"
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
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <MetricCard label="Total Agents" value={data?.total_agents ?? 0} />
          <MetricCard label="Executions Today" value={data?.executions_today ?? 0} />
          <MetricCard label="Pending Approvals" value={data?.pending_approvals ?? 0} />
          <MetricCard label="Open Incidents" value={data?.open_incidents ?? 0} />
          <MetricCard label="Blocked Executions" value={data?.blocked_executions ?? 0} />
          <MetricCard label="MCP Servers" value={data?.total_mcp_servers ?? 0} />
          <MetricCard label="Discovered Tools" value={data?.discovered_tools ?? 0} />
          <MetricCard label="Governance Gaps" value={data?.governance_gaps ?? 0} />
        </div>
      </DataState>

      <div className="mt-5 grid gap-4 xl:grid-cols-[1fr_1fr]">
        {canViewRisk ? (
          <DataState
            isLoading={riskSummary.isLoading}
            error={riskSummary.error}
            onRetry={() => void riskSummary.refetch()}
          >
            <Card>
              <h3 className="mb-3 text-sm font-semibold text-slate-900">Risk Trend</h3>
              <div className="flex min-h-28 items-end gap-2 overflow-x-auto">
                {riskSummary.data?.risk_trend.map((snapshot) => (
                  <div key={snapshot.date} className="flex min-w-16 flex-col items-center gap-2">
                    <div
                      className="w-7 rounded-t bg-blue-600"
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
        ) : null}
        {canViewAlerts ? (
          <DataState isLoading={recentAlerts.isLoading} error={recentAlerts.error}>
            <Card>
              <h3 className="mb-3 text-sm font-semibold text-slate-900">Recent Governance Alerts</h3>
              {recentAlerts.data?.items.length ? (
                <div className="space-y-3">
                  {recentAlerts.data.items.map((alert) => (
                    <div
                      key={alert.id}
                      className="flex flex-wrap justify-between gap-2 border-b pb-3 last:border-0 last:pb-0"
                    >
                      <div>
                        <div className="text-sm font-medium">{alert.title}</div>
                        <div className="text-xs text-slate-500">
                          {alert.alert_type.replace(/_/g, " ")}
                        </div>
                      </div>
                      <div className="text-xs text-slate-500">
                        {alert.severity} - {alert.status}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-slate-500">No governance alerts have been recorded.</p>
              )}
            </Card>
          </DataState>
        ) : null}
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-3">
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
    </>
  );
}

function HeroMetric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-md bg-slate-50 px-3 py-2.5">
      <div className="text-xs font-medium text-slate-500">{label}</div>
      <div className="mt-1 text-xl font-semibold text-slate-950">{value}</div>
    </div>
  );
}
