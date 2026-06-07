import { type FormEvent, useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";

import { getErrorMessage } from "../api/client";
import { useAuth } from "../auth/context";
import { Field, inputClass, PrimaryButton } from "../components/Ui";

export function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
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
      await login({ email, password });
      const destination = (location.state as { from?: string } | null)?.from ?? "/";
      navigate(destination, { replace: true });
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <AuthPageFrame title="Sign in to AgentHQ" subtitle="Access the enterprise governance console.">
      <form className="space-y-4" onSubmit={submit}>
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
            autoComplete="current-password"
            placeholder="Enter your password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </Field>
        {error ? <AuthError message={error} /> : null}
        <PrimaryButton disabled={isSubmitting}>
          {isSubmitting ? "Signing in..." : "Sign in"}
        </PrimaryButton>
      </form>
      <p className="mt-6 text-sm text-slate-500">
        Need an account?{" "}
        <Link className="font-medium text-slate-950 underline" to="/register">
          Register
        </Link>
      </p>
    </AuthPageFrame>
  );
}

export function AuthPageFrame({
  title,
  subtitle,
  children
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-100 px-4 py-10">
      <section className="w-full max-w-md rounded-md border border-slate-200 bg-white p-6 shadow-sm">
        <div className="mb-6 border-b border-slate-200 pb-5">
          <div className="text-lg font-semibold text-slate-950">AgentHQ</div>
          <h1 className="mt-4 text-2xl font-semibold text-slate-950">{title}</h1>
          <p className="mt-1 text-sm text-slate-500">{subtitle}</p>
        </div>
        {children}
      </section>
    </main>
  );
}

export function AuthError({ message }: { message: string }) {
  return <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">{message}</div>;
}
