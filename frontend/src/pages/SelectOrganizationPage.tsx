import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { getErrorMessage } from "../api/client";
import { useAuth } from "../auth/context";
import { formatRole } from "../utils/format";

/** Shown to accounts with several active memberships and no valid selection in this tab. */
export function SelectOrganizationPage() {
  const { memberships, selectOrganization, logout, user } = useAuth();
  const navigate = useNavigate();
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function choose(organizationId: string) {
    setPending(organizationId);
    setError(null);
    try {
      await selectOrganization(organizationId);
      navigate("/dashboard", { replace: true });
    } catch (caught) {
      setError(getErrorMessage(caught));
    } finally {
      setPending(null);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-100 px-4">
      <main className="w-full max-w-md rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="text-xl font-semibold text-slate-950">Choose an organization</h1>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          {user?.email} belongs to more than one organization. Choose the one to work in for this
          browser tab. You can switch at any time.
        </p>
        {error ? (
          <p role="alert" className="mt-4 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
            {error}
          </p>
        ) : null}
        <ul aria-label="Your organizations" className="mt-5 space-y-2">
          {memberships.map((membership) => (
            <li key={membership.organization_id}>
              <button
                type="button"
                disabled={pending !== null}
                onClick={() => void choose(membership.organization_id)}
                className="flex w-full items-center justify-between rounded-md border border-slate-200 px-4 py-3 text-left hover:border-slate-400 hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <span className="min-w-0">
                  <span className="block truncate text-sm font-semibold text-slate-900">
                    {membership.organization.name}
                  </span>
                  <span className="block text-xs text-slate-500">{formatRole(membership.role)}</span>
                </span>
                <span aria-hidden="true" className="text-sm text-slate-400">
                  {pending === membership.organization_id ? "…" : "→"}
                </span>
              </button>
            </li>
          ))}
        </ul>
        <button
          type="button"
          onClick={logout}
          className="mt-6 px-2 py-2 text-sm font-semibold text-slate-600 underline"
        >
          Sign out
        </button>
      </main>
    </div>
  );
}
