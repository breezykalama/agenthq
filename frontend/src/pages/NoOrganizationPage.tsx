import { useState } from "react";

import { getErrorMessage } from "../api/client";
import { useAuth } from "../auth/context";

/** Shown to signed-in accounts without any active organization membership. */
export function NoOrganizationPage() {
  const { user, refreshUser, logout } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);

  async function checkAgain() {
    setIsBusy(true);
    setError(null);
    try {
      await refreshUser();
    } catch (caught) {
      setError(getErrorMessage(caught));
    } finally {
      setIsBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-100 px-4">
      <main className="w-full max-w-md rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="text-xl font-semibold text-slate-950">No organization yet</h1>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          {user?.email} is not an active member of any organization. Ask an administrator to send
          you an invitation, then open the link in the email. If your membership was recently
          removed, contact your organization administrator.
        </p>
        {error ? (
          <p role="alert" className="mt-4 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
            {error}
          </p>
        ) : null}
        <div className="mt-6 flex flex-wrap gap-3">
          <button
            type="button"
            disabled={isBusy}
            onClick={() => void checkAgain()}
            className="rounded-md border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-800 hover:bg-slate-50 disabled:opacity-60"
          >
            Check again
          </button>
          <button
            type="button"
            onClick={logout}
            className="px-2 py-2 text-sm font-semibold text-slate-600 underline"
          >
            Sign out
          </button>
        </div>
      </main>
    </div>
  );
}
