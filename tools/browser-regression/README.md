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

  B12 is the corrected switch-back check described below.
- **B12: switching from Org B to Org A.** After the frontend has confirmed Org A, no newly issued
  request may carry Org B's `X-AgentHQ-Organization` header. B12 runs in four scenarios:

  | Scenario | What it does |
  |---|---|
  | `b12-normal` | Reload B's dashboard and switch as soon as the switcher appears, while B's queries are still in flight. |
  | `b12-inflight` | The same, but B's data requests are held at the network layer (CDP `Fetch`) across the switch and released only after confirmation. |
  | `b12-race` | Forces the historical false positive: header-B requests issued *before* the switch but reported by CDP *after* a request-count mark. The run passes only if the old (Step 105) algorithm fails on the same run while the corrected B12 passes. |
  | `b12-negative` | Negative control: inside the page, one post-confirmation request's organization header is rewritten to Org B. The run passes only if B12 fails on its post-confirmation assertion and names exactly that request. |

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
$H validate --tree "$TREE"            # 5. all four B12 scenarios (10 switches each) + core x3
$H run --tree "$TREE" b12-negative    #    or any subset: core b12-normal b12-inflight b12-race b12-negative
$H down                               # 6. stop containers, remove worktrees, delete every credential
```

- **Picking the tree.** `prepare-tree` prints the worktree path,
  `<state dir>/tree-<sha>`, as its last line. Pass it to `--tree`.
- **Testing another build** (for example a rollback candidate): run `prepare-tree --ref <sha>`,
  then `validate --tree <its path>`, against the same seeded database.
- **Options.**
  - `--iterations N`: switches per B12 scenario; the default is 10.
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

- **Database side effects.** A browser phase normally changes only the `audit_logs` table. On a
  fresh database, the first dashboard views may also populate `compliance_controls` and
  `risk_snapshots`.
- **Exit codes.** `validate` and `run` exit 0 only if every scenario passed.

## Interpreting a failure

Each B12 iteration prints its boundary, the request counts per phase, the `asserts` object and, on
failure, the offending requests, as `#seq@doc METHOD path hdr=<A|B|none> phase=<…> status=<…>`.

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
- **Test data.** Dual's extra memberships are provisioned directly through the application's
  models on the disposable database. The multi-membership flag is never enabled.
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

1. **The visible-data check is not yet proven by a negative control.** The injected request in
   `b12-negative` goes to an endpoint Org B's auditor cannot read (403), so no Org B data can
   render. The "no Org B data visible" text check has never been seen to fail.
2. **Browser delivery of stale responses is not covered.** In every run, the frontend cancelled
   all of B's in-flight requests before their responses could be delivered, so the late-response
   discard path is never reached in the browser. Forcing it would require changing application
   code. Frontend unit tests cover it, for example
   `frontend/src/auth/organizationSelection.test.tsx`: "never shows a late response from the
   previous organization".
3. **B5 and B9 still use the old request-count boundary** (`mark = requests.length`). They are
   exposed to the same CDP delivery-lag false positive and need the same timing-boundary review.
4. **Browser coverage is limited to the tested Chromium environment.** That is headless Google
   Chrome 157 on Windows, with Node 24, against local services. Other browsers, other operating
   systems, hosting platforms and live infrastructure are not covered.
5. **Non-Windows portability is unproven.** The Linux and macOS code paths have never been run.

Other limitations:
- **Markup coupling.** The confirmation and switching logic depend on the switcher markup: a
  `<select>` whose options contain "Rehearsal Org". The race scenario also depends on the
  `/audit-logs` navigation link.
- **One user, one direction.** The tested path is a single dual-membership user switching from
  B to A.
