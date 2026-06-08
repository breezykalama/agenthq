import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, getErrorMessage } from "../api/client";
import { endpoints } from "../api/queries";
import { Badge, Card, DataState, EmptyState, PageHeader, SecondaryButton } from "../components/Ui";
import type { Approval, ListResponse } from "../types/api";

export function ApprovalsPage() {
  const queryClient = useQueryClient();
  const approvals = useQuery({ queryKey: ["approvals"], queryFn: endpoints.approvals });
  const action = useMutation({
    mutationFn: ({ id, verb }: { id: string; verb: "approve" | "reject" | "cancel" }) =>
      api.post(`/api/v1/approvals/${id}/${verb}`, {
        approver: "demo-operator",
        decision_reason: `Demo ${verb}.`
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["approvals"] })
  });

  return (
    <>
      <PageHeader title="Approvals" subtitle="Review and decide pending governance approvals." />
      <Card>
        <DataState isLoading={approvals.isLoading} error={approvals.error}>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b text-xs uppercase text-slate-500">
                <tr><th className="py-2">Action</th><th>Status</th><th>Risk</th><th>Requested By</th><th>Approver</th><th>Decide</th></tr>
              </thead>
              <tbody>
                {(approvals.data as ListResponse<Approval> | undefined)?.items.map((approval) => (
                  <tr key={approval.id} className="border-b last:border-0">
                    <td className="py-3 font-medium">{approval.requested_action}</td>
                    <td><Badge>{approval.status}</Badge></td>
                    <td>{approval.risk_level}</td>
                    <td>{approval.requested_by}</td>
                    <td>{approval.approver ?? "-"}</td>
                    <td className="flex gap-2 py-2">
                      {approval.status === "pending" ? (
                        <>
                          <SecondaryButton onClick={() => action.mutate({ id: approval.id, verb: "approve" })}>Approve</SecondaryButton>
                          <SecondaryButton onClick={() => action.mutate({ id: approval.id, verb: "reject" })}>Reject</SecondaryButton>
                          <SecondaryButton onClick={() => action.mutate({ id: approval.id, verb: "cancel" })}>Cancel</SecondaryButton>
                        </>
                      ) : "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {approvals.data?.total === 0 ? (
            <div className="mt-4">
              <EmptyState
                title="No approvals requested for this organization"
                message="Approval requests appear when this organization's policy-controlled actions need a human decision."
              />
            </div>
          ) : null}
        </DataState>
        {action.error ? <p className="mt-3 text-sm text-red-600">{getErrorMessage(action.error)}</p> : null}
      </Card>
    </>
  );
}
