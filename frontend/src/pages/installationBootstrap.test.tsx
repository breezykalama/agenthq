import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { AUTH_TOKEN_KEY, api, gatewayApi } from "../api/client";
import { AuthProvider } from "../auth/AuthContext";
import { TenantQueryBoundary } from "../auth/TenantQueryBoundary";
import { resetOrganizationSessionForTests } from "../auth/organizationSession";
import { routes } from "../routes/router";
import { FakeBackend, uuid } from "../test/fakeBackend";

/**
 * First-install bootstrap is not customer onboarding: no public page advertises it, while
 * /bootstrap (and the older /?auth=bootstrap form) stay reachable for an operator installing
 * AgentHQ. The backend alone decides whether bootstrap is allowed.
 */

const A = uuid(1);
const PASSWORD = "Password123!";
const BOOTSTRAP = "/api/v1/organizations/bootstrap";
const CREATE_ORGANIZATION = /create (an |your )?organization/i;

let backend: FakeBackend;
const originalAdapter = api.defaults.adapter;
const originalGatewayAdapter = gatewayApi.defaults.adapter;

function renderRoutes(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <AuthProvider>
      <TenantQueryBoundary>
        <RouterProvider router={router} />
      </TenantQueryBoundary>
    </AuthProvider>
  );
  return router;
}

function advertisesNoOrganizationCreation(region: HTMLElement) {
  const scope = within(region);
  expect(scope.queryByRole("button", { name: CREATE_ORGANIZATION })).toBeNull();
  expect(scope.queryByRole("link", { name: CREATE_ORGANIZATION })).toBeNull();
  expect(scope.queryByText(CREATE_ORGANIZATION)).toBeNull();
  expect(scope.queryByRole("button", { name: /initial setup/i })).toBeNull();
  expect(region.querySelector('a[href="/bootstrap"]')).toBeNull();
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  window.history.replaceState(null, "", "/");
  resetOrganizationSessionForTests();
  backend = new FakeBackend();
  backend.addOrganization(A, "Org A");
  backend.addUser("u1", "member@example.com", "agent_owner");
  backend.addMembership("u1", A, "admin");
  api.defaults.adapter = backend.adapter;
  gatewayApi.defaults.adapter = backend.adapter;
});

afterEach(() => {
  cleanup();
  api.defaults.adapter = originalAdapter;
  gatewayApi.defaults.adapter = originalGatewayAdapter;
});

describe("public pages do not advertise first-install bootstrap", () => {
  it("1. landing navigation offers sign-in, not organization creation", async () => {
    renderRoutes("/");
    const navigation = await screen.findByRole("navigation", { name: "Public navigation" });
    advertisesNoOrganizationCreation(navigation);
    expect(within(navigation).getByRole("button", { name: "Sign in" })).toBeTruthy();
  });

  it("2. the landing hero offers sign-in and invitations only", async () => {
    renderRoutes("/");
    const heading = await screen.findByRole("heading", { level: 1 });
    const hero = heading.closest("section") as HTMLElement;
    advertisesNoOrganizationCreation(hero);
    expect(within(hero).getByRole("button", { name: "Sign in" })).toBeTruthy();
    expect(within(hero).getByRole("button", { name: "Accept invite" })).toBeTruthy();
  });

  it("3. the closing call to action does not advertise organization creation", async () => {
    renderRoutes("/");
    const heading = await screen.findByRole("heading", {
      name: "Build accountable agent operations from day one."
    });
    const closing = heading.closest("section") as HTMLElement;
    advertisesNoOrganizationCreation(closing);
    expect(within(closing).getByText(/invitation from their organization's administrator/i)).toBeTruthy();
    expect(within(closing).getByRole("button", { name: "Sign in" })).toBeTruthy();
  });

  it("the whole landing page has no organization-creation wording", async () => {
    renderRoutes("/");
    await screen.findByRole("navigation", { name: "Public navigation" });
    advertisesNoOrganizationCreation(document.body);
  });

  it("4. landing dialogs never switch to bootstrap", async () => {
    for (const mode of ["login", "invite", "forgot-password", "verify-email"]) {
      renderRoutes(`/?auth=${mode}`);
      const dialog = await screen.findByRole("dialog");
      advertisesNoOrganizationCreation(dialog);
      cleanup();
    }
  });

  it("5. the sign-in page has no organization-creation link", async () => {
    renderRoutes("/login");
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeTruthy();
    advertisesNoOrganizationCreation(document.body);
    expect(screen.getByRole("link", { name: "Forgot password?" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Accept invitation" })).toBeTruthy();
  });
});

describe("first-install bootstrap stays reachable", () => {
  it("6. /bootstrap renders the initial-setup page, not customer signup", async () => {
    renderRoutes("/bootstrap");
    expect(await screen.findByRole("heading", { name: "Initial AgentHQ setup" })).toBeTruthy();
    expect(screen.getByText("Available only before the first organization is created.")).toBeTruthy();
    expect(screen.getByText(/it is not customer signup/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Complete initial setup" })).toBeTruthy();
  });

  it("7. /bootstrap has no client-side bypass: the backend's refusal stands", async () => {
    // The real backend refuses bootstrap once any organization exists.
    const fake = backend as unknown as {
      route: (config: unknown, request: { url: string }) => [number, unknown];
    };
    const original = fake.route.bind(backend);
    fake.route = (config, request) =>
      request.url === BOOTSTRAP
        ? [409, { detail: "An active organization already exists." }]
        : original(config, request);
    const router = renderRoutes("/bootstrap");
    await userEvent.type(await screen.findByLabelText("Organization name"), "Late Org");
    await userEvent.type(screen.getByLabelText("Admin full name"), "Late Admin");
    await userEvent.type(screen.getByLabelText("Admin email"), "late@example.com");
    await userEvent.type(screen.getByLabelText("Admin password"), "LateAdminPassword123!");
    await userEvent.click(screen.getByRole("button", { name: "Complete initial setup" }));
    // The request goes to the bootstrap API, which decides; a refusal signs nobody in.
    await waitFor(() => expect(backend.requestsTo(BOOTSTRAP)).toHaveLength(1));
    expect(
      await screen.findByText(
        "An organization already exists. Please log in or ask your administrator for access."
      )
    ).toBeTruthy();
    expect(localStorage.getItem(AUTH_TOKEN_KEY)).toBeNull();
    expect(router.state.location.pathname).toBe("/bootstrap");
  });

  it("old /?auth=bootstrap links open the canonical page, not a second form", async () => {
    const router = renderRoutes("/?auth=bootstrap");
    await waitFor(() => expect(router.state.location.pathname).toBe("/bootstrap"));
    expect(await screen.findByRole("heading", { name: "Initial AgentHQ setup" })).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByLabelText("Bootstrap secret (if required)")).toBeTruthy();
  });
});

describe("sign-in still works from the landing page", () => {
  it("8. navigation Sign in opens the dialog and signs the member in", async () => {
    const router = renderRoutes("/");
    const navigation = await screen.findByRole("navigation", { name: "Public navigation" });
    await userEvent.click(within(navigation).getByRole("button", { name: "Sign in" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Email"), "member@example.com");
    await userEvent.type(within(dialog).getByLabelText("Password"), PASSWORD);
    await userEvent.click(within(dialog).getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(localStorage.getItem(AUTH_TOKEN_KEY)).not.toBeNull());
    await waitFor(() => expect(router.state.location.pathname).toBe("/dashboard"));
    expect(backend.requestsTo(BOOTSTRAP)).toHaveLength(0);
  });
});
