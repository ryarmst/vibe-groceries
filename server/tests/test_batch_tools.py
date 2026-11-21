from dataclasses import replace

import pytest

from shopping import context
from shopping.database import session_scope
from shopping.mcp_server import server as mcp
from shopping.models import ChoiceGroup, Selection, ShoppingRun
from test_service import FakeClient


class SearchingClient(FakeClient):
    async def search_products(self, query, page=1, **kw):
        q = query.lower().split()[0]
        return {"products": [p for p in self.products.values() if q in p.name.lower()], "total_results": 0}


@pytest.fixture
def fake(monkeypatch):
    c = SearchingClient()
    monkeypatch.setattr(context, "client", lambda: c)
    return c


async def test_stage_items_creates_run_stages_all_and_submits(fake):
    ids = list(fake.products)
    out_of_stock = ids[3]
    fake.products[out_of_stock] = replace(fake.products[out_of_stock], availability="OUT_OF_STOCK")
    r = await mcp.shopping_stage_items(summary="Batch test", submit=True, items=[
        mcp.StageItem(requirement="Peanut Butter", options=[mcp.ChoiceOption(product_id=ids[0]), mcp.ChoiceOption(product_id=ids[1])],
                      recommended_index=1, reasons=["grocery_list"]),
        mcp.StageItem(requirement="Jam", product_id=ids[2], quantity=2, reasons=["regular_staple"], rationale="due"),
        mcp.StageItem(requirement="Crackers", product_id=out_of_stock, reasons=["grocery_list"]),
        mcp.StageItem(requirement="Nothing"),
    ])
    assert r["staged"] == 2 and r["status"] == "review" and r["review_url"].startswith("#/runs/")
    assert {f["requirement"] for f in r["failed"]} == {"Crackers", "Nothing"} and "out of stock" in r["failed"][0]["error"]
    with session_scope() as s:
        run = s.get(ShoppingRun, r["run_id"])
        group = s.query(ChoiceGroup).filter_by(shopping_run_id=run.id).one()
        assert group.label == "Peanut Butter" and group.recommended_selection_id == group.selections[1].id
        assert {sel.requirement for sel in group.selections} == {"Peanut Butter"}
        jam = s.query(Selection).filter_by(shopping_run_id=run.id, requirement="Jam").one()
        assert jam.quantity == 2 and jam.reason_codes == ["regular_staple"]
    # A second batch into the same run.
    r2 = await mcp.shopping_stage_items(run_id=r["run_id"], items=[mcp.StageItem(requirement="More Jam", product_id=ids[4])])
    assert r2["run_id"] == r["run_id"] and r2["staged"] == 1


async def test_search_many(fake):
    some = next(iter(fake.products.values()))
    word = some.name.split()[0]
    fake.products["gone_EA"] = replace(some, retailer_product_id="gone_EA", availability="OUT_OF_STOCK")
    r = await mcp.shopping_search_many(queries=[word, word, "zzz-nothing"], per_query=3)
    assert set(r["results"]) == {word, "zzz-nothing"}  # duplicates collapsed
    hits = r["results"][word]
    assert 0 < len(hits) <= 3 and all("gone_EA" != h["product_id"] for h in hits)
    assert set(hits[0]) <= set(mcp.COMPACT_KEYS)
    assert r["results"]["zzz-nothing"] == []
