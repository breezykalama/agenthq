import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { endpoints } from "../api/queries";
import { useAuth } from "../auth/context";
import { getEffectiveRole } from "../auth/roles";
import {
  hasCompletedOnboardingStep,
  ONBOARDING_PROGRESS_EVENT,
  onboardingDismissedKey
} from "../onboarding/progress";
import type { UserRole } from "../types/api";
import { PrimaryButton, SecondaryButton } from "./Ui";

const tourSteps = [
  {
    title: "Measure risk",
    path: "/dashboard",
    body: "Start with the organization-wide risk, compliance, tool governance, and alert posture."
  },
  {
    title: "Discover",
    path: "/mcp-servers",
    body: "Register MCP servers to discover external tools and create linked agents.",
    roles: ["admin"] as UserRole[]
  },
  {
    title: "Govern",
    path: "/tool-governance",
    body: "Review discovered tools, assign risk and permissions, and inspect schemas.",
    roles: ["admin", "operator"] as UserRole[]
  },
  {
    title: "Set policy",
    path: "/policy-rules",
    body: "Define when tools are allowed, blocked, or require human approval.",
    roles: ["admin"] as UserRole[]
  },
  {
    title: "Review compliance",
    path: "/compliance",
    body: "See control violations, governance gaps, and the organization's compliance posture.",
    roles: ["admin", "auditor"] as UserRole[]
  }
];

export function TemporaryOnboarding() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [tourOpen, setTourOpen] = useState(false);
  const [, setProgressVersion] = useState(0);
  const [dismissed, setDismissed] = useState(
    () => Boolean(user && localStorage.getItem(onboardingDismissedKey(user.id)))
  );
  const role = getEffectiveRole(user);
  const isAdmin = role === "admin";
  const agents = useQuery({
    queryKey: ["agents"],
    queryFn: endpoints.agents,
    enabled: Boolean(user && (role === "admin" || role === "agent_owner"))
  });
  const servers = useQuery({
    queryKey: ["mcp-servers"],
    queryFn: endpoints.mcpServers,
    enabled: Boolean(user && isAdmin)
  });
  const policies = useQuery({
    queryKey: ["policy-rules"],
    queryFn: endpoints.policyRules,
    enabled: Boolean(user && isAdmin)
  });
  const toolSummary = useQuery({
    queryKey: ["tool-governance-summary"],
    queryFn: endpoints.toolGovernanceSummary,
    enabled: Boolean(user && (role === "admin" || role === "operator"))
  });

  useEffect(() => {
    const refreshProgress = () => setProgressVersion((version) => version + 1);
    window.addEventListener(ONBOARDING_PROGRESS_EVENT, refreshProgress);
    return () => window.removeEventListener(ONBOARDING_PROGRESS_EVENT, refreshProgress);
  }, []);

  useEffect(() => {
    if (user) setDismissed(Boolean(localStorage.getItem(onboardingDismissedKey(user.id))));
  }, [user]);

  if (!user || !isWithinFirstSevenDays(user.created_at) || dismissed) return null;

  const steps = [
    {
      label: "Create Agent",
      detail: "Register the identity that will use governed tools.",
      complete:
        (agents.data?.total ?? 0) > 0 || hasCompletedOnboardingStep(user.id, "createAgent"),
      path: "/agents",
      roles: ["admin", "agent_owner"] as UserRole[]
    },
    {
      label: "Register MCP Server",
      detail: "Connect a source of tools for this organization.",
      complete:
        (servers.data?.total ?? 0) > 0 ||
        hasCompletedOnboardingStep(user.id, "registerMcpServer"),
      path: "/mcp-servers",
      roles: ["admin"] as UserRole[]
    },
    {
      label: "Discover Tools",
      detail: "Sync MCP tools into the governance inventory.",
      complete:
        (toolSummary.data?.total_tools ?? 0) > 0 ||
        hasCompletedOnboardingStep(user.id, "discoverTools"),
      path: "/mcp-servers",
      roles: ["admin", "operator"] as UserRole[]
    },
    {
      label: "Review Risk",
      detail: "Inspect the AI Risk Register and compliance posture.",
      complete: hasCompletedOnboardingStep(user.id, "reviewRisk"),
      path: "/risk-register",
      roles: ["admin", "auditor"] as UserRole[]
    },
    {
      label: "Create Policy",
      detail: "Define an allow, approval, or block decision.",
      complete:
        (policies.data?.total ?? 0) > 0 || hasCompletedOnboardingStep(user.id, "createPolicy"),
      path: "/policy-rules",
      roles: ["admin"] as UserRole[]
    },
    {
      label: "Configure Gateway",
      detail: "Issue governed access for an external agent.",
      complete: hasCompletedOnboardingStep(user.id, "configureGateway"),
      path: "/gateway-credentials",
      roles: ["admin"] as UserRole[]
    }
  ];
  const availableSteps = steps.filter((step) => role && step.roles.includes(role));
  const completed = availableSteps.filter((step) => step.complete).length;
  const progress = availableSteps.length ? Math.round((completed * 100) / availableSteps.length) : 100;
  const nextStep = availableSteps.find((step) => !step.complete);
  const dismiss = () => {
    localStorage.setItem(onboardingDismissedKey(user.id), "true");
    setDismissed(true);
  };

  return (
    <>
      <aside
        aria-label="Getting started with AgentHQ"
        className="fixed inset-x-3 bottom-3 z-40 max-h-[78vh] overflow-y-auto rounded-md border border-slate-300 bg-white p-4 shadow-xl sm:inset-x-auto sm:bottom-5 sm:right-5 sm:w-[400px]"
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-xs font-medium uppercase text-slate-500">Guided onboarding</div>
            <h2 className="mt-1 text-base font-semibold text-slate-950">Build your governance foundation</h2>
          </div>
          <button
            type="button"
            onClick={dismiss}
            aria-label="Dismiss onboarding"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-slate-300 text-lg leading-none text-slate-600 hover:bg-slate-50"
          >
            x
          </button>
        </div>
        <div className="mt-3">
          <div className="flex items-center justify-between text-xs font-medium text-slate-500">
            <span>{completed} of {availableSteps.length} complete</span>
            <span>{progress}%</span>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100">
            <div className="h-full rounded-full bg-emerald-500 transition-all" style={{ width: `${progress}%` }} />
          </div>
        </div>
        {!isAdmin ? (
          <p className="mt-3 rounded-md border border-blue-200 bg-blue-50 p-2 text-xs text-blue-900">
            Ask an admin to register MCP servers, create policies, and configure gateway access.
          </p>
        ) : null}
        <ol className="mt-4 space-y-2">
          {availableSteps.map((step) => (
            <li key={step.label} className="flex gap-3 rounded-md px-1 py-1.5 text-sm">
              <span
                aria-hidden="true"
                className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold ${
                  step.complete
                    ? "bg-emerald-100 text-emerald-800"
                    : "border border-slate-300 text-slate-400"
                }`}
              >
                {step.complete ? "OK" : ""}
              </span>
              <span>
                <span className={step.complete ? "font-medium text-slate-500 line-through" : "font-medium text-slate-800"}>
                  {step.label}
                </span>
                <span className="mt-0.5 block text-xs leading-5 text-slate-500">{step.detail}</span>
              </span>
            </li>
          ))}
        </ol>
        <div className="mt-4 flex flex-wrap gap-2">
          {nextStep ? (
            <PrimaryButton type="button" onClick={() => navigate(nextStep.path)}>
              {nextStep.label}
            </PrimaryButton>
          ) : null}
          <SecondaryButton onClick={() => setTourOpen(true)}>Guided Tour</SecondaryButton>
          <button type="button" onClick={dismiss} className="px-2 py-2 text-sm font-medium text-slate-500 hover:text-slate-900">
            Dismiss for now
          </button>
        </div>
      </aside>
      <GuidedTour open={tourOpen} onFinish={() => setTourOpen(false)} />
    </>
  );
}

export function GuidedTour({ open, onFinish }: { open: boolean; onFinish: () => void }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const role = getEffectiveRole(user);
  const availableSteps = tourSteps.filter(
    (tourStep) => !tourStep.roles || (role && tourStep.roles.includes(role))
  );
  const current = availableSteps[step];

  useEffect(() => {
    if (open) navigate(current.path);
  }, [current.path, navigate, open]);

  useEffect(() => {
    if (open) setStep(0);
  }, [open]);

  if (!open) return null;

  const isLast = step === availableSteps.length - 1;
  return (
    <Modal title={current.title} onClose={onFinish}>
      <div className="mb-4 text-xs font-medium uppercase text-slate-500">
        Step {step + 1} of {availableSteps.length}
      </div>
      <p className="text-sm leading-6 text-slate-600">{current.body}</p>
      <div className="mt-6 flex items-center justify-between gap-3">
        <button type="button" className="text-sm font-medium text-slate-500 hover:text-slate-900" onClick={onFinish}>
          End tour
        </button>
        <div className="flex gap-2">
          {step > 0 ? <SecondaryButton onClick={() => setStep(step - 1)}>Back</SecondaryButton> : null}
          <PrimaryButton type="button" onClick={() => (isLast ? onFinish() : setStep(step + 1))}>
            {isLast ? "Finish" : "Next"}
          </PrimaryButton>
        </div>
      </div>
    </Modal>
  );
}

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 px-4 py-8" onMouseDown={onClose}>
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="onboarding-title"
        onMouseDown={(event) => event.stopPropagation()}
        className="max-h-full w-full max-w-2xl overflow-y-auto rounded-md border border-slate-200 bg-white p-6 shadow-xl"
      >
        <div className="mb-5 flex items-start justify-between gap-4">
          <div>
            <div className="text-sm font-medium text-slate-500">AgentHQ onboarding</div>
            <h2 id="onboarding-title" className="mt-1 text-2xl font-semibold text-slate-950">{title}</h2>
          </div>
          <button type="button" onClick={onClose} aria-label="Close onboarding" className="rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50">
            Close
          </button>
        </div>
        {children}
      </section>
    </div>
  );
}

function isWithinFirstSevenDays(createdAt: string) {
  const created = new Date(createdAt);
  const now = new Date();
  const createdDay = Date.UTC(created.getUTCFullYear(), created.getUTCMonth(), created.getUTCDate());
  const currentDay = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  const ageInDays = Math.floor((currentDay - createdDay) / (24 * 60 * 60 * 1000));
  return ageInDays >= 0 && ageInDays <= 7;
}
