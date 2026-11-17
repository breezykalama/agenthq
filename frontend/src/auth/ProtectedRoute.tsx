import { useState } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";

import { authApi } from "../api/auth";
import { getErrorMessage } from "../api/client";
import { useAuth } from "./context";

export function ProtectedRoute() {
  const { user, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-100">
        <div className="text-sm font-medium text-slate-600">Loading AgentHQ...</div>
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  // Mirrors the backend gate: newly bootstrapped administrators must verify before any
  // organization feature loads. Legacy accounts are not flagged and pass straight through.
  if (user.email_verification_required && !user.email_verified) {
    return <EmailVerificationRequired email={user.email} />;
  }

  return <Outlet />;
}

function EmailVerificationRequired({ email }: { email: string }) {
  const { logout, refreshUser } = useAuth();
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);

  async function run(action: () => Promise<void>) {
    setIsBusy(true);
    setError(null);
    try {
      await action();
    } catch (caught) {
      setError(getErrorMessage(caught));
    } finally {
      setIsBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-100 px-4">
      <div className="w-full max-w-md rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="text-xl font-semibold text-slate-950">Verify your email to continue</h1>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          We sent a verification link to <span className="font-medium text-slate-900">{email}</span>.
          Open it to unlock your organization workspace. Links expire after 24 hours.
        </p>
        {message ? (
          <p className="mt-4 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-900">{message}</p>
        ) : null}
        {error ? (
          <p className="mt-4 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p>
        ) : null}
        <div className="mt-6 flex flex-wrap gap-3">
          <button
            className="rounded-md bg-emerald-700 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-800 disabled:opacity-60"
            disabled={isBusy}
            onClick={() =>
              void run(async () => {
                const response = await authApi.resendVerification(email);
                setMessage(response.message);
              })
            }
            type="button"
          >
            Resend verification email
          </button>
          <button
            className="rounded-md border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-800 hover:bg-slate-50 disabled:opacity-60"
            disabled={isBusy}
            onClick={() => void run(refreshUser)}
            type="button"
          >
            I have verified
          </button>
          <button
            className="px-2 py-2 text-sm font-semibold text-slate-600 underline"
            onClick={logout}
            type="button"
          >
            Sign out
          </button>
        </div>
      </div>
    </div>
  );
}
