import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  AUTH_TOKEN_KEY,
  StaleOrganizationContextError,
  api,
  classifyRequestFailure,
  gatewayApi,
  tokenSubject
} from "../api/client";
import { AuthProvider } from "../auth/AuthContext";
import { TenantQueryBoundary } from "../auth/TenantQueryBoundary";
import { type AuthContextValue, useAuth } from "../auth/context";
import { resetOrganizationSessionForTests, setOrganizationContext } from "../auth/organizationSession";
import { getEffectiveRole } from "../auth/roles";
import { routes } from "../routes/router";
import { FakeBackend, uuid } from "../test/fakeBackend";
import { inviteFingerprint, sha256Hex } from "../utils/inviteAttempt";
import { INVITE_MESSAGES } from "./acceptInviteMessages";

/**
 * Invitation acceptance whose outcome is unknown (lost reply, transport failure, identity
 * change in another tab), on the production route tree and the real AcceptInvitePage.
 * jsdom has one window: "another tab" writes the shared localStorage token, and its storage
 * event arrives later as a task, as a browser delivers it.
 */

const A = uuid(1);
const B = uuid(2);
const PASSWORD = "Password123!";
const ACCEPT = "/api/v1/organization-invites/accept";
const ATTEMPT_KEY = "agenthq.invite-attempt";
const INVITE_TOKEN_KEY = "agenthq.identity-token.invite";

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

/** Open the emailed link (token in the fragment), as the browser would. */
function openInvite(token: string) {
  window.history.replaceState(null, "", `/accept-invite#token=${token}`);
  return renderRoutes("/accept-invite");
}

async function submitInvite(options: { password?: string; fullName?: string } = {}) {
  if (options.fullName) await userEvent.type(screen.getByLabelText("Full name"), options.fullName);
  const password = screen.getByLabelText("Password");
  await userEvent.clear(password);
  await userEvent.type(password, options.password ?? PASSWORD);
  await userEvent.click(screen.getByRole("button", { name: "Accept invitation" }));
}

function otherTabSignsIn(userId: string, { storageEvent = true } = {}) {
  const token = backend.tokenFor(userId);
  localStorage.setItem(AUTH_TOKEN_KEY, token);
  if (storageEvent) {
    act(() => {
      window.dispatchEvent(new StorageEvent("storage", { key: AUTH_TOKEN_KEY }));
    });
  }
  return token;
}

function signedIn(userId: string, organizationId?: string) {
  localStorage.setItem(AUTH_TOKEN_KEY, backend.tokenFor(userId));
  if (organizationId) sessionStorage.setItem(`agenthq.organization.tab.${userId}`, organizationId);
}

async function signInAs(email: string) {
  await userEvent.type(screen.getByLabelText("Email"), email);
  await userEvent.type(screen.getByLabelText("Password"), PASSWORD);
  await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

function membershipsOf(userId: string) {
  return backend.memberships.filter((m) => m.userId === userId && m.active).map((m) => m.organizationId);
}

const INVITEE = "user-invitee@example.com";

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
  backend.addUser("u2", "other@example.com");
  backend.addMembership("u2", A, "operator");
  backend.addMembership("u2", B, "admin");
  backend.addUser("u3", "single@example.com");
  backend.addMembership("u3", A, "agent_owner");
  backend.addUser("u4", "none@example.com", "admin");
  backend.invites.set("invite-b", { organizationId: B, email: "invitee@example.com", role: "operator" });
  backend.invites.set("invite-a-for-u3", { organizationId: A, email: "single@example.com", role: "auditor" });
  backend.invites.set("invite-b-for-u3", { organizationId: B, email: "single@example.com", role: "auditor" });
  backend.invites.set("invite-b-for-u4", { organizationId: B, email: "none@example.com", role: "auditor" });
  backend.invites.set("invite-unnamed", {
    organizationId: B,
    email: "newperson@example.com",
    role: "auditor",
    fullName: null
  });
  api.defaults.adapter = backend.adapter;
  gatewayApi.defaults.adapter = backend.adapter;
});

afterEach(() => {
  api.defaults.adapter = originalAdapter;
  gatewayApi.defaults.adapter = originalGatewayAdapter;
});

describe("request outcome classification", () => {
  it("only calls a request not sent when the client provably refused it before dispatch", async () => {
    localStorage.setItem(AUTH_TOKEN_KEY, backend.tokenFor("u1"));
    setOrganizationContext("u1", A);
    localStorage.setItem(AUTH_TOKEN_KEY, backend.tokenFor("u2")); // another tab, no event yet
    const refused = await api.post(ACCEPT, {}).catch((error: unknown) => error);
    expect(classifyRequestFailure(refused)).toBe("not-sent");
    expect(backend.requestsTo(ACCEPT)).toHaveLength(0);

    expect(classifyRequestFailure(new StaleOrganizationContextError())).toBe("unknown");
    backend.networkFailure = { match: () => true, when: "before-commit" };
    setOrganizationContext("u2", null);
    const transport = await api.get("/api/v1/agents").catch((error: unknown) => error);
    expect(classifyRequestFailure(transport)).toBe("unknown");
    const answered = await api.get("/api/v1/agents").catch((error: unknown) => error);
    expect(classifyRequestFailure(answered)).toBe("response"); // 409 selection required
  });
});

describe("invitation attempt fingerprint", () => {
  const hex = (buffer: ArrayBuffer) =>
    Array.from(new Uint8Array(buffer), (byte) => byte.toString(16).padStart(2, "0")).join("");

  it("is a real SHA-256: published vectors and Web Crypto at every padding boundary", async () => {
    expect(sha256Hex("")).toBe("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
    expect(sha256Hex("abc")).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    expect(sha256Hex("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq")).toBe(
      "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1"
    );
    expect(sha256Hex("a".repeat(1_000_000))).toBe(
      "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0"
    );
    for (const length of [1, 43, 54, 55, 56, 57, 63, 64, 65, 119, 120, 128, 200]) {
      const message = "xé中".repeat(length).slice(0, length);
      const expected = hex(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(message)));
      expect(sha256Hex(message), `length ${length}`).toBe(expected);
    }
  });

  it("is domain-separated from the server's token hash and tells near-identical tokens apart", () => {
    const token = "Zx9-invite_token_value";
    expect(inviteFingerprint(token)).toMatch(/^[0-9a-f]{64}$/);
    expect(inviteFingerprint(token)).not.toBe(sha256Hex(token)); // sha256(token) is what the server stores
    expect(inviteFingerprint(token)).not.toContain(token);
    expect(inviteFingerprint(`${token}a`)).not.toBe(inviteFingerprint(`${token}b`));
  });
});

describe("invitation acceptance recovery", () => {
  it("1. commits, but the reply is lost after another tab signs in: unknown outcome, newer identity kept", async () => {
    const router = openInvite("invite-b");
    const held = backend.hold((request) => request.url === ACCEPT, { ignoreAbort: true });
    await submitInvite();
    await waitFor(() => expect(backend.requestsTo(ACCEPT)).toHaveLength(1));
    const otherToken = otherTabSignsIn("u3");
    await waitFor(() => expect(auth.user?.id).toBe("u3"));
    held.release(); // the server commits; its reply is now stale here

    expect(await screen.findByText(INVITE_MESSAGES.unknown)).toBeTruthy();
    expect(backend.invites.has("invite-b")).toBe(false); // consumed server-side
    expect(membershipsOf(INVITEE)).toEqual([B]);
    expect(localStorage.getItem(AUTH_TOKEN_KEY)).toBe(otherToken);
    expect(auth.user?.id).toBe("u3");
    expect(auth.selectedOrganizationId).toBe(A);
    expect(getEffectiveRole(auth.user)).toBe("agent_owner");
    expect(router.state.location.pathname).toBe("/accept-invite");
    expect(screen.getByRole("button", { name: "Sign out and sign in with the invited account" })).toBeTruthy();
  });

  it("2. refused before dispatch: says nothing was submitted, and a retry works", async () => {
    signedIn("u1", A);
    const router = openInvite("invite-b");
    await waitFor(() => expect(auth.organizationStatus).toBe("selected"));
    otherTabSignsIn("u2", { storageEvent: false }); // the event has not arrived yet

    await submitInvite();
    expect(await screen.findByText(INVITE_MESSAGES.notSent)).toBeTruthy();
    expect(backend.requestsTo(ACCEPT)).toHaveLength(0);
    expect(backend.invites.has("invite-b")).toBe(true);
    await waitFor(() => expect(auth.user?.id).toBe("u2")); // this tab followed the new identity

    await submitInvite(); // explicit retry
    await waitFor(() => expect(router.state.location.pathname).toBe("/dashboard"));
    expect(auth.user?.id).toBe(INVITEE);
    expect(auth.selectedOrganizationId).toBe(B);
    expect(sessionStorage.getItem(ATTEMPT_KEY)).toBeNull();
  });

  it("3. transport failure after the commit: unknown outcome, then normal sign-in", async () => {
    const router = openInvite("invite-b");
    backend.networkFailure = { match: (request) => request.url === ACCEPT, when: "after-commit" };
    await submitInvite();

    expect(await screen.findByText(INVITE_MESSAGES.unknown)).toBeTruthy();
    expect(localStorage.getItem(AUTH_TOKEN_KEY)).toBeNull();
    expect(auth.organizationStatus).toBe("anonymous");
    expect(membershipsOf(INVITEE)).toEqual([B]);

    await userEvent.click(screen.getByRole("link", { name: "Sign in with the invited account" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/login"));
    await signInAs("invitee@example.com");
    await waitFor(() => expect(router.state.location.pathname).toBe("/dashboard"));
    // Only what the authenticated backend returns.
    expect(auth.memberships.map((m) => m.organization_id)).toEqual([B]);
    expect(getEffectiveRole(auth.user)).toBe("operator");
  });

  it("3b. a server error after the commit is an unknown outcome, not a failure", async () => {
    openInvite("invite-b");
    backend.networkFailure = { match: (request) => request.url === ACCEPT, when: "server-error-after-commit" };
    await submitInvite();
    expect(await screen.findByText(INVITE_MESSAGES.unknown)).toBeTruthy();
    expect(membershipsOf(INVITEE)).toEqual([B]);
    expect(localStorage.getItem(AUTH_TOKEN_KEY)).toBeNull();
  });

  it("4. transport failure before the commit: unknown outcome, the invitation still works", async () => {
    const router = openInvite("invite-b");
    backend.networkFailure = { match: (request) => request.url === ACCEPT, when: "before-commit" };
    await submitInvite();

    expect(await screen.findByText(INVITE_MESSAGES.unknown)).toBeTruthy();
    expect(backend.invites.has("invite-b")).toBe(true);
    expect(backend.users.has(INVITEE)).toBe(false);
    expect(sessionStorage.getItem(INVITE_TOKEN_KEY)).toBe("invite-b"); // kept for a retry

    await submitInvite();
    await waitFor(() => expect(router.state.location.pathname).toBe("/dashboard"));
    expect(auth.selectedOrganizationId).toBe(B);
    expect(sessionStorage.getItem(ATTEMPT_KEY)).toBeNull();
    expect(sessionStorage.getItem(INVITE_TOKEN_KEY)).toBeNull();
  });

  it("5. a retry after an unknown outcome that gets 400 does not claim a definite failure", async () => {
    openInvite("invite-b");
    backend.networkFailure = { match: (request) => request.url === ACCEPT, when: "after-commit" };
    await submitInvite();
    await screen.findByText(INVITE_MESSAGES.unknown);

    await submitInvite();
    expect(await screen.findByText(INVITE_MESSAGES.invalidAfterUnknown)).toBeTruthy();
    expect(screen.queryByText(INVITE_MESSAGES.invalid)).toBeNull();
    expect(screen.getByRole("link", { name: "Sign in with the invited account" })).toBeTruthy();
  });

  it("6. 409 already a member: says so and points to sign-in", async () => {
    openInvite("invite-a-for-u3");
    await submitInvite();
    expect(await screen.findByText(INVITE_MESSAGES.alreadyMember)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Sign in with the invited account" })).toBeTruthy();
    expect(membershipsOf("u3")).toEqual([A]);
    expect(auth.organizationStatus).toBe("anonymous");
  });

  it("7. 409 multiple organizations: not called invalid, and the invitation stays pending", async () => {
    openInvite("invite-b-for-u3");
    await submitInvite();
    expect(await screen.findByText(INVITE_MESSAGES.multipleOrganizations)).toBeTruthy();
    expect(screen.queryByText(INVITE_MESSAGES.invalid)).toBeNull();
    expect(backend.invites.has("invite-b-for-u3")).toBe(true);
    expect(membershipsOf("u3")).toEqual([A]);
    expect(sessionStorage.getItem(INVITE_TOKEN_KEY)).toBe("invite-b-for-u3");
  });

  it("8. 422 keeps the form usable and the invitation, then succeeds with a full name", async () => {
    const router = openInvite("invite-unnamed");
    await submitInvite();
    expect(await screen.findByText("Please check the submitted values and try again.")).toBeTruthy();
    expect(sessionStorage.getItem(INVITE_TOKEN_KEY)).toBe("invite-unnamed");
    expect(sessionStorage.getItem(ATTEMPT_KEY)).toBeNull(); // a definitive answer, not uncertain

    await submitInvite({ fullName: "New Person" });
    await waitFor(() => expect(router.state.location.pathname).toBe("/dashboard"));
    expect(auth.selectedOrganizationId).toBe(B);
  });

  it("9. an existing account signs in fine, but nothing claims a membership that was not created", async () => {
    const router = openInvite("invite-b-for-u4");
    backend.networkFailure = { match: (request) => request.url === ACCEPT, when: "before-commit" };
    await submitInvite();
    await screen.findByText(INVITE_MESSAGES.unknown);

    await userEvent.click(screen.getByRole("link", { name: "Sign in with the invited account" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/login"));
    await signInAs("none@example.com");
    expect(await screen.findByText("No organization yet")).toBeTruthy();
    expect(auth.memberships).toEqual([]);
    expect(membershipsOf("u4")).toEqual([]);
    expect(backend.invites.has("invite-b-for-u4")).toBe(true);
  });

  it("10. another account signed in: it is never replaced without an explicit sign-out", async () => {
    signedIn("u3", A);
    const router = openInvite("invite-b");
    await waitFor(() => expect(auth.organizationStatus).toBe("selected"));
    const u3Token = localStorage.getItem(AUTH_TOKEN_KEY);
    backend.networkFailure = { match: (request) => request.url === ACCEPT, when: "after-commit" };
    await submitInvite();
    await screen.findByText(INVITE_MESSAGES.unknown);

    expect(localStorage.getItem(AUTH_TOKEN_KEY)).toBe(u3Token);
    expect(auth.user?.id).toBe("u3");
    expect(screen.queryByRole("link", { name: "Sign in with the invited account" })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Sign out and sign in with the invited account" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/login"));
    expect(localStorage.getItem(AUTH_TOKEN_KEY)).toBeNull();
    await signInAs("invitee@example.com");
    await waitFor(() => expect(auth.user?.id).toBe(INVITEE));
    expect(getEffectiveRole(auth.user)).toBe("operator");
  });

  it("11. a reload after an unknown outcome explains it again, claims nothing, and stores no secrets", async () => {
    openInvite("invite-b");
    backend.networkFailure = { match: (request) => request.url === ACCEPT, when: "after-commit" };
    await submitInvite();
    await screen.findByText(INVITE_MESSAGES.unknown);
    const marker = sessionStorage.getItem(ATTEMPT_KEY) ?? "";
    expect(marker).not.toContain("invite-b");
    expect(marker).not.toContain(PASSWORD);
    expect(marker).not.toMatch(/eyJ/);
    expect(JSON.parse(marker)).toEqual({ fingerprint: inviteFingerprint("invite-b"), outcome: "unknown" });
    expect(marker).not.toContain(sha256Hex("invite-b"));

    // Reload: module memory is gone, this tab's sessionStorage survives, the URL has no token.
    cleanup();
    resetOrganizationSessionForTests();
    window.history.replaceState(null, "", "/accept-invite");
    const router = renderRoutes("/accept-invite");
    expect(await screen.findByText(INVITE_MESSAGES.unknown)).toBeTruthy();
    expect(router.state.location.pathname).toBe("/accept-invite");
    expect(auth.organizationStatus).toBe("anonymous");
    expect(screen.getByRole("button", { name: "Accept invitation" })).toBeTruthy();

    // A different invitation opened in this tab does not inherit the record.
    cleanup();
    openInvite("invite-unnamed");
    expect(screen.queryByText(INVITE_MESSAGES.unknown)).toBeNull();
    await waitFor(() => expect(sessionStorage.getItem(ATTEMPT_KEY)).toBeNull());
  });

  it("12. a stale invitation reply never replaces a newer identity, role or selected organization", async () => {
    signedIn("u1", B); // auditor in B in this tab
    openInvite("invite-b");
    await waitFor(() => expect(auth.organizationStatus).toBe("selected"));
    const held = backend.hold((request) => request.url === ACCEPT, { ignoreAbort: true });
    await submitInvite();
    await waitFor(() => expect(backend.requestsTo(ACCEPT)).toHaveLength(1));
    const u2Token = otherTabSignsIn("u2");
    await waitFor(() => expect(auth.user?.id).toBe("u2"));
    held.release();

    expect(await screen.findByText(INVITE_MESSAGES.unknown)).toBeTruthy();
    expect(localStorage.getItem(AUTH_TOKEN_KEY)).toBe(u2Token);
    expect(auth.user?.id).toBe("u2");
    expect(auth.organizationStatus).toBe("selection-required"); // u2's own state, nothing inherited
    expect(auth.selectedOrganizationId).toBeNull();
    expect(getEffectiveRole(auth.user)).toBeUndefined();
    const asInvitee = backend.requests.filter(
      (request) => tokenSubject(request.authorization?.replace("Bearer ", "") ?? null) === INVITEE
    );
    expect(asInvitee).toHaveLength(0); // the invitee's token was never used
  });

  it("13. a later attempt refused before dispatch never hides an earlier unknown outcome", async () => {
    signedIn("u3", A);
    openInvite("invite-b");
    await waitFor(() => expect(auth.organizationStatus).toBe("selected"));
    backend.networkFailure = { match: (request) => request.url === ACCEPT, when: "after-commit" };
    await submitInvite();
    await screen.findByText(INVITE_MESSAGES.unknown);

    otherTabSignsIn("u2", { storageEvent: false });
    await submitInvite(); // refused locally: not sent
    await waitFor(() => expect(auth.user?.id).toBe("u2"));
    expect(backend.requestsTo(ACCEPT)).toHaveLength(1);
    expect(await screen.findByText(INVITE_MESSAGES.unknown)).toBeTruthy(); // still uncertain
    expect(screen.queryByText(INVITE_MESSAGES.notSent)).toBeNull();
  });
});
