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
  SecondaryButton,
  inputClass
} from "../components/Ui";
import type { Incident, ListResponse } from "../types/api";

function formString(form: FormData, key: string) {
  return String(form.get(key) ?? "");
}

export function IncidentsPage() {
  const queryClient = useQueryClient();
  const incidents = useQuery({ queryKey: ["incidents"], queryFn: endpoints.incidents });
  const createIncident = useMutation({
    mutationFn: (payload: unknown) => api.post("/api/v1/incidents", payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["incidents"] })
  });
  const decide = useMutation({
    mutationFn: ({ id, verb }: { id: string; verb: "resolve" | "dismiss" }) =>
      api.post(`/api/v1/incidents/${id}/${verb}`, { resolution_notes: `Demo ${verb}.` }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["incidents"] })
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const executionId = formString(form, "execution_id");
    createIncident.mutate({
      agent_id: formString(form, "agent_id"),
      execution_id: executionId || null,
      title: formString(form, "title"),
      description: formString(form, "description"),
      severity: formString(form, "severity"),
      reported_by: formString(form, "reported_by") || "system"
    });
  }

  return (
    <>
      <PageHeader title="Incidents" subtitle="Record and close operational governance incidents." />
      <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <Card>
          <DataState isLoading={incidents.isLoading} error={incidents.error}>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="border-b text-xs uppercase text-slate-500">
                  <tr><th className="py-2">Title</th><th>Status</th><th>Severity</th><th>Assigned</th><th>Actions</th></tr>
                </thead>
                <tbody>
                  {(incidents.data as ListResponse<Incident> | undefined)?.items.map((incident) => (
                    <tr key={incident.id} className="border-b last:border-0">
                      <td className="py-3 font-medium">{incident.title}</td>
                      <td><Badge>{incident.status}</Badge></td>
                      <td>{incident.severity}</td>
                      <td>{incident.assigned_to ?? "-"}</td>
                      <td className="flex gap-2 py-2">
                        {incident.status === "open" || incident.status === "investigating" ? (
                          <>
                            <SecondaryButton onClick={() => decide.mutate({ id: incident.id, verb: "resolve" })}>Resolve</SecondaryButton>
                            <SecondaryButton onClick={() => decide.mutate({ id: incident.id, verb: "dismiss" })}>Dismiss</SecondaryButton>
                          </>
                        ) : "-"}
                      </td>
                    </tr>
                  ))}
                </tbody>
            </table>
          </div>
          {incidents.data?.total === 0 ? (
            <div className="mt-4">
              <EmptyState title="No incidents reported" message="Track governance issues and policy violations." />
            </div>
          ) : null}
        </DataState>
        </Card>
        <Card>
          <h3 className="mb-3 font-semibold">Create Incident</h3>
          <form onSubmit={submit} className="space-y-3">
            <Field label="Agent ID"><input name="agent_id" required className={inputClass} placeholder="Paste an agent UUID" /></Field>
            <Field label="Execution ID"><input name="execution_id" className={inputClass} placeholder="Optional related execution UUID" /></Field>
            <Field label="Title"><input name="title" required className={inputClass} placeholder="Blocked payment action" /></Field>
            <Field label="Description"><textarea name="description" required className={inputClass} placeholder="What happened and why it matters" /></Field>
            <Field label="Severity">
              <select name="severity" className={inputClass} defaultValue="high">
                <option value="low">low</option><option value="medium">medium</option><option value="high">high</option><option value="critical">critical</option>
              </select>
            </Field>
            <Field label="Reported By"><input name="reported_by" defaultValue="demo-operator" className={inputClass} /></Field>
            <PrimaryButton>Create Incident</PrimaryButton>
            {createIncident.error ? <p className="text-sm text-red-600">{getErrorMessage(createIncident.error)}</p> : null}
            {decide.error ? <p className="text-sm text-red-600">{getErrorMessage(decide.error)}</p> : null}
          </form>
        </Card>
      </div>
    </>
  );
}
