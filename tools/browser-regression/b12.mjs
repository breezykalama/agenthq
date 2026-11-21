// Step 108: repeatable B12 (organization switch B -> A) over the Chrome DevTools Protocol.
//   MODE=b12-normal    the Step 105 B12 sequence (reload B's dashboard, switch immediately)
//   MODE=b12-inflight  same, but header-B data requests are held at the network layer (CDP Fetch)
//                      across the switch and released only after confirmation
//   MODE=b12-race      deterministic Step 105 false positive: after B settles, one page evaluation
//                      opens B's Audit Logs page, waits until its header-B requests are issued,
//                      then switches (they are issued before the switch but after the index mark)
//   MODE=b12-negative  same as normal, with one post-confirmation request's organization header
//                      rewritten to Org B inside the page (a simulated frontend defect)
// ITERATIONS repeats the switch in one signed-in browser session. Passwords arrive through the
// environment and are never printed; only the organization header is recorded.
import { analyze, armAndSwitchJs, createLog, installProbe, quiesce, waitForConfirm } from "./b12_lib.mjs";

const { APP_ORIGIN: APP, CDP_PORT, MODE, DUAL_EMAIL, DUAL_PW, ORG_A, ORG_B, ORG_C, ORG_D } = process.env;
const ITERATIONS = Number(process.env.ITERATIONS ?? "5");
const HEADER = "x-agenthq-organization";
const labels = { [ORG_A]: "A", [ORG_B]: "B", [ORG_C]: "C", [ORG_D]: "D" };

const page = (await (await fetch(`http://127.0.0.1:${CDP_PORT}/json/list`)).json()).find((t) => t.type === "page");
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((resolve) => ws.addEventListener("open", resolve, { once: true }));
let nextId = 0;
const pending = new Map();
const cdpRequests = [];
const seenIds = new Set();
const log = createLog();
const problems = [];
let holdOther = false;
const held = [];
ws.addEventListener("message", (event) => {
  const msg = JSON.parse(event.data);
  if (msg.id && pending.has(msg.id)) {
    pending.get(msg.id)(msg);
    pending.delete(msg.id);
    return;
  }
  log.onMessage(msg);
  if (msg.method === "Network.requestWillBeSent") {
    const { request } = msg.params;
    if (request.url.includes("/api/") && request.method !== "OPTIONS" && !seenIds.has(msg.params.requestId)) {
      seenIds.add(msg.params.requestId);
      const headers = Object.fromEntries(Object.entries(request.headers).map(([k, v]) => [k.toLowerCase(), v]));
      cdpRequests.push({ id: msg.params.requestId, method: request.method, url: new URL(request.url).pathname, org: headers[HEADER] ?? null });
    }
  }
  if (msg.method === "Fetch.requestPaused") {
    const { request, requestId } = msg.params;
    const headers = Object.fromEntries(Object.entries(request.headers).map(([k, v]) => [k.toLowerCase(), v]));
    const path = new URL(request.url).pathname;
    if (holdOther && headers[HEADER] === ORG_B && !path.startsWith("/api/v1/auth/")) held.push({ requestId, path });
    else send("Fetch.continueRequest", { requestId }).catch(() => {});
  }
  if (msg.method === "Runtime.exceptionThrown") problems.push(msg.params.exceptionDetails.text);
});
const send = (method, params = {}) =>
  new Promise((resolve, reject) => {
    const id = ++nextId;
    pending.set(id, (msg) => (msg.error ? reject(new Error(`${method}: ${msg.error.message}`)) : resolve(msg.result)));
    ws.send(JSON.stringify({ id, method, params }));
  });
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
const body = () => evaluate("document.body ? document.body.innerText : ''");

await send("Page.enable");
await send("Runtime.enable");
await send("Network.enable");
await send("Network.setCacheDisabled", { cacheDisabled: true });
await installProbe(send);
if (MODE === "b12-inflight") await send("Fetch.enable", { patterns: [{ urlPattern: "*/api/v1/*", requestStage: "Request" }] });

const verdicts = [];
try {
  await navigate(`${APP}/login`);
  await evaluate("localStorage.clear(); sessionStorage.clear(); true");
  await navigate(`${APP}/login`);
  await waitFor("!!document.querySelector('input[type=password]')", "login form");
  await evaluate(`(() => { const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    for (const [sel, val] of [['input[type=email]', ${JSON.stringify(DUAL_EMAIL)}], ['input[type=password]', ${JSON.stringify(DUAL_PW)}]]) {
      const el = document.querySelector(sel); set.call(el, val); el.dispatchEvent(new Event('input', { bubbles: true })); }
    [...document.querySelectorAll('button')].find(b => b.innerText.trim() === 'Sign in').click(); return true; })()`);
  await waitFor("document.body.innerText.includes('Choose an organization')", "picker");
  await evaluate(`[...document.querySelectorAll('ul[aria-label="Your organizations"] button')].find(b => b.innerText.includes('Rehearsal Org B')).click()`);
  await waitFor(`location.pathname === '/dashboard' && ${selectedIs("Rehearsal Org B")}`, "dashboard in B");

  for (let i = 1; i <= ITERATIONS; i += 1) {
    await evaluate("window.__b12 ? window.__b12.reset() : true");
    if (!(await evaluate(selectedIs("Rehearsal Org B")))) {
      await evaluate(`(() => { const s = [...document.querySelectorAll('select')].find(x => x.innerText.includes('Rehearsal Org'));
        Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(s, ${JSON.stringify(ORG_B)});
        s.dispatchEvent(new Event('change', { bubbles: true })); return true; })()`);
      await waitFor(`location.pathname === '/dashboard' && ${selectedIs("Rehearsal Org B")}`, "back in B");
      await sleep(1000);
    }
    // As in the Step 105 B12: reload B's dashboard and switch as soon as the switcher is present,
    // while B's dashboard queries are still being issued / in flight.
    holdOther = MODE === "b12-inflight";
    held.length = 0;
    await navigate(`${APP}/dashboard`);
    await waitFor(selectedIs("Rehearsal Org B"), "switcher in B");
    if (holdOther) {
      for (let t = 0; t < 100 && held.length < 3; t += 1) await sleep(50);
    }
    if (MODE === "b12-race") {
      await quiesce(log, cdpRequests);
      await evaluate("[...document.querySelectorAll('nav button[aria-expanded=\"false\"]')].forEach(b => b.click()); true");
      await sleep(300);
    }
    const heldCount = held.length;
    const from = log.events.length;
    const legacyMark = cdpRequests.length;
    const armed = await evaluate(armAndSwitchJs(ORG_A, "Rehearsal Org A", MODE === "b12-negative" ? { inject: ORG_B } : {},
      MODE === "b12-race" ? "const s0 = window.__b12.state().seq; const link = [...document.querySelectorAll('nav a')].find(a => a.getAttribute('href') === '/audit-logs'); if (!link) return false; link.click(); for (let i = 0; i < 400 && window.__b12.state().seq === s0; i += 1) await new Promise(r => setTimeout(r, 5)); await new Promise(r => setTimeout(r, 30));" : ""));
    if (!armed) throw new Error("could not arm the switch");
    await waitForConfirm(log, from);
    let released = 0, releaseFailed = 0;
    if (holdOther) {
      holdOther = false;
      for (const h of held.splice(0)) {
        try { await send("Fetch.continueRequest", { requestId: h.requestId }); released += 1; } catch { releaseFailed += 1; }
      }
    }
    await sleep(1500);
    const afterSwitch = await body();
    const staleOnSwitch = afterSwitch.includes("Agent B") || afterSwitch.includes("Gateway B");
    const shownA = await evaluate(selectedIs("Rehearsal Org A"));
    await navigate(`${APP}/agents`);
    let agentsOk = false;
    try { await waitFor("document.body.innerText.includes('Agent A')", "Agent A"); agentsOk = true; } catch { /* reported */ }
    const agentsText = await body();
    const staleOnAgents = agentsText.includes("Agent B") || agentsText.includes("Gateway B");
    await quiesce(log, cdpRequests);
    const a = analyze(log, from, { target: ORG_A, other: ORG_B, labels, cdpRequests, legacyMark });
    const visibleOk = shownA && agentsOk && !staleOnSwitch && !staleOnAgents;
    console.log(`--- ${MODE} iteration ${i}/${ITERATIONS}`);
    if (MODE === "b12-inflight") console.log(`      held header-B requests across the switch: ${heldCount}; released after confirmation: ${released}; already cancelled by the page: ${releaseFailed}`);
    for (const line of a.lines) console.log(`      ${line}`);
    console.log(`      visible tenant data: switcher A=${shownA}, A agents listed=${agentsOk}, B data after switch=${staleOnSwitch}, B data on agents page=${staleOnAgents}`);
    if (MODE === "b12-negative") {
      const injected = a.culprits.filter((c) => c.includes("INJECTED") && c.includes("hdr=B") && c.includes("phase=post"));
      const detected = !a.ok && !a.asserts.post && injected.length === 1;
      console.log(`${detected ? "PASS" : "FAIL"}  NEGATIVE CONTROL: corrected B12 ${a.ok ? "PASSED (injection missed!)" : "FAILED as required"}; responsible request identified: ${injected[0] ?? "none"}`);
      verdicts.push(detected);
    } else {
      const ok = a.ok && visibleOk && (MODE !== "b12-inflight" || heldCount > 0);
      console.log(`${ok ? "PASS" : "FAIL"}  B12 (corrected) iteration ${i}`);
      if (MODE === "b12-race") console.log(`${a.legacyFail ? "PASS" : "FAIL"}  race reproduced: Step 105 B12 on the same run ${a.legacyFail ? "FAILS (false positive)" : "passes (race not triggered)"}; header-B requests issued before the switch but recorded after the index mark: ${a.legacyOther}`);
      verdicts.push(ok && (MODE !== "b12-race" || a.legacyFail));
    }
  }
} catch (error) {
  console.log(`FAIL  ${MODE} run completed  [${error.message}]`);
  verdicts.push(false);
}
console.log(`${verdicts.filter(Boolean).length}/${verdicts.length} ${MODE} iterations passed; uncaught page exceptions: ${problems.length}`);
ws.close();
process.exit(verdicts.length && verdicts.every(Boolean) && (MODE === "b12-negative" || problems.length === 0) ? 0 : 1);
