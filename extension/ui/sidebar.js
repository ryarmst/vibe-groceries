import { getConfig } from "../lib/auth.js";
import { mountChat } from "../lib/chat.js";
import { h, openApp } from "../lib/ui.js";

const root = document.getElementById("root");
const cfg = await getConfig();
if (!cfg.serverUrl) {
  root.append(h("div", { class: "card" }, h("p", {}, "This browser isn't paired yet."), h("button", { class: "primary", onclick: () => openApp("#/settings") }, "Open Settings")));
} else {
  const { thread } = await browser.storage.local.get("thread");
  mountChat(root, { threadId: thread || null, onThread: (id) => browser.storage.local.set({ thread: id }) });
}
