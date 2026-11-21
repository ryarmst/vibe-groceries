"""Suggested Meals: the week's plan, people's decisions (keep, reject, cooked + rating), promotion."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from shopping import appsettings
from shopping.api.deps import Caller, require_device
from shopping.core import inbox
from shopping.database import session_scope
from shopping.jobs import weekly
from shopping.meals import planner
from shopping.notion.client import NotionError
from shopping.notion.kitchen import open_kitchen

router = APIRouter(prefix="/api/meals", dependencies=[Depends(require_device)])

STATUS_FOR = {"keep": "Planned", "reject": "Rejected", "cooked": "Cooked", "skip": "Skipped", "suggested": "Suggested"}
RATINGS = {1: "★", 2: "★★", 3: "★★★", 4: "★★★★", 5: "★★★★★"}


@router.get("")
async def meals(week: str | None = None, all_weeks: bool = False):
    with session_scope() as session:
        jobs = appsettings.get(session, "jobs")
    wk = week or planner.week_start(weekday=int(jobs["weekly_plan_weekday"])).isoformat()
    try:
        async with open_kitchen() as k:
            rows = await k.meals(week=None if all_weeks else wk, limit=200)
            schema = await k.schema("meals")
    except NotionError as exc:
        return {"week": wk, "meals": [], "error": str(exc), "configured": False}
    from shopping.notion.props import options

    return {"week": wk, "meals": rows, "configured": True,
            "options": {name: options(schema, name) for name in ("Status", "Rating", "Leftovers", "Tags", "Novelty") if name in schema}}


class DecisionBody(BaseModel):
    action: str = Field(pattern="^(keep|reject|cooked|skip|suggested)$")
    rating: int | None = Field(default=None, ge=1, le=5)
    leftovers: str | None = Field(default=None, max_length=32)
    feedback: str | None = Field(default=None, max_length=2000)
    cooked_on: str | None = None


@router.post("/{page_id}/decision")
async def decide(page_id: str, body: DecisionBody, caller: Caller = Depends(require_device)):
    values: dict = {"Status": STATUS_FOR[body.action]}
    if body.action == "cooked":
        values["Cooked On"] = body.cooked_on or date.today().isoformat()
    if body.rating:
        values["Rating"] = RATINGS[body.rating]
    if body.leftovers:
        values["Leftovers"] = body.leftovers
    if body.feedback:
        values["Feedback"] = f"{body.feedback.strip()} — {caller.name}"
    async with open_kitchen() as k:
        result = await k.meal_update(page_id, values)
    with session_scope() as session:
        inbox.dismiss_key(session, f"checkin:{page_id}")
    return {"ok": True, **result}


@router.post("/{page_id}/promote")
async def promote(page_id: str):
    async with open_kitchen() as k:
        return await k.promote_meal(page_id)


@router.post("/plan-week")
async def plan_week(caller: Caller = Depends(require_device)):
    """Run the weekly plan now (in the background); its conversation shows up in Chat and the inbox."""
    thread_id = weekly.start_in_background(requested_by=caller.device_id)
    return {"started": bool(thread_id), "thread_id": thread_id,
            "message": "Planning the week… the meals and run will appear in a few minutes." if thread_id else "A plan is already running."}
