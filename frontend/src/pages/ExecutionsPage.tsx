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
import type { Execution, ListResponse } from "../types/api";

function formString(form: FormData, key: string) {
  return String(form.get(key) ?? "");
}

export function ExecutionsPage() {
  const queryClient = useQueryClient();
  const executions = useQuery({ queryKey: ["executions"], queryFn: endpoints.executions });
  const createExecution = useMutation({
    mutationFn: (payload: unknown) => api.post("/api/v1/executions", payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["executions"] })
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const toolId = formString(form, "tool_id");
    const approvalId = formString(form, "approval_id");
    createExecution.mutate({
      agent_id: formString(form, "agent_id"),
      tool_id: toolId || null,
      approval_id: approvalId || null,
      action_name: formString(form, "action_name"),
      input_summary: formString(form, "input_summary") || null,
      status: formString(form, "status"),
      risk_level: formString(form, "risk_level"),
      cost_usd: formString(form, "cost_usd") || null,
      latency_ms: formString(form, "latency_ms") ? Number(form.get("latency_ms")) : null
    });
  }

  return (
    <>
      <PageHeader title="Executions" subtitle="Track simulated executions and policy outcomes." />
      <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <Card>
          <DataState isLoading={executions.isLoading} error={executions.error}>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="border-b text-xs uppercase text-slate-500">
                  <tr><th className="py-2">Action</th><th>Status</th><th>Risk</th><th>Policy</th><th>Cost</th><th>Latency</th></tr>
                </thead>
                <tbody>
                  {(executions.data as ListResponse<Execution> | undefined)?.items.map((execution) => (
                    <tr key={execution.id} className="border-b last:border-0">
                      <td className="py-3 font-medium">{execution.action_name}</td>
                      <td><Badge>{execution.status}</Badge></td>
                      <td>{execution.risk_level}</td>
                      <td>{execution.policy_decision ?? "-"}</td>
                      <td>{execution.cost_usd ? `$${execution.cost_usd}` : "-"}</td>
                      <td>{execution.latency_ms ? `${execution.latency_ms} ms` : "-"}</td>
                    </tr>
                  ))}
                </tbody>
            </table>
          </div>
          {executions.data?.total === 0 ? (
            <div className="mt-4">
              <EmptyState
                title="No executions tracked for this organization"
                message="Run a simulated execution to test this organization's governance policies."
              />
            </div>
          ) : null}
        </DataState>
        </Card>
        <Card>
          <h3 className="mb-3 font-semibold">Create Simulated Execution</h3>
          <form onSubmit={submit} className="space-y-3">
            <Field label="Agent ID"><input name="agent_id" required className={inputClass} placeholder="Paste an agent UUID" /></Field>
            <Field label="Tool ID"><input name="tool_id" className={inputClass} placeholder="Optional tool UUID" /></Field>
            <Field label="Approval ID"><input name="approval_id" className={inputClass} placeholder="Optional approved approval UUID" /></Field>
            <Field label="Action Name"><input name="action_name" required defaultValue="run_tool" className={inputClass} /></Field>
            <Field label="Input Summary"><textarea name="input_summary" className={inputClass} placeholder="Briefly describe the simulated input" /></Field>
            <Field label="Status">
              <select name="status" className={inputClass} defaultValue="running">
                <option value="pending">pending</option><option value="running">running</option><option value="succeeded">succeeded</option><option value="failed">failed</option><option value="blocked">blocked</option>
              </select>
            </Field>
            <Field label="Risk Level">
              <select name="risk_level" className={inputClass} defaultValue="medium">
                <option value="low">low</option><option value="medium">medium</option><option value="high">high</option><option value="critical">critical</option>
              </select>
            </Field>
            <Field label="Cost USD"><input name="cost_usd" type="number" step="0.0001" min="0" className={inputClass} /></Field>
            <Field label="Latency MS"><input name="latency_ms" type="number" min="0" className={inputClass} /></Field>
            <PrimaryButton>Create Execution</PrimaryButton>
            {createExecution.error ? <p className="text-sm text-red-600">{getErrorMessage(createExecution.error)}</p> : null}
          </form>
        </Card>
      </div>
    </>
  );
}
