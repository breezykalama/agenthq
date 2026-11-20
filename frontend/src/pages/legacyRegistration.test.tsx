import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AxiosError, AxiosHeaders } from "axios";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { AUTH_TOKEN_KEY, api, gatewayApi, getErrorMessage } from "../api/client";
import { AuthProvider } from "../auth/AuthContext";
import { TenantQueryBoundary } from "../auth/TenantQueryBoundary";
import { resetOrganizationSessionForTests } from "../auth/organizationSession";
import { routes } from "../routes/router";
import { FakeBackend, uuid } from "../test/fakeBackend";

/**
 * Legacy self-registration is retired from the interface (the backend keeps it disabled unless
 * ALLOW_PUBLIC_REGISTRATION=true). These run on the production route tree.
 */

const A = uuid(1);
const PASSWORD = "Password123!";
const REGISTER = "/api/v1/auth/register";
const REGISTRATION_DISABLED =
  "Public registration is disabled. Ask your organization administrator for an invite.";

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

function noRegistrationEntryPoint() {
  expect(screen.queryByText(/create a legacy account/i)).toBeNull();
  expect(screen.queryByText(/legacy\/demo/i)).toBeNull();
  expect(screen.queryByRole("link", { name: /register/i })).toBeNull();
  expect(screen.queryByRole("button", { name: /register/i })).toBeNull();
  expect(document.querySelector('a[href="/register"]')).toBeNull();
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

describe("legacy registration entry points", () => {
  it("1. the sign-in page offers no legacy registration", async () => {
    renderRoutes("/login");
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeTruthy();
    noRegistrationEntryPoint();
    // The supported routes into AgentHQ stay available.
    expect(screen.getByRole("link", { name: "Accept invitation" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Forgot password?" })).toBeTruthy();
  });

  it("2. the landing page offers no legacy registration", async () => {
    renderRoutes("/");
    expect((await screen.findAllByRole("button", { name: "Accept invite" })).length).toBeGreaterThan(0);
    noRegistrationEntryPoint();
  });

  it("3 and 5. /register explains that registration is unavailable and submits nothing", async () => {
    renderRoutes("/register");
    expect(await screen.findByRole("heading", { name: "Registration is not available" })).toBeTruthy();
    expect(screen.getByText("Public registration is not currently available.")).toBeTruthy();
    expect(screen.getByText(/ask its administrator for an invitation/i)).toBeTruthy();
    // No form: nothing to submit, no email field that could probe for accounts.
    expect(document.querySelector("form")).toBeNull();
    expect(document.querySelector("input")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
    // It does not suggest that some other self-service signup exists.
    expect(screen.queryByText(/sign up|create (an )?account|create organization/i)).toBeNull();
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(backend.requestsTo(REGISTER)).toHaveLength(0);
  });

  it("4. the sign-in link from /register opens the working sign-in page", async () => {
    const router = renderRoutes("/register");
    await userEvent.click(await screen.findByRole("link", { name: "Sign in" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/login"));
    await userEvent.type(screen.getByLabelText("Email"), "member@example.com");
    await userEvent.type(screen.getByLabelText("Password"), PASSWORD);
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/dashboard"));
    expect(backend.requestsTo(REGISTER)).toHaveLength(0);
  });

  it("old ?auth=register links land on the unavailable page instead of a form", async () => {
    const router = renderRoutes("/?auth=register");
    await waitFor(() => expect(router.state.location.pathname).toBe("/register"));
    expect(await screen.findByRole("heading", { name: "Registration is not available" })).toBeTruthy();
    expect(document.querySelector("input")).toBeNull();
    expect(backend.requestsTo(REGISTER)).toHaveLength(0);
  });

  it("a signed-in user visiting /register goes to the dashboard (protected routes unchanged)", async () => {
    localStorage.setItem(AUTH_TOKEN_KEY, backend.tokenFor("u1"));
    const router = renderRoutes("/register");
    await waitFor(() => expect(router.state.location.pathname).toBe("/dashboard"));
    expect(backend.requestsTo(REGISTER)).toHaveLength(0);
  });
});

describe("403 handling", () => {
  function forbidden(detail: string): AxiosError {
    const config = { headers: new AxiosHeaders() };
    return new AxiosError("Request failed with status code 403", "ERR_BAD_REQUEST", config, {}, {
      status: 403,
      statusText: "Forbidden",
      headers: {},
      config,
      data: { detail }
    });
  }

  it("6 and 7. every 403 keeps the generic message: backend details are never shown globally", () => {
    // No interface calls the registration endpoint any more, so its disabled reply has no
    // screen to reach; the shared handler still never echoes any 403 detail.
    for (const detail of [REGISTRATION_DISABLED, "Insufficient permissions.", "Organization access denied."]) {
      expect(getErrorMessage(forbidden(detail))).toBe(
        "You do not have permission to access this resource."
      );
    }
  });
});

describe("identity flows that remain", () => {
  it("8. forgot password still submits only to its own endpoint", async () => {
    renderRoutes("/?auth=forgot-password");
    await userEvent.type(await screen.findByLabelText("Email"), "member@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Send reset link" }));
    await waitFor(() => expect(backend.requestsTo("/api/v1/auth/forgot-password")).toHaveLength(1));
    expect(backend.requestsTo(REGISTER)).toHaveLength(0);
  });

  it("8. emailed verification and reset links still reach their endpoints", async () => {
    window.history.replaceState(null, "", "/?auth=verify-email#token=verify-token-value");
    renderRoutes("/?auth=verify-email");
    await userEvent.click(await screen.findByRole("button", { name: "Verify email" }));
    await waitFor(() => expect(backend.requestsTo("/api/v1/auth/verify-email")).toHaveLength(1));
    // The emailed token travels in the request body, never in the URL.
    expect(backend.requests.some((request) => request.url.includes("verify-token-value"))).toBe(false);
    cleanup();

    window.history.replaceState(null, "", "/?auth=reset-password#token=reset-token-value");
    renderRoutes("/?auth=reset-password");
    await userEvent.type(await screen.findByLabelText("New password"), "NewPassword1234!");
    await userEvent.type(screen.getByLabelText("Confirm password"), "NewPassword1234!");
    await userEvent.click(screen.getByRole("button", { name: "Reset password" }));
    await waitFor(() => expect(backend.requestsTo("/api/v1/auth/reset-password")).toHaveLength(1));
    expect(backend.requestsTo(REGISTER)).toHaveLength(0);
  });
});
