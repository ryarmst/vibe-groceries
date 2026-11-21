# Roadmap

## Phase 0: spikes (do first; each answers a yes/no that changes the design)

| Spike | Question | How | If "no" |
|---|---|---|---|
| **S1 Retailer from a VPS** | Does api.pcexpress.ca serve search, product, cart and order calls from a datacenter IP? | Rent the VPS; run v1's client against it (search, product, cart GET with a fresh token) for a few days, varying the timing | Retailer gateway falls back to a **home worker** (the Plex box runs the retailer client and syncs with the VPS) or to an **extension relay** (cart and orders go through the user's browser). No bot-protection workarounds |
| **S2 Session capture** | Can the extension read the `AccessToken` cookie (domain, HttpOnly)? Does an open nofrills.ca tab renew it before the hour is up? | Prototype extension with `cookies.onChanged` logging (names and expiry only) | Manual "Send session" button; badge reminder when it's about to expire |
| **S3 Device keys in MV3** | Do non-exportable WebCrypto keys survive in IndexedDB from the Firefox extension background? | Tiny test extension | Fall back to a random device secret in `storage.local`, with a shorter life and easy revocation |
| **S4 mTLS from the extension** | Do the Firefox extension's background requests present the client certificate (with and without auto-select)? | Caddy with `client_auth` plus the test extension | Keep mTLS off; device keys only |
| **S5 Free-model quality** | Can Gemini Flash (free, the chosen default) run the shop and meals playbooks? Compare with Groq Llama and OpenRouter free models as backups | Eval harness: 20 tasks with fixed fixtures, scoring tool-call correctness and output quality | Mark which playbooks need the "smart" tier; keep free models for Q&A and routing |
| **S6 Notion API** | Data-source endpoints, relation writes, status property updates, rate limits on your plan | Script against a duplicated test teamspace | Adjust schema (e.g. select instead of status) |

## Phase 1: secure server core (API-first)
- `devices` + pairing + challenge/token auth; `secrets` vault; `inbox`.
- JSON API over v1's core (runs, triage, deals, context, catalogue, orders, history).
- Caddy deployment on the VPS; firewall; backups; migrate v1 data.
- **Exit:** a paired curl client (test script with a device key) can do everything the v1 web UI can;
  unpaired requests get 401 everywhere; secrets never appear in responses or logs (tested).

## Phase 2: extension MVP
- WXT scaffold; pairing; session capture; popup status; badge and inbox.
- Run review, Deals and History tabs (feature parity with the v1 web UI).
- **Exit:** a week of real shopping done entirely from the extension; v1 web UI no longer needed.

## Phase 3: agent in the server
- Provider adapters (OpenAI-compatible, Anthropic), settings and key entry, budget, audit.
- Playbooks ported from the grocery-shopping and meal-planner skills; deterministic helpers; tool tiers;
  confirmation cards.
- Chat panel with streaming.
- **Exit:** "do a grocery shop", "what's good this week?", "add milk to the list", "I made the chili" all
  work on the default free model or the configured smart model, with confirmations where required; eval
  suite ≥ target score.

## Phase 4: meals loop
- Notion Suggested Meals integration (create, update, promote); Plan tab.
- Weekly plan job (manual trigger first, then scheduled); check-ins; expiry-driven Uses Up; Skipped
  handling.
- **Exit:** two consecutive weeks planned proactively; at least 4 of 5 meals cooked; the household rates the
  effort "low".

## Phase 5: polish and hardening
- ntfy push (if wanted); price alerts on watched items; recipe-to-product
  mapping so plans price themselves; the MCP endpoint behind device auth for Claude Desktop users.

## Rough size
Spikes 1–2 days · Phase 1 ~3 days · Phase 2 ~4 days · Phase 3 ~5 days · Phase 4 ~4 days · Phase 5 as needed.
