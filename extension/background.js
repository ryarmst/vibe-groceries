// Background: keeps the No Frills session connected and the badge current.
// Reads exactly one cookie (AccessToken on nofrills.ca) and sends it to the server when it changes.
import { get, put } from "./lib/api.js";
import { getConfig } from "./lib/auth.js";

const COOKIE = "AccessToken";
let debounce = null;

async function sha256(text) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

function jwtExpiry(token) {
  try {
    const payload = JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
    return (payload.exp || 0) * 1000;
  } catch { return 0; }
}

async function sendSession(value, { force = false } = {}) {
  const cfg = await getConfig();
  if (!cfg.serverUrl || !value) return { sent: false, reason: "not_paired_or_empty" };
  if (jwtExpiry(value) < Date.now() + 60_000) return { sent: false, reason: "expired" };
  const hash = await sha256(value);
  const { lastSessionHash } = await browser.storage.local.get("lastSessionHash");
  if (!force && hash === lastSessionHash) return { sent: false, reason: "unchanged" };
  const res = await put("/api/retailer/session", { access_token: value });
  if (res.ok !== false) await browser.storage.local.set({ lastSessionHash: hash });
  refreshInbox();
  return { sent: res.ok !== false, state: res.state, error: res.error };
}

async function currentCookie() {
  const cookies = await browser.cookies.getAll({ domain: "nofrills.ca", name: COOKIE });
  return cookies.sort((a, b) => (b.expirationDate || 0) - (a.expirationDate || 0))[0]?.value || null;
}

browser.cookies.onChanged.addListener(({ removed, cookie }) => {
  if (removed || cookie.name !== COOKIE || !cookie.domain.endsWith("nofrills.ca")) return;
  clearTimeout(debounce);
  debounce = setTimeout(() => sendSession(cookie.value).catch((e) => console.warn("session send failed", e.message)), 1500);
});

async function refreshInbox() {
  try {
    const inbox = await get("/api/inbox");
    await browser.storage.local.set({ inboxSnapshot: { at: Date.now(), ...inbox } });
    const n = inbox.count || 0;
    await browser.action.setBadgeText({ text: n ? String(n) : "" });
    await browser.action.setBadgeBackgroundColor({ color: inbox.items?.some((i) => i.kind === "needs_session") ? "#b3261e" : "#2f7d4f" });
    return inbox;
  } catch (e) {
    await browser.action.setBadgeText({ text: e.code === "not_paired" ? "" : "!" });
    await browser.storage.local.set({ inboxSnapshot: { at: Date.now(), error: e.message } });
    return null;
  }
}

async function startup() {
  browser.alarms.create("inbox", { periodInMinutes: 15 });
  const value = await currentCookie().catch(() => null);
  if (value) await sendSession(value).catch(() => {});
  await refreshInbox();
}

browser.alarms.onAlarm.addListener((a) => { if (a.name === "inbox") refreshInbox(); });
browser.runtime.onStartup.addListener(startup);
browser.runtime.onInstalled.addListener(startup);

browser.runtime.onMessage.addListener((msg) => {
  if (msg?.type === "refreshInbox") return refreshInbox();
  if (msg?.type === "sendSessionNow") {
    return currentCookie().then((v) => v ? sendSession(v, { force: true }) : { sent: false, reason: "no_cookie" });
  }
  return undefined;
});
