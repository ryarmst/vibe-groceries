// Device pairing and sign-in.
// Pairing: generate an ECDSA P-256 key pair (private key non-extractable), send the public key with a
// one-time code. Sign-in: sign the server's challenge, get a 15-minute access token (kept in session
// storage, i.e. memory, cleared when the browser closes).
import { idbDelete, idbGet, idbSet } from "./idb.js";

const enc = new TextEncoder();

export function b64url(bytes) {
  let s = "";
  for (const b of new Uint8Array(bytes)) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export async function getConfig() {
  const { config } = await browser.storage.local.get("config");
  return config || {};
}

export function normalizeServer(url) {
  const u = new URL(url.trim());
  const local = ["localhost", "127.0.0.1"].includes(u.hostname);
  if (u.protocol !== "https:" && !(local && u.protocol === "http:")) throw new Error("The server URL must start with https://");
  return u.origin;
}

// Must be called from a user action (a click) so Firefox can ask for the host permission.
export async function requestServerPermission(serverUrl) {
  const origin = normalizeServer(serverUrl);
  const ok = await browser.permissions.request({ origins: [origin + "/*"] });
  if (!ok) throw new Error("Permission to reach the server was not granted.");
  return origin;
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST", credentials: "omit", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Server returned ${res.status}`);
  return data;
}

export async function pair(serverUrl, code, name) {
  const origin = normalizeServer(serverUrl);
  const pair = await crypto.subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, false, ["sign", "verify"]);
  const jwk = await crypto.subtle.exportKey("jwk", pair.publicKey);
  const data = await postJSON(origin + "/api/pair", {
    code, name: name || null, public_key: { kty: jwk.kty, crv: jwk.crv, x: jwk.x, y: jwk.y },
  });
  await idbSet("device", { privateKey: pair.privateKey, publicKey: pair.publicKey });
  await browser.storage.local.set({ config: { serverUrl: origin, deviceId: data.device_id, deviceName: data.name } });
  await browser.storage.session.remove("access");
  return data;
}

export async function forget() {
  await idbDelete("device");
  await browser.storage.local.remove(["config", "lastSessionHash", "inboxSnapshot"]);
  await browser.storage.session.remove("access");
}

let signingIn = null;

export async function signIn() {
  if (signingIn) return signingIn;
  signingIn = (async () => {
    const cfg = await getConfig();
    const keys = await idbGet("device");
    if (!cfg.serverUrl || !cfg.deviceId || !keys) throw Object.assign(new Error("This browser isn't paired yet."), { code: "not_paired" });
    const { challenge } = await postJSON(cfg.serverUrl + "/api/auth/challenge", { device_id: cfg.deviceId });
    const message = enc.encode(`vibe-groceries:auth:v1:${cfg.deviceId}:${challenge}`);
    const sig = await crypto.subtle.sign({ name: "ECDSA", hash: "SHA-256" }, keys.privateKey, message);
    const data = await postJSON(cfg.serverUrl + "/api/auth/token", { device_id: cfg.deviceId, challenge, signature: b64url(sig) });
    const access = { token: data.access_token, expiresAt: data.expires_at * 1000 };
    await browser.storage.session.set({ access });
    return access;
  })();
  try { return await signingIn; } finally { signingIn = null; }
}

export async function accessToken(force = false) {
  if (!force) {
    const { access } = await browser.storage.session.get("access");
    if (access && access.expiresAt - Date.now() > 60_000) return access.token;
  }
  return (await signIn()).token;
}
