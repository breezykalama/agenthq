// Step 111: repeatable B5 (session in A) and B9 (switch A -> B) over the Chrome DevTools Protocol.
// Each iteration is the suite's own sequence in a fresh sign-in: picker -> choose A -> Agents page
// (B5) -> switch to B -> dashboard -> Audit Logs (B9). Both are evaluated by issuance
// (b5b9_lib.mjs) and, for comparison, by the pre-Step-111 CDP list-index algorithm.
//   MODE=b5b9-normal    the suite's sequence
//   MODE=b5b9-inflight  header-A data requests of a reloaded A dashboard are held at the network
//                       layer (CDP Fetch) across the switch and released only after B is confirmed
//   MODE=b5b9-race      deterministic historical race: one page evaluation opens A's Audit Logs
//                       page, waits until its header-A requests are issued, then switches to B
//                       (issued before the switch, but after the CDP index mark)
//   MODE=b5-negative    one request in A's session is sent with Org B's header (simulated defect)
//   MODE=b9-negative    one request after the confirmed switch is sent with Org A's header
// ITERATIONS repeats the whole sequence. Passwords arrive through the environment and are never
// printed; only the organization header is recorded.
import { armAndSwitchJs, createLog, installProbe, quiesce, waitForConfirm } from "./b12_lib.mjs";
import { analyzeSession, analyzeSwitch, armAfter, armAndPickJs, legacyVerdict } from "./b5b9_lib.mjs";

const { APP_ORIGIN: APP, CDP_PORT, MODE, DUAL_EMAIL, DUAL_PW, ORG_A, ORG_B, ORG_C, ORG_D } = process.env;
const MODES = ["b5b9-normal", "b5b9-inflight", "b5b9-race", "b5-negative", "b9-negative"];
if (!MODES.includes(MODE)) throw new Error(`MODE must be one of ${MODES.join(", ")}`);
const ITERATIONS = Number(process.env.ITERATIONS ?? "5");
const HEADER = "x-agenthq-organization";
const labels = { [ORG_A]: "A", [ORG_B]: "B", [ORG_C]: "C", [ORG_D]: "D" };
const NEGATIVE = MODE.endsWith("-negative");

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
    if (holdOther && headers[HEADER] === ORG_A && !path.startsWith("/api/v1/auth/")) held.push({ requestId, path });
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
const expandNav = async () => {
  await evaluate("[...document.querySelectorAll('nav button[aria-expanded=\"false\"]')].forEach(b => b.click()); true");
  await sleep(300);
};
const clickNav = (text) =>
  evaluate(`(() => { const a = [...document.querySelectorAll('nav a')].find(e => e.innerText.includes(${JSON.stringify(text)}));
    if (!a) return false; a.click(); return true; })()`);
const showsA = (t) => t.includes("Agent A") || t.includes("Gateway A");
const RACE_PREAMBLE =
  "const s0 = window.__b12.state().seq; const link = [...document.querySelectorAll('nav a')].find(a => a.getAttribute('href') === '/audit-logs'); if (!link) return false; link.click(); for (let i = 0; i < 400 && window.__b12.state().seq === s0; i += 1) await new Promise(r => setTimeout(r, 5)); await new Promise(r => setTimeout(r, 30));";

await send("Page.enable");
await send("Runtime.enable");
await send("Network.enable");
await send("Network.setCacheDisabled", { cacheDisabled: true });
await installProbe(send);
if (MODE === "b5b9-inflight") await send("Fetch.enable", { patterns: [{ urlPattern: "*/api/v1/*", requestStage: "Request" }] });

const verdicts = [];
try {
  for (let i = 1; i <= ITERATIONS; i += 1) {
    // Fresh sign-in, as in the suite (B5 starts at the picker choice).
    await navigate(`${APP}/login`);
    await evaluate("localStorage.clear(); sessionStorage.clear(); true");
    await navigate(`${APP}/login`);
    await waitFor("!!document.querySelector('input[type=password]')", "login form");
    await evaluate(`(() => { const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      for (const [sel, val] of [['input[type=email]', ${JSON.stringify(DUAL_EMAIL)}], ['input[type=password]', ${JSON.stringify(DUAL_PW)}]]) {
        const el = document.querySelector(sel); set.call(el, val); el.dispatchEvent(new Event('input', { bubbles: true })); }
      [...document.querySelectorAll('button')].find(b => b.innerText.trim() === 'Sign in').click(); return true; })()`);
    await waitFor("document.body.innerText.includes('Choose an organization')", "picker");

    // --- Session in A (B5) ---
    const b5From = log.events.length;
    const b5LegacyMark = cdpRequests.length;
    if (!(await evaluate(armAndPickJs(ORG_A, "Rehearsal Org A", MODE === "b5-negative" ? { inject: ORG_B } : {})))) throw new Error("could not arm the picker choice");
    await waitFor(`location.pathname === '/dashboard' && ${selectedIs("Rehearsal Org A")}`, "dashboard in A");
    await expandNav();
    if (!(await clickNav("Agents"))) throw new Error("no Agents link in A");
    await waitFor("document.body.innerText.includes('Agent A')", "Agent A listed");
    const legacyB5 = legacyVerdict(cdpRequests, b5LegacyMark, ORG_A); // where the old B5 evaluated

    holdOther = MODE === "b5b9-inflight";
    held.length = 0;
    if (holdOther) {
      await navigate(`${APP}/dashboard`);
      await waitFor(selectedIs("Rehearsal Org A"), "switcher in A after reload");
      for (let t = 0; t < 100 && held.length < 3; t += 1) await sleep(50);
    }
    if (MODE === "b5b9-race") await expandNav();
    const since = MODE === "b5b9-race" ? await evaluate("(() => { const s = window.__b12.state(); return { doc: s.doc, seq: s.seq }; })()") : null;
    const heldCount = held.length;

    // --- Switch to B (B9) ---
    const b9From = log.events.length;
    const b9LegacyMark = cdpRequests.length;
    const armed = await evaluate(armAndSwitchJs(ORG_B, "Rehearsal Org B", MODE === "b9-negative" ? { inject: ORG_A } : {},
      MODE === "b5b9-race" ? RACE_PREAMBLE : ""));
    if (!armed) throw new Error("could not arm the switch to B");
    await waitForConfirm(log, b9From);
    let released = 0, releaseFailed = 0;
    const heldAtRelease = held.length;
    if (holdOther) {
      holdOther = false;
      for (const h of held.splice(0)) {
        try { await send("Fetch.continueRequest", { requestId: h.requestId }); released += 1; } catch { releaseFailed += 1; }
      }
    }
    await waitFor(`location.pathname === '/dashboard' && ${selectedIs("Rehearsal Org B")}`, "dashboard in B");
    await quiesce(log, cdpRequests);
    const b5 = analyzeSession(log, { start: armAfter(log, b5From), end: armAfter(log, b9From), org: ORG_A, labels, cdpRequests, since });
    await sleep(1500);
    const staleOnSwitch = showsA(await body());
    await expandNav();
    if (!(await clickNav("Audit Logs"))) throw new Error("no Audit Logs link in B");
    await waitFor("location.pathname === '/audit-logs'", "audit logs page in B");
    await sleep(1500);
    const staleOnAudit = showsA(await body());
    await quiesce(log, cdpRequests);
    const b9 = analyzeSwitch(log, b9From, { target: ORG_B, other: ORG_A, labels, cdpRequests, legacyMark: b9LegacyMark });
    await evaluate("window.__b12 ? window.__b12.reset() : true");

    console.log(`--- ${MODE} iteration ${i}/${ITERATIONS}`);
    for (const line of b5.lines) console.log(`      B5 ${line}`);
    console.log(`      B5 legacy (CDP index, at its old check point): ${legacyB5.ok ? "pass" : "FAIL"} over ${legacyB5.count} requests; corrected window: ${b5.counts?.scoped ?? 0}`);
    if (MODE === "b5b9-inflight") console.log(`      held header-A requests: ${heldCount} when the switch was armed, ${heldAtRelease} at B's confirmation; released after confirmation: ${released}; already cancelled by the page: ${releaseFailed}`);
    for (const line of b9.lines) console.log(`      B9 ${line}`);
    console.log(`      visible tenant data: A data after switch=${staleOnSwitch}, A data on B audit page=${staleOnAudit}`);
    const visibleOk = !staleOnSwitch && !staleOnAudit;
    const injectedIn = (a, hdr) => a.culprits.filter((c) => c.includes("INJECTED") && c.includes(`hdr=${hdr}`));
    if (MODE === "b5-negative") {
      const hit = injectedIn(b5, "B");
      const detected = !b5.ok && !b5.asserts.header && hit.length === 1 && b5.culprits.length === 1;
      console.log(`${detected ? "PASS" : "FAIL"}  B5 NEGATIVE CONTROL: corrected B5 ${b5.ok ? "PASSED (injection missed!)" : "FAILED as required"}; responsible request: ${hit[0] ?? "none"}; B9 on the same run: ${b9.ok ? "pass" : "FAIL"}`);
      verdicts.push(detected);
    } else if (MODE === "b9-negative") {
      const hit = injectedIn(b9, "A").filter((c) => c.includes("phase=post"));
      const detected = !b9.ok && !b9.asserts.post && hit.length === 1 && b9.culprits.length === 1;
      console.log(`${detected ? "PASS" : "FAIL"}  B9 NEGATIVE CONTROL: corrected B9 ${b9.ok ? "PASSED (injection missed!)" : "FAILED as required"}; responsible request: ${hit[0] ?? "none"}; B5 on the same run: ${b5.ok ? "pass" : "FAIL"}`);
      verdicts.push(detected);
    } else {
      const inflightOk = MODE !== "b5b9-inflight" || heldCount > 0;
      const raceOk = MODE !== "b5b9-race" || (b9.legacyFail && b5.asserts.lateIncluded);
      const ok = b5.ok && b9.ok && visibleOk && inflightOk;
      console.log(`${b5.ok ? "PASS" : "FAIL"}  B5 (corrected) iteration ${i}`);
      console.log(`${b9.ok ? "PASS" : "FAIL"}  B9 (corrected) iteration ${i}`);
      if (MODE === "b5b9-race") {
        console.log(`${b9.legacyFail ? "PASS" : "FAIL"}  race reproduced: pre-Step-111 B9 on the same run ${b9.legacyFail ? "FAILS (false positive)" : "passes (race not triggered)"}; header-A requests issued before the switch but recorded after the index mark: ${b9.legacyOther}`);
        console.log(`${b5.asserts.lateIncluded ? "PASS" : "FAIL"}  B5 window covers header-A requests issued just before the switch: ${b5.counts?.late ?? 0} (the old B5 had already been evaluated)`);
      }
      verdicts.push(ok && raceOk);
    }
  }
} catch (error) {
  console.log(`FAIL  ${MODE} run completed  [${error.message}]`);
  verdicts.push(false);
}
console.log(`${verdicts.filter(Boolean).length}/${verdicts.length} ${MODE} iterations passed; uncaught page exceptions: ${problems.length}`);
ws.close();
process.exit(verdicts.length && verdicts.every(Boolean) && (NEGATIVE || problems.length === 0) ? 0 : 1);
