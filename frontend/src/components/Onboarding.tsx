import { type ReactNode, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

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
    body: "Register an MCP server and sync it to create a linked agent and discover governed tools."
  },
  {
    title: "Agents",
    path: "/agents",
    body: "Review registered agents, ownership, risk level, lifecycle status, and allowed tools."
  },
  {
    title: "Policy Rules",
    path: "/policy-rules",
    body: "Define rules that allow, block, or require approval for agent actions."
  },
  {
    title: "Compliance",
    path: "/compliance",
    body: "Use read-only reports to review incidents, activity, and governance outcomes."
  }
];

export function WelcomeModal({
  open,
  onStartTour,
  onSkip
}: {
  open: boolean;
  onStartTour: () => void;
  onSkip: () => void;
}) {
  if (!open) return null;

  return (
    <Modal title="Welcome to AgentHQ" onClose={onSkip}>
      <p className="text-sm leading-6 text-slate-600">
        AgentHQ is an enterprise governance console for understanding what agents exist, which
        tools they can use, and how risky actions are controlled.
      </p>
      <div className="mt-5 grid gap-3 sm:grid-cols-3">
        <Explainer
          title="Agent governance"
          body="Ownership, policies, approvals, execution tracking, incidents, and auditability."
        />
        <Explainer
          title="MCP servers"
          body="Registered tool providers that AgentHQ can sync into a linked governed agent."
        />
        <Explainer
          title="Governance"
          body="The rules and evidence that determine whether agent actions are allowed or reviewed."
        />
      </div>
      <div className="mt-6 flex flex-wrap justify-end gap-2">
        <SecondaryButton onClick={onSkip}>Skip</SecondaryButton>
        <PrimaryButton type="button" onClick={onStartTour}>
          Start Guided Tour
        </PrimaryButton>
      </div>
    </Modal>
  );
}

export function GuidedTour({ open, onFinish }: { open: boolean; onFinish: () => void }) {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const current = tourSteps[step];

  useEffect(() => {
    if (open) navigate(current.path);
  }, [current.path, navigate, open]);

  useEffect(() => {
    if (open) setStep(0);
  }, [open]);

  if (!open) return null;

  const isLast = step === tourSteps.length - 1;
  return (
    <Modal title={current.title} onClose={onFinish}>
      <div className="mb-4 text-xs font-medium uppercase text-slate-500">
        Step {step + 1} of {tourSteps.length}
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

function Explainer({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
      <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
      <p className="mt-1 text-xs leading-5 text-slate-600">{body}</p>
    </div>
  );
}
