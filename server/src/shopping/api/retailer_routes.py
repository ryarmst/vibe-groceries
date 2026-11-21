"""The No Frills session: the extension sends the AccessToken cookie whenever it changes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from sqlalchemy import select

from shopping import context
from shopping.api.deps import Caller, require_device
from shopping.core import inbox
from shopping.core.cart_queue import queue as cart_queue
from shopping.database import session_scope
from shopping.models import RUN_APPROVED, RUN_PARTIAL, RUN_REVIEW, SEL_APPROVED, SEL_FAILED, Selection, ShoppingRun

router = APIRouter(prefix="/api/retailer")


class SessionBody(BaseModel):
    access_token: str = Field(min_length=20, max_length=8192)


def _status() -> dict:
    st = context.auth.status()
    return {"state": st.state, "label": st.label, "seconds_remaining": st.seconds_remaining,
            "expires_at": st.expires_at.isoformat() if st.expires_at else None}


@router.get("/session")
def session_status(_: Caller = Depends(require_device)):
    return _status()


@router.put("/session")
async def set_session(body: SessionBody, caller: Caller = Depends(require_device)):
    try:
        context.auth.set_access_token(body.access_token, by=caller.device_id)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), **_status()}
    # Items approved while the session was down: queue them now.
    with session_scope() as session:
        waiting = inbox.waiting_for_cart(session)
    if waiting:
        await requeue_waiting()
    return {"ok": True, **_status()}


async def requeue_waiting() -> int:
    n = 0
    with session_scope() as session:
        rows = session.execute(select(Selection.id, Selection.shopping_run_id).join(ShoppingRun).where(
            Selection.status.in_([SEL_APPROVED, SEL_FAILED]), Selection.approved_at.is_not(None),
            ShoppingRun.status.in_([RUN_REVIEW, RUN_PARTIAL, RUN_APPROVED]))).all()
    by_run: dict[str, list[str]] = {}
    for sid, rid in rows:
        by_run.setdefault(rid, []).append(sid)
    for rid, ids in by_run.items():
        n += cart_queue.enqueue(rid, ids)
    return n


@router.delete("/session")
async def clear_session(_: Caller = Depends(require_device)):
    await context.auth.clear()
    return _status()
