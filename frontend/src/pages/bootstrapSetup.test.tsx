import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AxiosHeaders, type InternalAxiosRequestConfig } from "axios";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { AUTH_TOKEN_KEY, api, gatewayApi } from "../api/client";
import { AuthProvider } from "../auth/AuthContext";
import { TenantQueryBoundary } from "../auth/TenantQueryBoundary";
import { type AuthContextValue, useAuth } from "../auth/context";
import { getOrganizationContext, resetOrganizationSessionForTests } from "../auth/organizationSession";
import { routes } from "../routes/router";
import { FakeBackend, uuid } from "../test/fakeBackend";
import type { User } from "../types/api";

/**
 * The canonical first-install page (/bootstrap): one form, usable in production because it sends
 * the deployment's bootstrap secret, which never leaves the X-Bootstrap-Secret request header.
 * The backend alone decides; these tests model its responses (409 once an organization exists,
 * 403 for a missing or wrong secret).
 */

const BOOTSTRAP = "/api/v1/organizations/bootstrap";
const SECRET = "s3cret-Setup-Value-9f8e7d";
const NEW_ORG = uuid(9);
const ADMIN_EMAIL = "founder@example.com";
const ADMIN_PASSWORD = "FounderPassword123!";
const AUTHORIZATION_FAILED =
  "Initial setup authorization failed. Check your setup credentials or contact the installation administrator.";
const ORGANIZATION_EXISTS =
  "An organization already exists. Please log in or ask your administrator for access.";

interface SeenBootstrap {
  secretHeader: string | null;
  body: string;
  url: string;
}

let backend: FakeBackend;
let auth: AuthContextValue;
let seen: SeenBootstrap[];
const originalAdapter = api.defaults.adapter;
const originalGatewayAdapter = gatewayApi.defaults.adapter;

type Route = (config: InternalAxiosRequestConfig, request: { url: string }) => [number, unknown];

/** The backend's bootstrap rules, applied by the fake: one organization, guarded by a secret. */
function bootstrapEndpoint(options: { requiredSecret: string | null; organizationExists: boolean }) {
  const fake = backend as unknown as {
    route: Route;
    userRead: (userId: string, explicit: boolean, selected: string | null) => User;
  };
  const original = fake.route.bind(backend);
  fake.route = (config, request) => {
    if (request.url !== BOOTSTRAP) return original(config, request);
    const secret = AxiosHeaders.from(config.headers).get("X-Bootstrap-Secret");
    seen.push({
      secretHeader: typeof secret === "string" ? secret : null,
      body: typeof config.data === "string" ? config.data : JSON.stringify(config.data ?? {}),
      url: `${config.baseURL ?? ""}${config.url ?? ""}`
    });
    if (options.organizationExists) return [409, { detail: "An active organization already exists." }];
    if (options.requiredSecret !== null && secret !== options.requiredSecret) {
      return [403, { detail: "Bootstrap authorization failed." }];
    }
    backend.addOrganization(NEW_ORG, "Founding Org");
    backend.addUser("founder", ADMIN_EMAIL, "admin");
    backend.addMembership("founder", NEW_ORG, "admin");
    return [
      201,
      {
        access_token: backend.tokenFor("founder"),
        token_type: "bearer",
        user: fake.userRead("founder", true, NEW_ORG)
      }
    ];
  };
}

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

async function fillSetup(secret: string | null) {
  await userEvent.type(await screen.findByLabelText("Organization name"), "Founding Org");
  await userEvent.type(screen.getByLabelText("Admin full name"), "Founder");
  await userEvent.type(screen.getByLabelText("Admin email"), ADMIN_EMAIL);
  await userEvent.type(screen.getByLabelText("Admin password"), ADMIN_PASSWORD);
  if (secret) await userEvent.type(screen.getByLabelText("Bootstrap secret (if required)"), secret);
}

function storageValues(): string {
  const values: string[] = [];
  for (const storage of [localStorage, sessionStorage]) {
    for (let index = 0; index < storage.length; index += 1) {
      const key = storage.key(index) ?? "";
      values.push(key, storage.getItem(key) ?? "");
    }
  }
  return values.join("\n");
}

function expectSecretNowhere(router: ReturnType<typeof renderRoutes>) {
  expect(storageValues()).not.toContain(SECRET);
  expect(window.location.href).not.toContain(SECRET);
  expect(`${router.state.location.pathname}${router.state.location.search}${router.state.location.hash}`).not.toContain(SECRET);
  for (const request of backend.requests) expect(request.url).not.toContain(SECRET);
  for (const request of seen) {
    expect(request.url).not.toContain(SECRET);
    expect(request.body).not.toContain(SECRET);
  }
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  window.history.replaceState(null, "", "/");
  resetOrganizationSessionForTests();
  backend = new FakeBackend();
  seen = [];
  api.defaults.adapter = backend.adapter;
  gatewayApi.defaults.adapter = backend.adapter;
});

afterEach(() => {
  cleanup();
  api.defaults.adapter = originalAdapter;
  gatewayApi.defaults.adapter = originalGatewayAdapter;
});

describe("canonical /bootstrap page", () => {
  it("1 and 2. renders the single setup form, including the bootstrap secret", async () => {
    renderRoutes("/bootstrap");
    expect(await screen.findByRole("heading", { name: "Initial AgentHQ setup" })).toBeTruthy();
    for (const label of ["Organization name", "Admin full name", "Admin email", "Admin password"]) {
      expect(screen.getByLabelText(label)).toBeTruthy();
    }
    const secret = screen.getByLabelText("Bootstrap secret (if required)") as HTMLInputElement;
    expect(secret.type).toBe("password");
    expect(secret.required).toBe(false); // optional for deployments without a configured secret
    expect(secret.autocomplete).toBe("off");
  });

  it("3, 4, 5 and 14. success: header-only secret, signed in to the new organization, secret cleared", async () => {
    bootstrapEndpoint({ requiredSecret: SECRET, organizationExists: false });
    const router = renderRoutes("/bootstrap");
    await fillSetup(SECRET);
    await userEvent.click(screen.getByRole("button", { name: "Complete initial setup" }));

    // Signing in to the new organization remounts the workspace, which lands on the dashboard.
    await waitFor(() => expect(router.state.location.pathname).toBe("/dashboard"));
    expect(seen).toHaveLength(1);
    expect(seen[0].secretHeader).toBe(SECRET); // sent as X-Bootstrap-Secret ...
    const body = JSON.parse(seen[0].body) as Record<string, unknown>;
    expect(body).toEqual({
      organization_name: "Founding Org",
      admin_full_name: "Founder",
      admin_email: ADMIN_EMAIL,
      admin_password: ADMIN_PASSWORD
    }); // ... and never in the JSON body
    // Authentication and organization context come from the backend's reply.
    expect(localStorage.getItem(AUTH_TOKEN_KEY)).not.toBeNull();
    await waitFor(() => expect(auth.user?.email).toBe(ADMIN_EMAIL));
    expect(auth.selectedOrganizationId).toBe(NEW_ORG);
    expect(getOrganizationContext().organizationId).toBe(NEW_ORG);
    expect((await screen.findAllByText("Founding Org · Admin")).length).toBeGreaterThan(0);
    // The form is gone and no element still holds the secret.
    expect(screen.queryByLabelText("Bootstrap secret (if required)")).toBeNull();
    for (const input of Array.from(document.querySelectorAll("input"))) expect(input.value).not.toBe(SECRET);
    expectSecretNowhere(router);
  });

  it("deployments without a configured secret send no X-Bootstrap-Secret header", async () => {
    bootstrapEndpoint({ requiredSecret: null, organizationExists: false });
    const router = renderRoutes("/bootstrap");
    await fillSetup(null);
    await userEvent.click(screen.getByRole("button", { name: "Complete initial setup" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/dashboard"));
    expect(seen[0].secretHeader).toBeNull();
  });

  it("6 and 8. a 403 shows the generic setup message, never the secret, and signs nobody in", async () => {
    bootstrapEndpoint({ requiredSecret: "the-real-secret", organizationExists: false });
    const router = renderRoutes("/bootstrap");
    await fillSetup(SECRET);
    await userEvent.click(screen.getByRole("button", { name: "Complete initial setup" }));
    expect(await screen.findByText(AUTHORIZATION_FAILED)).toBeTruthy();
    expect(document.body.textContent).not.toContain(SECRET);
    expect(document.body.textContent).not.toContain("Bootstrap authorization failed.");
    expect(localStorage.getItem(AUTH_TOKEN_KEY)).toBeNull();
    expect(router.state.location.pathname).toBe("/bootstrap");
    expectSecretNowhere(router);
  });

  it("6. a missing secret gets exactly the same message as a wrong one", async () => {
    bootstrapEndpoint({ requiredSecret: "the-real-secret", organizationExists: false });
    renderRoutes("/bootstrap");
    await fillSetup(null);
    await userEvent.click(screen.getByRole("button", { name: "Complete initial setup" }));
    expect(await screen.findByText(AUTHORIZATION_FAILED)).toBeTruthy();
    expect(seen[0].secretHeader).toBeNull();
  });

  it("7 and 8. a 409 keeps the already-initialized refusal and signs nobody in", async () => {
    bootstrapEndpoint({ requiredSecret: SECRET, organizationExists: true });
    const router = renderRoutes("/bootstrap");
    await fillSetup(SECRET);
    await userEvent.click(screen.getByRole("button", { name: "Complete initial setup" }));
    expect(await screen.findByText(ORGANIZATION_EXISTS)).toBeTruthy();
    expect(localStorage.getItem(AUTH_TOKEN_KEY)).toBeNull();
    expect(router.state.location.pathname).toBe("/bootstrap");
    expectSecretNowhere(router);
  });

  it("14. leaving the page discards the secret", async () => {
    const router = renderRoutes("/bootstrap");
    await userEvent.type(await screen.findByLabelText("Bootstrap secret (if required)"), SECRET);
    await userEvent.click(screen.getByRole("link", { name: "Sign in" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/login"));
    await router.navigate("/bootstrap");
    const secret = (await screen.findByLabelText("Bootstrap secret (if required)")) as HTMLInputElement;
    expect(secret.value).toBe("");
    expectSecretNowhere(router);
  });
});

describe("one form only", () => {
  it("10. the landing page no longer contains a bootstrap form", async () => {
    renderRoutes("/");
    await screen.findByRole("navigation", { name: "Public navigation" });
    expect(screen.queryByLabelText(/bootstrap secret/i)).toBeNull();
    expect(screen.queryByLabelText("Organization name")).toBeNull();
    expect(screen.queryByRole("button", { name: "Complete initial setup" })).toBeNull();
  });

  it("11. other landing dialogs still open (sign-in, invite, forgot password)", async () => {
    for (const [mode, heading] of [
      ["login", "Sign in"],
      ["invite", "Accept organization invite"],
      ["forgot-password", "Reset your password"]
    ]) {
      const router = renderRoutes(`/?auth=${mode}`);
      const dialog = await screen.findByRole("dialog");
      expect(dialog.textContent).toContain(heading);
      expect(router.state.location.pathname).toBe("/");
      cleanup();
    }
  });
});
