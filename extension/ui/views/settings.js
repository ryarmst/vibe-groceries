// Settings: pairing, No Frills session, devices, LLM providers and keys (write-only), Notion, budget, jobs.
import { del, get, post, put } from "../../lib/api.js";
import { forget, getConfig, normalizeServer, pair } from "../../lib/auth.js";
import { ago, busy, clear, h, money, toast, when } from "../../lib/ui.js";

const PROVIDER_LABELS = { gemini: "Google Gemini", openai: "OpenAI", anthropic: "Anthropic (Claude)", groq: "Groq",
  openrouter: "OpenRouter", mistral: "Mistral", custom: "Custom (OpenAI-compatible)" };
const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

export async function render(el) {
  el.append(h("h1", {}, "Settings"));
  const cfg = await getConfig();
  el.append(pairingCard(cfg));
  if (!cfg.serverUrl) return;
  const [all, secrets, devices, usage] = await Promise.all([get("/api/settings"), get("/api/settings/secrets"),
    get("/api/devices"), get("/api/llm/usage")]);
  el.append(await nofrillsCard(), budgetCard(all.budget, usage.summary), llmCard(all.llm, all.providers), keysCard(secrets.secrets),
    notionCard(all.notion), jobsCard(all.jobs), devicesCard(devices));
}

function section(title, ...body) { return h("section", { class: "card" }, h("h2", { style: { marginTop: 0 } }, title), ...body); }

function field(label, input, hint) {
  return h("label", {}, label, input, hint ? h("span", { class: "small muted" }, hint) : null);
}

function pairingCard(cfg) {
  if (cfg.serverUrl) {
    return section("This browser",
      h("p", {}, "Paired with ", h("strong", {}, cfg.serverUrl), " as ", h("strong", {}, cfg.deviceName || "this browser"), "."),
      h("button", { class: "danger", onclick: async (e) => {
        if (!confirm("Forget this pairing? You'll need a new pairing code to reconnect.")) return;
        await busy(e.target, forget);
        location.reload();
      } }, "Unpair this browser"));
  }
  const url = h("input", { type: "url", placeholder: "https://groceries.example.com", required: true, style: { width: "100%" } });
  const code = h("input", { placeholder: "XXXX-XXXX-XXXX-XXXX", autocomplete: "off", spellcheck: false });
  const name = h("input", { placeholder: "e.g. Steph laptop" });
  const button = h("button", { class: "primary", onclick: (e) => {
    let origin;
    try { origin = normalizeServer(url.value); } catch (err) { toast(err.message, "err"); return; }
    // The permission prompt must come straight from the click.
    browser.permissions.request({ origins: [origin + "/*"] }).then(async (granted) => {
      if (!granted) { toast("Permission to reach the server is needed.", "err"); return; }
      await busy(e.target, () => pair(origin, code.value, name.value));
      toast("Paired. Welcome!");
      browser.runtime.sendMessage({ type: "refreshInbox" });
      browser.runtime.sendMessage({ type: "sendSessionNow" });
      location.hash = "#/";
      location.reload();
    });
  } }, "Pair this browser");
  return section("Pair this browser",
    h("p", { class: "muted small" }, "On the server, run ", h("code", {}, "vibe pair --name \"Your name laptop\""),
      " (add --cert if client certificates are required) and enter the code here. The browser creates a key that never leaves it."),
    h("div", { class: "form-grid" }, field("Server URL", url), field("Pairing code", code), field("Name for this browser", name)),
    h("div", { class: "row", style: { marginTop: "10px" } }, button));
}

async function nofrillsCard() {
  const status = await get("/api/retailer/session");
  const hasPerm = await browser.permissions.contains({ origins: ["https://*.nofrills.ca/*"] });
  return section("No Frills session",
    h("p", {}, status.state === "connected" ? `Connected · ${Math.floor(status.seconds_remaining / 60)} minutes left.` :
      "Not connected. Open nofrills.ca and log in; the extension sends the session automatically."),
    h("p", { class: "small muted" }, "Only the AccessToken cookie is read, and only to keep the cart working. It expires after an hour; visiting nofrills.ca renews it."),
    hasPerm ? null : h("p", { class: "warn" }, "The extension doesn't have access to nofrills.ca cookies yet. ",
      h("button", { onclick: () => browser.permissions.request({ origins: ["https://*.nofrills.ca/*"] }).then(() => location.reload()) }, "Allow")),
    h("button", { onclick: async (e) => {
      const r = await busy(e.target, () => browser.runtime.sendMessage({ type: "sendSessionNow" }));
      toast(r?.sent ? "Session sent." : r?.reason === "no_cookie" ? "No session cookie found: open nofrills.ca and log in first." :
        r?.reason === "expired" ? "That session has expired: reload nofrills.ca." : r?.error || "Already up to date.", r?.sent ? "ok" : "err");
    } }, "Send session now"));
}

function budgetCard(b, s) {
  const cap = h("input", { type: "number", min: 0, max: 1000, step: 1, value: b.monthly_usd, style: { width: "7em" } });
  const warn = h("input", { type: "number", min: 1, max: 100, value: b.warn_at_pct, style: { width: "5em" } });
  const daily = h("input", { type: "number", min: 1, max: 10000, value: b.daily_requests, style: { width: "6em" } });
  const save = (value) => put("/api/settings/budget", value).then(() => { toast("Budget saved."); location.reload(); });
  return section("LLM budget",
    h("p", {}, `This month: ${money(s.month_spent_usd)} of ${money(s.monthly_cap_usd)} (${s.pct}%) · ${s.requests_today} requests today. `,
      s.warn ? h("strong", { class: "warn" }, "Near the cap.") : null),
    h("p", { class: "small muted" }, "Gemini's free tier counts as $0. Paid models without a price in LLM settings are counted at a deliberately high estimate."),
    h("div", { class: "row" }, h("span", { class: "small" }, "Quick set:"),
      ...[5, 10, 25, 50].map((v) => h("button", { onclick: () => save({ monthly_usd: v }) }, `$${v}`))),
    h("div", { class: "form-grid", style: { marginTop: "8px" } }, field("Monthly cap ($)", cap), field("Warn at (%)", warn), field("Requests per day", daily)),
    h("div", { class: "row", style: { marginTop: "8px" } }, h("button", { class: "primary", onclick: (e) => busy(e.target, () =>
      save({ monthly_usd: Number(cap.value), warn_at_pct: Number(warn.value), daily_requests: Number(daily.value) })) }, "Save budget")));
}

function llmCard(llm, providers) {
  const tierRow = (tier, help) => {
    const provider = h("select", {}, ...providers.map((p) => h("option", { value: p, selected: llm.tiers[tier].provider === p }, PROVIDER_LABELS[p] || p)));
    const model = h("input", { value: llm.tiers[tier].model, list: `models-${tier}`, style: { width: "16em" } });
    const list = h("datalist", { id: `models-${tier}` });
    return { provider, model, row: h("div", { class: "card" }, h("div", { class: "between" }, h("strong", {}, tier === "fast" ? "Fast model" : "Smart model"),
      h("span", { class: "small muted" }, help)),
      h("div", { class: "form-grid" }, field("Provider", provider), field("Model", h("span", {}, model, list))),
      h("div", { class: "row", style: { marginTop: "6px" } },
        h("button", { onclick: async (e) => {
          const r = await busy(e.target, () => get(`/api/llm/models/${provider.value}`));
          clear(list).append(...(r.models || []).map((m) => h("option", { value: m })));
          toast(r.error || `${(r.models || []).length} models available; start typing in the Model box.`, r.error ? "err" : "ok");
        } }, "Load models"),
        h("button", { onclick: async (e) => {
          const r = await busy(e.target, () => post("/api/llm/test", { provider: provider.value, model: model.value }));
          toast(r.ok ? `Works: “${r.reply}”` : r.error, r.ok ? "ok" : "err");
        } }, "Test"))) };
  };
  const fast = tierRow("fast", "Quick questions, pantry updates");
  const smart = tierRow("smart", "Shopping runs and meal plans");
  const fallback = h("textarea", { rows: 2, placeholder: "groq: llama-3.3-70b-versatile" },
    (llm.fallback || []).map((f) => `${f.provider}: ${f.model}`).join("\n"));
  const custom = h("input", { type: "url", value: llm.custom_base_url || "", placeholder: "http://localhost:11434/v1" });
  const temp = h("input", { type: "number", step: 0.1, min: 0, max: 1.5, value: llm.temperature, style: { width: "5em" } });
  const steps = h("input", { type: "number", min: 1, max: 40, value: llm.max_steps, style: { width: "5em" } });
  const prices = h("textarea", { rows: 2, placeholder: "claude-sonnet-4-5: 3, 15" },
    Object.entries(llm.prices || {}).map(([m, [i, o]]) => `${m}: ${i}, ${o}`).join("\n"));
  const parseLines = (text, fn) => text.value.split("\n").map((l) => l.trim()).filter(Boolean).map(fn);
  return section("LLM",
    fast.row, smart.row,
    h("div", { class: "form-grid" },
      field("Fallbacks (provider: model per line)", fallback, "Tried in order when the main model fails."),
      field("Custom endpoint base URL", custom, "For the Custom provider, e.g. a local Ollama."),
      field("Prices (model: input, output $/M tokens)", prices, "For budget tracking of paid models."),
      field("Temperature", temp), field("Max tool steps per reply", steps)),
    h("div", { class: "row", style: { marginTop: "8px" } }, h("button", { class: "primary", onclick: (e) => busy(e.target, async () => {
      await put("/api/settings/llm", {
        tiers: { fast: { provider: fast.provider.value, model: fast.model.value.trim() }, smart: { provider: smart.provider.value, model: smart.model.value.trim() } },
        fallback: parseLines(fallback, (l) => { const [p, ...m] = l.split(":"); return { provider: p.trim(), model: m.join(":").trim() }; }),
        custom_base_url: custom.value.trim(), temperature: Number(temp.value), max_steps: Number(steps.value),
        prices: Object.fromEntries(parseLines(prices, (l) => { const [m, rest] = l.split(/:(?=[^:]*$)/); return [m.trim(), rest.split(",").map(Number)]; })),
      });
      toast("LLM settings saved.");
    }) }, "Save LLM settings")));
}

function keysCard(secrets) {
  const rows = secrets.map((s) => {
    const input = h("input", { type: "password", autocomplete: "off", placeholder: s.set ? "Replace…" : "Paste key…", style: { width: "18em" } });
    return h("tr", {},
      h("td", {}, s.label, h("div", { class: "small muted" }, s.name)),
      h("td", { class: "small" }, s.set ? `set · …${s.last4 || "••••"} · ${ago(s.updated_at)}` : h("span", { class: "muted" }, "not set"),
        s.last_used_at ? h("div", { class: "muted" }, `used ${ago(s.last_used_at)}`) : null),
      h("td", {}, h("div", { class: "row" }, input,
        h("button", { onclick: (e) => busy(e.target, async () => {
          if (!input.value.trim()) return;
          await put(`/api/settings/secrets/${encodeURIComponent(s.name)}`, { value: input.value.trim() });
          input.value = "";
          toast("Saved. The key is stored encrypted on the server and never shown again.");
          location.reload();
        }) }, "Save"),
        s.set ? h("button", { class: "danger", onclick: (e) => busy(e.target, async () => {
          if (!confirm(`Remove the ${s.label}?`)) return;
          await del(`/api/settings/secrets/${encodeURIComponent(s.name)}`);
          location.reload();
        }) }, "Remove") : null)));
  });
  return section("API keys",
    h("p", { class: "small muted" }, "Keys go straight to the server, which stores them encrypted. They are never stored in this browser or sent back."),
    h("div", { class: "table-wrap" }, h("table", { class: "table" }, h("tbody", {}, ...rows))));
}

function notionCard(n) {
  const inputs = Object.fromEntries(["pantry", "groceries", "cooking", "meals"].map((k) => [k, h("input", { value: n[k] || "", placeholder: "data source id", style: { width: "100%" } })]));
  return section("Notion",
    h("p", { class: "small muted" }, "Create an internal integration in Notion, share these four databases with it, and save its token under API keys. ",
      "The data source id is the collection:// value (or the database URL's id)."),
    h("div", { class: "form-grid" }, field("Kitchen Pantry and Storage", inputs.pantry), field("Groceries", inputs.groceries),
      field("Cooking", inputs.cooking), field("Suggested Meals", inputs.meals)),
    h("div", { class: "row", style: { marginTop: "8px" } }, h("button", { class: "primary", onclick: (e) => busy(e.target, async () => {
      await put("/api/settings/notion", Object.fromEntries(Object.entries(inputs).map(([k, i]) => [k, i.value.trim()])));
      toast("Notion settings saved.");
    }) }, "Save Notion settings")));
}

function jobsCard(j) {
  const enabled = h("input", { type: "checkbox", checked: j.weekly_plan_enabled });
  const dayIn = h("select", {}, ...DAYS.map((d, i) => h("option", { value: i, selected: j.weekly_plan_weekday === i }, d)));
  const hour = h("input", { type: "number", min: 0, max: 23, value: j.weekly_plan_hour, style: { width: "5em" } });
  const meals = h("input", { type: "number", min: 1, max: 14, value: j.meals_per_week, style: { width: "5em" } });
  const checkins = h("input", { type: "checkbox", checked: j.checkins_enabled });
  const checkinHour = h("input", { type: "number", min: 0, max: 23, value: j.checkin_hour, style: { width: "5em" } });
  const orders = h("input", { type: "checkbox", checked: j.order_import_enabled });
  const dealsHour = h("input", { type: "number", min: 0, max: 23, value: j.deals_hour, style: { width: "5em" } });
  const alerts = h("input", { type: "checkbox", checked: j.deal_alerts });
  const review = h("input", { type: "checkbox", checked: j.deal_review });
  return section("Schedule",
    h("label", { class: "row" }, enabled, "Plan the week automatically (meals + a shopping run to review)"),
    h("div", { class: "form-grid" }, field("Day (new flyer: Thursday)", dayIn), field("Hour", hour), field("Meals per week", meals)),
    h("label", { class: "row", style: { marginTop: "10px" } }, checkins, "Daily check-in on planned meals at", checkinHour, ":00"),
    h("label", { class: "row" }, orders, "Import new No Frills orders each evening (when the session is connected)"),
    h("label", { class: "row", style: { marginTop: "10px" } }, "Check deals every day at", dealsHour, ":00 (no No Frills login needed)"),
    h("label", { class: "row" }, review, "Also ask the assistant for discoveries (great deals on things you haven't bought; one LLM call a day)"),
    h("label", { class: "row" }, alerts, "Send a phone alert for stock-up deals (needs an ntfy topic under API keys)",
      h("button", { class: "link", onclick: async (e) => {
        const r = await busy(e.target, () => post("/api/settings/notify/test"));
        toast(r.ok ? "Test alert sent." : r.error, r.ok ? "ok" : "err");
      } }, "Send test alert")),
    h("p", { class: "small muted" }, "ntfy: install the ntfy app, subscribe to a long random topic name (e.g. vibe-groceries-", "k3j9x…), ",
      "and save https://ntfy.sh/<that name> as the ntfy topic URL. Anyone who knows the name can read the alerts, so keep it random."),
    h("div", { class: "row", style: { marginTop: "8px" } }, h("button", { class: "primary", onclick: (e) => busy(e.target, async () => {
      await put("/api/settings/jobs", { weekly_plan_enabled: enabled.checked, weekly_plan_weekday: Number(dayIn.value),
        weekly_plan_hour: Number(hour.value), meals_per_week: Number(meals.value), checkins_enabled: checkins.checked,
        checkin_hour: Number(checkinHour.value), order_import_enabled: orders.checked,
        deals_hour: Number(dealsHour.value), deal_alerts: alerts.checked, deal_review: review.checked });
      toast("Schedule saved.");
    }) }, "Save schedule")));
}

function devicesCard(d) {
  const codeBox = h("div");
  return section("Paired browsers",
    h("table", { class: "table" }, h("tbody", {}, ...d.devices.map((x) => h("tr", {},
      h("td", {}, x.name, x.id === d.you ? h("span", { class: "badge ok" }, "this browser") : null),
      h("td", { class: "small muted" }, x.revoked ? "revoked" : `last seen ${ago(x.last_seen_at) || "never"}`, x.has_certificate ? " · certificate" : ""),
      h("td", {}, x.revoked ? null : h("button", { class: "danger", onclick: (e) => busy(e.target, async () => {
        if (!confirm(`Revoke ${x.name}? It stops working immediately.`)) return;
        await del(`/api/devices/${x.id}`);
        location.reload();
      }) }, "Revoke")))))),
    h("div", { class: "row", style: { marginTop: "8px" } }, h("button", { onclick: (e) => busy(e.target, async () => {
      const name = prompt("Name for the new browser (e.g. Steph laptop):");
      if (name === null) return;
      const r = await post("/api/devices/pairing-code", { name });
      clear(codeBox).append(r.code ? h("p", {}, "Pairing code (10 minutes, single use): ", h("strong", {}, r.code)) : h("p", { class: "warn" }, r.message));
    }) }, "New pairing code")), codeBox);
}
