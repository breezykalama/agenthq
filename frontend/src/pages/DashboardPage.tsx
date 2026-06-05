import { useQueries } from "@tanstack/react-query";

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
  const [summary, agentsByRisk, executionsByStatus, approvalsByStatus] = useQueries({
    queries: [
      { queryKey: ["dashboard-summary"], queryFn: endpoints.dashboardSummary },
      { queryKey: ["agents-by-risk"], queryFn: endpoints.agentsByRisk },
      { queryKey: ["executions-by-status"], queryFn: endpoints.executionsByStatus },
      { queryKey: ["approvals-by-status"], queryFn: endpoints.approvalsByStatus }
    ]
  });

  const data = summary.data as DashboardSummary | undefined;

  return (
    <>
      <PageHeader title="Dashboard" subtitle="Operational posture across agents, approvals, executions, and incidents." />
      <Card className="mb-6 bg-slate-950 text-white">
        <div className="max-w-3xl">
          <h3 className="text-base font-semibold">AgentHQ helps teams govern enterprise agents before they act.</h3>
          <p className="mt-2 text-sm leading-6 text-slate-300">
            Register agents and tools, define policies, require approvals for risky actions,
            track simulated executions, record incidents, and produce compliance-ready summaries.
          </p>
        </div>
      </Card>
      <DataState isLoading={summary.isLoading} error={summary.error}>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="Total Agents" value={data?.total_agents ?? 0} />
          <MetricCard label="Executions Today" value={data?.executions_today ?? 0} />
          <MetricCard label="Pending Approvals" value={data?.pending_approvals ?? 0} />
          <MetricCard label="Open Incidents" value={data?.open_incidents ?? 0} />
          <MetricCard label="Blocked Executions" value={data?.blocked_executions ?? 0} />
          <MetricCard label="Requires Approval" value={data?.requires_approval_executions ?? 0} />
          <MetricCard label="Total Cost" value={`$${data?.total_cost_usd ?? "0"}`} />
          <MetricCard label="Avg Latency" value={`${Math.round(data?.average_latency_ms ?? 0)} ms`} />
        </div>
      </DataState>
      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        <DataState isLoading={agentsByRisk.isLoading} error={agentsByRisk.error}>
          <CountList title="Agents by Risk" data={agentsByRisk.data} />
        </DataState>
        <DataState isLoading={executionsByStatus.isLoading} error={executionsByStatus.error}>
          <CountList title="Executions by Status" data={executionsByStatus.data} />
        </DataState>
        <DataState isLoading={approvalsByStatus.isLoading} error={approvalsByStatus.error}>
          <CountList title="Approvals by Status" data={approvalsByStatus.data} />
        </DataState>
      </div>
      {data?.total_agents === 0 ? (
        <div className="mt-6">
          <EmptyState
            title="No demo data yet"
            message="Run the seed script or create agents from the Agents page to populate the dashboard."
          />
        </div>
      ) : null}
    </>
  );
}
