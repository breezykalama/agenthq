import { type QueryClient, useQuery, useQueryClient } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  AUTH_TOKEN_KEY,
  ORGANIZATION_HEADER,
  StaleOrganizationContextError,
  api,
  gatewayApi,
  tokenSubject
} from "../api/client";
import { OrganizationSwitcher } from "../components/OrganizationSwitcher";
import { FakeBackend, uuid } from "../test/fakeBackend";
import type { User } from "../types/api";
import { AuthProvider } from "./AuthContext";
import { OrganizationAdminRoute } from "./OrganizationAdminRoute";
import { ProtectedRoute } from "./ProtectedRoute";
import { RoleRoute } from "./RoleRoute";
import { TenantQueryBoundary } from "./TenantQueryBoundary";
import { type AuthContextValue, useAuth } from "./context";
import {
  getOrganizationContext,
  resetOrganizationSessionForTests,
  setOrganizationContext
} from "./organizationSession";
import { chooseOrganizationCandidate, getEffectiveRole, getSelectedMembership } from "./roles";

const A = uuid(1);
const B = uuid(2);
const C = uuid(3); // dual's membership is inactive
const D = uuid(4); // deleted organization
const PASSWORD = "Password123!";

let backend: FakeBackend;
let auth: AuthContextValue;
let clients: QueryClient[];
const originalAdapter = api.defaults.adapter;
const originalGatewayAdapter = gatewayApi.defaults.adapter;

function Capture() {
  auth = useAuth();
  return null;
}

function TenantProbe() {
  const { user } = useAuth();
  const client = useQueryClient();
  if (!clients.includes(client)) clients.push(client);
  const agents = useQuery({
    queryKey: ["agents"],
    queryFn: () =>
      api
        .get<{ items: { id: string; name: string }[] }>("/api/v1/agents")
        .then((response) => response.data)
  });
  return (
    <div>
      <p data-testid="org">{getSelectedMembership(user)?.organization.name ?? "-"}</p>
      <p data-testid="role">{getEffectiveRole(user) ?? "-"}</p>
      <OrganizationSwitcher />
      <ul data-testid="agents">
        {agents.data?.items.map((agent) => <li key={agent.id}>{agent.name}</li>)}
      </ul>
      <button type="button" onClick={() => void agents.refetch()}>
        reload
      </button>
    </div>
  );
}

function renderApp(path = "/dashboard") {
  return render(
    <AuthProvider>
      <Capture />
      <TenantQueryBoundary>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/" element={<p>home page</p>} />
            <Route path="/login" element={<p>login page</p>} />
            <Route element={<ProtectedRoute />}>
              <Route path="/dashboard" element={<TenantProbe />} />
              <Route element={<OrganizationAdminRoute />}>
                <Route path="/organization" element={<p>admin area</p>} />
              </Route>
              <Route element={<RoleRoute allowedRoles={["admin", "auditor"]} />}>
                <Route path="/audit-logs" element={<p>audit area</p>} />
              </Route>
            </Route>
          </Routes>
        </MemoryRouter>
      </TenantQueryBoundary>
    </AuthProvider>
  );
}

function signedIn(userId: string) {
  localStorage.setItem(AUTH_TOKEN_KEY, backend.tokenFor(userId));
}

function last<T>(items: T[]): T | undefined {
  return items[items.length - 1];
}

function agentRequests() {
  return backend.requestsTo("/api/v1/agents");
}

async function selectedAs(name: string) {
  await waitFor(() => expect(screen.getByTestId("org").textContent).toBe(name));
}

async function showsAgent(name: string) {
  await waitFor(() => expect(screen.getByTestId("agents").textContent).toBe(name));
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  resetOrganizationSessionForTests();
  clients = [];
  backend = new FakeBackend();
  backend.addOrganization(A, "Org A");
  backend.addOrganization(B, "Org B");
  backend.addOrganization(C, "Org C");
  backend.addOrganization(D, "Org D", true);
  backend.addUser("u1", "dual@example.com", "admin"); // global role admin on purpose
  backend.addMembership("u1", A, "admin");
  backend.addMembership("u1", B, "auditor");
  backend.addMembership("u1", C, "admin", false);
  backend.addMembership("u1", D, "admin");
  backend.addUser("u2", "other@example.com");
  backend.addMembership("u2", A, "operator");
  backend.addMembership("u2", B, "admin");
  backend.addUser("u3", "single@example.com");
  backend.addMembership("u3", A, "agent_owner");
  backend.addUser("u4", "none@example.com", "admin");
  backend.invites.set("invite-b", { organizationId: B, email: "invitee@example.com", role: "operator" });
  backend.invites.set("invite-b-for-u3", { organizationId: B, email: "single@example.com", role: "auditor" });
  api.defaults.adapter = backend.adapter;
  gatewayApi.defaults.adapter = backend.adapter;
});

afterEach(() => {
  api.defaults.adapter = originalAdapter;
  gatewayApi.defaults.adapter = originalGatewayAdapter;
});

describe("membership states", () => {
  it("shows the no-organization page and never calls tenant routes without a membership", async () => {
    signedIn("u4");
    renderApp();
    expect(await screen.findByText("No organization yet")).toBeTruthy();
    expect(agentRequests()).toHaveLength(0);
    // Global users.role is admin, but no organization role is derived from it.
    expect(auth.user?.role).toBe("admin");
    expect(getEffectiveRole(auth.user)).toBeUndefined();
  });

  it("auto-selects the only membership and sends its header", async () => {
    signedIn("u3");
    renderApp();
    await selectedAs("Org A");
    await showsAgent("Agent of Org A");
    expect(screen.getByTestId("role").textContent).toBe("agent_owner");
    expect(agentRequests().every((request) => request.organization === A)).toBe(true);
    expect(screen.queryByLabelText("Organization")).toBeNull(); // nothing to switch to
  });

  it("asks a multi-membership account to choose and only lists active memberships", async () => {
    signedIn("u1");
    renderApp();
    expect(await screen.findByText("Choose an organization")).toBeTruthy();
    const list = screen.getByRole("list", { name: "Your organizations" });
    expect(list.textContent).toContain("Org A");
    expect(list.textContent).toContain("Org B");
    expect(list.textContent).not.toContain("Org C");
    expect(list.textContent).not.toContain("Org D");
    expect(agentRequests()).toHaveLength(0);

    await userEvent.click(screen.getByRole("button", { name: /Org B/ }));
    await selectedAs("Org B");
    await showsAgent("Agent of Org B");
    expect(screen.getByTestId("role").textContent).toBe("auditor");
    expect(agentRequests().map((request) => request.organization)).toEqual([B]);
  });
});

describe("switching", () => {
  it("switches through the layout switcher with an isolated cache and remount", async () => {
    signedIn("u1");
    sessionStorage.setItem("agenthq.organization.tab.u1", A);
    renderApp();
    await showsAgent("Agent of Org A");
    const firstClient = clients[0];

    await userEvent.selectOptions(screen.getByLabelText("Organization"), B);
    await selectedAs("Org B");
    await showsAgent("Agent of Org B");
    expect(clients.length).toBeGreaterThan(1);
    expect(last(clients)).not.toBe(firstClient);
    expect(firstClient.getQueryCache().getAll()).toHaveLength(0);
    expect(last(agentRequests())?.organization).toBe(B);
    expect(sessionStorage.getItem("agenthq.organization.tab.u1")).toBe(B);
  });

  it("never shows a late response from the previous organization", async () => {
    signedIn("u1");
    sessionStorage.setItem("agenthq.organization.tab.u1", A);
    const late = backend.hold((request) => request.url === "/api/v1/agents" && request.organization === A, {
      ignoreAbort: true
    });
    renderApp();
    await selectedAs("Org A");
    await waitFor(() => expect(agentRequests()).toHaveLength(1));

    await act(() => auth.selectOrganization(B));
    await showsAgent("Agent of Org B");
    late.release();
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.getByTestId("agents").textContent).toBe("Agent of Org B");
    expect(screen.queryByText("Agent of Org A")).toBeNull();
    for (const client of clients.slice(0, -1)) {
      expect(client.getQueryCache().getAll()).toHaveLength(0);
    }
  });

  it("settles on the last choice when switching rapidly", async () => {
    signedIn("u1");
    sessionStorage.setItem("agenthq.organization.tab.u1", A);
    renderApp();
    await showsAgent("Agent of Org A");
    const slowConfirmation = backend.hold(
      (request) => request.url === "/api/v1/auth/me" && request.organization === A,
      { ignoreAbort: true }
    );

    await act(async () => {
      void auth.selectOrganization(B).catch(() => undefined);
      void auth.selectOrganization(A).catch(() => undefined);
      void auth.selectOrganization(B).catch(() => undefined);
      await new Promise((resolve) => setTimeout(resolve, 10));
    });
    slowConfirmation.release();
    await selectedAs("Org B");
    await showsAgent("Agent of Org B");
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.getByTestId("org").textContent).toBe("Org B");
    expect(auth.selectedOrganizationId).toBe(B);
    expect(getOrganizationContext().organizationId).toBe(B);
    expect(last(agentRequests())?.organization).toBe(B);
  });
});

describe("API client", () => {
  it("rejects a response that arrives after the context changed", async () => {
    signedIn("u1");
    setOrganizationContext("u1", A);
    const late = backend.hold((request) => request.url === "/api/v1/agents", { ignoreAbort: true });
    const pending = api.get("/api/v1/agents");
    await waitFor(() => expect(agentRequests()).toHaveLength(1));
    setOrganizationContext("u1", B);
    late.release();
    await expect(pending).rejects.toBeInstanceOf(StaleOrganizationContextError);
  });

  it("aborts requests still in flight when the context changes", async () => {
    signedIn("u1");
    setOrganizationContext("u1", A);
    backend.hold((request) => request.url === "/api/v1/agents");
    const pending = api.get("/api/v1/agents");
    await waitFor(() => expect(agentRequests()).toHaveLength(1));
    setOrganizationContext("u1", B);
    await expect(pending).rejects.toBeInstanceOf(StaleOrganizationContextError);
  });

  it("ignores caller-supplied organization headers", async () => {
    signedIn("u1");
    setOrganizationContext("u1", A);
    await api.get("/api/v1/agents", { headers: { [ORGANIZATION_HEADER]: B } });
    expect(last(agentRequests())?.organization).toBe(A);
  });

  it("drops a caller-supplied organization header when nothing is selected", async () => {
    signedIn("u1");
    setOrganizationContext("u1", null);
    await api
      .get("/api/v1/agents", { headers: { [ORGANIZATION_HEADER]: B } })
      .catch(() => undefined);
    expect(last(agentRequests())?.organization).toBeNull();
  });

  it("rejects a late response even when the caller supplied its own abort signal", async () => {
    signedIn("u1");
    setOrganizationContext("u1", A);
    const late = backend.hold((request) => request.url === "/api/v1/agents", { ignoreAbort: true });
    const pending = api.get("/api/v1/agents", { signal: new AbortController().signal });
    await waitFor(() => expect(agentRequests()).toHaveLength(1));
    setOrganizationContext("u1", B);
    late.release();
    await expect(pending).rejects.toBeInstanceOf(StaleOrganizationContextError);
  });

  it("does not raise organization recovery for an error from a previous context", async () => {
    signedIn("u1");
    setOrganizationContext("u1", A);
    let recoveries = 0;
    const onRecovery = () => (recoveries += 1);
    window.addEventListener("agenthq:organization-unavailable", onRecovery);
    backend.forcedError = { status: 403, detail: "Organization access denied." };
    const late = backend.hold((request) => request.url === "/api/v1/agents", { ignoreAbort: true });
    const pending = api.get("/api/v1/agents", { signal: new AbortController().signal });
    await waitFor(() => expect(agentRequests()).toHaveLength(1));
    setOrganizationContext("u1", B);
    late.release();
    await expect(pending).rejects.toBeInstanceOf(StaleOrganizationContextError);
    window.removeEventListener("agenthq:organization-unavailable", onRecovery);
    expect(recoveries).toBe(0);
  });

  it("never sends the organization header on the gateway client", async () => {
    signedIn("u1");
    setOrganizationContext("u1", A);
    await gatewayApi.get("/api/v1/mcp-gateway/server/tools", {
      headers: { Authorization: "Bearer gateway-token" }
    });
    const gateway = backend.requestsTo("/api/v1/mcp-gateway/server/tools")[0];
    expect(gateway.organization).toBeNull();
    expect(gateway.authorization).toBe("Bearer gateway-token");
  });

  it("does not send a tab's selection with another user's token", async () => {
    signedIn("u1");
    sessionStorage.setItem("agenthq.organization.tab.u1", A);
    renderApp();
    await showsAgent("Agent of Org A");
    // Another tab signed in as u2 (the token is shared between tabs).
    localStorage.setItem(AUTH_TOKEN_KEY, backend.tokenFor("u2"));
    await userEvent.click(screen.getByRole("button", { name: "reload" }));

    await waitFor(() => expect(auth.user?.id).toBe("u2"));
    expect(await screen.findByText("Choose an organization")).toBeTruthy();
    // No request ever paired u2's token with u1's organization selection (the mismatched
    // request is cancelled before it is sent, and the identity is re-resolved).
    const withOtherToken = backend.requests.filter(
      (request) => tokenSubject(request.authorization?.replace("Bearer ", "") ?? null) === "u2"
    );
    expect(withOtherToken.length).toBeGreaterThan(0); // u2's /auth/me discovery
    expect(withOtherToken.every((request) => request.organization !== A)).toBe(true);
  });
});

describe("persistence", () => {
  it("keeps selections per user and never lets another user inherit them", async () => {
    renderApp();
    await act(() => auth.login({ email: "dual@example.com", password: PASSWORD }));
    expect(await screen.findByText("Choose an organization")).toBeTruthy();
    await act(() => auth.selectOrganization(B));
    expect(auth.selectedOrganizationId).toBe(B);
    act(() => auth.logout());

    await act(() => auth.login({ email: "other@example.com", password: PASSWORD }));
    expect(auth.organizationStatus).toBe("selection-required");
    expect(auth.selectedOrganizationId).toBeNull();
    act(() => auth.logout());

    await act(() => auth.login({ email: "dual@example.com", password: PASSWORD }));
    expect(auth.organizationStatus).toBe("selected");
    expect(auth.selectedOrganizationId).toBe(B); // u1's own preference, re-confirmed
  });

  it("keeps each tab's selection independent of other tabs", async () => {
    signedIn("u1");
    renderApp();
    expect(await screen.findByText("Choose an organization")).toBeTruthy();
    await act(() => auth.selectOrganization(A));
    await showsAgent("Agent of Org A");

    // Another tab of the same user picks B: only the shared preference changes.
    localStorage.setItem("agenthq.organization.preference.u1", B);
    window.dispatchEvent(new StorageEvent("storage", { key: "agenthq.organization.preference.u1" }));
    await userEvent.click(screen.getByRole("button", { name: "reload" }));
    await waitFor(() => expect(last(agentRequests())?.organization).toBe(A));
    expect(auth.selectedOrganizationId).toBe(A);
  });

  it("never selects a candidate the backend refuses to confirm", async () => {
    signedIn("u1");
    sessionStorage.setItem("agenthq.organization.tab.u1", A);
    // The membership is deactivated between discovery and confirmation.
    const confirmation = backend.hold(
      (request) => request.url === "/api/v1/auth/me" && request.organization === A
    );
    renderApp();
    await waitFor(() =>
      expect(backend.requestsTo("/api/v1/auth/me").some((r) => r.organization === A)).toBe(true)
    );
    backend.setMembershipActive("u1", A, false);
    confirmation.release();
    await selectedAs("Org B"); // the only remaining membership
    expect(agentRequests().some((request) => request.organization === A)).toBe(false);
    expect(sessionStorage.getItem("agenthq.organization.tab.u1")).toBe(B);
  });

  it("starts a new tab from the user's preference, validated by the backend", async () => {
    signedIn("u1");
    localStorage.setItem("agenthq.organization.preference.u1", B);
    renderApp();
    await selectedAs("Org B");
    expect(backend.requestsTo("/api/v1/auth/me").some((request) => request.organization === B)).toBe(true);
  });

  it.each([
    ["an inactive membership", C],
    ["a deleted organization", D],
    ["an unknown organization", uuid(99)]
  ])("ignores a stored selection of %s", async (_label, stored) => {
    signedIn("u1");
    sessionStorage.setItem("agenthq.organization.tab.u1", stored);
    localStorage.setItem("agenthq.organization.preference.u1", stored);
    renderApp();
    expect(await screen.findByText("Choose an organization")).toBeTruthy();
    expect(agentRequests()).toHaveLength(0);
  });
});

describe("recovery from organization errors", () => {
  it("falls back when the selected membership is deactivated (403)", async () => {
    signedIn("u1");
    sessionStorage.setItem("agenthq.organization.tab.u1", A);
    renderApp();
    await showsAgent("Agent of Org A");
    backend.setMembershipActive("u1", A, false);

    await userEvent.click(screen.getByRole("button", { name: "reload" }));
    // B is now the only active membership, so it is selected; A is forgotten.
    await selectedAs("Org B");
    await showsAgent("Agent of Org B");
    expect(sessionStorage.getItem("agenthq.organization.tab.u1")).toBe(B);
  });

  it.each([
    [409, "Organization selection required."],
    [400, "Invalid organization header."],
    [403, "Organization access denied."]
  ])("returns to the picker after a %s organization error", async (status, detail) => {
    signedIn("u1");
    sessionStorage.setItem("agenthq.organization.tab.u1", A);
    renderApp();
    await showsAgent("Agent of Org A");
    backend.forcedError = { status, detail };

    await userEvent.click(screen.getByRole("button", { name: "reload" }));
    expect(await screen.findByText("Choose an organization")).toBeTruthy();
    expect(sessionStorage.getItem("agenthq.organization.tab.u1")).toBeNull();
    backend.forcedError = null;
  });

  it("does not react to errors from a context that is no longer current", async () => {
    signedIn("u1");
    sessionStorage.setItem("agenthq.organization.tab.u1", A);
    const late = backend.hold((request) => request.url === "/api/v1/agents" && request.organization === A, {
      ignoreAbort: true
    });
    renderApp();
    await waitFor(() => expect(agentRequests()).toHaveLength(1));
    await act(() => auth.selectOrganization(B));
    await showsAgent("Agent of Org B");
    backend.forcedError = { status: 403, detail: "Organization access denied." };
    late.release();
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(auth.selectedOrganizationId).toBe(B);
    expect(auth.organizationStatus).toBe("selected");
    backend.forcedError = null;
  });
});

describe("roles", () => {
  it("derives navigation from the selected membership in each organization", async () => {
    signedIn("u1");
    sessionStorage.setItem("agenthq.organization.tab.u1", A);
    renderApp("/organization");
    expect(await screen.findByText("admin area")).toBeTruthy();
    await act(() => auth.selectOrganization(B)); // auditor in B: the admin page is refused
    expect(await screen.findByText("home page")).toBeTruthy();
    expect(screen.queryByText("admin area")).toBeNull();
    expect(getEffectiveRole(auth.user)).toBe("auditor");
  });

  it("allows auditor routes and blocks admin routes for an auditor", async () => {
    signedIn("u1");
    sessionStorage.setItem("agenthq.organization.tab.u1", B);
    const { unmount } = renderApp("/organization");
    expect(await screen.findByText("home page")).toBeTruthy();
    unmount();
    renderApp("/audit-logs");
    expect(await screen.findByText("audit area")).toBeTruthy();
  });

  it("never falls back to users.role", () => {
    const base: User = {
      id: "u",
      email: "u@example.com",
      full_name: "U",
      role: "admin",
      is_active: true,
      email_verified: true,
      email_verified_at: null,
      created_at: "",
      updated_at: "",
      organization_membership: null,
      organization_memberships: [],
      selected_organization_id: null
    };
    expect(getEffectiveRole(base)).toBeUndefined();
    const membership = {
      id: "m",
      organization_id: A,
      user_id: "u",
      role: "auditor" as const,
      is_active: true,
      created_at: "",
      updated_at: "",
      organization: { id: A, name: "Org A", slug: "org-a", created_at: "", updated_at: "" }
    };
    expect(getEffectiveRole({ ...base, organization_membership: membership, selected_organization_id: A })).toBe("auditor");
    // A singular membership that is not the backend's selection lends no role.
    expect(getEffectiveRole({ ...base, organization_membership: membership, selected_organization_id: B })).toBeUndefined();
    expect(getEffectiveRole({ ...base, organization_membership: membership, selected_organization_id: null })).toBeUndefined();
    // Older backend without selection fields (v0.8.1 rollback): its single membership is used.
    const legacy = { ...base, organization_membership: membership } as User;
    delete legacy.selected_organization_id;
    delete legacy.organization_memberships;
    expect(getEffectiveRole(legacy)).toBe("auditor");
  });

  it("only chooses candidates among the backend's memberships", () => {
    const memberships = [A, B].map((id) => ({ organization_id: id }) as never);
    expect(chooseOrganizationCandidate(memberships, { tab: uuid(9), preference: null })).toBeNull();
    expect(chooseOrganizationCandidate(memberships, { tab: B, preference: A })).toBe(B);
    expect(chooseOrganizationCandidate(memberships, { tab: null, preference: A }, uuid(9))).toBe(A);
    expect(chooseOrganizationCandidate([memberships[0]], { tab: null, preference: null })).toBe(A);
  });
});

describe("sign-in, sign-out and invitations", () => {
  it("clears tenant caches on logout and on signing in as someone else", async () => {
    signedIn("u3");
    renderApp();
    await showsAgent("Agent of Org A");
    const tenantClient = clients[0];
    expect(tenantClient.getQueryCache().getAll().length).toBeGreaterThan(0);

    act(() => auth.logout());
    expect(await screen.findByText("login page")).toBeTruthy();
    expect(tenantClient.getQueryCache().getAll()).toHaveLength(0);
    expect(getOrganizationContext().organizationId).toBeNull();
    expect(localStorage.getItem(AUTH_TOKEN_KEY)).toBeNull();

    await act(() => auth.login({ email: "other@example.com", password: PASSWORD }));
    expect(auth.organizationStatus).toBe("selection-required");
  });

  it("selects the organization from a successful invitation acceptance", async () => {
    renderApp();
    await act(() =>
      auth.acceptInvite({ token: "invite-b", password: PASSWORD, full_name: "Invitee" })
    );
    expect(auth.selectedOrganizationId).toBe(B);
    expect(getEffectiveRole(auth.user)).toBe("operator");
  });

  it("replaces a signed-in session and its caches when an invitation is accepted", async () => {
    signedIn("u2");
    sessionStorage.setItem("agenthq.organization.tab.u2", B);
    renderApp();
    await showsAgent("Agent of Org B");
    const previous = clients[0];
    await act(() =>
      auth.acceptInvite({ token: "invite-b", password: PASSWORD, full_name: "Invitee" })
    );
    expect(auth.user?.email).toBe("invitee@example.com");
    expect(getEffectiveRole(auth.user)).toBe("operator"); // not u2's admin role in B
    expect(previous.getQueryCache().getAll()).toHaveLength(0);
  });

  it("keeps the phase 0 guard: a second membership is refused and nothing changes", async () => {
    signedIn("u3");
    renderApp();
    await showsAgent("Agent of Org A");
    await expect(
      act(() => auth.acceptInvite({ token: "invite-b-for-u3", password: PASSWORD }))
    ).rejects.toBeTruthy();
    expect(auth.selectedOrganizationId).toBe(A);
    expect(screen.getByTestId("org").textContent).toBe("Org A");
  });
});

describe("cross-tab identity lifecycle", () => {
  // jsdom has one window, so "the other tab" is modelled the way a browser presents it to this
  // tab: it writes the shared localStorage token, and a storage event arrives later as a task.
  function otherTabWritesToken(token: string | null) {
    if (token === null) localStorage.removeItem(AUTH_TOKEN_KEY);
    else localStorage.setItem(AUTH_TOKEN_KEY, token);
  }
  function storageEventArrives(key: string | null = AUTH_TOKEN_KEY) {
    act(() => {
      window.dispatchEvent(new StorageEvent("storage", { key }));
    });
  }
  async function flush() {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }

  it.each([
    ["a different user", "u2"],
    ["the same user again", "u1"]
  ])(
    "a stale 401 for the old token never signs out %s who signed in in another tab",
    async (_label, nextUser) => {
      signedIn("u1");
      sessionStorage.setItem("agenthq.organization.tab.u1", A);
      renderApp();
      await showsAgent("Agent of Org A");

      // Tab B (this tab) has a request in flight with u1's token, which the server rejects...
      const inFlight = backend.hold((request) => request.url === "/api/v1/agents");
      await userEvent.click(screen.getByRole("button", { name: "reload" }));
      await waitFor(() => expect(agentRequests()).toHaveLength(2));
      backend.revokedTokens.add(localStorage.getItem(AUTH_TOKEN_KEY)!); // u1's token expired
      // ...while tab A signs in; the 401 arrives here before the storage event does.
      const fresh = backend.tokenFor(nextUser);
      otherTabWritesToken(fresh);
      inFlight.release();
      await flush();

      expect(localStorage.getItem(AUTH_TOKEN_KEY)).toBe(fresh); // tab A stays signed in
      storageEventArrives();
      await waitFor(() => expect(auth.user?.id).toBe(nextUser));
      expect(auth.organizationStatus).not.toBe("anonymous");
      expect(screen.queryByText("login page")).toBeNull();
    }
  );

  it("still signs out on a 401 for the token this tab is actually using", async () => {
    signedIn("u1");
    sessionStorage.setItem("agenthq.organization.tab.u1", A);
    renderApp();
    await showsAgent("Agent of Org A");
    backend.revokedTokens.add(localStorage.getItem(AUTH_TOKEN_KEY)!);
    await userEvent.click(screen.getByRole("button", { name: "reload" }));
    expect(await screen.findByText("login page")).toBeTruthy();
    expect(localStorage.getItem(AUTH_TOKEN_KEY)).toBeNull();
    expect(auth.organizationStatus).toBe("anonymous");
  });

  it("never sends a request issued for one user with another user's token", async () => {
    signedIn("u1");
    setOrganizationContext("u1", A);
    otherTabWritesToken(backend.tokenFor("u2"));
    // A mutation with its own signal, and a request while no organization is selected.
    const write = api.post("/api/v1/agents", {}, { signal: new AbortController().signal });
    await expect(write).rejects.toBeInstanceOf(StaleOrganizationContextError);
    setOrganizationContext("u1", null);
    await expect(api.get("/api/v1/agents")).rejects.toBeInstanceOf(StaleOrganizationContextError);
    expect(agentRequests()).toHaveLength(0);
  });

  it("drops a success for a token another tab replaced and re-resolves the identity", async () => {
    signedIn("u1");
    setOrganizationContext("u1", A);
    let identityChanges = 0;
    const onChange = () => (identityChanges += 1);
    window.addEventListener("agenthq:identity-changed", onChange);
    const inFlight = backend.hold((request) => request.url === "/api/v1/agents");
    const pending = api.get("/api/v1/agents");
    await waitFor(() => expect(agentRequests()).toHaveLength(1));
    otherTabWritesToken(backend.tokenFor("u2")); // no storage event yet
    inFlight.release();
    await expect(pending).rejects.toBeInstanceOf(StaleOrganizationContextError);
    await waitFor(() => expect(identityChanges).toBeGreaterThan(0));
    window.removeEventListener("agenthq:identity-changed", onChange);
  });

  it("stamps a request with the context it was issued in, not the one it is sent in", async () => {
    signedIn("u1");
    setOrganizationContext("u1", A);
    const issuedForA = api.get("/api/v1/agents");
    setOrganizationContext("u1", B); // same tick, before axios runs its interceptors
    await expect(issuedForA).rejects.toBeInstanceOf(StaleOrganizationContextError);
    expect(agentRequests().some((request) => request.organization === B)).toBe(false);
  });

  it.each([
    ["removes the token", AUTH_TOKEN_KEY],
    ["clears all storage", null]
  ])(
    "signs this tab out without side effects when another tab %s mid-request",
    async (_label, key) => {
      signedIn("u1");
      sessionStorage.setItem("agenthq.organization.tab.u1", A);
      renderApp();
      await showsAgent("Agent of Org A");
      const inFlight = backend.hold((request) => request.url === "/api/v1/agents", {
        ignoreAbort: true
      });
      await userEvent.click(screen.getByRole("button", { name: "reload" }));
      await waitFor(() => expect(agentRequests()).toHaveLength(2));

      otherTabWritesToken(null);
      storageEventArrives(key);
      expect(auth.organizationStatus).toBe("anonymous");
      expect(getOrganizationContext().userId).toBeNull();
      const sent = backend.requests.length;
      inFlight.release();
      await flush();
      expect(await screen.findByText("login page")).toBeTruthy();
      expect(backend.requests.length).toBe(sent); // no retry, no recovery, no reload
      expect(clients.every((client) => client.getQueryCache().getAll().length === 0)).toBe(true);
    }
  );

  it("gives a user signed in by another tab nothing of the previous user", async () => {
    signedIn("u1");
    sessionStorage.setItem("agenthq.organization.tab.u1", A);
    renderApp();
    await showsAgent("Agent of Org A");
    expect(getEffectiveRole(auth.user)).toBe("admin");
    const late = backend.hold((request) => request.url === "/api/v1/agents", { ignoreAbort: true });
    await userEvent.click(screen.getByRole("button", { name: "reload" }));
    await waitFor(() => expect(agentRequests()).toHaveLength(2));
    const previousClients = [...clients];

    otherTabWritesToken(backend.tokenFor("u2"));
    storageEventArrives();
    expect(await screen.findByText("Choose an organization")).toBeTruthy();
    late.release(); // u1's late success in org A
    await flush();

    expect(auth.user?.id).toBe("u2");
    expect(auth.selectedOrganizationId).toBeNull(); // u1's tab selection is not inherited
    expect(getEffectiveRole(auth.user)).toBeUndefined();
    expect(auth.memberships.map((m) => m.role).sort()).toEqual(["admin", "operator"]);
    for (const client of previousClients) expect(client.getQueryCache().getAll()).toHaveLength(0);

    await act(() => auth.selectOrganization(A));
    await showsAgent("Agent of Org A");
    expect(getEffectiveRole(auth.user)).toBe("operator"); // u2's own role in A, not u1's admin
    const forU2 = last(agentRequests());
    expect(tokenSubject(forU2?.authorization?.replace("Bearer ", "") ?? null)).toBe("u2");
    expect(sessionStorage.getItem("agenthq.organization.tab.u1")).toBe(A); // u1's own key only
  });

  it("settles on the last of two selections made in the same tick, with matching roles", async () => {
    signedIn("u1");
    sessionStorage.setItem("agenthq.organization.tab.u1", A);
    renderApp();
    await showsAgent("Agent of Org A");
    // Both loads start before either request reaches axios; with real network latency every
    // request is dispatched before any response arrives, and responses arrive in issue order.
    backend.latencyMs = 5;
    await act(async () => {
      const first = auth.selectOrganization(B);
      const second = auth.selectOrganization(A);
      await Promise.allSettled([first, second]);
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(auth.selectedOrganizationId).toBe(A);
    expect(getSelectedMembership(auth.user)?.organization_id).toBe(A);
    expect(getEffectiveRole(auth.user)).toBe("admin");
    await showsAgent("Agent of Org A");
    expect(agentRequests().every((request) => request.organization === A)).toBe(true);
  });
});
