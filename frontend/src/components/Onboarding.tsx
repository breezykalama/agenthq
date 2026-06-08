import { type ReactNode, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { endpoints } from "../api/queries";
import { useAuth } from "../auth/context";
import {
  hasCompletedOnboardingStep,
  ONBOARDING_PROGRESS_EVENT,
  onboardingDismissedKey
} from "../onboarding/progress";
import type { UserRole } from "../types/api";
import { PrimaryButton, SecondaryButton } from "./Ui";

const tourSteps = [
  {
    title: "Dashboard",
    path: "/",
    body: "Start here to understand your governance posture, pending work, and quick-start progress."
  },
  {
    title: "MCP Servers",
    path: "/mcp-servers",
    body: "Register an MCP server and sync it to create a linked agent and discover governed tools.",
    roles: ["admin"] as UserRole[]
  },
  {
    title: "Agents",
    path: "/agents",
    body: "Review registered agents, ownership, risk level, lifecycle status, and allowed tools.",
    roles: ["admin", "agent_owner"] as UserRole[]
  },
  {
    title: "Policy Rules",
    path: "/policy-rules",
    body: "Define rules that allow, block, or require approval for agent actions.",
    roles: ["admin"] as UserRole[]
  },
  {
    title: "Policy Decision Tester",
    path: "/policy-decisions",
    body: "Preview whether an agent action is allowed, blocked, or requires approval.",
    roles: ["admin", "operator"] as UserRole[]
  },
  {
    title: "Compliance",
    path: "/compliance",
    body: "Use read-only reports to review incidents, activity, and governance outcomes.",
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
  const isAdmin = user?.role === "admin";
  const servers = useQuery({
    queryKey: ["mcp-servers"],
    queryFn: endpoints.mcpServers,
    enabled: Boolean(isAdmin)
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

  const localProgress = {
    reviewLinkedAgent: hasCompletedOnboardingStep(user.id, "reviewLinkedAgent"),
    testPolicyDecision: hasCompletedOnboardingStep(user.id, "testPolicyDecision"),
    reviewCompliance: hasCompletedOnboardingStep(user.id, "reviewCompliance")
  };
  const hasMcpServer = isAdmin && (servers.data?.total ?? 0) > 0;
  const hasSyncedServer =
    isAdmin &&
    Boolean(servers.data?.items.some((server) => server.status === "connected" || server.last_sync_at));
  const steps = [
    {
      label: "Register MCP Server",
      complete: hasMcpServer,
      path: "/mcp-servers",
      roles: ["admin"] as UserRole[]
    },
    {
      label: "Sync Tools",
      complete: hasSyncedServer,
      path: "/mcp-servers",
      roles: ["admin"] as UserRole[]
    },
    {
      label: "Review Linked Agent",
      complete: localProgress.reviewLinkedAgent,
      path: "/agents",
      roles: ["admin", "agent_owner"] as UserRole[]
    },
    {
      label: "Test Policy Decision",
      complete: localProgress.testPolicyDecision,
      path: "/policy-decisions",
      roles: ["admin", "operator"] as UserRole[]
    },
    {
      label: "Review Compliance",
      complete: localProgress.reviewCompliance,
      path: "/compliance",
      roles: ["admin", "auditor"] as UserRole[]
    }
  ];
  const nextStep = steps.find((step) => !step.complete && step.roles.includes(user.role));
  const dismiss = () => {
    localStorage.setItem(onboardingDismissedKey(user.id), "true");
    setDismissed(true);
  };

  return (
    <>
      <aside
        aria-label="Getting started with AgentHQ"
        className="fixed inset-x-3 bottom-3 z-40 max-h-[75vh] overflow-y-auto rounded-md border border-slate-300 bg-white p-4 shadow-xl sm:inset-x-auto sm:bottom-5 sm:right-5 sm:w-[380px]"
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-xs font-medium uppercase text-slate-500">First 7 days</div>
            <h2 className="mt-1 text-base font-semibold text-slate-950">
              Getting started with AgentHQ
            </h2>
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
        <p className="mt-2 text-sm leading-5 text-slate-600">
          Register an MCP server, sync tools, review the linked agent, test a policy decision, and
          review compliance.
        </p>
        {!isAdmin ? (
          <p className="mt-3 rounded-md border border-blue-200 bg-blue-50 p-2 text-xs text-blue-900">
            Ask an admin to register and sync MCP servers.
          </p>
        ) : null}
        <ol className="mt-4 space-y-2">
          {steps.map((step) => (
            <li key={step.label} className="flex items-center gap-2 text-sm">
              <span
                aria-hidden="true"
                className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold ${
                  step.complete
                    ? "bg-emerald-100 text-emerald-800"
                    : "border border-slate-300 text-slate-400"
                }`}
              >
                {step.complete ? "OK" : ""}
              </span>
              <span className={step.complete ? "text-slate-500 line-through" : "text-slate-700"}>
                {step.label}
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
          <button
            type="button"
            onClick={dismiss}
            className="px-2 py-2 text-sm font-medium text-slate-500 hover:text-slate-900"
          >
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
  const availableSteps = tourSteps.filter((tourStep) => !tourStep.roles || (user && tourStep.roles.includes(user.role)));
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
        <button
          type="button"
          className="text-sm font-medium text-slate-500 hover:text-slate-900"
          onClick={onFinish}
        >
          End tour
        </button>
        <div className="flex gap-2">
          {step > 0 ? <SecondaryButton onClick={() => setStep(step - 1)}>Back</SecondaryButton> : null}
          <PrimaryButton
            type="button"
            onClick={() => {
              if (isLast) onFinish();
              else setStep(step + 1);
            }}
          >
            {isLast ? "Finish" : "Next"}
          </PrimaryButton>
        </div>
      </div>
    </Modal>
  );
}

function Modal({
  title,
  onClose,
  children
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 px-4 py-8">
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="onboarding-title"
        className="max-h-full w-full max-w-2xl overflow-y-auto rounded-md border border-slate-200 bg-white p-6 shadow-xl"
      >
        <div className="mb-5 flex items-start justify-between gap-4">
          <div>
            <div className="text-sm font-medium text-slate-500">AgentHQ onboarding</div>
            <h2 id="onboarding-title" className="mt-1 text-2xl font-semibold text-slate-950">
              {title}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close onboarding"
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50"
          >
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
