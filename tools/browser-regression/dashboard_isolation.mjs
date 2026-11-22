// Step 113: rendered-dashboard and tenant-cache isolation, over the Chrome DevTools Protocol.
//
// The seed gives the two organizations deliberately different dashboard data (Org A 17 agents,
// Org B 3, with different risk mixes). Expected values come from the backend itself, fetched with
// an explicit organization header. The browser side is observed, never modified, except where a
// mode below says otherwise:
//   - a sampler injected into every document records every committed DOM state of the dashboard
//     (switcher selection, "Total Agents" card, "Agents by Risk" list), on every DOM mutation and
//     on a 20 ms poll, including frames that are never painted;
//   - the live TanStack Query cache is read through React's fiber tree (read-only), and the
//     previous organization's QueryClient is kept by reference to prove it was emptied.
//
//   MODE=dash-normal        A, switch to B, back to A, to B again, reload B: rendered values,
//                           transient frames and per-organization caches
//   MODE=dash-stale         a response to a request issued in A *before* the switch is held at the
//                           network layer and delivered after B is confirmed; the switch's first
//                           cancellation is suppressed in the page so the response really reaches
//                           the page's XMLHttpRequest (tests the client's stale-response defence)
//   MODE=dash-wrong-header  one request after the confirmed switch is sent with Org A's header
//                           (simulated frontend defect): A's real data comes back for B's query
//   MODE=dash-negative      negative control for the visible-data check: B's own dashboard summary
//                           response is replaced at the network layer with Org A's genuine one,
//                           while every request header stays correct
// Passwords and tokens arrive or are created in memory and are never printed. Only the
// organization header, method and path of requests are recorded.
import { analyze, armAndSwitchJs, createLog, installProbe, quiesce, waitForConfirm } from "./b12_lib.mjs";
import { armAndPickJs } from "./b5b9_lib.mjs";

const { APP_ORIGIN: APP, API_BASE: API, CDP_PORT, MODE, DUAL_EMAIL, DUAL_PW, ORG_A, ORG_B, ORG_C, ORG_D } = process.env;
const MODES = ["dash-normal", "dash-stale", "dash-wrong-header", "dash-negative"];
if (!MODES.includes(MODE)) throw new Error(`MODE must be one of ${MODES.join(", ")}`);
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(API ?? "")) throw new Error("API_BASE must be a loopback origin");
const ITERATIONS = Number(process.env.ITERATIONS ?? "5");
const HEADER = "x-agenthq-organization";
const SUMMARY = "/api/v1/dashboard/summary";
const BY_RISK = "/api/v1/dashboard/agents-by-risk";
const labels = { [ORG_A]: "A", [ORG_B]: "B", [ORG_C]: "C", [ORG_D]: "D" };
const ORG = { A: ORG_A, B: ORG_B };
const NAME = { A: "Rehearsal Org A", B: "Rehearsal Org B" };
const DESIGNED = { A: 17, B: 3 }; // harness.py SEED_AGENTS
const other = (x) => (x === "A" ? "B" : "A");

// --- Expected values, straight from the backend (explicit organization header) ---------------
async function api(path, token, org) {
  const res = await fetch(`${API}${path}`, { headers: { Authorization: `Bearer ${token}`, ...(org ? { [HEADER]: org } : {}) } });
  return { status: res.status, text: await res.text() };
}
const loginRes = await fetch(`${API}/api/v1/auth/login`, {
  method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ email: DUAL_EMAIL, password: DUAL_PW }),
});
if (loginRes.status !== 200) throw new Error(`API sign-in failed: ${loginRes.status}`);
const apiToken = (await loginRes.json()).access_token;
const riskLabels = (raw) => Object.fromEntries(Object.entries(raw).map(([k, v]) => [k.replace(/_/g, " "), String(v)]));
const expected = {};
for (const x of ["A", "B"]) {
  const s = await api(SUMMARY, apiToken, ORG[x]);
  const r = await api(BY_RISK, apiToken, ORG[x]);
  if (s.status !== 200 || r.status !== 200) throw new Error(`expected-value fetch for Org ${x}: summary ${s.status}, by-risk ${r.status}`);
  const summary = JSON.parse(s.text);
  const risk = JSON.parse(r.text);
  expected[x] = { total: String(summary.total_agents), totalNum: summary.total_agents, risk: riskLabels(risk), riskRaw: risk, summaryBody: s.text };
}
const designOk = expected.A.totalNum === DESIGNED.A && expected.B.totalNum === DESIGNED.B
  && JSON.stringify(expected.A.risk) !== JSON.stringify(expected.B.risk);
console.log(`expected (backend, explicit header): Org A Total Agents=${expected.A.total}, Agents by Risk=${JSON.stringify(expected.A.risk)}; ` +
  `Org B Total Agents=${expected.B.total}, Agents by Risk=${JSON.stringify(expected.B.risk)}`);
if (!designOk) throw new Error("seeded data is not the designed, distinguishable data (17 vs 3 agents, different risk mix)");

// --- Page-side observers (installed into every document) --------------------------------------
const SAMPLER = String.raw`(() => {
  if (window.__isoSampler) return;
  window.__isoSampler = true;
  const doc = Math.random().toString(36).slice(2, 10);
  let last = "";
  const read = () => {
    const s = [...document.querySelectorAll("select")].find((x) => [...x.options].some((o) => o.text.includes("Rehearsal Org")));
    const sel = s ? (s.options[s.selectedIndex]?.text ?? "") : null;
    const org = sel === null ? null : sel.includes("Rehearsal Org A") ? "A" : sel.includes("Rehearsal Org B") ? "B" : "other";
    let total = null, totalVisible = null;
    for (const d of document.querySelectorAll("div")) {
      if (d.childElementCount === 0 && d.textContent.trim() === "Total Agents" && d.nextElementSibling) {
        const v = d.nextElementSibling;
        total = v.textContent.trim();
        // Rendered to the user, not merely present in the DOM: displayed, not hidden, not
        // transparent, and with a non-empty box.
        const box = v.getBoundingClientRect();
        totalVisible = v.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true }) && box.width > 0 && box.height > 0;
        break;
      }
    }
    let risk = null;
    const h = [...document.querySelectorAll("h3")].find((x) => x.textContent.trim() === "Agents by Risk");
    if (h) {
      risk = {};
      for (const row of h.parentElement.querySelectorAll("div.flex")) {
        const sp = row.querySelectorAll("span");
        if (sp.length === 2) risk[sp[0].textContent.trim()] = sp[1].textContent.trim();
      }
    }
    return { org, path: location.pathname, total, totalVisible, risk };
  };
  const sample = (how) => {
    let r;
    try { r = read(); } catch { return; }
    const k = JSON.stringify(r);
    if (k === last) return;
    last = k;
    if (typeof window.__isoemit === "function") window.__isoemit(JSON.stringify({ doc, how, ...r }));
  };
  // Read-only access to the live TanStack Query client: walk React's fiber tree up to the
  // QueryClientProvider. Nothing in the application is changed.
  window.__isoFindClient = () => {
    for (const el of document.querySelectorAll("body *")) {
      const key = Object.keys(el).find((k) => k.startsWith("__reactFiber$"));
      if (!key) continue;
      for (let f = el[key]; f; f = f.return) {
        const c = f.memoizedProps && f.memoizedProps.client;
        if (c && typeof c.getQueryCache === "function") return c;
      }
    }
    return null;
  };
  new MutationObserver(() => sample("dom")).observe(document, { subtree: true, childList: true, characterData: true, attributes: true });
  setInterval(() => sample("poll"), 20);
})();`;

const CACHE_JS = `(() => {
  const c = window.__isoFindClient && window.__isoFindClient();
  if (!c) return { found: false };
  const queries = c.getQueryCache().getAll().map((q) => ({
    hash: q.queryHash, key: String(q.queryKey[0]), status: q.state.status,
    total: q.state.data && typeof q.state.data === "object" ? q.state.data.total_agents ?? null : null,
    risk: q.queryKey[0] === "agents-by-risk" ? q.state.data ?? null : undefined,
  }));
  const prev = window.__isoPrev || null;
  return { found: true, queries, prevSize: prev ? prev.getQueryCache().getAll().length : null, samePrev: prev ? prev === c : null };
})()`;
const KEEP_PREV_JS = "(() => { window.__isoPrev = window.__isoFindClient && window.__isoFindClient(); return !!window.__isoPrev; })()";
// dash-stale only: let exactly one AbortController.abort() call (the context switch's
// cancellation of the previous organization's requests) do nothing, so the held response can
// reach the page. Restored immediately after the switch is confirmed.
const SUPPRESS_JS = `(() => {
  const orig = AbortController.prototype.abort;
  window.__isoSuppress = { used: false, restore: () => { AbortController.prototype.abort = orig; } };
  AbortController.prototype.abort = function (...args) {
    if (!window.__isoSuppress.used) { window.__isoSuppress.used = true; return; }
    return orig.apply(this, args);
  };
  return true; })()`;

// --- CDP plumbing -------------------------------------------------------------------------------
const page = (await (await fetch(`http://127.0.0.1:${CDP_PORT}/json/list`)).json()).find((t) => t.type === "page");
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((resolve) => ws.addEventListener("open", resolve, { once: true }));
let nextId = 0;
const pending = new Map();
const cdpRequests = [];
const seenIds = new Set();
const log = createLog();
const samples = [];
const problems = [];
const net = { holdStale: false, held: [], substitute: false, substituted: null };
ws.addEventListener("message", (event) => {
  const msg = JSON.parse(event.data);
  if (msg.id && pending.has(msg.id)) {
    pending.get(msg.id)(msg);
    pending.delete(msg.id);
    return;
  }
  log.onMessage(msg);
  if (msg.method === "Runtime.bindingCalled" && msg.params.name === "__isoemit") samples.push(JSON.parse(msg.params.payload));
  if (msg.method === "Network.requestWillBeSent") {
    const { request } = msg.params;
    if (request.url.includes("/api/") && request.method !== "OPTIONS" && !seenIds.has(msg.params.requestId)) {
      seenIds.add(msg.params.requestId);
      const headers = Object.fromEntries(Object.entries(request.headers).map(([k, v]) => [k.toLowerCase(), v]));
      cdpRequests.push({ id: msg.params.requestId, method: request.method, url: new URL(request.url).pathname, org: headers[HEADER] ?? null });
    }
  }
  if (msg.method === "Fetch.requestPaused") onPaused(msg.params);
  if (msg.method === "Runtime.exceptionThrown") problems.push(msg.params.exceptionDetails.text);
});
const send = (method, params = {}) =>
  new Promise((resolve, reject) => {
    const id = ++nextId;
    pending.set(id, (msg) => (msg.error ? reject(new Error(`${method}: ${msg.error.message}`)) : resolve(msg.result)));
    ws.send(JSON.stringify({ id, method, params }));
  });
const continuePaused = (requestId) => send("Fetch.continueResponse", { requestId }).catch(() => send("Fetch.continueRequest", { requestId }));
function onPaused(p) {
  const headers = Object.fromEntries(Object.entries(p.request.headers).map(([k, v]) => [k.toLowerCase(), v]));
  const path = new URL(p.request.url).pathname;
  const hdr = headers[HEADER] ?? null;
  if (p.request.method === "GET" && path === SUMMARY && p.responseStatusCode !== undefined) {
    if (net.holdStale && hdr === ORG_A) {
      net.held.push({ requestId: p.requestId, status: p.responseStatusCode });
      return;
    }
    if (net.substitute && !net.substituted && hdr === ORG_B && p.responseStatusCode === 200) {
      net.substituted = { hdr: "B", originalStatus: p.responseStatusCode };
      const responseHeaders = (p.responseHeaders ?? []).filter((h) => !["content-length", "content-encoding"].includes(h.name.toLowerCase()));
      send("Fetch.fulfillRequest", {
        requestId: p.requestId, responseCode: 200, responseHeaders,
        body: Buffer.from(expected.A.summaryBody, "utf8").toString("base64"),
      }).catch((e) => problems.push(`substitution failed: ${e.message}`));
      return;
    }
  }
  continuePaused(p.requestId).catch(() => {});
}
const evaluate = async (expression) => {
  const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.text);
  return r.result.value;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitFor(js, what, timeout = 15000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    try {
      if (await evaluate(js)) return true;
    } catch {
      /* navigating */
    }
    await sleep(100);
  }
  throw new Error(`timed out waiting for ${what}`);
}
const navigate = async (url) => {
  await send("Page.navigate", { url });
  await waitFor("document.readyState === 'complete'", `load ${url}`);
};
const selectedIs = (name) => `[...document.querySelectorAll('select')].some(s => s.options[s.selectedIndex]?.text.includes(${JSON.stringify(name)}))`;

// --- Assertions -----------------------------------------------------------------------------------
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const shows = (s, x) => s.path === "/dashboard" && s.org === x && s.total === expected[x].total && same(s.risk, expected[x].risk);
/**
 * Visible-data assertion. A dashboard frame whose switcher shows one organization must never show
 * the other's value for either field; while switching away from `origin`, a frame that shows no
 * organization must not show `origin`'s values either. Returns *distinct* violations (selected
 * organization, field, expected, observed), each with the number of recorded frames it was seen
 * in, so one contamination recorded in several DOM frames counts once.
 */
function visibleViolations(list, { origin = null } = {}) {
  const found = new Map();
  const add = (v) => {
    const key = `${v.selected}|${v.field}|${v.expected}|${v.observed}`;
    if (found.has(key)) found.get(key).frames += 1;
    else found.set(key, { ...v, frames: 1 });
  };
  const fields = (s, y, selected, exp) => {
    if (s.total !== null && s.total === expected[y].total)
      add({ selected, field: `Total Agents (GET ${SUMMARY} total_agents)`, expected: exp ? exp.total : "(no organization's value)", observed: s.total, belongsTo: NAME[y] });
    if (s.risk && same(s.risk, expected[y].risk))
      add({ selected, field: `Agents by Risk (GET ${BY_RISK})`, expected: exp ? JSON.stringify(exp.risk) : "(no organization's value)", observed: JSON.stringify(s.risk), belongsTo: NAME[y] });
  };
  for (const s of list) {
    if (s.path !== "/dashboard") continue;
    if (s.org === "A" || s.org === "B") fields(s, other(s.org), NAME[s.org], expected[s.org]);
    else if (origin) fields(s, origin, `(none shown; switching away from ${NAME[origin]})`, null);
  }
  return [...found.values()];
}
/** Compact sequence of distinct dashboard states: <switcher org>/<Total Agents> ("-" = not shown). */
const trace = (frames) => {
  const t = frames.map((s) => `${s.org ?? "none"}/${s.path === "/dashboard" ? s.total ?? "-" : s.path}`).filter((x, i, a) => i === 0 || x !== a[i - 1]);
  return t.length > 14 ? [...t.slice(0, 7), "...", ...t.slice(-6)].join(" > ") : t.join(" > ");
};
const fmtViolation = (v) => `selected organization=${v.selected}; field=${v.field}; expected=${v.expected}; observed=${v.observed} (${v.belongsTo}'s value); seen in ${v.frames} recorded frame(s)`;
/** Tenant-cache assertion on the live QueryClient of organization x. */
async function cacheCheck(x, { afterSwitch }) {
  const c = await evaluate(CACHE_JS);
  const y = other(x);
  const problemsHere = [];
  if (!c.found) return { ok: false, lines: ["no QueryClient found in the React tree"] };
  if (c.queries.length === 0) problemsHere.push("cache is empty");
  const foreign = c.queries.filter((q) => !q.hash.includes(`:${ORG[x]}:`) || q.hash.includes(ORG[y]));
  if (foreign.length) problemsHere.push(`queries not keyed to Org ${x}'s context: ${foreign.map((q) => q.key).join(",")}`);
  const sum = c.queries.find((q) => q.key === "dashboard-summary");
  const risk = c.queries.find((q) => q.key === "agents-by-risk");
  if (!sum || sum.status !== "success" || sum.total !== expected[x].totalNum) problemsHere.push(`dashboard-summary cached total_agents=${sum?.total ?? "absent"} (${sum?.status ?? "-"}), expected ${expected[x].totalNum}`);
  if (!risk || !same(risk.risk, expected[x].riskRaw)) problemsHere.push(`agents-by-risk cached ${JSON.stringify(risk?.risk ?? null)}, expected ${JSON.stringify(expected[x].riskRaw)}`);
  if (afterSwitch && !(c.prevSize === 0 && c.samePrev === false)) problemsHere.push(`previous organization's QueryClient: still ${c.prevSize} queries, same client=${c.samePrev}`);
  return {
    ok: problemsHere.length === 0,
    lines: [`cache (Org ${x}): ${c.queries.length} queries, all keyed to Org ${x}'s context=${foreign.length === 0}; summary total_agents=${sum?.total ?? "-"}; ` +
      `previous client ${afterSwitch ? `emptied=${c.prevSize === 0}, replaced=${c.samePrev === false}` : "n/a (new document)"}` +
      (problemsHere.length ? `; PROBLEMS: ${problemsHere.join("; ")}` : "")],
  };
}
async function settle(x, what, timeout = 15000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    const s = samples[samples.length - 1];
    if (s && shows(s, x)) return s;
    await sleep(50);
  }
  const s = samples[samples.length - 1];
  throw new Error(`timed out waiting for ${what}; last frame: ${JSON.stringify(s ?? null)}`);
}
/**
 * B12 classification of one switch (destination x). Waits until the probe and Chrome agree on the
 * request count first, as every other scenario does, and prints the full analysis (asserts,
 * offending requests, any probe/CDP mismatch) whenever it does not pass.
 */
const headerCheck = async (from, x = "B", { quiet = false } = {}) => {
  const opts = { target: ORG[x], other: ORG[other(x)], labels, cdpRequests };
  const early = analyze(log, from, opts); // diagnostic only: before the two streams agree
  await quiesce(log, cdpRequests);
  const a = analyze(log, from, opts);
  if (!early.ok && a.ok && !quiet) console.log(`      header analysis before probe and Chrome agreed (not a verdict): ${early.lines.find((l) => l.startsWith("asserts")) ?? ""}`);
  if (!a.ok && !quiet) for (const line of a.lines) console.log(`      header analysis: ${line}`);
  return a;
};
async function signInAndChooseA() {
  await navigate(`${APP}/login`);
  await evaluate("localStorage.clear(); sessionStorage.clear(); true");
  await navigate(`${APP}/login`);
  await waitFor("!!document.querySelector('input[type=password]')", "login form");
  await evaluate(`(() => { const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    for (const [sel, val] of [['input[type=email]', ${JSON.stringify(DUAL_EMAIL)}], ['input[type=password]', ${JSON.stringify(DUAL_PW)}]]) {
      const el = document.querySelector(sel); set.call(el, val); el.dispatchEvent(new Event('input', { bubbles: true })); }
    [...document.querySelectorAll('button')].find(b => b.innerText.trim() === 'Sign in').click(); return true; })()`);
  await waitFor("document.body.innerText.includes('Choose an organization')", "picker");
  if (!(await evaluate(armAndPickJs(ORG_A, NAME.A)))) throw new Error("could not choose Org A");
  return settle("A", "Org A's dashboard after the picker");
}
/** Switch from the current organization to x; returns the new frames and the header analysis start. */
async function switchTo(x, options = {}) {
  await evaluate(KEEP_PREV_JS);
  const from = log.events.length;
  const frameFrom = samples.length;
  if (!(await evaluate(armAndSwitchJs(ORG[x], NAME[x], options)))) throw new Error(`could not switch to Org ${x}`);
  await waitForConfirm(log, from);
  return { from, frameFrom };
}

await send("Page.enable");
await send("Runtime.enable");
await send("Network.enable");
await send("Network.setCacheDisabled", { cacheDisabled: true });
await installProbe(send);
await send("Runtime.addBinding", { name: "__isoemit" });
await send("Page.addScriptToEvaluateOnNewDocument", { source: SAMPLER });
if (MODE === "dash-stale" || MODE === "dash-negative")
  await send("Fetch.enable", { patterns: [{ urlPattern: `*${SUMMARY}*`, requestStage: "Response" }] });

const verdicts = [];
const report = (ok, text) => console.log(`${ok ? "PASS" : "FAIL"}  ${text}`);
try {
  for (let i = 1; i <= ITERATIONS; i += 1) {
    console.log(`--- ${MODE} iteration ${i}/${ITERATIONS}`);
    const pick = await signInAndChooseA();
    let ok = true;
    const step = (cond, text) => { report(cond, text); ok = ok && cond; };
    step(shows(pick, "A"), `C1 Org A shows its own values: Total Agents=${pick.total}, Agents by Risk=${JSON.stringify(pick.risk)}`);

    if (MODE === "dash-normal") {
      let c = await cacheCheck("A", { afterSwitch: false });
      c.lines.forEach((l) => console.log(`      ${l}`));
      step(c.ok, "C7 Org A's query cache holds only Org A's data");
      for (const [label, x] of [["C2/C3 A -> B", "B"], ["C4 B -> A", "A"], ["C5 A -> B again", "B"]]) {
        const { from, frameFrom } = await switchTo(x);
        const end = await settle(x, `Org ${x}'s dashboard`);
        await sleep(1000);
        const frames = samples.slice(frameFrom);
        const bad = visibleViolations(frames, { origin: other(x) });
        const hdr = await headerCheck(from, x);
        console.log(`      ${label} frames: ${trace(frames)}`);
        console.log(`      ${label}: ${frames.length} distinct frames recorded; final Total Agents=${end.total}, Agents by Risk=${JSON.stringify(end.risk)}; request headers ok=${hdr.ok}`);
        bad.slice(0, 3).forEach((v) => console.log(`      VISIBLE-DATA VIOLATION: ${fmtViolation(v)}`));
        step(bad.length === 0 && shows(samples[samples.length - 1], x), `${label}: no frame shows Org ${other(x)}'s values under Org ${x}; Org ${x}'s values restored`);
        c = await cacheCheck(x, { afterSwitch: true });
        c.lines.forEach((l) => console.log(`      ${l}`));
        step(c.ok, `C7 after ${label}: Org ${x}'s cache is distinct and the previous organization's cache was emptied`);
        step(hdr.ok, `${label}: request headers (B12 classification) clean`);
      }
      const frameFrom = samples.length;
      await navigate(`${APP}/dashboard`);
      const end = await settle("B", "Org B's dashboard after reload");
      await sleep(1000);
      const bad = visibleViolations(samples.slice(frameFrom));
      console.log(`      C6 reload frames: ${trace(samples.slice(frameFrom))}`);
      bad.slice(0, 3).forEach((v) => console.log(`      VISIBLE-DATA VIOLATION: ${fmtViolation(v)}`));
      step(bad.length === 0 && (await evaluate(selectedIs(NAME.B))), `C6 reload keeps Org B and shows only Org B's values (Total Agents=${end.total})`);
      c = await cacheCheck("B", { afterSwitch: false });
      c.lines.forEach((l) => console.log(`      ${l}`));
      step(c.ok, "C7 after reload: Org B's cache holds only Org B's data");
    }

    if (MODE === "dash-stale") {
      net.held.length = 0;
      net.holdStale = true;
      await navigate(`${APP}/dashboard`); // Org A's dashboard again: its summary response is held
      await waitFor(selectedIs(NAME.A), "switcher in A");
      for (let t = 0; t < 100 && net.held.length < 1; t += 1) await sleep(50);
      const heldCount = net.held.length;
      await evaluate(SUPPRESS_JS);
      const { from, frameFrom } = await switchTo("B");
      const suppressed = await evaluate("window.__isoSuppress.used");
      await evaluate("window.__isoSuppress.restore(); true");
      net.holdStale = false;
      await settle("B", "Org B's dashboard");
      const arm = log.events.slice(from).find((e) => e.type === "arm");
      const staleReqs = log.events.filter((e) => e.type === "req" && e.doc === arm.doc && e.seq <= arm.seq && e.path === SUMMARY && e.org === ORG_A);
      for (const h of net.held.splice(0)) await continuePaused(h.requestId).catch(() => {});
      let delivered = [];
      for (let t = 0; t < 100; t += 1) {
        delivered = log.events.filter((e) => e.type === "end" && e.doc === arm.doc && staleReqs.some((r) => r.seq === e.seq) && e.status === 200 && e.phaseAtEnd === "post");
        if (delivered.length) break;
        await sleep(50);
      }
      await sleep(1500);
      const frames = samples.slice(frameFrom);
      const bad = visibleViolations(frames, { origin: "A" });
      const final = samples[samples.length - 1];
      console.log(`      held Org A summary responses: ${heldCount}; first cancellation suppressed: ${suppressed}; ` +
        `delivered to the page's XMLHttpRequest after Org B was confirmed: ${delivered.length} (status ${delivered.map((d) => d.status).join(",") || "-"})`);
      console.log(`      frames: ${trace(frames)}`);
      bad.slice(0, 3).forEach((v) => console.log(`      VISIBLE-DATA VIOLATION: ${fmtViolation(v)}`));
      step(heldCount > 0 && suppressed && delivered.length > 0, "D2 Org A's pre-switch response actually reached the page after the switch (scenario exercised)");
      step(bad.length === 0 && shows(final, "B"), `D2 Org A's late response never appears under Org B (final Total Agents=${final.total})`);
      const c = await cacheCheck("B", { afterSwitch: true });
      c.lines.forEach((l) => console.log(`      ${l}`));
      step(c.ok, "D2 Org B's cache does not contain the late Org A response; Org A's old cache stays empty");
      const hdr = await headerCheck(from);
      step(hdr.ok, "D2 request headers (B12 classification) clean");
    }

    if (MODE === "dash-wrong-header") {
      const { from, frameFrom } = await switchTo("B", { inject: ORG_A });
      await sleep(3000);
      const hdr = await headerCheck(from);
      const injected = hdr.culprits.filter((c) => c.includes("INJECTED") && c.includes("hdr=A"));
      const bad = visibleViolations(samples.slice(frameFrom), { origin: "A" });
      console.log(`      injected request: ${injected[0] ?? "none"}`);
      console.log(`      frames: ${trace(samples.slice(frameFrom))}`);
      bad.slice(0, 2).forEach((v) => console.log(`      VISIBLE-DATA VIOLATION: ${fmtViolation(v)}`));
      // Expected outcome: both assertions fail. The mode passes only if both detect it.
      step(!hdr.ok && !hdr.asserts.post && injected.length === 1, "D1 request-header assertion detects the request sent with Org A's header");
      step(bad.length > 0, `D1 visible-data assertion detects Org A's data rendered under Org B (${bad.length} distinct violation(s))`);
    }

    if (MODE === "dash-negative") {
      net.substituted = null;
      net.substitute = true;
      const { from, frameFrom } = await switchTo("B");
      await sleep(3000);
      net.substitute = false;
      const hdr = await headerCheck(from);
      const bad = visibleViolations(samples.slice(frameFrom), { origin: "A" });
      const total = bad.filter((v) => v.field.startsWith("Total Agents") && v.selected === NAME.B && v.expected === expected.B.total && v.observed === expected.A.total);
      const final = samples[samples.length - 1];
      // The contamination must really be on screen (displayed, visible, non-empty box) and stay
      // there, not merely appear in one DOM mutation.
      const rendered = final.path === "/dashboard" && final.org === "B" && final.total === expected.A.total && final.totalVisible === true;
      console.log(`      substituted: ${net.substituted ? "Org B's own summary response replaced with Org A's genuine one (request header stayed B)" : "NOT substituted"}`);
      console.log(`      frames: ${trace(samples.slice(frameFrom))}`);
      total.slice(0, 1).forEach((v) => console.log(`      VISIBLE-DATA FAIL (expected): ${fmtViolation(v)}`));
      const c = await cacheCheck("B", { afterSwitch: true });
      c.lines.forEach((l) => console.log(`      ${l}`));
      step(Boolean(net.substituted), "E substitution delivered to the page");
      step(rendered, `E Org A's value is actually rendered and still on screen under Org B after 3 s (final frame: ${final.org}/${final.total}, visible=${final.totalVisible})`);
      step(total.length === 1 && bad.length === 1, `E NEGATIVE CONTROL: visible-data assertion FAILS on exactly the substituted field and names organization, field, expected and observed value (${bad.length} distinct violation(s))`);
      step(!c.ok && c.lines.join(" ").includes(`dashboard-summary cached total_agents=${expected.A.totalNum}`), "E cache-isolation assertion also detects Org A's summary cached under Org B");
      step(hdr.ok, "E request-header assertion still passes on the same run (the visible failure is not a header failure)");
    }
    await evaluate("window.__b12 ? window.__b12.reset() : true");
    verdicts.push(ok);
  }
} catch (error) {
  console.log(`FAIL  ${MODE} run completed  [${error.message}]`);
  verdicts.push(false);
}
console.log(`${verdicts.filter(Boolean).length}/${verdicts.length} ${MODE} iterations passed; uncaught page exceptions: ${problems.length}${problems.length ? ` (${problems.slice(0, 2).join("; ")})` : ""}`);
ws.close();
const exceptionsMatter = MODE === "dash-normal" || MODE === "dash-stale";
process.exit(verdicts.length && verdicts.every(Boolean) && (!exceptionsMatter || problems.length === 0) ? 0 : 1);
