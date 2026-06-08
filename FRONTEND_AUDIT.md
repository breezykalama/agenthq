# AgentHQ Frontend Feature Audit

Audit scope: current `frontend/` implementation only. No application code or API contracts were changed.

## Executive Summary

AgentHQ has the core frontend surfaces needed to demonstrate the onboarding workflow, including authentication, first-visit onboarding, MCP server registration and sync, agent/tool review, policy decision testing, simulated execution creation, and compliance reporting.

The complete governance workflow is **Partially Supported**. A user can complete every major step, but the experience is fragmented by missing MCP management actions, limited sync detail, missing agent editing, and manual UUID transfer between pages.

## Implemented Features

### Authentication

| Capability | Status | Evidence |
| --- | --- | --- |
| Registration page | Implemented | `/register` uses the authentication API and signs in after registration. |
| Login page | Implemented | `/login` authenticates and redirects to the requested protected route. |
| Logout | Implemented | Desktop and mobile layout include sign-out actions. |
| Current user display | Implemented | Layout displays the current user's full name and role. |
| Protected routes | Implemented | All application routes are wrapped by `ProtectedRoute`; unauthenticated users are redirected to `/login`. |

JWT persistence, authenticated API headers, current-user loading, automatic logout on HTTP 401, and clear HTTP 403 messaging are also implemented.

### Onboarding

| Capability | Status | Evidence |
| --- | --- | --- |
| Welcome modal on first login | Implemented | First authenticated visit is detected per user with `localStorage`. |
| Guided tour | Implemented | Tour covers Dashboard, MCP Servers, Agents, Policy Rules, and Compliance. |
| Dashboard onboarding checklist | Implemented | Quick Start links cover MCP registration, sync, agent review, policy testing, and compliance. |
| Demo banner | Implemented | Dashboard detects known seed-agent names and shows a dismissible sample-data banner. |

Notes:

- First-visit state is browser-local and does not follow a user across browsers or devices.
- The guided tour navigates between pages and explains each area, but does not highlight specific controls.
- The Policy Decision checklist item is always incomplete.
- The Compliance checklist item is inferred from execution count, not from whether compliance was reviewed.

### MCP Server Management

| Capability | Status | Notes |
| --- | --- | --- |
| View MCP servers | Implemented | Registry lists server name, URL, and status. |
| Create/register MCP server | Implemented | Admin users have a registration form. |
| Edit MCP server | Missing | No update form or PATCH action exists. |
| Delete MCP server | Missing | No delete action exists. |
| Sync MCP server | Implemented | Each listed server has a Sync Tools action. |
| View sync status | Implemented | Server status is shown as a badge. |
| View last sync time | Missing | `last_sync_at` exists in frontend types but is not displayed. |
| View sync errors | Implemented | Stored `last_error` and current sync request errors are displayed. |

### MCP Tool Discovery UX

| Capability | Status | Notes |
| --- | --- | --- |
| See discovered tools | Implemented | Synced tools are visible from the linked agent's tool list on the Agents page. |
| See linked agent | Missing | The MCP server row does not display or link to its `agent_id`. |
| See discovered tool count | Missing | The sync response contains `discovered_tools_count`, but the UI does not display it. |
| Trigger sync from UI | Implemented | Sync Tools action calls the MCP sync endpoint. |
| View sync results | Implemented | Success message reports created and updated tool counts; failures display an error. |

### Agent Management

| Capability | Status | Notes |
| --- | --- | --- |
| List agents | Implemented | Agent registry table is available. |
| Create agents | Implemented | Create Agent form is available. |
| View details | Implemented | Selecting a row shows the agent name, description, and tools. |
| Edit agents | Missing | No agent update form or action exists. |
| View linked tools | Implemented | Selected-agent tool cards show description, permission, risk, and enabled state. |

### Governance Workflow

The following major actions are available in the frontend:

1. Register MCP Server
2. Sync MCP Server
3. Review the created agent
4. Review discovered tools
5. Test a policy decision
6. Create a simulated execution
7. Review compliance summary and incidents

Overall workflow status: **Partially Supported**.

## Partially Implemented Features

### End-to-End Governance Workflow

The full flow can be completed, but it is not seamless:

- Users must manually locate the synced agent after MCP sync.
- Policy Decision Tester requires manually pasted agent and optional tool UUIDs.
- Execution creation requires manually pasted agent, tool, and optional approval UUIDs.
- There is no direct transition from a policy decision result to a prefilled execution.
- There is no direct transition from MCP sync results to the linked agent or discovered tools.
- The quick-start checklist does not reliably track policy-decision testing or compliance review.
- MCP registration is correctly hidden for non-admins, but Sync Tools remains visible and relies on the backend to reject unauthorized users.

## Missing Features

### MCP Server Management

| Capability | Status |
| --- | --- |
| Edit MCP server | Missing |
| Delete MCP server | Missing |

### MCP Tool Discovery UX

- No linked-agent display or direct link from an MCP server.
- No direct discovered-tools view from an MCP server.
- No display of the discovered tool count.
- No persistent display of the latest created and updated tool counts.
- No last-sync timestamp display.
- No per-server sync loading state; while one sync is pending, every Sync Tools button shows `Syncing...`.

### Agent Management

- No agent editing.
- No delete/archive action from the frontend.
- No tool editing, disabling, or deletion.
- No explicit MCP server linkage display.
- Selected agent rows are clickable but do not provide button semantics or keyboard interaction.

### Onboarding and Navigation

- No server-persisted onboarding completion state.
- No role-aware navigation; users can navigate to pages they cannot access and then receive a 403 message.
- No contextual action buttons connecting the onboarding steps.
- No reliable completion tracking for policy-decision testing or compliance review.

## Recommended Next Frontend Improvements

1. **Close the MCP management gaps**
   - Add MCP server edit and delete actions.
   - Display linked agent, last sync time, status, and last error together.
   - Show discovered, created, and updated tool counts after sync.
   - Use a per-server loading state for sync actions.

2. **Create direct workflow transitions**
   - Link sync results directly to the linked agent and its tools.
   - Add "Test policy" actions from agents and tools with IDs prefilled.
   - Add "Create execution" from a policy decision result with request values prefilled.
   - Add "Review compliance" after execution creation.

3. **Reduce UUID copy/paste**
   - Replace agent, tool, and approval UUID text fields with searchable selectors.
   - Filter tools by the selected agent.
   - Filter approvals by the selected agent and approved status.

4. **Complete agent management**
   - Add agent editing.
   - Add tool editing, enable/disable, and deletion.
   - Display complete agent metadata and MCP linkage.

5. **Make onboarding progress trustworthy**
   - Track policy-decision evaluations and compliance visits locally or through backend-supported progress state.
   - Make checklist completion user-specific.
   - Keep the guided tour available, but add contextual focus or highlighting for the relevant page controls.

6. **Improve role-aware UX**
   - Hide or disable unauthorized navigation and actions based on the current role.
   - Keep backend authorization as the source of truth while preventing avoidable 403 dead ends.
