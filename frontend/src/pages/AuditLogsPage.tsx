import { useQuery } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { type AuditLogFilters, endpoints } from "../api/queries";
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
import type { AuditLog } from "../types/api";

const PAGE_LIMIT = 50;

const emptyFilters: AuditLogFilters = {
  action: undefined,
  entity_type: undefined,
  actor: undefined
};

export function AuditLogsPage() {
  const [filters, setFilters] = useState<AuditLogFilters>(emptyFilters);
  const [offset, setOffset] = useState(0);
  const auditLogs = useQuery({
    queryKey: ["audit-logs", filters, offset],
    queryFn: () => endpoints.auditLogs({ ...filters, limit: PAGE_LIMIT, offset })
  });

  function applyFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setFilters({
      action: optionalFormValue(form, "action"),
      entity_type: optionalFormValue(form, "entity_type"),
      actor: optionalFormValue(form, "actor")
    });
    setOffset(0);
  }

  function clearFilters() {
    setFilters(emptyFilters);
    setOffset(0);
    const form = document.getElementById("audit-log-filters");
    if (form instanceof HTMLFormElement) form.reset();
  }

  const total = auditLogs.data?.total ?? 0;
  const pageStart = total === 0 ? 0 : offset + 1;
  const pageEnd = Math.min(offset + PAGE_LIMIT, total);

  return (
    <>
      <PageHeader title="Audit Logs" subtitle="Audit activity for this organization." />
      <Card className="mb-4">
        <form
          id="audit-log-filters"
          onSubmit={applyFilters}
          className="grid gap-3 md:grid-cols-3 xl:grid-cols-[1fr_1fr_1fr_auto]"
        >
          <Field label="Action">
            <input
              name="action"
              className={inputClass}
              placeholder="agent.created"
              defaultValue={filters.action}
            />
          </Field>
          <Field label="Entity type">
            <input
              name="entity_type"
              className={inputClass}
              placeholder="agent"
              defaultValue={filters.entity_type}
            />
          </Field>
          <Field label="Actor">
            <input
              name="actor"
              className={inputClass}
              placeholder="system or user email"
              defaultValue={filters.actor}
            />
          </Field>
          <div className="flex items-end gap-2">
            <PrimaryButton>Apply filters</PrimaryButton>
            <SecondaryButton onClick={clearFilters}>Clear filters</SecondaryButton>
          </div>
        </form>
      </Card>
      <Card>
        <DataState
          isLoading={auditLogs.isLoading}
          error={auditLogs.error}
          onRetry={() => void auditLogs.refetch()}
        >
          {auditLogs.data?.items.length ? (
            <>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[940px] text-left text-sm">
                  <thead className="border-b border-slate-200 text-xs uppercase text-slate-500">
                    <tr>
                      <th className="py-2 pr-4">Created</th>
                      <th className="pr-4">Actor</th>
                      <th className="pr-4">Action</th>
                      <th className="pr-4">Entity type</th>
                      <th className="pr-4">Entity ID</th>
                      <th>Details</th>
                    </tr>
                  </thead>
                  <tbody>
                    {auditLogs.data.items.map((auditLog) => (
                      <AuditLogRow key={auditLog.id} auditLog={auditLog} />
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="mt-4 flex flex-col gap-3 border-t border-slate-200 pt-4 sm:flex-row sm:items-center sm:justify-between">
                <p className="text-sm text-slate-500">
                  Showing {pageStart}-{pageEnd} of {total}
                </p>
                <div className="flex gap-2">
                  <SecondaryButton
                    disabled={offset === 0 || auditLogs.isFetching}
                    onClick={() => setOffset(Math.max(0, offset - PAGE_LIMIT))}
                  >
                    Previous
                  </SecondaryButton>
                  <SecondaryButton
                    disabled={offset + PAGE_LIMIT >= total || auditLogs.isFetching}
                    onClick={() => setOffset(offset + PAGE_LIMIT)}
                  >
                    Next
                  </SecondaryButton>
                </div>
              </div>
            </>
          ) : (
            <EmptyState
              title="No audit activity"
              message="No audit activity has been recorded for this organization yet."
            />
          )}
        </DataState>
      </Card>
    </>
  );
}

function AuditLogRow({ auditLog }: { auditLog: AuditLog }) {
  const hasSnapshots = auditLog.before !== null || auditLog.after !== null;

  return (
    <tr className="border-b border-slate-100 align-top last:border-0">
      <td className="whitespace-nowrap py-3 pr-4 text-slate-600">
        {new Date(auditLog.created_at).toLocaleString()}
      </td>
      <td className="pr-4 font-medium text-slate-900">{auditLog.actor}</td>
      <td className="pr-4">
        <Badge>{auditLog.action}</Badge>
      </td>
      <td className="pr-4 text-slate-700">{auditLog.entity_type}</td>
      <td className="max-w-52 break-all pr-4 font-mono text-xs text-slate-600">
        {auditLog.entity_id}
      </td>
      <td className="min-w-72 py-2">
        {hasSnapshots ? (
          <details className="rounded-md border border-slate-200 bg-slate-50">
            <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-slate-700">
              View snapshots
            </summary>
            <div className="grid gap-3 border-t border-slate-200 p-3">
              <Snapshot label="Before" value={auditLog.before} />
              <Snapshot label="After" value={auditLog.after} />
            </div>
          </details>
        ) : (
          <span className="text-slate-400">No snapshots</span>
        )}
      </td>
    </tr>
  );
}

function Snapshot({
  label,
  value
}: {
  label: string;
  value: Record<string, unknown> | null;
}) {
  return (
    <div>
      <div className="mb-1 text-xs font-medium uppercase text-slate-500">{label}</div>
      <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-all rounded-md bg-slate-950 p-3 text-xs leading-5 text-slate-100">
        {value === null ? "null" : JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}

function optionalFormValue(form: FormData, key: string): string | undefined {
  const value = String(form.get(key) ?? "").trim();
  return value || undefined;
}
