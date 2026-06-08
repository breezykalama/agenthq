import { useMutation } from "@tanstack/react-query";
import { FormEvent, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { getErrorMessage } from "../api/client";
import { endpoints } from "../api/queries";
import { useAuth } from "../auth/context";
import { Badge, Card, Field, PageHeader, PrimaryButton, inputClass } from "../components/Ui";
import { markOnboardingStepComplete } from "../onboarding/progress";

function formString(form: FormData, key: string) {
  return String(form.get(key) ?? "");
}

export function PolicyDecisionPage() {
  const { user } = useAuth();
  const [searchParams] = useSearchParams();
  const [agentId, setAgentId] = useState(searchParams.get("agentId") ?? "");
  const [toolId, setToolId] = useState(searchParams.get("toolId") ?? "");
  const [requestedAction, setRequestedAction] = useState(searchParams.get("action") ?? "run_tool");
  const evaluate = useMutation({
    mutationFn: endpoints.evaluatePolicy,
    onSuccess: () => {
      if (user) markOnboardingStepComplete(user.id, "testPolicyDecision");
    }
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    evaluate.mutate({
      agent_id: agentId,
      tool_id: toolId || null,
      requested_action: requestedAction,
      risk_level: formString(form, "risk_level")
    });
  }

  return (
    <>
      <PageHeader title="Policy Decision Tester" subtitle="Evaluate policy without executing anything." />
      <div className="grid gap-4 lg:grid-cols-[0.8fr_1fr]">
        <Card>
          <p className="mb-4 text-sm leading-6 text-slate-600">
            Use this form to preview what AgentHQ would decide for an agent action. The result
            can allow the action, require human approval, or block it based on active policy rules.
          </p>
          <form onSubmit={submit} className="space-y-3">
            <Field label="Agent ID">
              <input name="agent_id" required className={inputClass} placeholder="Paste an agent UUID" value={agentId} onChange={(event) => setAgentId(event.target.value)} />
            </Field>
            <Field label="Tool ID">
              <input name="tool_id" className={inputClass} placeholder="Optional tool UUID" value={toolId} onChange={(event) => setToolId(event.target.value)} />
            </Field>
            <Field label="Requested Action">
              <input name="requested_action" required className={inputClass} placeholder="refund_review" value={requestedAction} onChange={(event) => setRequestedAction(event.target.value)} />
            </Field>
            <Field label="Risk Level">
              <select name="risk_level" className={inputClass} defaultValue="high">
                <option value="low">low</option><option value="medium">medium</option><option value="high">high</option><option value="critical">critical</option>
              </select>
            </Field>
            <PrimaryButton disabled={evaluate.isPending}>
              {evaluate.isPending ? "Evaluating..." : "Evaluate Decision"}
            </PrimaryButton>
            {evaluate.error ? <p className="text-sm text-red-600">{getErrorMessage(evaluate.error)}</p> : null}
          </form>
        </Card>
        <Card>
          <h3 className="mb-3 font-semibold">Decision</h3>
          {evaluate.isPending ? <p>Evaluating...</p> : null}
          {evaluate.data ? (
            <div className="space-y-3 text-sm">
              <div><Badge>{evaluate.data.decision}</Badge></div>
              <p className="text-slate-700">{evaluate.data.reason}</p>
              <p><span className="font-medium">Matched rule:</span> {evaluate.data.matched_rule_name ?? "None"}</p>
              <p><span className="font-medium">Requires approval:</span> {evaluate.data.requires_approval ? "yes" : "no"}</p>
              <p className="rounded-md bg-slate-50 p-3 text-slate-600">
                `allow` means the execution may proceed, `require_approval` means an approved
                approval is needed before completion, and `block` means AgentHQ should stop the action.
              </p>
            </div>
          ) : <p className="text-sm text-slate-500">Submit a request to see a decision.</p>}
        </Card>
      </div>
    </>
  );
}
