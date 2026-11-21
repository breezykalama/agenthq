// Step 108: corrected B12 boundary. Shared by browser_core.mjs (the 16-check suite) and b12.mjs
// (repeat runs, in-flight hold, negative control).
//
// Why: the Step 105 B12 used `mark = requests.length` over the CDP event stream as its "switch"
// boundary. Network.requestWillBeSent events for header-B requests issued *before* the switch
// were still being delivered after the mark, so they were counted as if issued after it.
//
// Fix: a passive probe injected into every document (Page.addScriptToEvaluateOnNewDocument)
// numbers each /api/ request at the moment the page calls XMLHttpRequest.send()/fetch(), and
// records the organization header it carries at that moment. Each request is classified by the
// page itself, synchronously, at issuance:
//   pre         issued before the switch was armed (the arm happens in the same synchronous
//               evaluation that dispatches the switch, so the boundary is exact)
//   confirming  issued after the switch began, before the frontend confirmed the new organization
//   post        issued after confirmation (and every request in any later document of the tab)
// Confirmation is deterministic and observable: (1) an /auth/me request carrying the candidate
// organization's header, issued after the switch began, completed with HTTP 200 (the backend
// confirmed the selection), and (2) the frontend committed it: the organization switcher shows the
// candidate as its selected value. (2) is re-evaluated on every DOM mutation, on every request
// issuance (synchronously, before the request is numbered) and on a 20 ms poll.
// Only the organization header is captured: never Authorization, cookies, bodies or tokens.

export const BINDING = "__b12emit";

export const PROBE = String.raw`(() => {
  if (window.__b12) return;
  const HEADER = "x-agenthq-organization";
  const KEY = "__b12_switch";
  const doc = Math.random().toString(36).slice(2, 10);
  let seq = 0;
  const queue = [];
  const emit = (rec) => {
    queue.push(JSON.stringify(rec));
    if (typeof window.${BINDING} === "function") while (queue.length) window.${BINDING}(queue.shift());
  };
  let sw = null;
  try { sw = JSON.parse(sessionStorage.getItem(KEY) || "null"); } catch { sw = null; }
  const persist = () => { try { sw ? sessionStorage.setItem(KEY, JSON.stringify(sw)) : sessionStorage.removeItem(KEY); } catch {} };
  const inflight = new Set();
  const pathOf = (u) => { try { return new URL(u, location.href).pathname; } catch { return ""; } };
  const isApi = (u) => pathOf(u).startsWith("/api/");
  const phase = () => (!sw ? "pre" : sw.confirmed ? "post" : "confirming");
  const committed = () => {
    if (!sw || sw.confirmed || !sw.candidateOk) return false;
    const s = [...document.querySelectorAll("select")].find((x) => [...x.options].some((o) => o.text.includes("Rehearsal Org")));
    return !!s && s.value === sw.target && (s.options[s.selectedIndex]?.text ?? "").includes(sw.targetName);
  };
  const confirmIfCommitted = (how) => {
    if (!committed()) return;
    sw.confirmed = true; sw.confirmDoc = doc; sw.confirmSeq = seq; persist();
    emit({ type: "confirm", doc, seq, how });
  };
  const started = (rec, onEnd) => {
    confirmIfCommitted("issue");
    rec.seq = ++seq; rec.doc = doc; rec.phase = phase();
    inflight.add(rec.seq);
    emit({ type: "req", ...rec });
    return (status) => {
      inflight.delete(rec.seq);
      if (sw && !sw.confirmed && rec.phase === "confirming" && rec.path === "/api/v1/auth/me"
          && rec.org === sw.target && status === 200) {
        sw.candidateOk = true; persist();
        emit({ type: "candidate-ok", doc, seq: rec.seq });
      }
      emit({ type: "end", doc, seq: rec.seq, status, atSeq: seq, phaseAtEnd: phase() });
    };
  };
  const maybeInject = (m, value) => {
    if (sw && sw.confirmed && sw.inject && !sw.inject.done && !m.path.startsWith("/api/v1/auth/")) {
      sw.inject.done = true; persist(); m.injected = true;
      return sw.inject.org;
    }
    return value;
  };
  const X = XMLHttpRequest.prototype, open = X.open, setHeader = X.setRequestHeader, send = X.send;
  X.open = function (method, url) {
    const m = { method: String(method).toUpperCase(), path: pathOf(String(url)), api: isApi(String(url)), org: null, injected: false, end: null };
    this.__b12m = m;
    // Registered before the application's own onloadend handler, so confirmation evidence is
    // recorded before the application can react to the response.
    if (m.api) this.addEventListener("loadend", () => m.end && m.end(this.status));
    return open.apply(this, arguments);
  };
  X.setRequestHeader = function (name, value) {
    const m = this.__b12m;
    if (m && m.api && String(name).toLowerCase() === HEADER) {
      value = maybeInject(m, String(value)); // negative control only (armed with inject)
      m.org = String(value);
    }
    return setHeader.call(this, name, value);
  };
  X.send = function () {
    const m = this.__b12m;
    if (m && m.api) m.end = started({ kind: "xhr", method: m.method, path: m.path, org: m.org, injected: m.injected });
    return send.apply(this, arguments);
  };
  const nativeFetch = window.fetch;
  window.fetch = function (input, init) {
    let end = null;
    try {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (isApi(url)) {
        const headers = new Headers((init && init.headers) || (input instanceof Request ? input.headers : undefined));
        const method = ((init && init.method) || (input instanceof Request ? input.method : "GET")).toUpperCase();
        end = started({ kind: "fetch", method, path: pathOf(url), org: headers.get(HEADER), injected: false });
      }
    } catch {}
    const p = nativeFetch.apply(this, arguments);
    if (end) p.then((r) => end(r.status), () => end(0));
    return p;
  };
  window.__b12 = {
    arm(target, targetName, options = {}) {
      sw = { target, targetName, confirmed: false, candidateOk: false, armDoc: doc, armSeq: seq,
             inject: options.inject ? { org: options.inject, done: false } : null };
      persist();
      emit({ type: "arm", doc, seq, inflight: [...inflight] });
      return true;
    },
    reset() { sw = null; persist(); emit({ type: "reset", doc, seq }); return true; },
    state() { return { doc, seq, sw }; },
  };
  emit({ type: "doc", doc, path: location.pathname, phase: phase() });
  const watch = () => { if (sw && !sw.confirmed) confirmIfCommitted("dom"); };
  new MutationObserver(watch).observe(document, { subtree: true, childList: true, attributes: true, characterData: true });
  setInterval(() => { if (sw && !sw.confirmed) confirmIfCommitted("poll"); }, 20);
})();`;

/** Install the probe for every future document of the page, and the channel it reports on. */
export async function installProbe(send) {
  await send("Runtime.addBinding", { name: BINDING });
  await send("Page.addScriptToEvaluateOnNewDocument", { source: PROBE });
}

/** Collects probe events (in issuance order: bindings are delivered in call order). */
export function createLog() {
  const events = [];
  return {
    events,
    onMessage(msg) {
      if (msg.method === "Runtime.bindingCalled" && msg.params.name === BINDING) events.push(JSON.parse(msg.params.payload));
    },
  };
}

/** One synchronous page evaluation: arm the boundary, then dispatch the switcher change. */
export const armAndSwitchJs = (orgId, orgName, options = {}, preamble = "") => `(async () => {
  ${preamble}
  const s = [...document.querySelectorAll('select')].find(x => x.innerText.includes('Rehearsal Org'));
  if (!s || !window.__b12) return false;
  window.__b12.arm(${JSON.stringify(orgId)}, ${JSON.stringify(orgName)}, ${JSON.stringify(options)});
  const set = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set;
  set.call(s, ${JSON.stringify(orgId)}); s.dispatchEvent(new Event('change', { bubbles: true }));
  return true; })()`;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function waitForConfirm(log, from, timeout = 15000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    if (log.events.slice(from).some((e) => e.type === "confirm")) return true;
    await sleep(25);
  }
  throw new Error("timed out waiting for the switch confirmation boundary");
}

/** Wait until the probe and CDP agree on how many requests were issued and nothing is pending. */
export async function quiesce(log, cdpRequests, timeout = 8000) {
  const start = Date.now();
  let last = -1, stableSince = Date.now();
  while (Date.now() - start < timeout) {
    const n = log.events.length + cdpRequests.length;
    if (n !== last) { last = n; stableSince = Date.now(); }
    const reqs = log.events.filter((e) => e.type === "req").length;
    if (reqs === cdpRequests.length && Date.now() - stableSince > 800) return true;
    await sleep(100);
  }
  return false;
}

/**
 * Classify the requests of one switch (from log index `from`) and evaluate the assertions.
 * target/other: organization ids of the switch destination and origin. labels: id -> "A"/"B"/...
 */
export function analyze(log, from, { target, other, labels, cdpRequests, legacyMark }) {
  const ev = log.events.slice(from);
  const lab = (org) => (org === null || org === undefined ? "none" : labels[org] ?? "unknown");
  const arm = ev.find((e) => e.type === "arm");
  const out = { ok: false, lines: [], culprits: [] };
  if (!arm) { out.lines.push("no arm event: boundary never established"); return out; }
  const armAt = ev.indexOf(arm);
  const confirm = ev.slice(armAt).find((e) => e.type === "confirm");
  const candidate = ev.slice(armAt).find((e) => e.type === "candidate-ok");
  // Every probe event since the start of the whole log, so that pre-switch requests and late
  // completions of earlier requests can be resolved.
  const all = log.events;
  const reqKey = (e) => `${e.doc}:${e.seq}`;
  const ends = new Map(all.filter((e) => e.type === "end").map((e) => [reqKey(e), e]));
  const armDocReqs = all.filter((e) => e.type === "req" && e.doc === arm.doc);
  const pre = armDocReqs.filter((e) => e.seq <= arm.seq);
  const inflightAtArm = pre.filter((e) => arm.inflight.includes(e.seq));
  const windowReqs = ev.slice(armAt).filter((e) => e.type === "req");
  const confirming = windowReqs.filter((e) => e.phase === "confirming");
  const post = windowReqs.filter((e) => e.phase === "post");
  const strayPre = windowReqs.filter((e) => e.phase === "pre"); // must be empty (monotonic phases)
  const fmt = (e) => {
    const end = ends.get(reqKey(e));
    return `#${e.seq}@${e.doc} ${e.method} ${e.path} hdr=${lab(e.org)} phase=${e.phase}${e.injected ? " INJECTED" : ""} status=${end ? end.status : "pending"}`;
  };
  const count = (list) => {
    const c = {};
    for (const e of list) c[lab(e.org)] = (c[lab(e.org)] ?? 0) + 1;
    return JSON.stringify(c);
  };

  // A1: the boundary exists and is backed by the backend's confirmation.
  const a1 = Boolean(confirm && candidate && ev.indexOf(candidate) < ev.indexOf(confirm));
  // A2: after confirmation, every newly issued request carries the destination's header; the only
  // header-less request allowed is identity discovery (/auth/me). Nothing is excluded by endpoint.
  const postWrong = post.filter((e) => e.org !== null && e.org !== target);
  const postBare = post.filter((e) => e.org === null && e.path !== "/api/v1/auth/me");
  const postScoped = post.filter((e) => e.org === target);
  const a2 = postScoped.length > 0 && postWrong.length === 0 && postBare.length === 0;
  // A3: while confirming, the old organization's header is never issued (neutral context).
  const confirmingWrong = confirming.filter((e) => e.org !== null && e.org !== target);
  const a3 = confirmingWrong.length === 0;
  const a4 = strayPre.length === 0;
  // A5: probe completeness: every /api/ request Chrome saw was numbered by the probe with the same
  // method, path and organization header (multiset equality over the whole run).
  const key = (method, path, org) => `${method} ${path} ${lab(org)}`;
  const bag = new Map();
  for (const e of all.filter((x) => x.type === "req")) bag.set(key(e.method, e.path, e.org), (bag.get(key(e.method, e.path, e.org)) ?? 0) + 1);
  for (const r of cdpRequests) bag.set(key(r.method, r.url, r.org), (bag.get(key(r.method, r.url, r.org)) ?? 0) - 1);
  const mismatch = [...bag].filter(([, n]) => n !== 0);
  const a5 = mismatch.length === 0;

  out.culprits = [...postWrong, ...postBare, ...confirmingWrong, ...strayPre].map(fmt);
  out.ok = a1 && a2 && a3 && a4 && a5;
  out.asserts = { boundary: a1, post: a2, confirming: a3, monotonic: a4, complete: a5 };
  out.counts = {
    pre: pre.length, preOther: pre.filter((e) => e.org === other).length,
    inflightAtArm: inflightAtArm.length,
    inflightAborted: inflightAtArm.filter((e) => ends.get(reqKey(e))?.status === 0).length,
    inflightCompletedAfterArm: inflightAtArm.filter((e) => (ends.get(reqKey(e))?.status ?? 0) !== 0).length,
    confirming: confirming.length, post: post.length,
  };
  // The Step 105 algorithm, recomputed on the same run for comparison: CDP list index at the switch.
  if (legacyMark !== undefined) {
    const legacy = cdpRequests.slice(legacyMark).filter((r) => r.org !== null && !r.url.endsWith("/auth/login"));
    out.legacyFail = !(legacy.length > 0 && legacy.every((r) => r.org === target));
    out.legacyOther = legacy.filter((r) => r.org === other).length;
  }
  out.lines.push(
    `boundary: switch armed after #${arm.seq}@${arm.doc}; backend confirmed via /auth/me #${candidate?.seq ?? "-"}; ` +
      `frontend committed after #${confirm?.seq ?? "-"}@${confirm?.doc ?? "-"} (detected by ${confirm?.how ?? "-"})`,
    `pre-switch (switch document): ${pre.length} requests ${count(pre)}; in flight at the switch: ${inflightAtArm.length} ` +
      `(aborted ${out.counts.inflightAborted}, answered after the switch ${out.counts.inflightCompletedAfterArm})`,
    `confirming: ${confirming.length} requests ${count(confirming)} [${confirming.map((e) => `${e.path}:${lab(e.org)}`).join(", ")}]`,
    `post-confirmation: ${post.length} requests ${count(post)}`,
    `asserts: ${JSON.stringify(out.asserts)}${mismatch.length ? ` probe/CDP mismatch: ${JSON.stringify(mismatch.slice(0, 5))}` : ""}`,
  );
  if (legacyMark !== undefined) out.lines.push(`legacy (Step 105) B12 on this run: ${out.legacyFail ? "FAIL" : "pass"} (header-${lab(other)} requests after the index mark: ${out.legacyOther})`);
  if (out.culprits.length) out.lines.push(`offending requests: ${out.culprits.join(" ; ")}`);
  return out;
}
