import axios from "axios";
import { type FormEvent, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { getErrorMessage } from "../api/client";
import { useAuth } from "../auth/context";
import { Field, inputClass, PrimaryButton } from "../components/Ui";
import { AuthError, AuthPageFrame } from "./LoginPage";

const INVALID_INVITE_MESSAGE =
  "This invitation is invalid, expired, revoked, or has already been accepted. Ask your organization administrator for a new invitation.";

export function AcceptInvitePage() {
  const { acceptInvite } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token") ?? "";
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!token) {
      setError(INVALID_INVITE_MESSAGE);
      return;
    }
    setError("");
    setIsSubmitting(true);
    try {
      await acceptInvite({
        token,
        full_name: fullName || null,
        password
      });
      navigate("/", { replace: true });
    } catch (requestError) {
      setError(getInviteErrorMessage(requestError));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <AuthPageFrame
      title="Accept your AgentHQ organization invite"
      subtitle="Join an organization workspace with governed access."
    >
      <p className="mb-5 text-sm leading-6 text-slate-600">
        Confirm your name and create a password to join the AgentHQ organization that invited you.
      </p>
      {!token ? <AuthError message={INVALID_INVITE_MESSAGE} /> : null}
      <form className="mt-4 space-y-4" onSubmit={submit}>
        <Field label="Full name">
          <input
            className={inputClass}
            autoComplete="name"
            placeholder="Required if not provided by your administrator"
            value={fullName}
            onChange={(event) => setFullName(event.target.value)}
          />
        </Field>
        <Field label="Password">
          <input
            className={inputClass}
            type="password"
            autoComplete="new-password"
            minLength={12}
            maxLength={128}
            placeholder="At least 12 characters"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </Field>
        {error ? <AuthError message={error} /> : null}
        <PrimaryButton disabled={isSubmitting || !token}>
          {isSubmitting ? "Accepting invitation..." : "Accept invitation"}
        </PrimaryButton>
      </form>
      <p className="mt-6 text-sm text-slate-500">
        Already joined?{" "}
        <Link className="font-medium text-slate-950 underline" to="/login">
          Sign in
        </Link>
      </p>
    </AuthPageFrame>
  );
}

function getInviteErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    if (error.response?.status === 400 || error.response?.status === 409) {
      return INVALID_INVITE_MESSAGE;
    }
  }
  return getErrorMessage(error);
}
