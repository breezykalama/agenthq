import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useState } from "react";

import { api, getErrorMessage } from "../api/client";
import { endpoints } from "../api/queries";
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
import type { ListResponse, PolicyRule, PolicySimulation } from "../types/api";

function formString(form: FormData, key: string) {
  return String(form.get(key) ?? "");
}

export function PolicyRulesPage() {
  const queryClient = useQueryClient();
  const [previewPayload, setPreviewPayload] = useState<Record<string, unknown> | null>(null);
  const [editingRule, setEditingRule] = useState<PolicyRule | null>(null);
  const rules = useQuery({ queryKey: ["policy-rules"], queryFn: endpoints.policyRules });
  const simulation = useMutation({
    mutationFn: (payload: unknown) => endpoints.simulatePolicy(payload)
  });
  const saveRule = useMutation({
    mutationFn: ({ policyId, payload }: { policyId?: string; payload: Record<string, unknown> }) =>
      policyId
        ? api.patch(`/api/v1/policy-rules/${policyId}`, payload)
        : api.post("/api/v1/policy-rules", payload),
    onSuccess: () => {
      simulation.reset();
      setPreviewPayload(null);
      setEditingRule(null);
      void queryClient.invalidateQueries({ queryKey: ["policy-rules"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] });
      void queryClient.invalidateQueries({ queryKey: ["tool-governance"] });
    }
  });

  function payloadFromForm(form: FormData): Record<string, unknown> {
    const agentId = formString(form, "agent_id");
    const toolId = formString(form, "tool_id");
    return {
      name: formString(form, "name"),
      description: formString(form, "description") || null,
      scope: formString(form, "scope"),
      agent_id: agentId || null,
      tool_id: toolId || null,
      risk_level: formString(form, "risk_level"),
      effect: formString(form, "effect"),
      is_enabled: form.get("is_enabled") === "on",
      priority: Number(form.get("priority") || 100)
    };
  }

  function submitRule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const payload = payloadFromForm(form);
    if (editingRule) payload.policy_id = editingRule.id;
    setPreviewPayload(payload);
    simulation.mutate(payload);
  }

  return (
    <>
      <PageHeader title="Policy Rules" subtitle="Policies for this organization." />
      <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <Card>
          <h3 className="mb-3 font-semibold">Rules</h3>
          <DataState isLoading={rules.isLoading} error={rules.error}>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="border-b text-xs uppercase text-slate-500">
                  <tr><th className="py-2">Name</th><th>Scope</th><th>Risk</th><th>Effect</th><th>Priority</th><th>Enabled</th><th /></tr>
                </thead>
                <tbody>
                  {(rules.data as ListResponse<PolicyRule> | undefined)?.items.map((rule) => (
                    <tr key={rule.id} className="border-b last:border-0">
                      <td className="py-3 font-medium">{rule.name}</td>
                      <td>{rule.scope}</td>
                      <td>{rule.risk_level}</td>
                      <td><Badge>{rule.effect}</Badge></td>
                      <td>{rule.priority}</td>
                      <td>{rule.is_enabled ? "yes" : "no"}</td>
                      <td><SecondaryButton onClick={() => { setEditingRule(rule); simulation.reset(); setPreviewPayload(null); }}>Edit</SecondaryButton></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {rules.data?.total === 0 ? (
              <div className="mt-4">
                <EmptyState
                  title="No policy rules created for this organization"
                  message="Create a policy rule to govern this organization's agent behavior."
                />
              </div>
            ) : null}
          </DataState>
        </Card>
        <Card>
          <h3 className="mb-3 font-semibold">{editingRule ? "Edit Rule" : "Create Rule"}</h3>
          <form key={editingRule?.id ?? "create"} onSubmit={submitRule} className="space-y-3">
            <Field label="Name"><input name="name" required defaultValue={editingRule?.name} className={inputClass} placeholder="Global high-risk requires approval" /></Field>
            <Field label="Description"><textarea name="description" defaultValue={editingRule?.description ?? ""} className={inputClass} placeholder="When and why this rule should apply" /></Field>
            <Field label="Scope">
              <select name="scope" className={inputClass} defaultValue={editingRule?.scope ?? "global"}>
                <option value="global">global</option><option value="agent">agent</option><option value="tool">tool</option>
              </select>
            </Field>
            <Field label="Agent ID"><input name="agent_id" defaultValue={editingRule?.agent_id ?? ""} className={inputClass} placeholder="Required for agent/tool scope" /></Field>
            <Field label="Tool ID"><input name="tool_id" defaultValue={editingRule?.tool_id ?? ""} className={inputClass} placeholder="Required for tool scope" /></Field>
            <Field label="Risk Level">
              <select name="risk_level" className={inputClass} defaultValue={editingRule?.risk_level ?? "high"}>
                <option value="low">low</option><option value="medium">medium</option><option value="high">high</option><option value="critical">critical</option>
              </select>
            </Field>
            <Field label="Effect">
              <select name="effect" className={inputClass} defaultValue={editingRule?.effect ?? "require_approval"}>
                <option value="allow">allow</option><option value="require_approval">require_approval</option><option value="block">block</option>
              </select>
            </Field>
            <Field label="Priority"><input name="priority" type="number" defaultValue={editingRule?.priority ?? 100} className={inputClass} /></Field>
            <label className="flex items-center gap-2 text-sm text-slate-700"><input name="is_enabled" type="checkbox" defaultChecked={editingRule?.is_enabled ?? true} /> Enabled</label>
            <PrimaryButton disabled={simulation.isPending}>
              {simulation.isPending ? "Analyzing..." : "Preview Impact"}
            </PrimaryButton>
            {editingRule ? <SecondaryButton onClick={() => setEditingRule(null)}>Cancel Edit</SecondaryButton> : null}
            {simulation.error ? <p className="text-sm text-red-600">{getErrorMessage(simulation.error)}</p> : null}
            {saveRule.error ? <p className="text-sm text-red-600">{getErrorMessage(saveRule.error)}</p> : null}
          </form>
        </Card>
      </div>
      {simulation.data ? (
        <ImpactPreview
          impact={simulation.data}
          isSaving={saveRule.isPending}
          onCancel={() => {
            simulation.reset();
            setPreviewPayload(null);
          }}
          onSave={() => {
            if (previewPayload) {
              const { policy_id, ...payload } = previewPayload;
              saveRule.mutate({
                policyId: typeof policy_id === "string" ? policy_id : undefined,
                payload
              });
            }
          }}
        />
      ) : null}
    </>
  );
}

function ImpactPreview({
  impact,
  isSaving,
  onCancel,
  onSave
}: {
  impact: PolicySimulation;
  isSaving: boolean;
  onCancel: () => void;
  onSave: () => void;
}) {
  return (
    <Card className="mt-6 border-blue-200">
      <h3 className="font-semibold text-slate-950">Policy Impact Preview</h3>
      <p className="mt-1 text-sm text-slate-500">Simulation only. No policy, alert, or governance data has been changed.</p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <ImpactMetric label="Affected Tools" value={impact.affected_tools.count} />
        <ImpactMetric label="Affected Agents" value={impact.affected_agents.count} />
        <ImpactMetric label="Affected MCP Servers" value={impact.affected_mcp_servers.count} />
        <ImpactMetric label="Governance Gaps Resolved" value={impact.governance_gaps_resolved} />
        <ImpactMetric label="Projected Governed Tools" value={impact.projected_coverage.governed_tools} />
        <ImpactMetric label="Projected Coverage" value={`${impact.projected_coverage.policy_coverage_percentage}%`} />
        <ImpactMetric label="Potential Conflicts" value={impact.alert_impact.potentially_created_conflicts} />
        <ImpactMetric label="Alerts Potentially Resolved" value={impact.alert_impact.potentially_resolved_ungoverned_tool + impact.alert_impact.potentially_resolved_policy_coverage_lost} />
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div><h4 className="text-sm font-semibold">Governance changes</h4><p className="mt-1 text-sm text-slate-600">Blocked: {impact.governance_changes.becoming_blocked.count} · Approval required: {impact.governance_changes.becoming_approval_required.count} · Explicitly allowed: {impact.governance_changes.becoming_explicitly_allowed.count}</p></div>
        <div><h4 className="text-sm font-semibold">Warnings</h4><p className="mt-1 text-sm text-slate-600">{impact.warning_count ? `${impact.warning_count} overlapping or conflicting policy matches detected.` : "No overlapping policy warnings detected."}</p></div>
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <ImpactList title="Affected tools" items={impact.affected_tools.items.map((item) => item.name)} />
        <ImpactList title="Affected agents" items={impact.affected_agents.items.map((item) => item.name)} />
        <ImpactList title="Affected MCP servers" items={impact.affected_mcp_servers.items.map((item) => item.name)} />
      </div>
      {impact.warnings.length ? <div className="mt-4"><h4 className="text-sm font-semibold">Potential conflicts and overlaps</h4><ul className="mt-2 space-y-1 text-sm text-amber-800">{impact.warnings.slice(0, 8).map((warning, index) => <li key={`${warning.tool_id}-${index}`}>{warning.tool_name}: {warning.existing_policy_name} ({warning.existing_effect}) vs proposed {warning.proposed_effect}</li>)}</ul></div> : null}
      <div className="mt-5 flex gap-2"><PrimaryButton type="button" disabled={isSaving} onClick={onSave}>{isSaving ? "Saving..." : "Save Policy"}</PrimaryButton><SecondaryButton onClick={onCancel}>Cancel</SecondaryButton></div>
    </Card>
  );
}

function ImpactMetric({ label, value }: { label: string; value: string | number }) {
  return <div className="rounded-md bg-slate-50 p-3"><div className="text-xs uppercase text-slate-500">{label}</div><div className="mt-1 text-xl font-semibold">{value}</div></div>;
}

function ImpactList({ title, items }: { title: string; items: string[] }) {
  return <div><h4 className="text-sm font-semibold">{title}</h4><p className="mt-1 text-sm text-slate-600">{items.length ? items.slice(0, 8).join(", ") : "None"}</p></div>;
}
