import { Link, Navigate } from "react-router-dom";

import { useAuth } from "../auth/context";
import { AuthPageFrame } from "./LoginPage";

/**
 * Kept at /register so old links still land somewhere useful. Legacy self-registration is
 * retired from the interface: this page never submits anything and reveals nothing about any
 * account. Access to an organization comes from an invitation by its administrator.
 */
export function RegisterPage() {
  const { user } = useAuth();

  if (user) return <Navigate to="/dashboard" replace />;

  return (
    <AuthPageFrame
      title="Registration is not available"
      subtitle="AgentHQ accounts are created by invitation."
    >
      <div className="mb-5 rounded-md border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
        <p className="font-medium text-slate-950">Public registration is not currently available.</p>
        <p className="mt-1">
          To join an organization, ask its administrator for an invitation. The invitation email
          contains a link to set up your account.
        </p>
      </div>
      <p className="text-sm text-slate-500">
        Already have an account?{" "}
        <Link className="font-medium text-slate-950 underline" to="/login">
          Sign in
        </Link>
      </p>
      <p className="mt-3 text-sm text-slate-500">
        Have an invitation?{" "}
        <Link className="font-medium text-slate-950 underline" to="/accept-invite">
          Accept invitation
        </Link>
      </p>
    </AuthPageFrame>
  );
}
