import axios from "axios";
import { type FormEvent, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";

import { getErrorMessage } from "../api/client";
import { useAuth } from "../auth/context";
import { Field, inputClass, PrimaryButton } from "../components/Ui";
import { AuthError, AuthPageFrame } from "./LoginPage";

const ORGANIZATION_EXISTS_MESSAGE =
  "An organization already exists. Please log in or ask your administrator for access.";

export function BootstrapPage() {
  const { user, bootstrap } = useAuth();
  const navigate = useNavigate();
  const [organizationName, setOrganizationName] = useState("");
  const [adminFullName, setAdminFullName] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [adminPassword, setAdminPassword] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (user) return <Navigate to="/" replace />;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setIsSubmitting(true);
    try {
      await bootstrap({
        organization_name: organizationName,
        admin_full_name: adminFullName,
        admin_email: adminEmail,
        admin_password: adminPassword
      });
      navigate("/", { replace: true });
    } catch (requestError) {
      setError(
        axios.isAxiosError(requestError) && requestError.response?.status === 409
          ? ORGANIZATION_EXISTS_MESSAGE
          : getErrorMessage(requestError)
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <AuthPageFrame
      title="Create your AgentHQ organization workspace"
      subtitle="Set up the first governed workspace for this deployment."
    >
      <p className="mb-5 text-sm text-slate-600">
        You will become the first administrator for this organization.
      </p>
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
        {error ? <AuthError message={error} /> : null}
        <PrimaryButton disabled={isSubmitting}>
          {isSubmitting ? "Creating workspace..." : "Create organization workspace"}
        </PrimaryButton>
      </form>
      <p className="mt-6 text-sm text-slate-500">
        Already set up?{" "}
        <Link className="font-medium text-slate-950 underline" to="/login">
          Sign in
        </Link>
      </p>
    </AuthPageFrame>
  );
}
