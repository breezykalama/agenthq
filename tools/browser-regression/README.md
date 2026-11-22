# Browser regression harness: organization selection and switching

An opt-in, local-only release-validation tool. It drives headless Chrome over the Chrome DevTools
Protocol against a real backend and frontend built from a clean checkout, using disposable
PostgreSQL 18 and Redis containers. It checks that a multi-membership user only ever sends, and
only ever sees, the organization they selected.

Nothing here runs in CI or against hosted services. Run it by hand, locally, before a release or
rollback decision.

## What it checks

- **`core`: the 16-check browser suite (B1–B16).** It covers:
  - the organization picker;
  - role-based navigation;
  - cache isolation across switches;
  - inactive (C) and deleted (D) organizations never being sent;
  - single-membership sign-in;
  - the absence of page exceptions.

  B5, B9 and B12 are the corrected request-header checks described below.
- **B5 and B9: choosing Org A, then switching from A to B.**
  - **B5:** every organization-scoped request issued while Org A is the chosen organization, from
    the picker choice up to the switch to B, carries Org A's header.
  - **B9:** after the frontend has confirmed Org B, no newly issued request carries Org A's (or
    any other) header, and none does while the switch is being confirmed.

  Each iteration of these scenarios is the suite's own sequence in a fresh sign-in: picker,
  choose A, Agents page, switch to B, dashboard, Audit Logs.

  | Scenario | What it does |
  |---|---|
  | `b5b9-normal` | The suite's sequence. |
  | `b5b9-inflight` | Reloads A's dashboard and holds its header-A data requests at the network layer (CDP `Fetch`) across the switch, releasing them only after B is confirmed. |
  | `b5b9-race` | Forces the historical B9 false positive: one page evaluation opens A's Audit Logs page, waits until its header-A requests are issued, then switches. The run passes only if the old (pre-Step-111) B9 fails on the same run while the corrected B5 and B9 pass, and B5's window contains those last header-A requests. |
  | `b5-negative` | Negative control: one request in A's session is sent with Org B's header. Passes only if B5 fails on its header assertion and names exactly that request. |
  | `b9-negative` | Negative control: one request after B is confirmed is sent with Org A's header. Passes only if B9 fails on its post-confirmation assertion and names exactly that request. |
- **B12: switching from Org B to Org A.** After the frontend has confirmed Org A, no newly issued
  request may carry Org B's `X-AgentHQ-Organization` header. B12 runs in four scenarios:

  | Scenario | What it does |
  |---|---|
  | `b12-normal` | Reload B's dashboard and switch as soon as the switcher appears, while B's queries are still in flight. |
  | `b12-inflight` | The same, but B's data requests are held at the network layer (CDP `Fetch`) across the switch and released only after confirmation. |
  | `b12-race` | Forces the historical false positive: header-B requests issued *before* the switch but reported by CDP *after* a request-count mark. The run passes only if the old (Step 105) algorithm fails on the same run while the corrected B12 passes. |
  | `b12-negative` | Negative control: inside the page, one post-confirmation request's organization header is rewritten to Org B. The run passes only if B12 fails on its post-confirmation assertion and names exactly that request. |

- **Dashboard rendering and tenant-cache isolation (`dashboard_isolation.mjs`).** The seed gives
  the two organizations deliberately different dashboard data: Org A has 17 agents (1 low, 16
  medium risk), Org B has 3 (1 low, 2 high). The checked fields are:
  - the **Total Agents** card, from `GET /api/v1/dashboard/summary` (`total_agents`: the
    organization's non-deleted agents);
  - the **Agents by Risk** list, from `GET /api/v1/dashboard/agents-by-risk`.

  Expected values are fetched from the backend with an explicit organization header at the
  start of each run, and the run stops if they are not the designed 17/3 split.

  | Scenario | What it does |
  |---|---|
  | `dash-normal` | Chooses A, switches to B, back to A, to B again, then reloads in B. Checks rendered values, every transient frame and the live query cache at each step. |
  | `dash-stale` | Holds the response to Org A's dashboard-summary request, issued *before* the switch, and delivers it after B is confirmed. The switch's first cancellation is suppressed inside the page so that the response really reaches the page's `XMLHttpRequest`. The run passes only if that delivery happened and A's values never appear under B, on screen or in B's cache. |
  | `dash-wrong-header` | After the switch to B, one request is sent with Org A's header (a simulated frontend defect). The run passes only if both the request-header check and the visible-data check detect it. |
  | `dash-negative` | Negative control for the visible-data check: Org B's own dashboard-summary response is replaced at the network layer with Org A's genuine one, while every request header stays correct. The run passes only if the visible-data check fails and names the organization, field, expected value and observed value, while the request-header check still passes. |

### What each kind of check proves

| Layer | Question | Proven by | Not proven |
|---|---|---|---|
| **Request isolation** | Does every request carry the selected organization's header, and only that? | B5, B9, B12 and their negative controls; B13 (never C or D) | — |
| **Stale-response protection** | Is a response to a request issued under the previous organization kept out of the new one? | `b12-inflight`, `b5b9-inflight` (the frontend cancels it before delivery); `dash-stale` (forced delivery to the page, then neither rendered nor cached) | Other endpoints and timings (limitation 2) |
| **Query-cache isolation** | Does the live cache hold only the selected organization's keys and values, with the previous one emptied? | `dash-normal`, `dash-stale`; detects contamination in `dash-negative` | Cache contents of pages other than the dashboard |
| **Rendering isolation** | Does any rendered frame show the other organization's values? | `dash-normal` (every frame, every switch, reload), with `dash-negative` and `dash-wrong-header` proving detection; older name-based text checks B4, B7, B8 | Fields other than Total Agents and Agents by Risk (limitation 1) |
| **Backend response correctness** | Does the server answer each header with that organization's data only? | Not by this harness: the backend test suite. Here it is only assumed when expected values are fetched with an explicit header | Everything here; a substituted response is rendered as-is (limitation 3) |

### How dashboard isolation is checked

- **Every frame.** A sampler injected into every document records each committed DOM state:
  the switcher's selected organization, the Total Agents value and the Agents by Risk list. It
  samples on every DOM mutation and on a 20 ms poll, so it also sees frames that are never
  painted.
- **Visible-data assertion.** A frame whose switcher shows one organization must never show the
  other organization's value for either field. While switching away from an organization, a
  frame that shows no organization must not show the old organization's values either. After
  each transition, the final frame must show exactly the selected organization's expected
  values; the run waits for that frame and fails on a timeout, so an unfinished page cannot
  pass. A failure prints `selected organization=…; field=…; expected=…; observed=…; seen in N
  recorded frame(s)`. A violation seen in several recorded DOM frames is counted once.
- **Cache assertion.** The live TanStack Query client is read, read-only, through React's fiber
  tree. Every cached query must be keyed to the selected organization's context, and the cached
  summary and risk data must equal that organization's API values. After a switch, the previous
  organization's client (kept by reference) must be empty and must have been replaced.
- **The application's isolation mechanisms being tested** (none is modified):
  - every request is stamped synchronously with the current context generation, abort signal
    and organization header (`frontend/src/api/client.ts`);
  - a response for a generation that is no longer current is rejected before it reaches any
    cache;
  - each user and organization context gets its own `QueryClient`, with hashes prefixed by the
    context key. The previous client's queries are cancelled and its cache cleared, and the
    tree below it remounts (`frontend/src/auth/TenantQueryBoundary.tsx`,
    `tenantQueryClient.ts`).

### How B12 decides (see `b12_lib.mjs`)

- **Recording.** A passive probe is injected into every document of the tab. It numbers each
  `/api/` request at the moment the page calls `XMLHttpRequest.send()` or `fetch()`, and records
  only its method, path and organization header. It never records `Authorization`, cookies,
  bodies or tokens.
- **Switch start.** The boundary is set in the same synchronous page evaluation that dispatches
  the switch, so it is exact.
- **Confirmation.** Org A counts as confirmed when both hold:
  - an `/auth/me` request carrying candidate header A has returned HTTP 200 (the backend
    confirmed the selection);
  - the switcher shows Org A as selected.

  The second condition is re-checked on every DOM mutation, on every request issuance and on a
  20 ms poll.
- **Classification.** Each request is classified by the page when it is issued:
  - `pre`: before the switch; the requests still in flight at the switch are listed separately;
  - `confirming`;
  - `post`: after confirmation, including every request in any later document of the tab.
- **Assertions.**
  - The boundary exists and is backed by the backend's confirmation.
  - Every `post` request carries header A. The only header-less request allowed is identity
    discovery (`/auth/me`), and no endpoint category is excluded.
  - No `confirming` request carries a foreign header.
  - Phases are monotonic.
  - The probe and Chrome's independent `Network` events agree on every request's method, path and
    header (multiset equality), so the test cannot pass by missing requests.

### How B5 and B9 decide (see `b5b9_lib.mjs`)

Before Step 111, both used `mark = requests.length`, an index into Chrome's
`Network.requestWillBeSent` stream. Chrome reports requests late, so that index records when a
request was *reported*, not when it was *issued*:

- **B9 (the defect).** Header-A requests issued in A's session before the switch, but reported
  after the mark, counted as post-switch: a false "header A after the switch" failure. This is
  the B12 race in the other direction, and `b5b9-race` reproduces it on every run.
- **B5 (an omission, not a false failure).** Everything issued before the picker choice is
  header-less, which B2 checks, so a late report there could not fail B5. But B5 was evaluated
  whenever the check ran, so requests issued in A but not yet reported were left out. Once B9
  classifies by issuance, those requests would be "pre-switch" for B9 as well, and a wrong
  header issued late in A would escape both checks.

Both now use the B12 probe (`b12_lib.mjs`, unchanged):

- **Boundaries.** Each boundary is a probe arm placed in the same page evaluation as the user's
  action: the picker choice for B5, the switcher change for B9. Requests are ordered by the
  probe's issuance record (document, then sequence number), never by Chrome's delivery order.
- **B5.** The window is every request issued after the picker-choice arm, up to and including the
  arm of the switch to B, however late Chrome reports it. It asserts:
  - at least one organization-scoped request;
  - every organization-scoped request carries header A (header-less requests are ignored, as
    before);
  - the window includes the candidate `/auth/me` and `GET /api/v1/agents` with header A;
  - the probe and Chrome agree on every request (multiset equality);
  - every recorded request can be ordered (its document was announced); otherwise B5 fails
    rather than leaving the request out.
- **B9.** The B12 classification and assertions (`analyze`) with destination B, plus a
  requirement that `GET /api/v1/audit-logs`, the page B8 checks, was issued after confirmation
  with header B. Requests that were issued in A and still in flight at the switch are `pre` and
  listed separately; they are not violations.
- **Settling.** Both checks run only after the probe and Chrome agree on the request count.

## Tested environment

**Validated only on Windows 11:**
- Git Bash as the shell;
- Docker Desktop;
- Google Chrome 157 (headless), Node.js 24 and Python 3.12 via `uv`.

The harness has code paths for Linux and macOS (POSIX process groups, symlinked `node_modules`,
other Chrome locations), but they have **not been tested**. Do not rely on them until they are.
The commands below use bash syntax; PowerShell invocations are untested.

## Prerequisites

- Docker, able to pull `postgres:18-bookworm` and `redis:7-alpine`. It binds `127.0.0.1` ports
  55420, 56380, 8019, 4174 and 9334 by default; override them with `up --pg-port …` and the other
  port options.
- Node.js 22 or later, for the built-in `WebSocket`. Node 24 is tested.
- Google Chrome or Chromium: found on `PATH` or at the standard install path, or given with
  `--chrome PATH` or `CHROME_PATH`.
- The backend's Python environment, `uv sync` in `backend/`. The harness needs only the standard
  library, plus `psycopg`, which is a backend dependency.
- Git, for clean worktrees.

## Commands

Run these from the repository root, in Git Bash. `H` stands for the harness invoked with the
backend's locked environment:

```sh
H="uv run --project backend --frozen python tools/browser-regression/harness.py"

$H guard-selftest                     # 1a. prove the safety guards refuse unsafe targets
$H cleanup-selftest                   # 1b. prove cleanup refuses resources it does not own
$H up                                 # 2. disposable PostgreSQL 18 + Redis, local-only credentials
TREE=$($H prepare-tree --ref HEAD --node-modules-from frontend/node_modules | tail -n 1)
                                      # 3. clean detached worktree to test; its path is the last
                                      #    line printed (omit --node-modules-from to `npm ci` in it)
$H seed --tree "$TREE"                # 4. isolated test data
$H validate --tree "$TREE"            # 5. every B12, B5/B9 and dashboard scenario (10 iterations each) + core x3
$H run --tree "$TREE" b12-negative    #    or any subset of the scenarios listed under "What it checks"
$H down                               # 6. stop containers, remove worktrees, delete every credential
```

- **Picking the tree.** `prepare-tree` prints the worktree path,
  `<state dir>/tree-<sha>`, as its last line. Pass it to `--tree`.
- **Testing another build** (for example a rollback candidate): run `prepare-tree --ref <sha>`,
  then `validate --tree <its path>`, against the same seeded database.
- **Options.**
  - `--iterations N`: iterations per B12, B5/B9 or dashboard scenario; the default is 10.
  - `--core-runs N`: runs of the 16-check suite in `validate`; the default is 3.
  - `--state-dir DIR`: the state directory; give it before the sub-command.

## Expected results

| Scenario | Expected result |
|---|---|
| `core` | `16/16 browser checks passed` |
| `b12-normal` | `10/10` iterations. Typical classification: about 9 `pre` requests (8 with header B, about 7 of them in flight at the switch and aborted by the frontend), 2 `confirming` (`/auth/me` with no header, then with header A), 15 `post` (14 with header A, 1 identity discovery). |
| `b12-inflight` | `10/10`. About 7 header-B requests are held across the switch; the page has already cancelled all of them by release time. No Org B data is visible. |
| `b12-race` | `10/10`, each with `race reproduced: Step 105 B12 on the same run FAILS (false positive)`. |
| `b12-negative` | `10/10`, each with `NEGATIVE CONTROL: corrected B12 FAILED as required; responsible request identified: #… GET /api/v1/… hdr=B phase=post INJECTED …` |
| `b5b9-normal` | `10/10`. Typical: a B5 window of 15 requests (14 with header A, 1 identity discovery); B9 with about 17 `pre` requests (a few to 9 header-A requests in flight at the switch, all aborted by the frontend), 2 `confirming` (`/auth/me` with no header, then with header B), 9 `post`, all with header B. |
| `b5b9-inflight` | `10/10`. Header-A requests are held across the switch; the page has cancelled most of them by release time. No Org A data is visible. |
| `b5b9-race` | `10/10`, each with `race reproduced: pre-Step-111 B9 on the same run FAILS (false positive)` and `B5 window covers header-A requests issued just before the switch`. |
| `b5-negative` | `10/10`, each with `B5 NEGATIVE CONTROL: corrected B5 FAILED as required; responsible request: #… GET /api/v1/agents hdr=B phase=post INJECTED status=403` |
| `b9-negative` | `10/10`, each with `B9 NEGATIVE CONTROL: corrected B9 FAILED as required; responsible request: #… GET /api/v1/dashboard/summary hdr=A phase=post INJECTED status=200` |
| `dash-normal` | `10/10`. Org A shows Total Agents 17, Org B shows 3, with their own risk lists. Every transition runs `none/- > <new org>/- > <new org>/<its value>`: the old dashboard is removed before the new organization is shown. Every cache is keyed to its organization, and the previous one is emptied. |
| `dash-stale` | `10/10`, each with `delivered to the page's XMLHttpRequest after Org B was confirmed: 1 (status 200)` and Org B still showing 3. |
| `dash-wrong-header` | `10/10`. The injected `GET /api/v1/dashboard/summary hdr=A` returns 200, and the page then shows `B/17`. Both checks detect it. |
| `dash-negative` | `10/10`, each with `VISIBLE-DATA FAIL (expected): selected organization=Rehearsal Org B; field=Total Agents (…); expected=3; observed=17 (…); seen in N recorded frame(s)`, the 17 still visibly on screen after 3 s, the cache check also failing on `total_agents=17`, and the request-header check passing. |

- **Database side effects.** A browser phase normally changes only the `audit_logs` table. On a
  fresh database, the first dashboard views may also populate `compliance_controls` and
  `risk_snapshots`.
- **Exit codes.** `validate` and `run` exit 0 only if every scenario passed.

## Interpreting a failure

Each B12, B5 and B9 evaluation prints its boundary, the request counts, the `asserts` object
and, on failure, the offending requests, as `#seq@doc METHOD path hdr=<A|B|none> phase=<…>
status=<…>`. In B9 the destination is B and the origin is A; read the B12 notes below with the
letters swapped.

- **B5 `header: false`.** A request issued while A was chosen carried another organization's
  header. Treat it as a real defect; the named request is responsible.
- **B5 `coverage: false` or `scoped: false`.** The A session did not issue the expected
  requests (the picker confirmation or the Agents list), so B5 proved nothing. Look for a
  routing or markup change.
- **B5 `ordered: false`.** A recorded request came from a document the probe never announced,
  so it could not be placed in or out of the window. Do not trust the run.
- **B9 `coverage: false`.** The Audit Logs page in B was never requested with header B.
- **`b5-negative` or `b9-negative` fails.** That check can no longer detect a wrong header. Do not
  trust its other results.
- **`VISIBLE-DATA VIOLATION` in `dash-normal` or `dash-stale`.** One organization's dashboard
  value was rendered while the switcher showed the other. Treat it as a real isolation defect.
  The line names the selected organization, the field, the expected value and the observed one.
- **A `cache (Org …)` line with `PROBLEMS`.** The live query cache holds data or keys of the
  wrong organization, or the previous organization's cache was not emptied.
- **A `dash-*` request-header step fails.** The `header analysis:` lines that follow give the
  B12 `asserts` object and the offending requests; read them as for B12. Every header check
  waits until the probe and Chrome agree on the request count. A line marked `before probe and
  Chrome agreed (not a verdict)` is diagnostic only.
- **`dash-stale` fails on "scenario exercised".** The late response never reached the page
  (it was still cancelled, or the response was not held). The run proves nothing about
  late-response handling; it is not a product result.
- **`dash-negative` fails.** The visible-data check can no longer see a foreign value. Do not
  trust the other dashboard results.
- **`seeded data is not the designed, distinguishable data`.** The database was not seeded by
  this version of the harness. Run `down`, `up` and `seed` again.
- **`a previous seed attempt did not complete`.** Seeding is not idempotent, so `seed` runs at
  most once per database, even after a failure. Run `down` and `up` for a fresh one.

- **`post: false` in `b12-normal` or `b12-inflight`.** A request issued after confirmation carried
  another organization's header, or carried no header on an endpoint other than `/auth/me`. Treat
  this as a real cross-tenant defect until shown otherwise. The named request is the one
  responsible.
- **`confirming: false`.** The previous organization's header was issued after the switch began.
  The neutral context should make that impossible.
- **`boundary: false`.** No backend-confirmed selection was observed. The switch failed, or the
  switcher markup changed; see the limitations below.
- **`complete: false`.** The probe and Chrome disagree about which requests were sent. The
  recorder missed something, for example a new transport. Do not trust the run.
- **Visible-data line shows `B data …=true`.** Org B names were rendered in Org A.
- **`b12-negative` fails.** The control did not detect the injection, so B12 itself is broken.
  Do not trust any other B12 result.
- **`b12-race` fails with "race not triggered".** The forced race did not happen, because the
  audit-logs navigation link changed. This weakens only the regression evidence, not the
  product.
- **Setup errors, such as `REFUSED: …` or timeouts.** These are not product results. Fix the
  environment and run again.

## Credential and data safety

- **Guards.** Before anything connects:
  - `guard()` refuses any database or Redis URL that is not loopback, not this run's port, or
    not the harness database;
  - it refuses any URL or origin that is not loopback or that looks hosted (Railway, Render,
    Vercel, Supabase, Neon, AWS, Azure, Heroku, "staging", "prod").
  - `verify_disposable()` requires both services to be this run's labelled, auto-removed
    (`--rm`), loopback-only containers, with PostgreSQL on tmpfs.
  - Trees containing `backend/.env` or `frontend/.env*` are refused, because the application
    would read developer or deployment settings from them.
- **Inherited environment.** The backend inherits no environment variables except basic OS
  ones. It runs with:
  - `MULTI_ORGANIZATION_MEMBERSHIPS_ENABLED=false`;
  - `ALLOW_PUBLIC_REGISTRATION=false`. Seeding verifies that registration returns 403;
  - production mode, with Redis, for every browser phase.
- **Test data.** Agents (17 in Org A, 3 in Org B) and gateways are created through the real API
  by each organization's own admin. Dual's extra memberships are provisioned directly
  through the application's models on the disposable database. The multi-membership flag is never enabled.
- **Secrets.** Every secret is generated per run. This covers the database password, JWT key,
  bootstrap secret and test-user passwords. They live only in the state directory (by default
  `<system temp>/agenthq-browser-regression`, which must be outside the repository), are passed
  to the browser scripts through environment variables, and are never printed.
  - The seed step's e-mail log, which holds verification links, is deleted as soon as seeding
    ends.
  - There are no real credentials or customer data, and no deployment credentials are used.

## Cleanup and resource ownership

`down` deletes only what this run provably created. `cleanup-selftest` demonstrates each rule
below against sentinel resources it creates itself; expect `17/17 cleanup ownership checks
passed`.

- **Records at creation.** Each run gets a random 16-hex-digit ID. `up` refuses to use a state
  directory that already has content, and writes `run.json` recording each container's full
  Docker ID, name and image as it is created. `prepare-tree` records each worktree's path,
  commit and `node_modules` kind and target.
- **Plan before acting.** `down` first proves ownership of every recorded resource, and refuses
  before deleting *anything* if any check fails:
  - **Containers** are stopped only by their recorded full ID, and only if the live container's
    ID, name, run label and image all still match. A container that merely shares the
    `agenthq-br-` name prefix or the run label is never touched.
  - **Worktrees** are removed only if they sit directly in the state directory, are named
    `tree-<sha>`, and are registered with this repository as a detached worktree at the recorded
    commit. The development checkout and any other worktree are refused.
  - **Links.** A `node_modules` link is removed only if it points exactly at the recorded target.
    The link is removed, never followed, so the target (for example your development
    `node_modules`) is untouched. Any other symlink or junction inside a worktree or the state
    directory stops cleanup.
  - **State directory.** It must hold the harness's own `run.json`, written for that exact
    directory, and only entries the harness creates. Any unexpected file stops cleanup.
- **No repository-wide git operations.** In particular, there is no `git worktree prune`.
- **Processes.** Only the subprocesses the harness itself spawned are terminated (backend, Vite
  preview, Chrome). Nothing is looked up or killed by name or PID. If the harness is interrupted,
  stop any leftover `uvicorn`, `vite preview` or headless Chrome yourself.
- **If `down` refuses,** it prints why. Nothing has been deleted at that point: inspect the named
  resource and remove it by hand if it is really yours.

## Limitations (open coverage gaps)

1. **Numeric rendering is verified for two dashboard fields.** The `dash-*` scenarios cover the
   Total Agents card and the Agents by Risk list on the dashboard, plus the live query cache,
   with a working negative control (`dash-negative`). Other pages and fields (agents list, audit
   logs, compliance, risk) are covered only by the older name-based text checks ("Agent A",
   "Gateway A") in B7, B8 and B12, which have no numeric negative control.
2. **Stale-response delivery is tested for one endpoint and one timing.** Normally the frontend
   cancels every in-flight request at the switch, so no late response reaches the page; every
   other scenario shows that. `dash-stale` suppresses that one cancellation inside the page to
   force a real late delivery of `GET /api/v1/dashboard/summary`, released after Org B is
   confirmed and rendered, and shows it is neither rendered nor cached. Other endpoints, other
   timings (for example, delivery while the new organization is still being confirmed) and
   multiple concurrent late responses are not covered. The harness also cannot tell which of the
   two remaining defences discarded the response: the API client's generation check, or the
   discarded previous `QueryClient`.
3. **A substituted backend response is not independently rejected by the frontend.** The
   dashboard payloads carry no organization identifier, so a correct-header request answered
   with another organization's genuine data is rendered as-is (`dash-negative`). The frontend
   does not validate tenant ownership of arbitrary backend payloads, and does not claim to: the
   correctness of what the server returns rests on backend authorization, covered by the backend
   test suite and, at the request level, by the header checks.
4. **React-internal cache inspection may need maintenance after frontend upgrades.** The cache
   assertion finds the `QueryClient` through React's fiber tree (`__reactFiber$…`) and the public
   TanStack Query API. An upgrade could break that lookup. It then fails explicitly with "no
   QueryClient found" (or "cache is empty") rather than passing.
5. **Testing is limited to Chrome on Windows.** That is headless Google Chrome 157 on Windows 11,
   with Node 24, against local services. Other browsers and operating systems (the Linux and
   macOS code paths have never been run), hosting platforms and live infrastructure are not
   covered.
6. **No application vulnerability has been established by the intentional mismatches.** In
   `dash-negative` (substituted response), `dash-wrong-header` and `b9-negative` (request
   deliberately sent with the other organization's header), the harness itself creates the
   mismatch. The test user is a legitimate member of both organizations, so a 200 for Org A's
   data is the backend answering correctly for that user. These scenarios prove that the checks
   detect contamination, not that the application produces it.

Other limitations:
- **B2 and B15 still use a request-count boundary** (`mark = requests.length`). Neither is
  exposed to the delivery-lag false positive: B2's mark comes before the first sign-in of the
  run, and B15 accepts header A or no header, which is all the previous (dual-user) session in A
  can have sent. Neither has a negative control.
- **Markup coupling.** The confirmation and switching logic depend on the switcher markup: a
  `<select>` whose options contain "Rehearsal Org". The race scenario depends on the
  `/audit-logs` navigation link. The dashboard sampler depends on the "Total Agents" and
  "Agents by Risk" labels.
- **One user, two directions.** The tested paths are a single dual-membership user choosing A
  and switching A to B (B5, B9, dashboard) and B back to A (B12, dashboard).
