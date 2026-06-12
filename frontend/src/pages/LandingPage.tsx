import axios from "axios";
import { FormEvent, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { getErrorMessage } from "../api/client";
import { useAuth } from "../auth/context";

type AuthMode = "login" | "bootstrap" | "invite" | "register";

const authModes = new Set<AuthMode>(["login", "bootstrap", "invite", "register"]);

const risks = [
  ["Unknown agents", "Teams lose sight of which agents exist, who owns them, and what they can reach."],
  ["Uncontrolled tools", "Agent capabilities expand without a shared view of permissions or risk."],
  ["Missing approvals", "High-impact actions can move forward without the right human decision."],
  ["Poor auditability", "Important activity becomes difficult to explain to operators, auditors, and regulators."],
  ["Cross-team gaps", "Governance varies by team, leaving inconsistent controls across the organization."],
];

const capabilities = [
  ["Agent registry", "Maintain a clear inventory of agents, owners, risk levels, and tools."],
  ["Policy enforcement", "Define consistent rules for allowed, blocked, and approval-gated actions."],
  ["Approval workflows", "Route higher-risk activity to accountable human decision-makers."],
  ["Execution tracking", "Monitor simulated agent actions, outcomes, costs, latency, and policy decisions."],
  ["Incident management", "Record, investigate, resolve, and report governance incidents."],
  ["Audit and compliance", "Review organization-scoped audit trails and compliance summaries."],
];

const workflow = [
  "Create organization",
  "Invite users",
  "Register MCP servers",
  "Sync tools",
  "Define policies",
  "Monitor executions",
  "Review audit and compliance",
];

const securityControls = [
  "Multi-tenant isolation",
  "Organization memberships",
  "Role-based access control",
  "Audit redaction",
  "Rate limiting",
  "Security event trails",
];

const invalidInviteMessage =
  "This invitation is invalid, expired, revoked, or has already been accepted. Ask your organization administrator for a new invitation.";

const fieldClass =
  "mt-2 w-full rounded-md border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-950 outline-none transition placeholder:text-slate-400 focus:border-emerald-600 focus:ring-2 focus:ring-emerald-100";

function LandingPage() {
  const { user, login, register, bootstrap, acceptInvite } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loginForm, setLoginForm] = useState({ email: "", password: "" });
  const [bootstrapForm, setBootstrapForm] = useState({
    organization_name: "",
    admin_full_name: "",
    admin_email: "",
    admin_password: "",
    bootstrap_secret: "",
  });
  const [inviteForm, setInviteForm] = useState({
    token: searchParams.get("token") ?? "",
    full_name: "",
    password: "",
  });
  const [registerForm, setRegisterForm] = useState({ full_name: "", email: "", password: "" });
  const dialogRef = useRef<HTMLDivElement>(null);

  const authParam = searchParams.get("auth");
  const mode = authParam && authModes.has(authParam as AuthMode) ? (authParam as AuthMode) : null;

  useEffect(() => {
    const token = searchParams.get("token");
    if (mode === "invite" && token) {
      setInviteForm((current) => ({ ...current, token }));
    }
  }, [mode, searchParams]);

  useEffect(() => {
    if (!mode) {
      return;
    }

    setError(null);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.setTimeout(() => dialogRef.current?.querySelector<HTMLInputElement>("input")?.focus(), 0);

    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !isSubmitting) {
        setSearchParams({});
      }
    };
    window.addEventListener("keydown", closeOnEscape);

    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [isSubmitting, mode, setSearchParams]);

  const openAuth = (nextMode: AuthMode) => {
    setError(null);
    setSearchParams(nextMode === "invite" && inviteForm.token ? { auth: nextMode, token: inviteForm.token } : { auth: nextMode });
  };

  const closeAuth = () => {
    if (!isSubmitting) {
      setSearchParams({});
    }
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!mode) {
      return;
    }

    setIsSubmitting(true);
    setError(null);
    try {
      if (mode === "login") {
        await login(loginForm);
      } else if (mode === "bootstrap") {
        await bootstrap({
          ...bootstrapForm,
          bootstrap_secret: bootstrapForm.bootstrap_secret || undefined,
        });
      } else if (mode === "invite") {
        await acceptInvite(inviteForm);
      } else {
        await register(registerForm);
      }
      navigate("/dashboard", { replace: true });
    } catch (caught) {
      setError(mode === "invite" ? getInviteErrorMessage(caught) : getErrorMessage(caught));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-white text-slate-950">
      <header className="absolute inset-x-0 top-0 z-20 border-b border-white/15">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-4 sm:px-6 lg:px-8">
          <a className="text-lg font-semibold text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4" href="/">
            AgentHQ
          </a>
          <nav aria-label="Public navigation" className="flex items-center gap-2">
            {user ? (
              <button className="landing-button landing-button-light" onClick={() => navigate("/dashboard")} type="button">
                Go to dashboard
              </button>
            ) : (
              <>
                <button className="landing-link hidden sm:inline-flex" onClick={() => openAuth("login")} type="button">
                  Sign in
                </button>
                <button className="landing-button landing-button-light" onClick={() => openAuth("bootstrap")} type="button">
                  Create organization
                </button>
              </>
            )}
          </nav>
        </div>
      </header>

      <main>
        <section className="relative flex min-h-[92vh] items-end overflow-hidden bg-slate-950 text-white">
          <div className="absolute inset-0 opacity-35" aria-hidden="true">
            <div className="absolute left-[8%] top-[18%] h-px w-[84%] bg-emerald-300" />
            <div className="absolute left-[20%] top-[18%] h-[64%] w-px bg-white/40" />
            <div className="absolute right-[18%] top-[18%] h-[64%] w-px bg-white/40" />
            <div className="absolute left-[8%] top-[52%] h-px w-[84%] bg-white/40" />
          </div>
          <div className="relative mx-auto grid w-full max-w-7xl gap-12 px-4 pb-16 pt-32 sm:px-6 sm:pb-20 lg:grid-cols-[1.15fr_0.85fr] lg:px-8">
            <div className="max-w-3xl self-end">
              <p className="mb-5 text-sm font-semibold uppercase tracking-[0.18em] text-emerald-300">Enterprise AI agent governance</p>
              <h1 className="max-w-4xl text-5xl font-semibold leading-[1.05] sm:text-6xl lg:text-7xl">
                Govern AI agents before they govern your business.
              </h1>
              <p className="mt-6 max-w-2xl text-lg leading-8 text-slate-300">
                AgentHQ is a multi-tenant governance platform that gives organizations clear control over agents, tools, policies, approvals, executions, incidents, and compliance.
              </p>
              <div className="mt-8 flex flex-wrap gap-3">
                {user ? (
                  <button className="landing-button landing-button-primary" onClick={() => navigate("/dashboard")} type="button">
                    Go to dashboard
                  </button>
                ) : (
                  <>
                    <button className="landing-button landing-button-primary" onClick={() => openAuth("login")} type="button">
                      Sign in
                    </button>
                    <button className="landing-button landing-button-outline" onClick={() => openAuth("bootstrap")} type="button">
                      Create organization
                    </button>
                    <button className="landing-button landing-button-outline" onClick={() => openAuth("invite")} type="button">
                      Accept invite
                    </button>
                    <button className="landing-link px-2" onClick={() => openAuth("register")} type="button">
                      Legacy/demo register
                    </button>
                  </>
                )}
              </div>
            </div>

            <div className="self-end border border-white/20 bg-slate-900/90 p-5 shadow-2xl shadow-black/30 backdrop-blur-sm">
              <div className="flex items-center justify-between border-b border-white/10 pb-4">
                <div>
                  <p className="text-xs uppercase tracking-[0.16em] text-slate-400">Governance overview</p>
                  <p className="mt-1 font-semibold">Organization control plane</p>
                </div>
                <span className="rounded-full bg-emerald-400/15 px-3 py-1 text-xs font-medium text-emerald-300">Operational</span>
              </div>
              <div className="grid grid-cols-2 gap-px bg-white/10">
                {[
                  ["Agents governed", "24"],
                  ["Policies active", "38"],
                  ["Approvals pending", "04"],
                  ["Incidents open", "02"],
                ].map(([label, value]) => (
                  <div className="bg-slate-900 px-4 py-5" key={label}>
                    <p className="text-2xl font-semibold">{value}</p>
                    <p className="mt-1 text-xs text-slate-400">{label}</p>
                  </div>
                ))}
              </div>
              <div className="mt-4 space-y-3">
                {[
                  ["MCP tool discovery completed", "Allowed"],
                  ["Payment operation requested", "Approval required"],
                  ["Critical external action", "Blocked"],
                ].map(([label, status], index) => (
                  <div className="flex items-center justify-between gap-4 border-b border-white/10 pb-3 text-sm last:border-0 last:pb-0" key={label}>
                    <span className="text-slate-300">{label}</span>
                    <span className={index === 0 ? "text-emerald-300" : index === 1 ? "text-amber-300" : "text-rose-300"}>{status}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section className="bg-slate-100 py-20 sm:py-24">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <p className="section-kicker">The governance gap</p>
            <h2 className="section-heading max-w-3xl">AI agents are moving from experiments to operations.</h2>
            <p className="section-copy max-w-3xl">
              As agents take on real business work, organizations need a reliable way to understand their capabilities, control risk, and explain every important decision.
            </p>
            <div className="mt-12 grid gap-px overflow-hidden border border-slate-300 bg-slate-300 md:grid-cols-2 lg:grid-cols-5">
              {risks.map(([title, description]) => (
                <article className="bg-white p-6" key={title}>
                  <h3 className="font-semibold text-slate-950">{title}</h3>
                  <p className="mt-3 text-sm leading-6 text-slate-600">{description}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section className="py-20 sm:py-24">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <div className="grid gap-10 lg:grid-cols-[0.75fr_1.25fr]">
              <div>
                <p className="section-kicker">The AgentHQ approach</p>
                <h2 className="section-heading">One governance layer for the agent lifecycle.</h2>
                <p className="section-copy">
                  AgentHQ brings governance teams, operators, owners, and auditors into one organization workspace without slowing responsible adoption.
                </p>
              </div>
              <div className="grid gap-px overflow-hidden border border-slate-200 bg-slate-200 sm:grid-cols-2">
                {capabilities.map(([title, description]) => (
                  <article className="bg-white p-6" key={title}>
                    <h3 className="font-semibold">{title}</h3>
                    <p className="mt-2 text-sm leading-6 text-slate-600">{description}</p>
                  </article>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section className="bg-slate-950 py-20 text-white sm:py-24">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <p className="section-kicker text-emerald-300">How it works</p>
            <h2 className="section-heading max-w-3xl text-white">Move from visibility to enforceable governance.</h2>
            <div className="mt-12 grid gap-px overflow-hidden border border-white/15 bg-white/15 sm:grid-cols-2 lg:grid-cols-7">
              {workflow.map((step, index) => (
                <div className="bg-slate-950 p-5" key={step}>
                  <span className="text-xs font-semibold text-emerald-300">{String(index + 1).padStart(2, "0")}</span>
                  <p className="mt-4 text-sm font-medium leading-6">{step}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="py-20 sm:py-24">
          <div className="mx-auto grid max-w-7xl gap-12 px-4 sm:px-6 lg:grid-cols-2 lg:px-8">
            <div>
              <p className="section-kicker">Security by design</p>
              <h2 className="section-heading">Controls that travel with every organization.</h2>
              <p className="section-copy">
                Each workspace is isolated, role-aware, and backed by security event trails that help teams investigate denied actions and operational risk.
              </p>
              <div className="mt-8 grid gap-3 sm:grid-cols-2">
                {securityControls.map((control) => (
                  <div className="flex items-center gap-3 border border-slate-200 px-4 py-3 text-sm font-medium" key={control}>
                    <span className="h-2 w-2 rounded-full bg-emerald-600" aria-hidden="true" />
                    {control}
                  </div>
                ))}
              </div>
            </div>
            <div className="bg-emerald-700 p-8 text-white sm:p-10">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-emerald-100">MCP integration</p>
              <h2 className="mt-4 text-3xl font-semibold">Bring external agent tools into the governance layer.</h2>
              <p className="mt-5 leading-7 text-emerald-50">
                Register MCP servers, discover tools, and govern those capabilities alongside every other agent resource. Repeated syncs preserve manually reviewed risk levels and permissions.
              </p>
              <ul className="mt-8 space-y-4 text-sm">
                {["Register MCP servers", "Discover and sync tools", "Govern discovered capabilities", "Preserve risk and permission edits"].map((item) => (
                  <li className="border-b border-emerald-500 pb-4 last:border-0" key={item}>
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </section>

        <section className="border-t border-slate-200 bg-slate-100 py-16">
          <div className="mx-auto flex max-w-7xl flex-col items-start justify-between gap-6 px-4 sm:px-6 lg:flex-row lg:items-center lg:px-8">
            <div>
              <h2 className="text-2xl font-semibold">Build accountable agent operations from day one.</h2>
              <p className="mt-2 text-slate-600">Create an organization workspace or sign in to continue governing your agents.</p>
            </div>
            <div className="flex flex-wrap gap-3">
              {user ? (
                <button className="landing-button landing-button-dark" onClick={() => navigate("/dashboard")} type="button">
                  Go to dashboard
                </button>
              ) : (
                <>
                  <button className="landing-button landing-button-dark" onClick={() => openAuth("bootstrap")} type="button">
                    Create organization
                  </button>
                  <button className="landing-button landing-button-white" onClick={() => openAuth("login")} type="button">
                    Sign in
                  </button>
                </>
              )}
            </div>
          </div>
        </section>
      </main>

      <footer className="bg-slate-950 px-4 py-8 text-sm text-slate-400 sm:px-6 lg:px-8">
        <div className="mx-auto flex max-w-7xl flex-col justify-between gap-2 sm:flex-row">
          <span>AgentHQ</span>
          <span>Organization-based AI agent governance</span>
        </div>
      </footer>

      {mode ? (
        <div
          className="fixed inset-0 z-50 flex items-end justify-center bg-slate-950/70 p-0 sm:items-center sm:p-6"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              closeAuth();
            }
          }}
        >
          <div
            aria-labelledby="auth-dialog-title"
            aria-modal="true"
            className="max-h-[92vh] w-full overflow-y-auto border border-slate-200 bg-white p-5 shadow-2xl sm:max-w-lg sm:rounded-md sm:p-7"
            ref={dialogRef}
            role="dialog"
          >
            <div className="flex items-start justify-between gap-5">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-emerald-700">AgentHQ access</p>
                <h2 className="mt-2 text-2xl font-semibold" id="auth-dialog-title">
                  {mode === "login"
                    ? "Sign in"
                    : mode === "bootstrap"
                      ? "Create your organization"
                      : mode === "invite"
                        ? "Accept organization invite"
                        : "Legacy/demo registration"}
                </h2>
                <p className="mt-2 text-sm leading-6 text-slate-600">
                  {mode === "login"
                    ? "Continue to your organization governance workspace."
                    : mode === "bootstrap"
                      ? "Create the first organization workspace and administrator account for this deployment."
                      : mode === "invite"
                        ? "Join an AgentHQ organization using the invitation shared by its administrator."
                        : "Direct registration is retained for legacy and demo access. Organization access normally happens through an invite."}
                </p>
              </div>
              <button
                aria-label="Close dialog"
                className="shrink-0 rounded-md border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-600"
                disabled={isSubmitting}
                onClick={closeAuth}
                type="button"
              >
                Close
              </button>
            </div>

            <form className="mt-6 space-y-4" onSubmit={submit}>
              {mode === "login" ? (
                <>
                  <TextField
                    autoComplete="email"
                    label="Email"
                    onChange={(value) => setLoginForm((current) => ({ ...current, email: value }))}
                    placeholder="you@company.com"
                    type="email"
                    value={loginForm.email}
                  />
                  <TextField
                    autoComplete="current-password"
                    label="Password"
                    onChange={(value) => setLoginForm((current) => ({ ...current, password: value }))}
                    placeholder="Enter your password"
                    type="password"
                    value={loginForm.password}
                  />
                </>
              ) : null}

              {mode === "bootstrap" ? (
                <>
                  <TextField label="Organization name" onChange={(value) => setBootstrapForm((current) => ({ ...current, organization_name: value }))} placeholder="Equity Bank" value={bootstrapForm.organization_name} />
                  <TextField autoComplete="name" label="Admin full name" onChange={(value) => setBootstrapForm((current) => ({ ...current, admin_full_name: value }))} placeholder="Amina Njoroge" value={bootstrapForm.admin_full_name} />
                  <TextField autoComplete="email" label="Admin email" onChange={(value) => setBootstrapForm((current) => ({ ...current, admin_email: value }))} placeholder="admin@company.com" type="email" value={bootstrapForm.admin_email} />
                  <TextField autoComplete="new-password" label="Admin password" minLength={12} onChange={(value) => setBootstrapForm((current) => ({ ...current, admin_password: value }))} placeholder="At least 12 characters" type="password" value={bootstrapForm.admin_password} />
                  <TextField label="Bootstrap secret (optional)" onChange={(value) => setBootstrapForm((current) => ({ ...current, bootstrap_secret: value }))} placeholder="Required when configured by your deployment" type="password" value={bootstrapForm.bootstrap_secret} />
                </>
              ) : null}

              {mode === "invite" ? (
                <>
                  <TextField label="Invite token" onChange={(value) => setInviteForm((current) => ({ ...current, token: value }))} placeholder="Paste your invitation token" value={inviteForm.token} />
                  <TextField autoComplete="name" label="Full name" onChange={(value) => setInviteForm((current) => ({ ...current, full_name: value }))} placeholder="Required if not provided by your administrator" required={false} value={inviteForm.full_name} />
                  <TextField autoComplete="new-password" label="Password" minLength={12} onChange={(value) => setInviteForm((current) => ({ ...current, password: value }))} placeholder="At least 12 characters" type="password" value={inviteForm.password} />
                </>
              ) : null}

              {mode === "register" ? (
                <>
                  <TextField autoComplete="name" label="Full name" onChange={(value) => setRegisterForm((current) => ({ ...current, full_name: value }))} placeholder="Your full name" value={registerForm.full_name} />
                  <TextField autoComplete="email" label="Email" onChange={(value) => setRegisterForm((current) => ({ ...current, email: value }))} placeholder="you@company.com" type="email" value={registerForm.email} />
                  <TextField autoComplete="new-password" label="Password" minLength={12} onChange={(value) => setRegisterForm((current) => ({ ...current, password: value }))} placeholder="At least 12 characters" type="password" value={registerForm.password} />
                </>
              ) : null}

              {error ? <p className="border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p> : null}

              <button
                className="w-full rounded-md bg-emerald-700 px-4 py-3 text-sm font-semibold text-white transition hover:bg-emerald-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-700 disabled:cursor-not-allowed disabled:opacity-60"
                disabled={isSubmitting}
                type="submit"
              >
                {isSubmitting
                  ? "Please wait..."
                  : mode === "login"
                    ? "Sign in"
                    : mode === "bootstrap"
                      ? "Create organization"
                      : mode === "invite"
                        ? "Accept invite"
                        : "Create demo account"}
              </button>
            </form>

            <div className="mt-5 flex flex-wrap gap-x-4 gap-y-2 border-t border-slate-200 pt-4 text-sm">
              {mode !== "login" ? <AuthSwitch label="Sign in instead" onClick={() => openAuth("login")} /> : null}
              {mode !== "bootstrap" ? <AuthSwitch label="Create organization" onClick={() => openAuth("bootstrap")} /> : null}
              {mode !== "invite" ? <AuthSwitch label="Accept invite" onClick={() => openAuth("invite")} /> : null}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function TextField({
  label,
  value,
  onChange,
  type = "text",
  placeholder,
  autoComplete,
  required = true,
  minLength,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  placeholder: string;
  autoComplete?: string;
  required?: boolean;
  minLength?: number;
}) {
  return (
    <label className="block text-sm font-medium text-slate-700">
      {label}
      <input
        autoComplete={autoComplete}
        className={fieldClass}
        minLength={minLength}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        required={label === "Bootstrap secret (optional)" ? false : required}
        type={type}
        value={value}
      />
    </label>
  );
}

function getInviteErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error) && (error.response?.status === 400 || error.response?.status === 409)) {
    return invalidInviteMessage;
  }
  return getErrorMessage(error);
}

function AuthSwitch({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button className="font-semibold text-emerald-700 hover:text-emerald-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-600" onClick={onClick} type="button">
      {label}
    </button>
  );
}

export { LandingPage };
