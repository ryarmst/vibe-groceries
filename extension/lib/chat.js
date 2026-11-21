// Chat with the assistant: threads, mode chips, streamed replies, tool activity, confirmation cards.
import { del, get, post, stream } from "./api.js";
import { busy, clear, h, link, openApp, richText, toast } from "./ui.js";

const MODES = [["auto", "Auto"], ["ask", "Ask"], ["shop", "Shop"], ["meals", "Meals"], ["pantry", "Pantry"], ["recipes", "Recipes"]];
const TOOL_LABELS = {
  shopping_get_context: "Checking this week's deals", shopping_search_products: "Searching the store", shopping_search_catalog: "Searching the catalogue",
  shopping_create_run: "Starting a shopping run", shopping_add_selection: "Adding an item", shopping_add_choice_group: "Adding options",
  shopping_submit_run_for_review: "Sending the run for review", shopping_get_requirement_history: "Checking what's due",
  notion_pantry: "Reading the pantry", notion_grocery_list: "Reading the grocery list", notion_cooking_search: "Searching recipes",
  meals_context: "Gathering deals, pantry and recipes", meal_cost: "Pricing a recipe", meal_suggest: "Saving a suggested meal",
};

export function mountChat(root, { threadId = null, onThread = () => {} } = {}) {
  let thread = threadId, mode = "auto", controller = null;
  const log = h("div", { class: "log" });
  const input = h("textarea", { rows: 2, placeholder: "Ask, shop, plan meals, or paste a receipt…  (Enter to send, Shift+Enter for a new line)" });
  const sendBtn = h("button", { class: "primary" }, "Send");
  const stopBtn = h("button", { hidden: true, onclick: () => controller?.abort() }, "Stop");
  const chips = h("div", { class: "chips" });
  const threadSelect = h("select", { style: { maxWidth: "60%" } });

  function drawChips() {
    clear(chips).append(...MODES.map(([k, label]) => h("button", { class: `chip ${k === mode ? "on" : ""}`, onclick: () => { mode = k; drawChips(); } }, label)));
  }

  async function loadThreads() {
    const { threads } = await get("/api/chat/threads");
    clear(threadSelect).append(h("option", { value: "" }, "New conversation"),
      ...threads.map((t) => h("option", { value: t.thread_id, selected: t.thread_id === thread }, (t.system ? "📅 " : "") + t.title)));
  }

  async function open(id) {
    thread = id || null;
    onThread(thread);
    clear(log);
    if (!thread) { log.append(h("div", { class: "muted small", style: { padding: "20px 4px" } }, "Try: “do a grocery shop, we need bread”, “plan the week around the deals”, “we used up the eggs”, or “what's a good price for chicken thighs?”")); return; }
    const t = await get(`/api/chat/threads/${thread}`);
    mode = t.mode || "auto";
    drawChips();
    for (const m of t.messages) renderStored(m);
    log.scrollTop = log.scrollHeight;
  }

  function renderStored(m) {
    if (m.role === "user") log.append(h("div", { class: "msg user" }, h("div", { class: "bubble" }, m.content)));
    else if (m.role === "assistant") {
      if (m.content) log.append(h("div", { class: "msg assistant" }, h("div", { class: "bubble" }, richText(m.content)),
        m.model ? h("div", { class: "meta" }, `${m.provider} · ${m.model}${m.cost_usd ? ` · $${m.cost_usd.toFixed(4)}` : ""}`) : null));
      for (const c of m.tool_calls || []) log.append(h("div", { class: "toolline" }, "⚙ ", TOOL_LABELS[c.name] || c.name));
    } else if (m.role === "tool" && m.status === "pending_confirmation") log.append(confirmCard({ message_id: m.id, name: m.tool_name, preview: m.preview }));
    else if (m.role === "tool" && m.status === "declined") log.append(h("div", { class: "toolline error" }, "✕ ", m.content));
  }

  function confirmCard(ev) {
    const note = h("input", { placeholder: "Note if declining (optional)", style: { flex: 1 } });
    const card = h("div", { class: "confirm" }, h("strong", {}, "Confirm this change?"), h("pre", {}, ev.preview || ev.name),
      h("div", { class: "row" }, note,
        h("button", { onclick: (e) => busy(e.target, () => resolve(card, ev.message_id, false, note.value)) }, "Decline"),
        h("button", { class: "primary", onclick: (e) => busy(e.target, () => resolve(card, ev.message_id, true, null)) }, "Approve")));
    return card;
  }

  async function resolve(card, messageId, approve, note) {
    card.querySelectorAll("button").forEach((b) => (b.disabled = true));
    card.append(h("div", { class: "small muted" }, approve ? "Approved." : "Declined."));
    await run(`/api/chat/threads/${thread}/confirm/${messageId}`, { approve, note: note || null });
  }

  async function run(path, body) {
    controller = new AbortController();
    sendBtn.disabled = true; stopBtn.hidden = false;
    let bubble = null, text = "", meta = null;
    const status = h("div", { class: "toolline" }, "Thinking…");
    log.append(status);
    const scroll = () => { log.scrollTop = log.scrollHeight; };
    try {
      for await (const ev of stream(path, body, controller.signal)) {
        if (ev.type === "mode") status.textContent = `${ev.title} mode…`;
        else if (ev.type === "text") {
          if (!bubble) { bubble = h("div", { class: "bubble" }); log.append(h("div", { class: "msg assistant" }, bubble)); }
          text += ev.text;
          bubble.textContent = text;
        } else if (ev.type === "tool") {
          if (ev.status === "running") log.append(h("div", { class: "toolline" }, "⚙ ", TOOL_LABELS[ev.name] || ev.name, "…"));
          else if (ev.status === "error" || ev.status === "declined") log.append(h("div", { class: "toolline error" }, "✕ ", ev.name, ": ", (ev.summary || "").slice(0, 200)));
          finish();
        } else if (ev.type === "confirm") { finish(); log.append(confirmCard(ev)); }
        else if (ev.type === "notice") log.append(h("div", { class: "toolline error" }, ev.text));
        else if (ev.type === "usage") meta = `${ev.provider} · ${ev.model}${ev.cost_usd ? ` · $${ev.cost_usd.toFixed(4)}` : ""}`;
        else if (ev.type === "error") log.append(h("div", { class: "flash err" }, ev.message));
        scroll();
      }
    } catch (e) {
      if (e.name !== "AbortError") log.append(h("div", { class: "flash err" }, e.message));
    } finally {
      finish();
      status.remove();
      sendBtn.disabled = false; stopBtn.hidden = true; controller = null;
      browser.runtime.sendMessage({ type: "refreshInbox" }).catch(() => {});
      scroll();
    }
    function finish() {
      if (bubble) { const done = richText(text); bubble.replaceWith(done); if (meta) done.after(h("div", { class: "meta" }, meta)); }
      bubble = null; text = ""; meta = null;
    }
  }

  async function send() {
    const textValue = input.value.trim();
    if (!textValue || controller) return;
    if (!thread) {
      const t = await post("/api/chat/threads", { mode });
      thread = t.thread_id;
      onThread(thread);
      clear(log);
    }
    input.value = "";
    log.append(h("div", { class: "msg user" }, h("div", { class: "bubble" }, textValue)));
    await run(`/api/chat/threads/${thread}/messages`, { text: textValue, mode });
    loadThreads();
  }

  sendBtn.addEventListener("click", send);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
  threadSelect.addEventListener("change", () => open(threadSelect.value));

  root.append(h("div", { class: "chat" },
    h("div", { class: "row", style: { padding: "8px 10px", borderBottom: "1px solid var(--line)" } }, threadSelect,
      h("button", { class: "link", onclick: () => { threadSelect.value = ""; open(null); } }, "New"),
      h("span", { class: "spacer" }),
      h("button", { class: "link", title: "Delete this conversation", onclick: async () => {
        if (!thread || !confirm("Delete this conversation?")) return;
        await del(`/api/chat/threads/${thread}`); toast("Deleted."); await loadThreads(); open(null);
      } }, "🗑")),
    log,
    h("div", { class: "composer" }, chips, h("div", { style: { marginTop: "6px" } }, input),
      h("div", { class: "row", style: { marginTop: "6px" } }, h("span", { class: "small muted" }, "Changes to Notion ask before they happen."),
        h("span", { class: "spacer" }), stopBtn, sendBtn))));
  drawChips();
  loadThreads().then(() => open(thread)).catch((e) => log.append(h("div", { class: "flash err" }, e.message)));
  return { open };
}
