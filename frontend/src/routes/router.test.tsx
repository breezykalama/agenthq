import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { AUTH_TOKEN_KEY, api, gatewayApi, tokenSubject } from "../api/client";
import { AuthProvider } from "../auth/AuthContext";
import { TenantQueryBoundary } from "../auth/TenantQueryBoundary";
import { type AuthContextValue, useAuth } from "../auth/context";
import { resetOrganizationSessionForTests } from "../auth/organizationSession";
import { getEffectiveRole } from "../auth/roles";
import { FakeBackend, uuid } from "../test/fakeBackend";
import { routes } from "./router";

/**
 * The production route tree (the same RouteObjects the browser router uses) on a memory
 * router, so data-router navigation, redirects and route guards are exercised against the
 * installed react-router version, not a hand-written test tree.
 */

const A = uuid(1);
const B = uuid(2);
const PASSWORD = "Password123!";

let backend: FakeBackend;
let auth: AuthContextValue;
const originalAdapter = api.defaults.adapter;
const originalGatewayAdapter = gatewayApi.defaults.adapter;

function Capture() {
  auth = useAuth();
  return null;
}

function renderRoutes(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <AuthProvider>
      <Capture />
      <TenantQueryBoundary>
        <RouterProvider router={router} />
      </TenantQueryBoundary>
    </AuthProvider>
  );
  return router;
}

function signedIn(userId: string) {
  localStorage.setItem(AUTH_TOKEN_KEY, backend.tokenFor(userId));
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  window.history.replaceState(null, "", "/");
  resetOrganizationSessionForTests();
  backend = new FakeBackend();
  backend.addOrganization(A, "Org A");
  backend.addOrganization(B, "Org B");
  backend.addUser("u1", "dual@example.com", "admin");
  backend.addMembership("u1", A, "admin");
  backend.addMembership("u1", B, "auditor");
  backend.addUser("u3", "single@example.com");
  backend.addMembership("u3", A, "agent_owner");
  backend.invites.set("invite-b", { organizationId: B, email: "invitee@example.com", role: "operator" });
  api.defaults.adapter = backend.adapter;
  gatewayApi.defaults.adapter = backend.adapter;
});

afterEach(() => {
  api.defaults.adapter = originalAdapter;
  gatewayApi.defaults.adapter = originalGatewayAdapter;
});

describe("production routes", () => {
  it("sends a signed-out visitor to sign-in and back to the page they asked for", async () => {
    const router = renderRoutes("/agents");
    await waitFor(() => expect(router.state.location.pathname).toBe("/login"));
    await userEvent.type(screen.getByLabelText("Email"), "single@example.com");
    await userEvent.type(screen.getByLabelText("Password"), PASSWORD);
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/agents"));
    expect(auth.organizationStatus).toBe("selected");
    expect(getEffectiveRole(auth.user)).toBe("agent_owner");
  });

  it("gates routes on the selected membership's role", async () => {
    signedIn("u1");
    sessionStorage.setItem("agenthq.organization.tab.u1", B); // auditor in B
    const router = renderRoutes("/audit-logs");
    await waitFor(() => expect(auth.organizationStatus).toBe("selected"));
    expect(router.state.location.pathname).toBe("/audit-logs");

    await act(() => router.navigate("/organization"));
    await waitFor(() => expect(router.state.location.pathname).toBe("/"));
    await act(() => router.navigate("/policy-rules"));
    await waitFor(() => expect(router.state.location.pathname).toBe("/"));
  });

  it("switches organization from the real layout and returns to the dashboard", async () => {
    signedIn("u1");
    sessionStorage.setItem("agenthq.organization.tab.u1", A); // admin in A
    const router = renderRoutes("/organization");
    const switcher = await screen.findByRole("combobox", { name: "Organization" });
    expect(router.state.location.pathname).toBe("/organization");

    await userEvent.selectOptions(switcher, B);
    await waitFor(() => expect(auth.selectedOrganizationId).toBe(B));
    await waitFor(() => expect(router.state.location.pathname).toBe("/dashboard"));
    expect(getEffectiveRole(auth.user)).toBe("auditor");
  });

  it("accepts an invitation through the real page and lands in the joined organization", async () => {
    window.history.replaceState(null, "", "/accept-invite#token=invite-b");
    const router = renderRoutes("/accept-invite");
    expect(window.location.hash).toBe(""); // the token is stripped from the address bar
    await userEvent.type(screen.getByLabelText("Password"), PASSWORD);
    await userEvent.click(screen.getByRole("button", { name: "Accept invitation" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/dashboard"));
    expect(auth.selectedOrganizationId).toBe(B);
    expect(getEffectiveRole(auth.user)).toBe("operator");
    expect(tokenSubject(localStorage.getItem(AUTH_TOKEN_KEY))).toBe("user-invitee@example.com");
  });
});
