// The app page: a hash router over the views. Each view module exports render(el, params, query).
import { getConfig } from "../lib/auth.js";
import { get } from "../lib/api.js";
import { clear, errorBox, h } from "../lib/ui.js";

const ROUTES = [
  [/^#\/?$/, "home", "Home"],
  [/^#\/runs\/([\w-]+)$/, "run"],
  [/^#\/runs$/, "runs", "Runs"],
  [/^#\/meals$/, "meals", "Meals"],
  [/^#\/deals$/, "deals", "Deals"],
  [/^#\/cart$/, "cart", "Cart"],
  [/^#\/product\/([\w-]+)$/, "product"],
  [/^#\/orders\/(\d+)$/, "order"],
  [/^#\/orders$/, "orders", "Orders"],
  [/^#\/history$/, "history", "History"],
  [/^#\/chat\/([\w-]+)$/, "chat"],
  [/^#\/chat$/, "chat", "Chat"],
  [/^#\/settings$/, "settings", "Settings"],
];

const NAV = ROUTES.filter((r) => r[2]);
const view = document.getElementById("view");
const nav = document.getElementById("nav");
let current = null;

function renderNav(name) {
  clear(nav);
  for (const [, mod, label] of NAV) {
    const hash = mod === "home" ? "#/" : `#/${mod}`;
    const on = name === mod || (name === "run" && mod === "runs") || (name === "order" && mod === "orders") || (name === "product" && mod === "cart");
    nav.append(h("a", { href: hash, class: on ? "on" : "" }, label));
  }
}

async function route() {
  const [path, qs] = (location.hash || "#/").split("?");
  const query = Object.fromEntries(new URLSearchParams(qs || ""));
  const match = ROUTES.map(([re, mod]) => [re.exec(path), mod]).find(([m]) => m);
  const [m, mod] = match || [[], "home"];
  renderNav(mod);
  if (current?.cleanup) current.cleanup();
  clear(view);
  const cfg = await getConfig();
  if (!cfg.serverUrl && mod !== "settings") {
    view.append(h("div", { class: "card" }, h("h1", {}, "Welcome"),
      h("p", {}, "This browser isn't paired with your server yet."), h("a", { href: "#/settings" }, "Pair it in Settings →")));
    return;
  }
  try {
    const module = await import(`./views/${mod}.js`);
    current = (await module.render(view, m.slice(1), query)) || null;
  } catch (e) {
    view.append(errorBox(e));
    console.error(e);
  }
}

async function sessionPill() {
  const pill = document.getElementById("session");
  try {
    const s = await get("/api/retailer/session");
    pill.className = `pill ${s.state}`;
    pill.textContent = s.state === "connected" ? `No Frills · ${Math.floor(s.seconds_remaining / 60)} min` : "No Frills: open nofrills.ca to connect";
    pill.title = "The extension sends your No Frills session to the server when you visit nofrills.ca while logged in.";
  } catch {
    pill.textContent = "Not connected";
  }
}

window.addEventListener("hashchange", route);
route();
sessionPill();
setInterval(sessionPill, 60_000);
