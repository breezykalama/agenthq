// Step 111: issuance-ordered boundaries for B5 and B9, built on the Step 108 B12 probe
// (b12_lib.mjs, used unchanged). Shared by browser_core.mjs (the 16-check suite) and b5b9.mjs
// (repeat runs, forced race, in-flight hold, negative controls).
//
// Why: B5 and B9 used `mark = requests.length` over the CDP Network.requestWillBeSent stream.
// Those notifications are delivered late, so the list index says when Chrome *reported* a
// request, not when the page *issued* it:
//   B9 (switch A -> B): header-A requests issued in A's session before the switch, but reported
//       after the mark, were counted as post-switch -> false "header A after the switch" failure
//       (the B12 race, in the other direction).
//   B5 (session in A): the window ended whenever the check happened to run, so requests issued in
//       A but not yet reported were silently left out, and once B9 classifies by issuance they
//       would be "pre-switch" there too: a wrong header issued late in A would escape both checks.
//
// Fix: every boundary is a probe "arm" placed in the same page evaluation as the user action
// (picker choice, switcher change), and requests are ordered by the probe's issuance record
// (document, then per-document sequence number), never by CDP delivery order.
//   B5 window: after the picker-choice arm, up to and including the B9 switch arm, i.e. every
//              request issued while A was the chosen organization, however late it was reported.
//   B9: the B12 classification (b12_lib.analyze) with target B and other A.
// Both checks run only after quiesce() (probe and CDP agree on the request count) and reconcile
// the probe against CDP (multiset of method, path and organization header over the whole run),
// so neither can pass because requests were not recorded.

import { analyze } from "./b12_lib.mjs";

export const AUTH_ME = "/api/v1/auth/me";
export const B5_REQUIRED = [
  ["GET", AUTH_ME], // the candidate identity confirmation for A
  ["GET", "/api/v1/agents"], // the page B4 checks
];
export const B9_REQUIRED_POST = [["GET", "/api/v1/audit-logs"]]; // the page B8 checks

/** One page evaluation: arm the boundary, then choose the organization on the picker. */
export const armAndPickJs = (orgId, orgName, options = {}) => `(() => {
  const b = [...document.querySelectorAll('ul[aria-label="Your organizations"] button')]
    .find(x => x.innerText.includes(${JSON.stringify(orgName)}));
  if (!b || !window.__b12) return false;
  window.__b12.arm(${JSON.stringify(orgId)}, ${JSON.stringify(orgName)}, ${JSON.stringify(options)});
  b.click(); return true; })()`;

/** The first probe "arm" event at or after log index `from` (null if none yet). */
export const armAfter = (log, from) => log.events.slice(from).find((e) => e.type === "arm") ?? null;

const labeller = (labels) => (org) => (org === null || org === undefined ? "none" : labels[org] ?? "unknown");

/** Compare two probe records by issuance: document creation order, then sequence number. */
function issuanceOrder(log) {
  const rank = new Map();
  log.events.forEach((e, i) => {
    if (e.type === "doc" && !rank.has(e.doc)) rank.set(e.doc, i);
  });
  const cmp = (a, b) => (rank.get(a.doc) ?? -1) - (rank.get(b.doc) ?? -1) || a.seq - b.seq;
  return { cmp, known: (doc) => rank.has(doc) };
}

/** Probe vs CDP over the whole run: every /api/ request Chrome saw, numbered with the same header. */
export function reconcile(log, cdpRequests, labels) {
  const lab = labeller(labels);
  const key = (method, path, org) => `${method} ${path} ${lab(org)}`;
  const bag = new Map();
  for (const e of log.events.filter((x) => x.type === "req")) bag.set(key(e.method, e.path, e.org), (bag.get(key(e.method, e.path, e.org)) ?? 0) + 1);
  for (const r of cdpRequests) bag.set(key(r.method, r.url, r.org), (bag.get(key(r.method, r.url, r.org)) ?? 0) - 1);
  return [...bag].filter(([, n]) => n !== 0);
}

const formatter = (log, lab) => {
  const ends = new Map(log.events.filter((e) => e.type === "end").map((e) => [`${e.doc}:${e.seq}`, e]));
  return (e) => {
    const end = ends.get(`${e.doc}:${e.seq}`);
    return `#${e.seq}@${e.doc} ${e.method} ${e.path} hdr=${lab(e.org)} phase=${e.phase}${e.injected ? " INJECTED" : ""} status=${end ? end.status : "pending"}`;
  };
};

/**
 * B5: every organization-scoped request issued while `org` was the chosen organization carries
 * `org`. The session is every request issued after the `start` arm (picker choice) up to and
 * including the `end` arm (the next switch), ordered by issuance. `since` optionally names an
 * issuance point ({doc, seq}); the window must contain requests issued after it (forced race).
 */
export function analyzeSession(log, { start, end, org, labels, cdpRequests, required = B5_REQUIRED, since = null }) {
  const lab = labeller(labels);
  const out = { ok: false, lines: [], culprits: [], asserts: {} };
  if (!start || !end) {
    out.lines.push(`session boundary missing (start=${Boolean(start)}, end=${Boolean(end)})`);
    return out;
  }
  const { cmp, known } = issuanceOrder(log);
  const reqs = log.events.filter((e) => e.type === "req");
  // A request whose document announced no "doc" event cannot be ordered; fail closed rather than
  // silently leaving it out of the window.
  const unordered = reqs.filter((e) => !known(e.doc));
  const window = reqs.filter((e) => known(e.doc) && cmp(e, start) > 0 && cmp(e, end) <= 0);
  const scoped = window.filter((e) => e.org !== null);
  const wrong = scoped.filter((e) => e.org !== org);
  const missing = required.filter(([m, p]) => !scoped.some((e) => e.method === m && e.path === p && e.org === org));
  const mismatch = reconcile(log, cdpRequests, labels);
  const lateIssued = since ? window.filter((e) => cmp(e, since) > 0) : [];
  const fmt = formatter(log, lab);
  const count = (list) => {
    const c = {};
    for (const e of list) c[lab(e.org)] = (c[lab(e.org)] ?? 0) + 1;
    return JSON.stringify(c);
  };
  out.asserts = {
    boundary: known(start.doc) && known(end.doc) && cmp(start, end) < 0,
    ordered: unordered.length === 0,
    scoped: scoped.length > 0,
    header: wrong.length === 0,
    coverage: missing.length === 0,
    complete: mismatch.length === 0,
    ...(since ? { lateIncluded: lateIssued.length > 0 } : {}),
  };
  out.ok = Object.values(out.asserts).every(Boolean);
  out.culprits = [...wrong.map(fmt), ...unordered.map((e) => `${fmt(e)} (document never announced)`)];
  out.counts = { window: window.length, scoped: scoped.length, late: lateIssued.length };
  out.lines.push(
    `session: chosen after #${start.seq}@${start.doc}, ended by the switch armed after #${end.seq}@${end.doc}; ` +
      `${window.length} requests issued ${count(window)}, ${scoped.length} organization-scoped`,
    ...(since ? [`issued in the last moments before the switch (after #${since.seq}@${since.doc}): ${lateIssued.length} ${count(lateIssued)}`] : []),
    `asserts: ${JSON.stringify(out.asserts)}` +
      (missing.length ? ` missing coverage: ${missing.map(([m, p]) => `${m} ${p} hdr=${lab(org)}`).join(", ")}` : "") +
      (mismatch.length ? ` probe/CDP mismatch: ${JSON.stringify(mismatch.slice(0, 5))}` : ""),
  );
  if (out.culprits.length) out.lines.push(`offending requests: ${out.culprits.join(" ; ")}`);
  return out;
}

/**
 * B9: after the confirmed switch to `target`, no newly issued request carries another
 * organization's header, none does while confirming, and the destination page was requested
 * with the destination's header. Classification is b12_lib.analyze, unchanged.
 */
export function analyzeSwitch(log, from, { target, other, labels, cdpRequests, legacyMark, requiredPost = B9_REQUIRED_POST }) {
  const a = analyze(log, from, { target, other, labels, cdpRequests, legacyMark });
  a.lines = a.lines.map((l) => l.replace("legacy (Step 105) B12 on this run", "legacy (pre-Step-111 CDP index) B9 on this run"));
  const lab = labeller(labels);
  const post = log.events.slice(from).filter((e) => e.type === "req" && e.phase === "post" && e.org === target);
  const missing = requiredPost.filter(([m, p]) => !post.some((e) => e.method === m && e.path === p));
  a.asserts = { ...(a.asserts ?? {}), coverage: missing.length === 0 };
  a.ok = a.ok && missing.length === 0;
  if (missing.length) a.lines.push(`missing post-confirmation coverage: ${missing.map(([m, p]) => `${m} ${p} hdr=${lab(target)}`).join(", ")}`);
  return a;
}

/** The pre-Step-111 B5/B9 verdict on a CDP list slice (for comparison on the same run). */
export function legacyVerdict(cdpRequests, mark, org, endIndex = cdpRequests.length) {
  const list = cdpRequests.slice(mark, endIndex).filter((r) => r.org !== null && !r.url.endsWith("/auth/login"));
  return { ok: list.length > 0 && list.every((r) => r.org === org), count: list.length, wrong: list.filter((r) => r.org !== org).length };
}
