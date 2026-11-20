/**
 * Remembers, for this tab only, that an earlier attempt to accept the current invitation ended
 * without a definitive answer from the server, so the page can keep explaining that after a
 * remount (identity changes remount the app) or a reload.
 *
 * It is never evidence that the invitation was accepted. It stores no password, JWT or
 * invitation content: only a SHA-256 fingerprint tying it to the invitation token held for this
 * tab (so a different invitation ignores it) and the attempt's outcome.
 */

export type InviteAttemptOutcome = "not-sent" | "unknown";

const STORAGE_KEY = "agenthq.invite-attempt";
/** Fired when the record changes, so a page mounted later (after a remount) still sees it. */
export const INVITE_ATTEMPT_EVENT = "agenthq:invite-attempt";

function changed(): void {
  window.dispatchEvent(new Event(INVITE_ATTEMPT_EVENT));
}

// SHA-256 (FIPS 180-4) round constants and initial hash values.
const K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
]);
const H0 = [
  0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19
];

const rotr = (value: number, bits: number) => (value >>> bits) | (value << (32 - bits));

/**
 * SHA-256 of a string's UTF-8 bytes, as hex. Synchronous on purpose: the record is read during
 * render, and Web Crypto (asynchronous, and absent outside secure contexts) cannot be.
 */
export function sha256Hex(message: string): string {
  const data = new TextEncoder().encode(message);
  const length = Math.ceil((data.length + 9) / 64) * 64;
  const bytes = new Uint8Array(length);
  bytes.set(data);
  bytes[data.length] = 0x80;
  const view = new DataView(bytes.buffer);
  view.setUint32(length - 8, Math.floor(data.length / 0x20000000));
  view.setUint32(length - 4, (data.length * 8) >>> 0);

  const hash = Uint32Array.from(H0);
  const w = new Uint32Array(64);
  for (let offset = 0; offset < length; offset += 64) {
    for (let i = 0; i < 16; i += 1) w[i] = view.getUint32(offset + i * 4);
    for (let i = 16; i < 64; i += 1) {
      const s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >>> 3);
      const s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >>> 10);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
    }
    let [a, b, c, d, e, f, g, h] = hash;
    for (let i = 0; i < 64; i += 1) {
      const t1 =
        (h + (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) + ((e & f) ^ (~e & g)) + K[i] + w[i]) >>> 0;
      const t2 = ((rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) >>> 0;
      h = g;
      g = f;
      f = e;
      e = (d + t1) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (t1 + t2) >>> 0;
    }
    [a, b, c, d, e, f, g, h].forEach((value, index) => {
      hash[index] = (hash[index] + value) >>> 0;
    });
  }
  return Array.from(hash, (word) => word.toString(16).padStart(8, "0")).join("");
}

// Domain-separated, so the stored value is never the server's token hash (plain SHA-256 of the
// token, organization_invites.py) and cannot be matched against it.
const FINGERPRINT_CONTEXT = "agenthq:invite-attempt:v1\u0000";

/** Ties the record to one invitation token without storing the token or the server's hash. */
export function inviteFingerprint(token: string): string {
  return sha256Hex(FINGERPRINT_CONTEXT + token);
}

export function readInviteAttempt(token: string): InviteAttemptOutcome | null {
  if (!token) return null;
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { fingerprint?: unknown; outcome?: unknown };
    if (parsed.fingerprint !== inviteFingerprint(token)) return null;
    return parsed.outcome === "unknown" || parsed.outcome === "not-sent" ? parsed.outcome : null;
  } catch {
    return null;
  }
}

/** Record an attempt's outcome. "unknown" is sticky: a later refused attempt cannot hide it. */
export function recordInviteAttempt(token: string, outcome: InviteAttemptOutcome): void {
  if (!token) return;
  if (outcome === "not-sent" && readInviteAttempt(token) === "unknown") return;
  try {
    window.sessionStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ fingerprint: inviteFingerprint(token), outcome })
    );
  } catch {
    // Storage unavailable: the explanation is shown until the page remounts.
  }
  changed();
}

/** Forget it: after a confirmed acceptance, or when the invitation flow is abandoned. */
export function clearInviteAttempt(): void {
  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Nothing stored.
  }
  changed();
}
