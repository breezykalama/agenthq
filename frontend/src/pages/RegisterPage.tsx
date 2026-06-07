import { type FormEvent, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";

import { getErrorMessage } from "../api/client";
import { useAuth } from "../auth/context";
import { Field, inputClass, PrimaryButton } from "../components/Ui";
import { AuthError, AuthPageFrame } from "./LoginPage";

export function RegisterPage() {
  const { user, register } = useAuth();
  const navigate = useNavigate();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (user) return <Navigate to="/" replace />;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setIsSubmitting(true);
    try {
      await register({ full_name: fullName, email, password });
      navigate("/", { replace: true });
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <AuthPageFrame title="Create your account" subtitle="Register an identity for governed access.">
      <div className="mb-5 rounded-md border border-blue-200 bg-blue-50 p-3 text-sm text-blue-950">
        The first registered user becomes admin. Later users default to agent owner.
      </div>
      <form className="space-y-4" onSubmit={submit}>
        <Field label="Full name">
          <input
            className={inputClass}
            autoComplete="name"
            placeholder="Alex Morgan"
            value={fullName}
            onChange={(event) => setFullName(event.target.value)}
            required
          />
        </Field>
        <Field label="Email">
          <input
            className={inputClass}
            type="email"
            autoComplete="email"
            placeholder="you@company.com"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />
        </Field>
        <Field label="Password">
          <input
            className={inputClass}
            type="password"
            autoComplete="new-password"
            minLength={12}
            placeholder="At least 12 characters"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </Field>
        {error ? <AuthError message={error} /> : null}
        <PrimaryButton disabled={isSubmitting}>
          {isSubmitting ? "Creating account..." : "Create account"}
        </PrimaryButton>
      </form>
      <p className="mt-6 text-sm text-slate-500">
        Already registered?{" "}
        <Link className="font-medium text-slate-950 underline" to="/login">
          Sign in
        </Link>
      </p>
    </AuthPageFrame>
  );
}
