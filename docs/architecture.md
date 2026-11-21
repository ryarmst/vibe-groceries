# Architecture

## Components

```
 Browser (each paired device)                       VPS (Docker)
┌──────────────────────────────────┐              ┌───────────────────────────────────────────────────┐
│ Extension (MV3)                  │   HTTPS 443  │ Caddy: TLS, optional mTLS, rate limits             │
│  • side panel: chat              │─────────────▶│   │                                               │
│  • tab pages: runs, deals,       │  signed      │   ▼                                               │
│    meals, history, settings      │  device      │ App (FastAPI, one process)                        │
│  • background: device key,       │  session     │  ├─ api/      JSON API for the extension          │
│    session token capture, inbox  │              │  ├─ agent/    LLM loop, playbooks, tools, budget  │
│    polling, badge                │              │  ├─ core/     v1: runs, catalogue, deals, orders, │
│  • reads nofrills.ca cookie ─────┼──┐           │  │            feedback, cart queue                │
└──────────────────────────────────┘  │           │  ├─ retailer/ PC Express client (allowlisted)     │
                                      │ session   │  ├─ notion/   Notion API client (4 databases)     │
                                      └─token────▶│  ├─ secrets/  encrypted vault (LLM, Notion,       │
                                                  │  │            No Frills token)                     │
                                                  │  ├─ jobs/     scheduler: deal scan, weekly plan,   │
                                                  │  │            check-ins                            │
                                                  │  └─ SQLite (WAL) + backups                         │
                                                  └───────┬─────────────┬──────────────┬──────────────┘
                                                          │             │              │
                                               api.pcexpress.ca   api.notion.com   LLM provider
                                               (or via fallback)                   (key from the vault)
```

The MCP endpoint from v1 stays available. It can be switched off, or put behind the same device auth, for
anyone who still wants to use Claude Desktop or Claude Code directly.

## Main flows

### Pairing a device (once per browser)
1. On the server: `grocery pair --name "Ryan laptop"`. It prints a one-time code, valid for 10 minutes.
   (Later, an already-paired device can issue codes too.)
2. In the extension: enter the server URL and the code. The extension creates an **ECDSA P-256 key pair
   that can't be exported** (WebCrypto) and keeps it in IndexedDB. It sends `{code, publicKey, name}`.
3. The server stores the public key against a device record. The code is burned.

### Every session
1. The extension asks for a challenge (`POST /api/auth/challenge`), signs it, and gets back a short-lived
   access token (15 minutes, kept only in memory).
2. Each API call carries `Authorization: Bearer <token>`. When it expires, the extension repeats step 1
   automatically.
3. Revoking a device on the server ends its access immediately. With mTLS (planned as required), Caddy
   also refuses any connection without that device's client certificate, before the app sees anything.

### Keeping the No Frills session connected
- The extension has the `cookies` permission for `*.nofrills.ca`. When the `AccessToken` cookie changes
  (you log in, or the site renews it), it sends the token to `PUT /api/retailer/session`.
- When the server needs a session and has none valid, it sets `needs_session` in the inbox. The extension
  shows a badge and a "Open nofrills.ca to reconnect" prompt.
- No logins are automated, and no bot protection is worked around. Tokens only come from your own normal
  browsing.

### Chat
1. The side panel sends a message: `POST /api/chat/{thread}/messages`. The reply streams back as
   Server-Sent Events: text pieces, tool calls, and confirmation cards.
2. The server's agent loop picks a playbook (shop, plan meals, pantry and receipts, recipes, Q&A),
   exposes only that playbook's tools, and runs until the model gives a final answer or a step needs a
   human.
3. When a step needs confirmation (for example a pantry edit), the agent stops with a confirmation card.
   The user's choice resumes the loop.

### Weekly plan (proactive; Thursdays, when the new flyer starts)
1. Deal scan (v1's catalogue scan).
2. The planner computes candidate meals: protein and produce deals, cross-checked with on-hand items
   near expiry, regular recipes and the history of past suggestions.
3. The LLM picks and writes about 5 meals into **Suggested Meals** (Status *Suggested*), each with its
   deals, what it uses up, cost, effort and a shopping manifest.
4. It stages a shopping run from the meals plus regular purchases that are due, and flags a few Top
   deals.
5. The inbox gets "Week of Nov 26: 5 meals, run ready (~$84)". The badge lights up.
6. People review the meals (keep or reject) and the run (approve puts items in the cart), then check out
   on nofrills.ca as today.
7. **Check-ins** during the week, a light nudge: "Cooked the carnitas? 👍 / 👎 / didn't get to it". The
   answer updates Suggested Meals, plus pantry expirations and leftovers once confirmed.

## The agent

### Playbooks instead of one giant prompt
Today's skills (grocery-shopping, meal-planner, plus the receipt and shelf-life references) become
server-side **playbooks**. Each one is:
- a short system prompt for one job;
- a fixed tool list;
- the reference snippets that job needs (for example shelf-life rules only for receipts).

A small router picks the playbook (cheap model call or keyword rules); the user can also pick one with a
mode chip. Small contexts and few tools per turn are what make free and cheap models reliable.

### Tools are server functions, not HTTP
Tools call v1's core functions in-process, so they're fast with no extra auth hop. Each tool declares:
- a JSON Schema for its inputs;
- a **permission tier**:

| Tier | Examples | Behaviour |
|---|---|---|
| Read | context, catalogue search, run/feedback/order history, Notion queries | Runs immediately |
| Safe write | create Suggested Meals, stage a run, flag a Top deal, add a note | Runs immediately, logged, reversible |
| Confirm | edit Pantry rows, Groceries rows, Cooking pages, Shopping Preferences | Stops with a confirmation card; runs only after a human taps Approve |
| Human-only | approve run items (puts them in the cart), revoke devices, change keys | Not available to the agent at all |
| Never | checkout, payment, timeslots, arbitrary HTTP or URL fetch, sending messages | No code path exists |

### Deterministic helpers the model calls instead of reasoning out
- `rank_deals(focus)` (v1 `shopping_context`)
- `due_regulars()` (v1 requirement history)
- `size_quantity(item, need)` turns "3 lb" into packages
- `cost_meal(manifest)` prices a manifest from the catalogue
- `expiring_on_hand(days)` reads pantry `Expiration`
- `meal_candidates()` scores regulars and past suggestions against deals and expiring items

### Model choice and fallbacks
- Each playbook can name a model tier (`fast` or `smart`), mapped in settings to a provider and model.
  Default (decided): fast = Gemini Flash on the free tier. smart = optional paid model (Claude Sonnet, GPT,
  paid Gemini Pro), used only for playbooks that S5 shows need it.
- If a provider errors or hits a rate limit, the loop retries once, then falls back to the next
  configured provider, and says so in the chat.
- An **eval suite** of about 20 scripted household tasks (with fixed catalogue and Notion fixtures) scores
  each provider and model on correctness and tool use before it becomes a default.

## Security model

### What's at stake
- The **No Frills session**: an account with saved payment details and PC Optimum points.
- LLM and Notion keys (cost and data).
- Household data (Notion, purchase history).

### Threats and controls

| Threat | Control |
|---|---|
| Internet scanning and brute force | Only 443 open (SSH by key, or behind Tailscale). Caddy rejects connections without a client certificate; every `/api` route also requires device auth. Rate limits and lockout on auth endpoints. No server-rendered UI. |
| Stolen API credential | Two locks: a client certificate (mTLS) and a device key that can't be exported. Access tokens live 15 minutes in memory; devices are revocable. |
| Database or backup leak | Secrets are encrypted with AES-GCM under a master key that lives in the environment and never in the DB or backups. Backups are encrypted too. |
| The No Frills token used beyond our purpose | The retailer client calls only an **allowlist** of endpoints (v1 already does this). There is no code path to checkout, payment or timeslots. The token is never logged and never returned by the API. |
| Prompt injection (Notion pages, product text, recipes pasted from the web) | Tool results are framed as data. Tiered permissions: anything consequential needs a human tap. No tool can reach arbitrary URLs, so data can't be sent out. Recipe import is a human paste, not a fetch. |
| Runaway cost | Daily and monthly token budgets per provider; per-turn step limit (for example 12 tool calls); hard stop with a clear message. |
| A malicious or buggy extension update | The extension is self-built and signed as an unlisted Firefox add-on, with updates from the server. Minimal permissions: `cookies`, `storage`, `alarms`, host access to `*.nofrills.ca` and the server only. No content scripts are needed for the main features. |
| Supply chain | Pinned dependencies with hashes; a small dependency set (two thin LLM adapters instead of a large multi-provider library). |

Everything the agent does is recorded in an **audit log**: tool calls, external writes and model and cost
per turn. Users can view it in the extension.
