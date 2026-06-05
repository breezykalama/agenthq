import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent } from "react";

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
  inputClass
} from "../components/Ui";
import type { ListResponse, PolicyRule } from "../types/api";

function formString(form: FormData, key: string) {
  return String(form.get(key) ?? "");
}

export function PolicyRulesPage() {
  const queryClient = useQueryClient();
  const rules = useQuery({ queryKey: ["policy-rules"], queryFn: endpoints.policyRules });
  const createRule = useMutation({
    mutationFn: (payload: unknown) => api.post("/api/v1/policy-rules", payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["policy-rules"] })
  });

  function submitRule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const agentId = formString(form, "agent_id");
    const toolId = formString(form, "tool_id");
    createRule.mutate({
      name: formString(form, "name"),
      description: formString(form, "description") || null,
      scope: formString(form, "scope"),
      agent_id: agentId || null,
      tool_id: toolId || null,
      risk_level: formString(form, "risk_level"),
      effect: formString(form, "effect"),
      is_enabled: form.get("is_enabled") === "on",
      priority: Number(form.get("priority") || 100)
    });
  }

  return (
    <>
      <PageHeader title="Policy Rules" subtitle="Define governance rules for agents and tools." />
      <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <Card>
          <h3 className="mb-3 font-semibold">Rules</h3>
          <DataState isLoading={rules.isLoading} error={rules.error}>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="border-b text-xs uppercase text-slate-500">
                  <tr><th className="py-2">Name</th><th>Scope</th><th>Risk</th><th>Effect</th><th>Priority</th><th>Enabled</th></tr>
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
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {rules.data?.total === 0 ? (
              <div className="mt-4">
                <EmptyState title="No policy rules yet" message="Create a global, agent, or tool rule to drive policy decisions." />
              </div>
            ) : null}
          </DataState>
        </Card>
        <Card>
          <h3 className="mb-3 font-semibold">Create Rule</h3>
          <form onSubmit={submitRule} className="space-y-3">
            <Field label="Name"><input name="name" required className={inputClass} placeholder="Global high-risk requires approval" /></Field>
            <Field label="Description"><textarea name="description" className={inputClass} placeholder="When and why this rule should apply" /></Field>
            <Field label="Scope">
              <select name="scope" className={inputClass} defaultValue="global">
                <option value="global">global</option><option value="agent">agent</option><option value="tool">tool</option>
              </select>
            </Field>
            <Field label="Agent ID"><input name="agent_id" className={inputClass} placeholder="Required for agent/tool scope" /></Field>
            <Field label="Tool ID"><input name="tool_id" className={inputClass} placeholder="Required for tool scope" /></Field>
            <Field label="Risk Level">
              <select name="risk_level" className={inputClass} defaultValue="high">
                <option value="low">low</option><option value="medium">medium</option><option value="high">high</option><option value="critical">critical</option>
              </select>
            </Field>
            <Field label="Effect">
              <select name="effect" className={inputClass} defaultValue="require_approval">
                <option value="allow">allow</option><option value="require_approval">require_approval</option><option value="block">block</option>
              </select>
            </Field>
            <Field label="Priority"><input name="priority" type="number" defaultValue={100} className={inputClass} /></Field>
            <label className="flex items-center gap-2 text-sm text-slate-700"><input name="is_enabled" type="checkbox" defaultChecked /> Enabled</label>
            <PrimaryButton>Create Rule</PrimaryButton>
            {createRule.error ? <p className="text-sm text-red-600">{getErrorMessage(createRule.error)}</p> : null}
          </form>
        </Card>
      </div>
    </>
  );
}
