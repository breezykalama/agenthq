import { useQueries } from "@tanstack/react-query";
import { useState } from "react";

import { endpoints } from "../api/queries";
import { Card, DataState, EmptyState, MetricCard, PageHeader } from "../components/Ui";
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
  const [demoBannerDismissed, setDemoBannerDismissed] = useState(
    () => localStorage.getItem("agenthq_demo_banner_dismissed") === "true"
  );
  const [summary, agentsByRisk, executionsByStatus, approvalsByStatus, agents] = useQueries({
    queries: [
      { queryKey: ["dashboard-summary"], queryFn: endpoints.dashboardSummary },
      { queryKey: ["agents-by-risk"], queryFn: endpoints.agentsByRisk },
      { queryKey: ["executions-by-status"], queryFn: endpoints.executionsByStatus },
      { queryKey: ["approvals-by-status"], queryFn: endpoints.approvalsByStatus },
      { queryKey: ["agents"], queryFn: endpoints.agents }
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
      <PageHeader title="Dashboard" subtitle="Your organization's agent governance overview." />
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
          <MetricCard label="Active Users" value={data?.active_users ?? 0} />
          <MetricCard label="Total Cost" value={`$${data?.total_cost_usd ?? "0"}`} />
          <MetricCard label="Avg Latency" value={`${Math.round(data?.average_latency_ms ?? 0)} ms`} />
        </div>
      </DataState>
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
      {data?.total_agents === 0 ? (
        <div className="mt-6">
          <EmptyState
            title="Your organization governance workspace is ready"
            message="Register an MCP server for this organization, or create its first agent manually."
          />
        </div>
      ) : null}
    </>
  );
}
