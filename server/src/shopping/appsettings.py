"""Runtime settings the household changes from the extension (stored as JSON in app_settings).

Environment variables give the defaults; anything saved here wins. Every section is validated on save,
so a bad value is refused instead of breaking a job at 7 a.m. on Thursday.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any

from sqlalchemy.orm import Session

from shopping.config import settings
from shopping.models import AppSetting

PROVIDERS = {
    # name: (adapter, default base URL, secret name)
    "gemini": ("openai", "https://generativelanguage.googleapis.com/v1beta/openai", "llm:gemini"),
    "openai": ("openai", "https://api.openai.com/v1", "llm:openai"),
    "groq": ("openai", "https://api.groq.com/openai/v1", "llm:groq"),
    "openrouter": ("openai", "https://openrouter.ai/api/v1", "llm:openrouter"),
    "mistral": ("openai", "https://api.mistral.ai/v1", "llm:mistral"),
    "anthropic": ("anthropic", "https://api.anthropic.com", "llm:anthropic"),
    "custom": ("openai", "", "llm:custom"),  # any OpenAI-compatible endpoint (e.g. a local Ollama)
}

DEFAULTS: dict[str, dict[str, Any]] = {
    "llm": {
        "tiers": {
            "fast": {"provider": "gemini", "model": "gemini-flash-latest"},  # alias: follows Google's current Flash
            "smart": {"provider": "gemini", "model": "gemini-flash-latest"},
        },
        "fallback": [],  # list of {"provider", "model"} tried when the tier's provider fails
        "custom_base_url": "",
        "max_steps": 12,  # tool calls per turn
        "temperature": 0.4,
        # USD per million tokens (input, output) for cost tracking; free tiers are 0. Edit as prices change.
        "prices": {},
    },
    "budget": {
        "monthly_usd": settings.monthly_budget_usd,  # hard stop for paid models
        "warn_at_pct": 80,
        "daily_requests": 400,  # also bounds free tiers (they rate-limit anyway)
    },
    "notion": {
        "pantry": "40a2d1e0-e400-80f0-a008-000be000338e",
        "groceries": "3542d1e0-e400-80df-bb84-000b39732b7d",
        "cooking": "40c2d1e0-e400-80f9-a500-000b07d74a74",
        "meals": "",  # Suggested Meals data source; empty until the database exists
    },
    "jobs": {
        "weekly_plan_enabled": False,
        "weekly_plan_weekday": 3,  # Monday=0 … Thursday=3 (new flyer)
        "weekly_plan_hour": 7,
        "meals_per_week": 5,
        "checkins_enabled": True,
        "checkin_hour": 17,
        "order_import_enabled": True,
        "deals_hour": 6,  # daily: scan the store's deals, then refresh Today's top deals
        "deal_alerts": True,  # push stock-up deals to ntfy (when a topic is set)
        "deal_review": True,  # after the rules, ask the LLM for discoveries (one call per assessment)
    },
}

_UUID = re.compile(r"^[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}$")


class SettingsError(ValueError):
    pass


def _key(section: str) -> str:
    return f"v2:{section}"


def get(session: Session, section: str) -> dict:
    if section not in DEFAULTS:
        raise SettingsError(f"Unknown settings section {section!r}.")
    value = copy.deepcopy(DEFAULTS[section])
    row = session.get(AppSetting, _key(section))
    if row and row.value:
        try:
            saved = json.loads(row.value)
        except ValueError:
            saved = {}
        _merge(value, saved)
    return value


def _merge(base: dict, extra: dict) -> None:
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict) and k not in ("prices",):
            _merge(base[k], v)
        else:
            base[k] = v


def update(session: Session, section: str, changes: dict) -> dict:
    """Merge `changes` into the section, validate the result, save, and return it."""
    current = get(session, section)
    _merge(current, changes or {})
    VALIDATORS[section](current)
    row = session.get(AppSetting, _key(section)) or AppSetting(key=_key(section))
    row.value = json.dumps(current)
    session.add(row)
    session.flush()
    return current


def _validate_llm(v: dict) -> None:
    for tier in ("fast", "smart"):
        t = v["tiers"].get(tier) or {}
        if t.get("provider") not in PROVIDERS:
            raise SettingsError(f"{tier}: unknown provider {t.get('provider')!r}; choose one of {', '.join(PROVIDERS)}.")
        if not str(t.get("model") or "").strip() or len(t["model"]) > 100:
            raise SettingsError(f"{tier}: give a model name.")
    for f in v.get("fallback") or []:
        if f.get("provider") not in PROVIDERS or not f.get("model"):
            raise SettingsError("Each fallback needs a known provider and a model.")
    url = v.get("custom_base_url") or ""
    if url and not re.match(r"^https?://[^\s]+$", url):
        raise SettingsError("Custom base URL must be an http(s) URL.")
    if not 1 <= int(v.get("max_steps", 12)) <= 40:
        raise SettingsError("max_steps must be between 1 and 40.")
    if not 0 <= float(v.get("temperature", 0.4)) <= 1.5:
        raise SettingsError("temperature must be between 0 and 1.5.")
    for model, pair in (v.get("prices") or {}).items():
        if not (isinstance(pair, list) and len(pair) == 2 and all(isinstance(x, (int, float)) and x >= 0 for x in pair)):
            raise SettingsError(f"Price for {model} must be [input, output] USD per million tokens.")


def _validate_budget(v: dict) -> None:
    if not 0 <= float(v["monthly_usd"]) <= 1000:
        raise SettingsError("Monthly budget must be between $0 and $1000.")
    if not 1 <= int(v["warn_at_pct"]) <= 100:
        raise SettingsError("Warning threshold must be 1–100%.")
    if not 1 <= int(v["daily_requests"]) <= 10000:
        raise SettingsError("Daily request limit must be 1–10000.")


def _validate_notion(v: dict) -> None:
    for name in ("pantry", "groceries", "cooking", "meals"):
        val = (v.get(name) or "").strip()
        if val and not _UUID.match(val.replace("collection://", "")):
            raise SettingsError(f"Notion {name}: expected a data source id (UUID).")
        v[name] = val.replace("collection://", "")


def _validate_jobs(v: dict) -> None:
    if not 0 <= int(v["weekly_plan_weekday"]) <= 6 or not 0 <= int(v["weekly_plan_hour"]) <= 23:
        raise SettingsError("Weekly plan day must be 0–6 and hour 0–23.")
    if not 1 <= int(v["meals_per_week"]) <= 14:
        raise SettingsError("Meals per week must be 1–14.")
    if not 0 <= int(v["checkin_hour"]) <= 23 or not 0 <= int(v["deals_hour"]) <= 23:
        raise SettingsError("Hours must be 0–23.")


VALIDATORS = {"llm": _validate_llm, "budget": _validate_budget, "notion": _validate_notion, "jobs": _validate_jobs}
