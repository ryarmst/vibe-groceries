// Deals: your items on sale, best deals per aisle (from the store-wide scan), and the Top deals list.
import { get, post } from "../../lib/api.js";
import { ago, badge, busy, clear, empty, h, link, money, pct, toast, unit } from "../../lib/ui.js";

export async function render(el) {
  const [ctx, top] = await Promise.all([get("/api/deals/context"), get("/api/deals/top")]);
  const scan = ctx.deal_data;
  el.append(h("div", { class: "between" }, h("h1", {}, "Deals"),
    h("span", { class: "small muted" }, scan.last_scan ? `${scan.deals_known_now} items on sale · scanned ${ago(scan.last_scan.finished_at)}` : "No scan yet",
      scan.scan_running ? " (scanning now)" : " ",
      scan.scan_running ? null : h("button", { class: "link", onclick: (e) => busy(e.target, async () => {
        await post("/api/deals/scan"); toast("Scanning every aisle; about 3 minutes.");
      }) }, "Rescan"))));

  const active = top.deals.filter((d) => d.status === "active");
  el.append(h("h2", {}, "Top deals (flagged by the assistant)"));
  if (!active.length) el.append(empty("None flagged right now."));
  for (const d of active) el.append(topDeal(d));

  el.append(h("h2", {}, "Your items on sale"));
  if (!ctx.your_items_on_sale.length) el.append(empty("Nothing you've bought before is on sale right now."));
  el.append(h("div", {}, ...ctx.your_items_on_sale.map((p) => productRow(p))));

  el.append(h("h2", {}, "Best by aisle"));
  for (const [aisle, items] of Object.entries(ctx.top_deals_by_aisle)) {
    el.append(h("details", { class: "card" }, h("summary", {}, h("strong", {}, aisle), h("span", { class: "muted small" }, ` · ${items.length}`)),
      ...items.map((p) => productRow(p))));
  }
  el.append(addOwn());
}

function productRow(p) {
  return h("div", { class: "between", style: { padding: "6px 0", borderBottom: "1px solid var(--line)" } },
    h("div", {}, h("strong", {}, `${p.brand ? p.brand + " " : ""}${p.name}`), " ", h("span", { class: "small muted" }, p.size || ""),
      h("div", { class: "small muted" }, [p.deal, p.deal_ends ? `ends ${p.deal_ends}` : null, p.is_lowest_seen ? "lowest we've seen" : null,
        p.bought_before ? `bought ${p.bought_before.times}×` : null, p.other_variants_same_price ? `+${p.other_variants_same_price} other flavours` : null].filter(Boolean).join(" · "))),
    h("div", { class: "price" }, h("span", { class: "sale" }, money(p.price)), p.regular_price ? h("span", { class: "was" }, " ", money(p.regular_price)) : null,
      h("div", { class: "small muted" }, unit(p.unit_price, p.unit_price_basis)), link(`#/product/${p.product_id}`, "details")));
}

function topDeal(d) {
  const qty = h("input", { type: "number", min: 1, step: 1, value: d.suggested_quantity || 1, style: { width: "4.5em" } });
  const note = h("input", { placeholder: "Why not? (optional)", style: { flex: 1, minWidth: "180px" } });
  return h("section", { class: "card" },
    h("div", { class: "between" }, h("h3", {}, d.relevant_to || "Deal"), h("span", { class: "badge ok" }, "★".repeat(d.rating), " ", d.rating_label)),
    h("div", { class: "product" }, d.image_url ? h("img", { src: d.image_url, alt: "" }) : h("div"),
      h("div", {}, h("div", { class: "small muted" }, d.brand || ""), h("div", { class: "name" }, d.name, " ", h("span", { class: "small muted" }, d.size || "")),
        badge(d.headline, "sale"), h("div", { class: "small" }, d.why || ""),
        h("div", { class: "small muted" }, [d.deal_text, d.ends ? `ends ${d.ends}` : null, d.lowest_seen && d.days_observed > 1 ? `lowest seen ${money(d.lowest_seen)}` : null].filter(Boolean).join(" · ")),
        d.price_changed_since_flagged ? h("div", { class: "small warn" }, `Price changed since flagged: now ${money(d.latest_price)}`) : null),
      h("div", { class: "price" }, h("div", { class: "now sale" }, money(d.price)), d.discount_pct ? h("div", { class: "was" }, money(d.regular_price)) : null,
        h("div", { class: "small muted" }, unit(d.unit_price, d.unit_price_basis)))),
    h("div", { class: "row", style: { marginTop: "8px" } }, qty,
      h("button", { class: "primary", onclick: (e) => busy(e.target, async () => {
        const r = await post(`/api/deals/top/${d.deal_id}/cart`, { quantity: Number(qty.value) }); toast(r.message); location.reload();
      }) }, "Add to cart"),
      h("span", { class: "spacer" }), note,
      h("button", { onclick: (e) => busy(e.target, async () => {
        await post(`/api/deals/top/${d.deal_id}/dismiss`, { note: note.value || null }); toast("Dismissed; the assistant will see why."); location.reload();
      }) }, "Not for me")));
}

function addOwn() {
  const product = h("input", { placeholder: "nofrills.ca product link or code", style: { width: "100%" } });
  const why = h("input", { placeholder: "Why (optional)" });
  const forItem = h("input", { placeholder: "For (pantry item, optional)" });
  return h("details", { class: "card" }, h("summary", {}, "Add a deal yourself"),
    h("div", { class: "form-grid", style: { marginTop: "8px" } }, h("label", {}, "Product", product), h("label", {}, "Why", why), h("label", {}, "For", forItem)),
    h("div", { class: "row", style: { marginTop: "8px" } }, h("button", { onclick: (e) => busy(e.target, async () => {
      await post("/api/deals/top", { product: product.value, why: why.value || null, relevant_to: forItem.value || null });
      toast("Added to Top deals."); location.reload();
    }) }, "Add deal")));
}
