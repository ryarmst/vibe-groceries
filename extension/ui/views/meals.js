// This week's suggested meals (Notion): keep, reject, cooked (+ rating, leftovers, note), skip, promote.
import { get, post } from "../../lib/api.js";
import { badge, busy, clear, day, empty, extLink, h, link, money, toast } from "../../lib/ui.js";

export async function render(el, _params, query) {
  const data = await get(`/api/meals${query.all ? "?all_weeks=true" : ""}`);
  el.append(h("div", { class: "between" }, h("h1", {}, query.all ? "All suggested meals" : `Meals · week of ${day(data.week)}`),
    h("div", { class: "row" },
      h("a", { href: query.all ? "#/meals" : "#/meals?all=1" }, query.all ? "This week" : "All weeks"),
      h("button", { class: "primary", onclick: (e) => busy(e.target, async () => {
        const r = await post("/api/meals/plan-week"); toast(r.message, r.started ? "ok" : "err");
      }) }, "Plan the week now"))));
  if (!data.configured) {
    el.append(h("div", { class: "flash err" }, data.error, " ", link("#/settings", "Settings")));
    return;
  }
  if (!data.meals.length) { el.append(empty("No meals suggested for this week yet.")); return; }
  const leftoverOptions = data.options?.Leftovers?.length ? data.options.Leftovers : ["None", "Some", "Too much", "Not enough"];
  for (const m of data.meals) el.append(mealCard(m, leftoverOptions));
}

function mealCard(m, leftoverOptions) {
  const box = h("section", { class: "card" });
  const status = m.Status || "Suggested";
  box.append(h("div", { class: "between" },
    h("div", {}, h("strong", { style: { fontSize: "17px" } }, m.Name || "Untitled"), " ",
      m.url ? extLink(m.url, "open in Notion") : null),
    h("span", { class: `status ${status}` }, status)));
  const facts = [m["Cook By"] ? `cook by ${day(m["Cook By"])}` : null, m["Active Time"] ? `${m["Active Time"]} min active` : null,
    m["Total Time"] ? `${m["Total Time"]} min total` : null, m.Servings ? `serves ${m.Servings}` : null,
    m["Est. Cost"] ? `${money(m["Est. Cost"])}${m.Servings ? ` (${money(m["Est. Cost"] / m.Servings)}/serving)` : ""}` : null].filter(Boolean);
  box.append(h("div", { class: "small muted" }, facts.join(" · ")));
  box.append(h("div", { style: { marginTop: "4px" } }, m.Novelty ? badge(m.Novelty, m.Novelty === "New" ? "warn" : "") : null,
    ...(m.Tags || []).map((t) => badge(t)), m.Cuisine ? badge(m.Cuisine) : null));
  if (m.Deals) box.append(h("p", { class: "small sale" }, "Deals: ", m.Deals));
  if (m.Feedback) box.append(h("p", { class: "small" }, "✎ ", m.Feedback));
  if (m.Rating) box.append(h("p", { class: "small" }, m.Rating, m.Leftovers ? ` · leftovers: ${m.Leftovers}` : ""));

  const note = h("input", { placeholder: "Note (optional): what to change, why not…", style: { flex: 1, minWidth: "220px" } });
  const act = (action, extra = {}) => (e) => busy(e.target, async () => {
    await post(`/api/meals/${m.id}/decision`, { action, feedback: note.value || null, ...extra });
    toast(`${m.Name}: ${action === "keep" ? "planned" : action}.`);
    location.reload();
  });
  if (["Suggested"].includes(status)) {
    box.append(h("div", { class: "row", style: { marginTop: "8px" } }, note,
      h("button", { class: "danger", onclick: act("reject") }, "Reject"), h("button", { class: "primary", onclick: act("keep") }, "Keep")));
  } else if (status === "Planned") {
    let rating = 0;
    const stars = h("span", { class: "stars" });
    const drawStars = () => { clear(stars).append(...[1, 2, 3, 4, 5].map((n) => h("button", { class: n <= rating ? "on" : "", title: `${n} stars`,
      onclick: () => { rating = n; drawStars(); } }, "★"))); };
    drawStars();
    const leftovers = h("select", {}, h("option", { value: "" }, "Leftovers?"), ...leftoverOptions.map((o) => h("option", { value: o }, o)));
    box.append(h("div", { class: "row", style: { marginTop: "8px" } }, "Cooked it?", stars, leftovers),
      h("div", { class: "row", style: { marginTop: "6px" } }, note,
        h("button", { onclick: act("skip") }, "Didn't get to it"),
        h("button", { class: "primary", onclick: (e) => act("cooked", { rating: rating || null, leftovers: leftovers.value || null })(e) }, "Cooked")));
  } else if (status === "Cooked") {
    box.append(h("div", { class: "row", style: { marginTop: "8px" } }, h("span", { class: "small muted" }, "A keeper?"),
      h("button", { onclick: (e) => busy(e.target, async () => {
        const r = await post(`/api/meals/${m.id}/promote`);
        toast(r.already_promoted ? "Already in Cooking." : "Saved to Cooking."); location.reload();
      }) }, "Promote to Cooking")));
  }
  return box;
}
