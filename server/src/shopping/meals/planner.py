"""Deterministic meal-planning helpers.

The model chooses meals and writes them up; these functions do the arithmetic and matching it would
otherwise guess at: which week it is, what's expiring, which regular recipes line up with this week's deals,
and roughly what a recipe costs from the catalogue.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from sqlalchemy.orm import Session

from shopping.core import catalog
from shopping.notion.kitchen import Kitchen, norm


def week_start(today: date | None = None, weekday: int = 3) -> date:
    """The plan week starts on flyer day (Thursday by default)."""
    today = today or date.today()
    return today - timedelta(days=(today.weekday() - weekday) % 7)


def parse_manifest(text: str | None) -> tuple[int | None, list[dict]]:
    """`Serves: 6` then `Name | quantity [| optional]` lines (the Cooking database's Shopping Ingredients)."""
    serves, items = None, []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"(?i)^serves\s*:\s*(\d+)", line)
        if m:
            serves = int(m.group(1))
            continue
        parts = [p.strip() for p in line.split("|")]
        if parts[0]:
            items.append({"name": parts[0], "quantity": parts[1] if len(parts) > 1 else "",
                          "optional": len(parts) > 2 and parts[2].lower().startswith("optional")})
    return serves, items


def price_ingredient(session: Session, name: str) -> dict | None:
    """The product the household would most likely buy for an ingredient, with its current price."""
    rows = catalog.search_catalog(session, query=name, limit=30)
    rows = [r for r in rows if r.get("price") is not None and (r.get("aisle") or "") not in
            ("Pet Food & Supplies", "Baby", "Personal Care & Beauty", "Household Supplies")]
    if not rows:
        return None
    bought = [r for r in rows if r.get("bought_before")]
    if bought:
        return bought[0]
    on_sale = [r for r in rows if r.get("discount_pct")]
    pool = on_sale or rows
    return sorted(pool, key=lambda r: (r.get("unit_price") is None, r.get("unit_price") or 0))[0]


def cost_manifest(session: Session, manifest: str) -> dict:
    """Rough cost: one package of the likely product per ingredient (pantry staples on hand aren't excluded
    here; the caller decides). Good enough to compare meals and show cost per serving."""
    serves, items = parse_manifest(manifest)
    lines, total, missing = [], 0.0, []
    for it in items:
        p = price_ingredient(session, it["name"])
        if p is None:
            missing.append(it["name"])
            continue
        total += float(p["price"])
        lines.append({"ingredient": it["name"], "quantity": it["quantity"], "product": f"{p.get('brand') or ''} {p['name']}".strip(),
                      "product_id": p["product_id"], "price": p["price"], "on_sale": bool(p.get("discount_pct")),
                      "deal": p.get("deal"), "deal_ends": p.get("deal_ends")})
    return {"serves": serves, "estimated_total": round(total, 2),
            "per_serving": round(total / serves, 2) if serves else None, "lines": lines, "not_found": missing,
            "note": "Estimate: one package of the usual product per ingredient, current prices."}


async def candidates(session: Session, kitchen: Kitchen, *, expiring_days: int = 7, limit: int = 12) -> dict:
    """Regular recipes ranked for this week: deals they'd use, expiring pantry items they'd use up, and
    whether they were cooked (or rejected) recently."""
    regulars = await kitchen.cooking_search(regular_only=True, limit=100)
    expiring = await kitchen.expiring(expiring_days)
    expiring_names = {norm(r["Name"]): r for r in expiring}
    recent: dict[str, dict] = {}
    try:
        for m in await kitchen.meals(limit=100):
            if m.get("Name"):
                recent[norm(m["Name"])] = m
    except Exception:  # noqa: BLE001 - the Meals database may not exist yet
        pass
    out = []
    cutoff = (date.today() - timedelta(days=21)).isoformat()
    for r in regulars:
        serves, items = parse_manifest(r.get("Shopping Ingredients"))
        on_sale, uses_up = [], []
        for it in items:
            key = norm(it["name"])
            if key in expiring_names:
                uses_up.append({"name": expiring_names[key]["Name"], "expires": expiring_names[key]["Expiration"]})
            p = price_ingredient(session, it["name"])
            if p and p.get("discount_pct"):
                on_sale.append({"ingredient": it["name"], "product": p["name"], "price": p["price"],
                                "discount_pct": p["discount_pct"], "ends": p.get("deal_ends")})
        last = recent.get(norm(r.get("Name") or ""))
        cooked_recently = bool(last and last.get("Status") == "Cooked" and (last.get("Cooked On") or "") >= cutoff)
        rejected = bool(last and last.get("Status") == "Rejected")
        score = 10 * len(uses_up) + 4 * len(on_sale) - (15 if cooked_recently else 0) - (20 if rejected else 0)
        if last and last.get("Rating"):
            score += 2 * str(last["Rating"]).count("★")
        out.append({"cooking_id": r["id"], "name": r.get("Name"), "tags": r.get("Tags"), "main_ingredient": r.get("Main Ingredient"),
                    "serves": serves, "has_manifest": bool(items), "uses_up": uses_up, "ingredients_on_sale": on_sale,
                    "cooked_recently": cooked_recently, "previously_rejected": rejected,
                    "last_feedback": (last or {}).get("Feedback"), "score": score})
    out.sort(key=lambda c: -c["score"])
    return {"regular_recipes": out[:limit], "expiring_on_hand": [{"name": e["Name"], "expires": e["Expiration"],
                                                                   "where": f"{e.get('Location') or ''} / {e.get('Sub-Location') or ''}"}
                                                                  for e in expiring]}


def recent_meal_history(meals: list[dict], *, weeks: int = 6) -> dict:
    """Outcomes of recent suggestions: what got cooked, rated, rejected or skipped, in people's words."""
    cutoff = (date.today() - timedelta(weeks=weeks)).isoformat()
    recent = [m for m in meals if (m.get("Week") or m.get("Cook By") or "") >= cutoff]
    pick = lambda status: [{k: m.get(k) for k in ("Name", "Rating", "Leftovers", "Feedback", "Novelty", "Active Time") if m.get(k)}  # noqa: E731
                           for m in recent if m.get("Status") == status]
    return {"cooked": pick("Cooked") + pick("Promoted"), "rejected": pick("Rejected"), "skipped": pick("Skipped"),
            "planned_now": pick("Planned"), "suggested_now": pick("Suggested")}
