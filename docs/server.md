# Server plan

## Layout (evolving the v1 package)

```
src/shopping/
  retailer/      (v1) PC Express client, normalisation; + a gateway interface: direct | worker | extension relay
  core/          (v1) service, catalog, deals, feedback, orders, cart_queue, modify, activity
  notion/        new: typed client for 4 databases, schema checks, rate limiting (3 requests/s), retries
  meals/         new: meal candidates, costing, manifests, check-ins, promotion to Cooking
  agent/         new: providers/, playbooks/, tools/, loop.py, router.py, budget.py, audit.py
  api/           new: JSON routes for the extension (replaces web/ templates)
  auth/          v1 session.py (No Frills token) + devices.py (pairing, challenge, access tokens)
  secrets/       new: vault (AES-GCM, master key from env)
  jobs/          new: scheduler (deal scan; weekly plan Thu 07:00 America/Toronto; daily check-ins)
  mcp_server/    (v1) optional; behind device auth or disabled
```

`web/` (server-rendered pages) is removed once the extension covers it. Its templates are a useful
reference for the extension's screens.

## API (JSON; everything except `/healthz` and the pairing and auth endpoints needs a device token)

| Area | Endpoints |
|---|---|
| Auth | `POST /api/pair` `{code, public_key, name}` · `POST /api/auth/challenge` · `POST /api/auth/token` `{device_id, signature}` · `GET/DELETE /api/devices[/{id}]` · `POST /api/devices/pairing-code` |
| Secrets | `GET /api/settings/secrets` (status only: set/unset, last 4 characters, last used) · `PUT /api/settings/secrets/{llm:<provider>\|notion}` · `DELETE …` |
| LLM settings | `GET/PUT /api/settings/llm` (provider and model per tier, budget, fallback order) · `POST /api/settings/llm/test` |
| Retailer session | `PUT /api/retailer/session` `{access_token}` · `GET /api/retailer/session` (state, minutes left, customer id; never the token) |
| Inbox | `GET /api/inbox?since=` (needs_session, plan_ready, run_ready, check-ins, cart events), polled by the extension every 15 minutes and on open |
| Runs | v1 equivalents: list, get, triage (`decision`, `note`, `option`, `quantity`, `sub_note`), approve-all, cart queue status |
| Deals | context, catalogue search, aisles, top deals (add, dismiss, restore), rescan |
| Meals | `GET /api/meals?week=` (mirrors Notion), `POST /api/meals/{id}/status` (keep, reject, cooked, plus rating, leftovers, note), `POST /api/meals/{id}/promote`, `POST /api/plan/week` (run the weekly plan now) |
| Chat | `POST /api/chat/threads` · `POST /api/chat/{thread}/messages` → SSE stream · `POST /api/chat/{thread}/confirm/{call_id}` `{approve}` · `GET /api/chat/threads/{id}` |
| History | activity, feedback, orders (import), product history, audit log |

All writes are JSON POST, PUT or DELETE with a bearer token. CSRF doesn't apply (there are no cookies),
and CORS allows only the extension origins.

## Data model additions (Alembic 0008+)

| Table | Purpose |
|---|---|
| `devices` | id, name, public_key (JWK), created_at, last_seen_at, revoked_at |
| `pairing_codes` | code hash, expires_at, used_at, created_by_device |
| `secrets` | name (`llm:gemini`, `notion`, `retailer:access_token`), ciphertext, nonce, last4, updated_at, last_used_at |
| `llm_settings` | tier → provider, model; fallback order; budgets |
| `chat_threads`, `chat_messages` | role, content, tool calls and results (results trimmed), device, model, tokens, cost |
| `agent_audit` | thread, tool, tier, arguments (secrets redacted), outcome, external ids (Notion page, run), duration |
| `usage` | per day and provider: tokens in and out, cost estimate |
| `meal_suggestions` | Local mirror of Suggested Meals rows (Notion page id, week, status, cost, deals, run id) for fast queries and check-ins. Notion stays the source of truth for content |
| `inbox_events` | kind, payload, created_at, seen_by_device |

`Feedback` gains `device_id` so notes record who wrote them. A new `meal_feedback` action type covers
ratings, rejections and leftovers.

## LLM providers

```python
class Provider(Protocol):
    async def complete(self, messages, tools, *, model, max_tokens, stream) -> AsyncIterator[Event]: ...
# Events: TextDelta | ToolCall(id, name, args) | Usage(in, out) | Done(stop_reason)
```

- **OpenAICompatible(base_url, key)** for OpenAI, Gemini (`generativelanguage.googleapis.com/v1beta/openai`),
  Groq, OpenRouter, Mistral, DeepSeek and Ollama. Tool calling uses `tools` / `tool_calls`.
- **Anthropic(key)** uses native Messages, `tool_use` blocks and prompt caching on the playbook prompt.
- The internal message format is provider-neutral; adapters translate both ways. Tool-call ids are
  normalised.
- Per-provider quirks live in the adapter: Gemini's schema subset (no `oneOf`), Groq's parallel tool
  calls, OpenRouter's model routing.
- If a model can't call tools, it can still answer Q&A; the router won't give it a tool-heavy playbook.

## Notion client

- Official REST API, data-source endpoints (API version 2025-09-03 or later), internal integration token
  from the vault.
- The databases are configured once in settings (validated against their schemas on startup):
  Pantry, Groceries, Cooking, Suggested Meals.
- Typed helpers mirror the meal-planner rules:
  - `pantry.list()` (paginated, cached about 5 minutes);
  - `pantry.update_expiration()`;
  - `groceries.upsert(name, quantity, pantry_rel)` (no duplicates; updates `Quantity`);
  - `cooking.find()`, `cooking.create_from_meal()`;
  - `meals.create()`, `meals.update()`.
- Writes go through the tool tiers. Pantry, Groceries and Cooking writes are Confirm unless done in a
  human-initiated flow that already confirms (for example a meal check-in button).

## Jobs

| Job | When | What |
|---|---|---|
| Deal scan | daily (v1) | Refresh catalogue and current deals |
| Weekly plan | Thu 07:00 (configurable; off by default until trusted) | Meals → Suggested Meals → staged run → inbox |
| Check-ins | daily 17:00 | For planned meals whose Cook By is today or past: an inbox nudge |
| Expire suggestions | daily | Suggested or Planned meals more than 3 days past Cook By become *Skipped* (a learning signal) and prompt a "what happened to the ingredients?" check-in |
| Order import | when the session is valid, daily | Import new past orders (v1); mark Groceries Purchased (Confirm tier: shown as one card) |
| Backup | nightly | SQLite `.backup` → encrypted → object storage (or Litestream continuously) |

## Deployment

- Docker Compose with `caddy` and `app` (read-only root filesystem, non-root user, memory cap 512 MB now
  that the agent runs here), plus a named volume.
- Env: `MASTER_KEY` (32 random bytes, base64), `PUBLIC_URL`, `ALLOWED_ORIGINS` (extension ids),
  `STORE_ID`, `TZ`.
- Firewall: 443 (and 80 for certificate challenges) open; SSH by key only, or Tailscale-only SSH.
  Unattended security upgrades.
- mTLS (planned as required; spike S4): Caddy `client_auth { mode require_and_verify; trust_pool file /certs/ca.pem }`
  on `/api/*`. `grocery cert issue --device NAME` creates a per-device P12 for Firefox. The app keeps
  the revocation list Caddy reads.
- Migration from v1: copy `app.db` to the VPS (the schema carries forward); rotate the No Frills token by
  logging in again; v1 on the Plex box stays up read-only until cut-over.
