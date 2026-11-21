// Toolbar popup: status at a glance and shortcuts.
import { get } from "../lib/api.js";
import { getConfig } from "../lib/auth.js";
import { ago, h, link, openApp } from "../lib/ui.js";

const root = document.getElementById("root");
const cfg = await getConfig();
const go = (hash) => () => { openApp(hash); window.close(); };

if (!cfg.serverUrl) {
  root.append(h("p", {}, "Not paired yet."), h("button", { class: "primary", onclick: go("#/settings") }, "Pair this browser"));
} else {
  root.append(h("div", { class: "row" },
    h("button", { class: "primary", onclick: () => { browser.sidebarAction.open(); window.close(); } }, "💬 Chat"),
    h("button", { onclick: go("#/") }, "Open app")));
  const box = h("div", { style: { marginTop: "10px" } }, h("div", { class: "small muted" }, "Loading…"));
  root.append(box);
  const inbox = await browser.runtime.sendMessage({ type: "refreshInbox" }).catch(() => null)
    || await get("/api/inbox").catch((e) => ({ error: e.message }));
  box.replaceChildren();
  if (!inbox || inbox.error) box.append(h("p", { class: "small bad" }, inbox?.error || "Can't reach the server."));
  else {
    const s = inbox.retailer_session;
    box.append(h("p", { class: "small" }, s.state === "connected" ? `🟢 No Frills connected (${Math.floor(s.seconds_remaining / 60)} min)` : "🟠 No Frills: visit nofrills.ca while logged in"),
      h("p", { class: "small muted" }, "Deals scanned ", inbox.deal_scan.last ? ago(inbox.deal_scan.last.finished_at) : "never"));
    if (!inbox.items.length) box.append(h("p", { class: "small muted" }, "Nothing needs you."));
    for (const item of inbox.items.slice(0, 6)) box.append(h("div", { class: "small", style: { padding: "4px 0" } }, "• ",
      item.link ? h("a", { href: "#", onclick: (e) => { e.preventDefault(); go(item.link)(); } }, item.title) : item.title));
  }
}
