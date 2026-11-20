import axios from "axios";
import { type FormEvent, useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { Link, useNavigate } from "react-router-dom";

import { classifyRequestFailure, getErrorMessage } from "../api/client";
import { useAuth } from "../auth/context";
import { captureIdentityToken, clearIdentityToken } from "../utils/identityTokens";
import {
  INVITE_ATTEMPT_EVENT,
  clearInviteAttempt,
  readInviteAttempt,
  recordInviteAttempt
} from "../utils/inviteAttempt";
import { Field, inputClass, PrimaryButton, SecondaryButton } from "../components/Ui";
import { INVITE_MESSAGES } from "./acceptInviteMessages";
import { AuthError, AuthPageFrame } from "./LoginPage";


// Exact backend replies (backend/app/api/organization_invites.py).
const ALREADY_MEMBER_DETAIL = "User is already a member of this organization.";
const MULTIPLE_ORGANIZATIONS_DETAIL = "Multiple organizations are not yet supported.";

/** A definitive answer from the server about this attempt. */
type InviteFailure =
  | { kind: "invalid" | "already-member" | "multiple-organizations" }
  | { kind: "message"; message: string };

type Classified = InviteFailure | { kind: "not-sent" } | { kind: "unknown" };

function classifyInviteFailure(error: unknown): Classified {
  const outcome = classifyRequestFailure(error);
  if (outcome !== "response" || !axios.isAxiosError(error) || !error.response) {
    return outcome === "not-sent" ? { kind: "not-sent" } : { kind: "unknown" };
  }
  const { status, data } = error.response;
  const detail = (data as { detail?: unknown } | undefined)?.detail;
  // A server error can follow a committed acceptance (the reply is built after the commit).
  if (status >= 500) return { kind: "unknown" };
  if (status === 409 && detail === ALREADY_MEMBER_DETAIL) return { kind: "already-member" };
  if (status === 409 && detail === MULTIPLE_ORGANIZATIONS_DETAIL) {
    return { kind: "multiple-organizations" };
  }
  if (status === 400 || status === 409) return { kind: "invalid" };
  return { kind: "message", message: getErrorMessage(error) };
}

export function AcceptInvitePage() {
  const { acceptInvite, user, logout } = useAuth();
  const navigate = useNavigate();
  // Captured once on mount; the token is stripped from the address bar immediately.
  const [token] = useState(() => captureIdentityToken("invite"));
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [failure, setFailure] = useState<InviteFailure | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Survives remounts (a sign-in change in any tab remounts the app) and reloads of this tab.
  const subscribe = useCallback((onChange: () => void) => {
    window.addEventListener(INVITE_ATTEMPT_EVENT, onChange);
    return () => window.removeEventListener(INVITE_ATTEMPT_EVENT, onChange);
  }, []);
  const earlierAttempt = useSyncExternalStore(subscribe, () => readInviteAttempt(token));

  useEffect(() => {
    // A record left by a different invitation in this tab does not apply to this one.
    if (token && readInviteAttempt(token) === null) clearInviteAttempt();
  }, [token]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!token) {
      setFailure({ kind: "invalid" });
      return;
    }
    setFailure(null);
    setIsSubmitting(true);
    try {
      await acceptInvite({
        token,
        full_name: fullName || null,
        password
      });
      // Confirmed by the server's own reply: only now is the attempt settled.
      clearInviteAttempt();
      clearIdentityToken("invite");
      navigate("/dashboard", { replace: true });
    } catch (requestError) {
      const classified = classifyInviteFailure(requestError);
      if (classified.kind === "not-sent" || classified.kind === "unknown") {
        // The invitation token is kept: a retry is legitimate (single use is enforced server-side).
        recordInviteAttempt(token, classified.kind);
      } else {
        if (readInviteAttempt(token) === "not-sent") clearInviteAttempt();
        setFailure(classified);
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  const shown: Classified | null =
    failure ??
    (earlierAttempt === "unknown"
      ? { kind: "unknown" }
      : earlierAttempt === "not-sent"
        ? { kind: "not-sent" }
        : null);
  const message = !shown
    ? null
    : shown.kind === "message"
      ? shown.message
      : shown.kind === "invalid"
        ? earlierAttempt === "unknown"
          ? INVITE_MESSAGES.invalidAfterUnknown
          : INVITE_MESSAGES.invalid
        : shown.kind === "not-sent"
          ? INVITE_MESSAGES.notSent
          : shown.kind === "unknown"
            ? INVITE_MESSAGES.unknown
            : shown.kind === "already-member"
              ? INVITE_MESSAGES.alreadyMember
              : INVITE_MESSAGES.multipleOrganizations;
  const offerSignIn =
    shown !== null &&
    (shown.kind === "unknown" ||
      shown.kind === "already-member" ||
      (shown.kind === "invalid" && earlierAttempt === "unknown"));

  function signOutForInvitedAccount() {
    // Explicit choice only: the other account is never replaced automatically.
    logout();
    navigate("/login");
  }

  return (
    <AuthPageFrame
      title="Accept your AgentHQ organization invite"
      subtitle="Join an organization workspace with governed access."
    >
      <p className="mb-5 text-sm leading-6 text-slate-600">
        Confirm your name and create a password to join the AgentHQ organization that invited you.
      </p>
      {user ? (
        <p className="mb-4 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          You're signed in as {user.email} in this browser. Accepting this invitation signs this
          browser in as the invited account instead.
        </p>
      ) : null}
      {!token ? <AuthError message={INVITE_MESSAGES.invalid} /> : null}
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
        {message ? (
          <div role="alert" className="space-y-3">
            <AuthError message={message} />
            {offerSignIn ? (
              user ? (
                <div className="space-y-2 text-sm text-slate-600">
                  <p>
                    You're signed in as {user.email}. To continue with the invited account, sign
                    out first.
                  </p>
                  <SecondaryButton onClick={signOutForInvitedAccount}>
                    Sign out and sign in with the invited account
                  </SecondaryButton>
                </div>
              ) : (
                <Link className="inline-block font-medium text-slate-950 underline" to="/login">
                  Sign in with the invited account
                </Link>
              )
            ) : null}
          </div>
        ) : null}
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
