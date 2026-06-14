import { useQuery } from "@tanstack/react-query";
import { type FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { endpoints } from "../api/queries";
import { useAuth } from "../auth/context";
import { markOnboardingStepComplete } from "../onboarding/progress";
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

const emptyFilters = {
  risk_level: "",
  compliance_status: "",
  governance_status: "",
  policy_coverage_status: ""
};

export function RiskRegisterPage() {
  const { user } = useAuth();
  const [filters, setFilters] = useState(emptyFilters);
  const riskRegister = useQuery({
    queryKey: ["risk-register", filters],
    queryFn: () =>
      endpoints.riskRegister(
        Object.fromEntries(Object.entries(filters).filter(([, value]) => value))
      )
  });

  useEffect(() => {
    if (user) markOnboardingStepComplete(user.id, "reviewRisk");
  }, [user]);

  function applyFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setFilters({
      risk_level: String(form.get("risk_level") ?? ""),
      compliance_status: String(form.get("compliance_status") ?? ""),
      governance_status: String(form.get("governance_status") ?? ""),
      policy_coverage_status: String(form.get("policy_coverage_status") ?? "")
    });
  }

  return (
    <>
      <PageHeader
        title="AI Risk Register"
        subtitle="Organization-wide visibility into governed tool risk and compliance posture."
      />
      <Card>
        <form
          key={JSON.stringify(filters)}
          className="grid gap-3 md:grid-cols-2 xl:grid-cols-5"
          onSubmit={applyFilters}
        >
          <Field label="Risk level">
            <select name="risk_level" className={inputClass} defaultValue={filters.risk_level}>
              <option value="">All risk levels</option>
              <option value="low">Low</option><option value="medium">Medium</option>
              <option value="high">High</option><option value="critical">Critical</option>
            </select>
          </Field>
          <Field label="Compliance">
            <select name="compliance_status" className={inputClass} defaultValue={filters.compliance_status}>
              <option value="">All statuses</option>
              <option value="compliant">Compliant</option><option value="warning">Warning</option>
              <option value="non_compliant">Non-compliant</option>
            </select>
          </Field>
          <Field label="Governance">
            <select name="governance_status" className={inputClass} defaultValue={filters.governance_status}>
              <option value="">All statuses</option>
              <option value="unreviewed">Unreviewed</option><option value="reviewed">Reviewed</option>
              <option value="governed">Governed</option>
            </select>
          </Field>
          <Field label="Policy coverage">
            <select name="policy_coverage_status" className={inputClass} defaultValue={filters.policy_coverage_status}>
              <option value="">All coverage</option>
              <option value="covered">Covered</option>
              <option value="partially_covered">Partially covered</option>
              <option value="uncovered">Uncovered</option>
            </select>
          </Field>
          <div className="flex items-end gap-2">
            <PrimaryButton>Apply filters</PrimaryButton>
            <SecondaryButton onClick={() => setFilters(emptyFilters)}>Clear</SecondaryButton>
          </div>
        </form>
      </Card>
      <Card className="mt-6">
        <DataState
          isLoading={riskRegister.isLoading}
          error={riskRegister.error}
          onRetry={() => void riskRegister.refetch()}
        >
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1100px] text-left text-sm">
              <thead className="border-b text-xs uppercase text-slate-500">
                <tr>
                  <th className="py-2">Tool</th><th>Agent</th><th>MCP Server</th><th>Risk</th>
                  <th>Governance</th><th>Policy Coverage</th><th>Compliance</th>
                  <th>Owner</th><th>Last Reviewed</th>
                </tr>
              </thead>
              <tbody>
                {riskRegister.data?.items.map((item) => (
                  <tr key={item.id} className="border-b last:border-0">
                    <td className="py-3">
                      <div className="font-medium text-slate-950">{item.tool_name}</div>
                      {item.violated_controls.length ? (
                        <div className="mt-1 text-xs text-red-600">
                          {item.violated_controls.join(", ")}
                        </div>
                      ) : null}
                    </td>
                    <td>{item.agent_name}</td><td>{item.mcp_server_name}</td>
                    <td><Badge>{item.risk_level}</Badge></td>
                    <td><Badge>{item.governance_status}</Badge></td>
                    <td><Badge>{item.policy_coverage_status.replace(/_/g, " ")}</Badge></td>
                    <td><Badge>{item.compliance_status.replace(/_/g, " ")}</Badge></td>
                    <td className="font-mono text-xs">{item.owner_user_id ?? "Unassigned"}</td>
                    <td>{item.last_reviewed_at ? new Date(item.last_reviewed_at).toLocaleString() : "Never"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {riskRegister.data?.total === 0 ? (
            <div className="mt-4">
              <EmptyState
                title="No AI risks found"
                message="The Risk Register measures governance and compliance posture for every discovered tool. Sync an MCP server to begin building the inventory."
                actions={<Link to="/mcp-servers" className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700">Discover tools</Link>}
              />
            </div>
          ) : null}
        </DataState>
      </Card>
    </>
  );
}
