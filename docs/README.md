# grocery-assist v2: design

Status: **draft, first decisions made** (2026-11-20). Nothing here is built yet. Decisions are recorded below;
the remaining open questions are at the end.

v2 moves the app from a LAN box to an internet-facing VPS. A browser extension becomes the only client.
The server runs the shopping app, an LLM agent that can use several providers, and a Notion client. The
extension is the household's whole interface: chat with the agent, review shopping runs and deals, give
feedback, and keep the No Frills session connected.

| Doc | What's in it |
|---|---|
| [architecture.md](architecture.md) | Components, data flow, the agent design, and the security model |
| [server.md](server.md) | Server modules, API, data model changes, LLM providers, scheduler, deployment |
| [extension.md](extension.md) | Extension structure, screens, pairing and auth, capturing the session, settings |
| [notion-suggested-meals.md](notion-suggested-meals.md) | The new Notion database: schema, lifecycle, views, and how the agent uses it |
| [roadmap.md](roadmap.md) | Spikes first, then phases with exit criteria |

## Guiding principles

These come from what the household wants: eat well for less, with little effort and little waste.

1. **Deals drive the plan, not the other way round.** Each week starts from what is genuinely cheap,
   judged against our own price history and not the retailer's "SALE" tag. Meals are built around those
   deals.
2. **Use what's on hand first.** Perishables close to their `Expiration` outrank new purchases. A meal
   that uses something up is worth more than one that's slightly cheaper.
3. **Delicious and low-effort by default; new things in moderation.** A typical week is mostly proven
   dishes or variations of them, plus about one new dish. Effort is shown on every meal.
4. **Buy what will be cooked.** Quantities come from the meals plus regular purchases. Ingredients are
   shared across meals, and anything planned for late in the week is chosen to freeze or keep. Meals not
   cooked by their date are followed up rather than forgotten.
5. **Humans decide; the agent prepares.**
   - The agent can suggest meals, stage shopping runs, flag deals and draft Notion changes.
   - Only a person can put items in the cart (by approving a run) or make lasting changes to the pantry
     and recipes.
   - There is no checkout, payment or timeslot booking, ever.
6. **Learn from every decision.** Approvals, removals, ratings, rejections and leftovers are recorded in
   people's own words and fed back into the next plan.
7. **Logic in code, judgment in the model.** Ranking deals, deciding what's due, sizing quantities and
   costing meals are deterministic code. The LLM handles taste, trade-offs and language. This keeps
   cheap or free models usable and results repeatable.
8. **Small trusted circle, strong locks.** A few paired devices with equal access. The server holds
   valuable credentials, so it is locked down like it does.

## Key decisions (proposed)

| Topic | Proposal | Why |
|---|---|---|
| Client | **Firefox desktop only** (decided). Sidebar for chat, tab pages for everything else | One target keeps the extension simple |
| Client auth | **Two locks: mTLS at the proxy plus paired device keys.** Each device has a client certificate (Caddy rejects anything without one), and the extension also holds a key it can't export, registered with a one-time pairing code; each session is proven by a signature. If spike S4 shows Firefox's extension background can't present the certificate, device keys alone | With Firefox desktop as the only client, every device can hold a certificate, so the internet sees nothing without one |
| Exposure | Caddy with automatic HTTPS; only port 443 open; no web UI on the server, only a JSON API | Smallest possible attack surface |
| LLM providers | Two adapters: **OpenAI-compatible** (covers Gemini's free tier, Groq, OpenRouter, OpenAI, Mistral, local Ollama) and **Anthropic native**. **Default: Gemini Flash on the free tier** (decided: you accept that Google may use prompts), with a paid "smart" model available for heavier tasks | Covers almost every provider without a heavy dependency |
| Provider keys | Entered in the extension, sent once, **stored encrypted on the server only**, write-only (the client sees "set, ends …a1b2") | Matches "configurable from the client, not stored there" |
| Notion | The official Notion API with an **internal integration token** shared with exactly four databases | Least privilege; no MCP needed on the server |
| Retailer access | Server-side, as in v1, **if No Frills accepts the VPS's IP** (spike S1). The fallback (home worker on Plex, or relay through the extension) is **decided after the test** | Akamai risk |
| Codebase | Evolve v1 in place: the core (retailer client, catalogue, runs, feedback, orders) carries over. Add `server/api`, `server/agent` and `server/notion`, plus a new `extension/` | v1's core is tested and working; a rewrite would throw that away |
| Storage | SQLite (WAL) with Litestream, or nightly encrypted backups to object storage | One household; simple and enough |

## Decisions so far
- Browser: **Firefox desktop** only.
- Default LLM: **Gemini Flash, free tier** (prompts may be used by Google; no payment details are ever sent).
- If the VPS is blocked by No Frills: **decide after spike S1**.
- Promotion to Cooking and `Regular Recipe?` are **separate decisions** (the agent offers the second).

## Open questions
1. **Who uses it.** Just you and Steph? Should notes and ratings record who made them? (The design
   assumes yes: each paired device has a name.)
2. **Notifications.** Is the extension badge enough, or do you also want phone push (for example ntfy)
   when the weekly plan is ready? (A phone isn't a client, but it could still get a heads-up.)
3. **Spend cap.** Mostly moot on the free tier; for the paid "smart" model, what monthly cap? (Proposed: $10,
   with a warning at 80%.)
4. **v1.** Should the Plex instance keep running until v2 is proven (proposed), with its data migrated
   at cut-over?
5. **Groceries ↔ meals.** Do you want the optional `For Meals` relation on Groceries (see
   notion-suggested-meals.md)? It lets a rejected meal's ingredients be dropped before they're bought.
