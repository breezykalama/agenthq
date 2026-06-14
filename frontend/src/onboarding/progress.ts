export type OnboardingProgressStep =
  | "createAgent"
  | "registerMcpServer"
  | "discoverTools"
  | "reviewRisk"
  | "createPolicy"
  | "configureGateway"
  | "reviewLinkedAgent"
  | "testPolicyDecision"
  | "reviewCompliance";

export const ONBOARDING_PROGRESS_EVENT = "agenthq:onboarding-progress";

function progressKey(userId: string, step: OnboardingProgressStep) {
  return `agenthq_onboarding_progress:${userId}:${step}`;
}

export function hasCompletedOnboardingStep(userId: string, step: OnboardingProgressStep) {
  return localStorage.getItem(progressKey(userId, step)) === "true";
}

export function markOnboardingStepComplete(userId: string, step: OnboardingProgressStep) {
  localStorage.setItem(progressKey(userId, step), "true");
  window.dispatchEvent(new Event(ONBOARDING_PROGRESS_EVENT));
}

export function onboardingDismissedKey(userId: string) {
  return `agenthq_onboarding_dismissed:${userId}`;
}
