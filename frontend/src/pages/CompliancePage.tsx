import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";

import { endpoints } from "../api/queries";
import { useAuth } from "../auth/context";
import { Card, DataState, EmptyState, MetricCard, PageHeader } from "../components/Ui";
import { markOnboardingStepComplete } from "../onboarding/progress";
import type { ComplianceIncident, ListResponse } from "../types/api";

export function CompliancePage() {
  const { user } = useAuth();
  const summary = useQuery({ queryKey: ["compliance-summary"], queryFn: endpoints.complianceSummary });
  const incidents = useQuery({ queryKey: ["compliance-incidents"], queryFn: endpoints.complianceIncidents });

  useEffect(() => {
    if (user) markOnboardingStepComplete(user.id, "reviewCompliance");
  }, [user]);

  return (
    <>
      <PageHeader title="Compliance" subtitle="Compliance reporting for this organization." />
      <Card className="mb-6 border-blue-200 bg-blue-50 text-blue-950">
        <h3 className="text-sm font-semibold">Read-only compliance view</h3>
        <p className="mt-1 text-sm leading-6">
          These read-only reports summarize this organization's governance activity. They do not
          change agents, approvals, policies, executions, or incidents.
        </p>
      </Card>
      <DataState isLoading={summary.isLoading} error={summary.error}>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
          <MetricCard label="Agents" value={summary.data?.total_agents ?? 0} />
          <MetricCard label="Executions" value={summary.data?.total_executions ?? 0} />
          <MetricCard label="Blocked" value={summary.data?.blocked_executions ?? 0} />
          <MetricCard label="Open Incidents" value={summary.data?.open_incidents ?? 0} />
          <MetricCard label="Audit Events" value={summary.data?.audit_events ?? 0} />
        </div>
      </DataState>
      <Card className="mt-6">
        <h3 className="mb-3 font-semibold">Incident Report</h3>
        <DataState isLoading={incidents.isLoading} error={incidents.error}>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b text-xs uppercase text-slate-500">
                <tr><th className="py-2">Title</th><th>Severity</th><th>Status</th><th>Reported By</th><th>Assigned</th><th>Created</th></tr>
              </thead>
              <tbody>
                {(incidents.data as ListResponse<ComplianceIncident> | undefined)?.items.map((incident) => (
                    <tr key={incident.id} className="border-b last:border-0">
                      <td className="py-3 font-medium">{incident.title}</td>
                      <td>{incident.severity}</td>
                      <td>{incident.status}</td>
                      <td>{incident.reported_by}</td>
                      <td>{incident.assigned_to ?? "-"}</td>
                      <td>{new Date(incident.created_at).toLocaleString()}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
          {incidents.data?.total === 0 ? (
            <div className="mt-4">
              <EmptyState
                title="No incidents in this organization's report"
                message="Reported governance issues for this organization will appear here for read-only review."
              />
            </div>
          ) : null}
        </DataState>
      </Card>
    </>
  );
}
