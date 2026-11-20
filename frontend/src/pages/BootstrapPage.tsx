import axios from "axios";
import { type FormEvent, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";

import { getErrorMessage } from "../api/client";
import { useAuth } from "../auth/context";
import { Field, inputClass, PrimaryButton } from "../components/Ui";
import { AuthError, AuthPageFrame } from "./LoginPage";

const ORGANIZATION_EXISTS_MESSAGE =
  "An organization already exists. Please log in or ask your administrator for access.";
// One message for any refused setup authorization: it never says whether a bootstrap secret was
// missing or wrong, and never repeats what was entered.
const SETUP_AUTHORIZATION_FAILED_MESSAGE =
  "Initial setup authorization failed. Check your setup credentials or contact the installation administrator.";

export function BootstrapPage() {
  const { user, bootstrap } = useAuth();
  const navigate = useNavigate();
  const [organizationName, setOrganizationName] = useState("");
  const [adminFullName, setAdminFullName] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [adminPassword, setAdminPassword] = useState("");
  // Held only in this form's state (gone when the page unmounts) and sent only as the
  // X-Bootstrap-Secret header by authApi.bootstrap; never in the URL, storage or a message.
  const [bootstrapSecret, setBootstrapSecret] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (user && !success) return <Navigate to="/dashboard" replace />;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setIsSubmitting(true);
    try {
      await bootstrap({
        organization_name: organizationName,
        admin_full_name: adminFullName,
        admin_email: adminEmail,
        admin_password: adminPassword,
        bootstrap_secret: bootstrapSecret || undefined
      });
      setBootstrapSecret("");
      setAdminPassword("");
      setSuccess(true);
    } catch (requestError) {
      const status = axios.isAxiosError(requestError) ? requestError.response?.status : undefined;
      setError(
        status === 409
          ? ORGANIZATION_EXISTS_MESSAGE
          : status === 403
            ? SETUP_AUTHORIZATION_FAILED_MESSAGE
            : getErrorMessage(requestError)
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <AuthPageFrame
      title="Initial AgentHQ setup"
      subtitle="Available only before the first organization is created."
    >
      <p className="mb-5 text-sm text-slate-600">
        Use this once, when installing AgentHQ, to create the first organization and become its
        administrator. It is not customer signup: to join an existing organization, ask its
        administrator for an invitation.
      </p>
      {success ? (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 p-4">
          <p className="text-sm font-medium text-emerald-950">
            Organization created. Check your email to verify your account.
          </p>
          <PrimaryButton onClick={() => navigate("/dashboard")}>
            Go to dashboard
          </PrimaryButton>
        </div>
      ) : (
      <form className="space-y-4" onSubmit={submit}>
        <Field label="Organization name">
          <input
            className={inputClass}
            autoComplete="organization"
            placeholder="Equity Bank"
            value={organizationName}
            onChange={(event) => setOrganizationName(event.target.value)}
            required
          />
        </Field>
        <Field label="Admin full name">
          <input
            className={inputClass}
            autoComplete="name"
            placeholder="Alex Morgan"
            value={adminFullName}
            onChange={(event) => setAdminFullName(event.target.value)}
            required
          />
        </Field>
        <Field label="Admin email">
          <input
            className={inputClass}
            type="email"
            autoComplete="email"
            placeholder="admin@company.com"
            value={adminEmail}
            onChange={(event) => setAdminEmail(event.target.value)}
            required
          />
        </Field>
        <Field label="Admin password">
          <input
            className={inputClass}
            type="password"
            autoComplete="new-password"
            minLength={12}
            placeholder="At least 12 characters"
            value={adminPassword}
            onChange={(event) => setAdminPassword(event.target.value)}
            required
          />
        </Field>
        <Field label="Bootstrap secret (if required)">
          <input
            className={inputClass}
            type="password"
            autoComplete="off"
            placeholder="Required when your deployment configures one"
            value={bootstrapSecret}
            onChange={(event) => setBootstrapSecret(event.target.value)}
          />
        </Field>
        {error ? <AuthError message={error} /> : null}
        <PrimaryButton disabled={isSubmitting}>
          {isSubmitting ? "Completing setup..." : "Complete initial setup"}
        </PrimaryButton>
      </form>
      )}
      <p className="mt-6 text-sm text-slate-500">
        Already set up?{" "}
        <Link className="font-medium text-slate-950 underline" to="/login">
          Sign in
        </Link>
      </p>
    </AuthPageFrame>
  );
}
