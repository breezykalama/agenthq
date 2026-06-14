import type { ReactNode } from "react";

import { getErrorMessage } from "../api/client";

export function PageHeader({
  title,
  subtitle,
  actions
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-5 flex min-w-0 flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <h2 className="break-words text-2xl font-semibold tracking-tight text-slate-950">{title}</h2>
        {subtitle ? <p className="mt-1 max-w-3xl break-words text-sm leading-6 text-slate-500">{subtitle}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap gap-2">{actions}</div> : null}
    </div>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <section className={`min-w-0 rounded-md border border-slate-200 bg-white p-4 shadow-sm ${className}`}>
      {children}
    </section>
  );
}

export function MetricCard({ label, value }: { label: string; value: ReactNode }) {
  return (
    <Card className="min-h-24">
      <div className="text-sm text-slate-500">{label}</div>
      <div className="mt-2 break-words text-2xl font-semibold tracking-tight text-slate-950">{value}</div>
    </Card>
  );
}

export function Badge({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex rounded-md bg-slate-100 px-2 py-1 text-xs font-medium text-slate-700">
      {children}
    </span>
  );
}

export function DataState({
  isLoading,
  error,
  onRetry,
  children
}: {
  isLoading: boolean;
  error: unknown;
  onRetry?: () => void;
  children: ReactNode;
}) {
  if (isLoading) {
    return (
      <Card>
        <div className="h-4 w-32 animate-pulse rounded bg-slate-200" />
        <div className="mt-4 space-y-2">
          <div className="h-3 animate-pulse rounded bg-slate-100" />
          <div className="h-3 w-3/4 animate-pulse rounded bg-slate-100" />
        </div>
      </Card>
    );
  }
  if (error) {
    const message = getErrorMessage(error);
    const permissionDenied = message === "You do not have permission to access this resource.";
    return (
      <Card className="border-red-200 bg-red-50 text-red-800">
        <div className="font-medium">
          {permissionDenied ? "You do not have permission." : "Unable to load this section."}
        </div>
        <div className="mt-1 text-sm">{message}</div>
        {onRetry ? (
          <button
            type="button"
            onClick={onRetry}
            className="mt-3 rounded-md border border-red-300 px-3 py-2 text-sm font-medium hover:bg-red-100"
          >
            Retry
          </button>
        ) : null}
      </Card>
    );
  }
  return <>{children}</>;
}

export function EmptyState({
  title,
  message,
  actions
}: {
  title: string;
  message: string;
  actions?: ReactNode;
}) {
  return (
    <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 px-4 py-8 text-center sm:px-8">
      <div className="font-medium text-slate-900">{title}</div>
      <p className="mx-auto mt-1 max-w-md text-sm text-slate-500">{message}</p>
      {actions ? <div className="mt-4 flex flex-wrap justify-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </span>
      {children}
    </label>
  );
}

export const inputClass =
  "min-h-9 min-w-0 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none placeholder:text-slate-400 focus:border-slate-900 focus:ring-2 focus:ring-slate-200";

export function PrimaryButton({
  children,
  type = "submit",
  disabled = false,
  onClick
}: {
  children: ReactNode;
  type?: "submit" | "button";
  disabled?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      type={type}
      disabled={disabled}
      onClick={onClick}
      className="min-h-9 rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900 disabled:cursor-not-allowed disabled:bg-slate-400"
    >
      {children}
    </button>
  );
}

export function SecondaryButton({
  children,
  onClick,
  disabled = false
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="min-h-9 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
    >
      {children}
    </button>
  );
}
