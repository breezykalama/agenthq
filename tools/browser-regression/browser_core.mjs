// Real-browser check of the rollback frontend against the rollback backend, over the Chrome
// DevTools Protocol (Node's built-in WebSocket; nothing installed). Credentials arrive through
// environment variables and are never printed.
import { analyze, armAndSwitchJs, createLog, installProbe, quiesce, waitForConfirm } from "./b12_lib.mjs";

const APP = process.env.APP_ORIGIN;
const HEADER = "x-agenthq-organization";
const { DUAL_EMAIL, DUAL_PW, SINGLE_EMAIL, SINGLE_PW, ORG_A, ORG_B, ORG_C, ORG_D, CDP_PORT } = process.env;

const results = [];
const check = (name, ok, detail = "") => {
  results.push({ name, ok: Boolean(ok) });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  [${detail}]` : ""}`);
};

const targets = await (await fetch(`http://127.0.0.1:${CDP_PORT}/json/list`)).json();
const page = targets.find((t) => t.type === "page");
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((resolve) => ws.addEventListener("open", resolve, { once: true }));
let nextId = 0;
const pending = new Map();
const requests = [];
const problems = [];
const b12log = createLog();
ws.addEventListener("message", (event) => {
  const msg = JSON.parse(event.data);
  if (msg.id && pending.has(msg.id)) {
    pending.get(msg.id)(msg);
    pending.delete(msg.id);
    return;
  }
  b12log.onMessage(msg);
  if (msg.method === "Network.requestWillBeSent") {
    const { request } = msg.params;
    if (request.url.includes("/api/") && request.method !== "OPTIONS") {
      const headers = Object.fromEntries(Object.entries(request.headers).map(([k, v]) => [k.toLowerCase(), v]));
      requests.push({ id: msg.params.requestId, method: request.method, url: new URL(request.url).pathname, org: headers[HEADER] ?? null, wall: msg.params.wallTime * 1000 });
    }
  }
  if (msg.method === "Network.responseReceived") {
    const r = requests.find((x) => x.id === msg.params.requestId);
    if (r) r.status = msg.params.response.status;
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
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.text + " " + (r.exceptionDetails.exception?.description ?? ""));
  return r.result.value;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitFor(predicateJs, what, timeout = 15000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    try {
      if (await evaluate(predicateJs)) return true;
    } catch {
      /* page navigating */
    }
    await sleep(150);
  }
  throw new Error(`timed out waiting for ${what}`);
}
const bodyText = () => evaluate("document.body ? document.body.innerText : ''");
const path = () => evaluate("location.pathname");
const navigate = async (url) => {
  await send("Page.navigate", { url });
  await waitFor("document.readyState === 'complete'", `load ${url}`);
};
const switcherText = () =>
  evaluate(`(() => { const s = [...document.querySelectorAll('select')].find(x => x.innerText.includes('Rehearsal Org'));
                     return s ? s.options[s.selectedIndex].text : null; })()`);
// Sections are collapsible; expand all so every link the role may see is in the DOM.
const navLinks = async () => {
  await evaluate("[...document.querySelectorAll('nav button[aria-expanded=\"false\"]')].forEach(b => b.click()); true");
  await sleep(200);
  return evaluate("[...document.querySelectorAll('nav a')].map(a => a.getAttribute('href'))");
};
const clickText = (selector, text) =>
  evaluate(`(() => { const el = [...document.querySelectorAll(${JSON.stringify(selector)})]
                       .find(e => e.innerText.includes(${JSON.stringify(text)}));
                     if (!el) return false; el.click(); return true; })()`);
async function login(email, password) {
  await navigate(`${APP}/login`);
  await waitFor("!!document.querySelector('input[type=password]')", "login form");
  await evaluate(`(() => {
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    for (const [sel, val] of [['input[type=email]', ${JSON.stringify(email)}], ['input[type=password]', ${JSON.stringify(password)}]]) {
      const el = document.querySelector(sel); set.call(el, val); el.dispatchEvent(new Event('input', { bubbles: true }));
    }
    [...document.querySelectorAll('button')].find(b => b.innerText.trim() === 'Sign in').click();
    return true; })()`);
}
async function switchTo(orgId) {
  await evaluate(`(() => { const s = [...document.querySelectorAll('select')].find(x => x.innerText.includes('Rehearsal Org'));
    const set = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set;
    set.call(s, ${JSON.stringify(orgId)}); s.dispatchEvent(new Event('change', { bubbles: true })); return true; })()`);
}
const orgRequestsSince = (index) => requests.slice(index).filter((r) => !r.url.endsWith("/auth/login"));

await send("Page.enable");
await send("Runtime.enable");
await send("Network.enable");
await send("Network.setCacheDisabled", { cacheDisabled: true });
await installProbe(send); // passive until B12 arms it
await navigate(`${APP}/login`);
await evaluate("localStorage.clear(); sessionStorage.clear(); true");

try {
  // --- Multi-membership user: picker -------------------------------------------------------
  let mark = requests.length;
  await login(DUAL_EMAIL, DUAL_PW);
  await waitFor("document.body.innerText.includes('Choose an organization')", "organization picker");
  const choices = await evaluate("[...document.querySelectorAll('ul[aria-label=\"Your organizations\"] button')].map(b => b.innerText.replace(/\\s+/g, ' ').trim())");
  check("B1. picker lists exactly the two active memberships with their roles",
    choices.length === 2 && choices.some((t) => t.includes("Rehearsal Org A") && t.includes("Admin"))
      && choices.some((t) => t.includes("Rehearsal Org B") && t.includes("Auditor"))
      && !choices.some((t) => t.includes("Org C") || t.includes("Org D")),
    choices.join(" | "));
  const beforePick = orgRequestsSince(mark);
  check("B2. nothing organization-scoped is requested before a choice (discovery only)",
    beforePick.every((r) => r.url.endsWith("/auth/me") && r.org === null), beforePick.map((r) => `${r.url}:${r.org ? "hdr" : "none"}`).join(","));

  // --- Choose A -----------------------------------------------------------------------------
  mark = requests.length;
  await clickText("ul[aria-label=\"Your organizations\"] button", "Rehearsal Org A");
  await waitFor("location.pathname === '/dashboard' && [...document.querySelectorAll('select')].some(s => s.innerText.includes('Rehearsal Org'))", "dashboard in A");
  let links = await navLinks();
  check("B3. after choosing A: switcher shows Org A · Admin, admin navigation present",
    (await switcherText())?.includes("Rehearsal Org A") && (await switcherText())?.includes("Admin")
      && links.includes("/agents") && links.includes("/organization"), `${await switcherText()}; nav=${links.join(",")}`);
  await clickText("nav a", "Agents");
  await waitFor("document.body.innerText.includes('Agent A')", "Agent A listed");
  let text = await bodyText();
  check("B4. Org A agents page shows A's agents only", text.includes("Agent A") && !text.includes("Agent B"));
  const inA = orgRequestsSince(mark).filter((r) => r.org !== null);
  check("B5. every organization-scoped request in A carries header A",
    inA.length > 0 && inA.every((r) => r.org === ORG_A), `${inA.length} requests`);

  // --- Switch to B --------------------------------------------------------------------------
  mark = requests.length;
  await switchTo(ORG_B);
  await waitFor("location.pathname === '/dashboard' && [...document.querySelectorAll('select')].some(s => s.options[s.selectedIndex]?.text.includes('Rehearsal Org B'))", "dashboard in B");
  await sleep(1500); // let every query of the new workspace settle
  links = await navLinks();
  text = await bodyText();
  check("B6. after switching to B: Org B · Auditor, no admin/agent navigation",
    (await switcherText())?.includes("Auditor") && !links.includes("/agents") && !links.includes("/organization")
      && links.includes("/audit-logs"), `${await switcherText()}; nav has ${links.length} links`);
  check("B7. no Org A data rendered after the switch (cache isolation)",
    !text.includes("Agent A") && !text.includes("Gateway A"));
  await clickText("nav a", "Audit Logs");
  await waitFor("location.pathname === '/audit-logs'", "audit logs page");
  await sleep(1500);
  text = await bodyText();
  check("B8. Org B audit page renders without Org A names", !text.includes("Agent A") && !text.includes("Gateway A"));
  const afterSwitch = orgRequestsSince(mark).filter((r) => r.org !== null);
  check("B9. every organization-scoped request after the switch carries header B, none A",
    afterSwitch.length > 0 && afterSwitch.every((r) => r.org === ORG_B), `${afterSwitch.length} requests`);
  // Direct navigation to an admin-only page while auditor.
  await navigate(`${APP}/agents`);
  await sleep(1500);
  text = await bodyText();
  check("B10. reload keeps B (tab-scoped) and the agents route is refused for an auditor",
    (await path()) !== "/agents" && !text.includes("Agent A"), `landed on ${await path()}`);

  // --- Back to A, then a reload -------------------------------------------------------------
  await navigate(`${APP}/dashboard`);
  await waitFor("[...document.querySelectorAll('select')].some(s => s.innerText.includes('Rehearsal Org'))", "switcher");
  // Step 108: the boundary is armed in the same synchronous evaluation that dispatches the switch,
  // and requests are classified by the page at issuance (see b12_lib.mjs), not by CDP list index.
  const b12From = b12log.events.length;
  const legacyMark = requests.length;
  if (!(await evaluate(armAndSwitchJs(ORG_A, "Rehearsal Org A")))) throw new Error("could not arm the B12 switch");
  await waitForConfirm(b12log, b12From);
  await waitFor("[...document.querySelectorAll('select')].some(s => s.options[s.selectedIndex]?.text.includes('Rehearsal Org A'))", "back in A");
  await navigate(`${APP}/agents`);
  await waitFor("document.body.innerText.includes('Agent A')", "Agent A after switching back");
  check("B11. switching back to A and reloading restores A's admin view",
    (await switcherText())?.includes("Admin") && (await path()) === "/agents");
  await quiesce(b12log, requests);
  const b12 = analyze(b12log, b12From, { target: ORG_A, other: ORG_B, labels: { [ORG_A]: "A", [ORG_B]: "B", [ORG_C]: "C", [ORG_D]: "D" }, cdpRequests: requests, legacyMark });
  for (const line of b12.lines) console.log(`      B12 ${line}`);
  check("B12. after the confirmed switch back to A, no newly issued request carries header B (and none while confirming)",
    b12.ok, `${b12.counts.post} post-confirmation, ${b12.counts.confirming} confirming, ${b12.counts.pre} pre-switch (${b12.counts.inflightAtArm} in flight)`);
  await evaluate("window.__b12 ? window.__b12.reset() : true");
  const forbidden = requests.filter((r) => r.org === ORG_C || r.org === ORG_D);
  check("B13. the UI never sent the inactive (C) or deleted (D) organization", forbidden.length === 0);

  // --- Single-membership user ---------------------------------------------------------------
  await evaluate("localStorage.clear(); sessionStorage.clear(); true");
  mark = requests.length;
  await login(SINGLE_EMAIL, SINGLE_PW);
  await waitFor("location.pathname === '/dashboard' && document.body.innerText.includes('Rehearsal Org A')", "single user dashboard");
  text = await bodyText();
  links = await navLinks();
  check("B14. single-membership user goes straight to the dashboard as Org A · Operator, no picker",
    !text.includes("Choose an organization") && text.includes("Operator") && !links.includes("/agents") && links.includes("/approvals"));
  const single = orgRequestsSince(mark);
  check("B15. single-membership session gets no 409 and sends only its own organization",
    single.every((r) => r.status !== 409 && (r.org === null || r.org === ORG_A)), `${single.length} requests`);
} catch (error) {
  check("browser run completed", false, error.message);
}
check("B16. no uncaught page exceptions", problems.length === 0, problems.slice(0, 3).join("; "));
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} browser checks passed`);
ws.close();
process.exit(failed.length ? 1 : 0);
