# Browser extension plan

## Stack
- **Target: Firefox desktop** (decided). **WXT** (Vite-based, Manifest V3) with TypeScript. Chrome stays
  possible later because WXT builds both, but nothing is designed around it.
- **Preact** (or Svelte) for the UI. No remote code: everything is bundled, which extension CSP requires.
- Distribution: an AMO-signed **unlisted** XPI (self-distributed; Firefox requires signing for permanent
  installs). Updates come from a self-hosted `update_url` on the server.

## Permissions (minimal)
- `storage` (settings; tokens in `storage.session`), `alarms` (inbox polling), `cookies`; the sidebar via
  `sidebar_action`.
- Host permissions: `https://*.nofrills.ca/*` (to read the session cookie) and the configured server
  origin only (added at runtime with an optional permission request).
- No `tabs`, no `<all_urls>`, and no content scripts for the main features. (Possible later: an optional
  "add to plan" button on nofrills.ca product pages.)

## Surfaces

| Surface | Contents |
|---|---|
| **Sidebar** (main) | Chat with the agent: mode chips (Shop, Meals, Pantry, Recipes, Ask), streaming replies, tool activity lines ("Searching deals in Meat…"), confirmation cards (Approve / Edit / Skip), quick replies |
| **Tab: Plan** | This week's meals as cards: deals used, uses-up, cost/serving, effort, Cook By. Buttons: Keep, Reject (+ note), Cooked (+ rating, leftovers, note), Promote. Links to the Notion page |
| **Tab: Run** | v1 triage UI rebuilt natively: approve, remove or switch, note, substitution note, quantity; approve all; live "adding to cart" status |
| **Tab: Deals** | Top deals plus "your items on sale" and best per aisle, from the context API; add to cart; dismiss with a note |
| **Tab: History** | Activity, feedback, orders, product price history, audit log |
| **Tab: Settings** | Server URL and pairing; devices (list, revoke, new pairing code); LLM providers (key entry, which is write-only, model per tier, Test); Notion token and database pickers; budgets; weekly-plan schedule on/off |
| **Popup** (toolbar) | Status at a glance: server connected, No Frills session (minutes left), inbox items. Opens the panel |
| **Badge** | Count of inbox items needing a person (plan ready, run ready, needs session, check-ins) |


## Background service worker
- **Device key:** created at pairing; ECDSA P-256 with `extractable: false`; the `CryptoKey` lives in
  IndexedDB.
- **Access token:** obtained by signing a challenge; kept in `storage.session` (memory, cleared when the
  browser closes); refreshed when it's about to expire.
- **Session capture:**
  - `cookies.onChanged` filtered to the `.nofrills.ca` `AccessToken` cookie → `PUT /api/retailer/session`
    (debounced). Also checked at startup and on the popup's "Reconnect" button.
  - Only that one cookie is read. Nothing else from nofrills.ca is sent.
- **Inbox:** an alarm every 15 minutes (and on panel open) → `GET /api/inbox` → badge. While a run is being
  added to the cart, the panel polls faster, as the v1 page does.
- **No secrets at rest in the extension:** provider and Notion keys go straight from the Settings form to
  the server and are never written to extension storage. The only long-lived secret is the device
  private key, which can't be exported.

## Pairing flow
1. Settings → enter server URL → the extension requests host permission for that origin.
2. Enter the one-time code (from `grocery pair` on the server, or Settings → "New pairing code" on an
   already-paired device).
3. Generate the key pair → `POST /api/pair` → success shows the device name. On failure, the code is
   unchanged and three attempts are allowed before it's burned.

## mTLS (planned as required)
Every device is Firefox desktop, so Caddy requires a per-device client certificate on all `/api` routes,
on top of device keys.
- Setup per device: `grocery cert issue --device NAME` makes a `.p12`; import it in Firefox → Settings →
  Certificates → Your Certificates.
- Firefox prompts to choose the certificate once per session. To avoid the prompt, set
  `security.default_personal_cert = Select Automatically` for that profile.
- **Spike S4** confirms the extension's background requests present the certificate. If they don't,
  mTLS stays off and device keys are the single lock.
- Revoking a device revokes both its key and its certificate (Caddy reads a CRL / allowlist the app
  maintains).

## Chat UX details
- Streaming via `fetch` and a `ReadableStream` parsing SSE. A **Stop** button cancels the request and the
  server stops the loop.
- Tool activity appears as small grey lines; expanding one shows its arguments and result summary.
- Confirmation cards show exactly what will be written (for example "Pantry → Chicken Thighs:
  Expiration = Nov 27"). Approve, Edit (opens a small form) or Skip.
- Each answer shows the model and cost ("Gemini Flash · free" / "Sonnet · $0.012").
- Threads are kept on the server so they're shared across devices. The panel shows the last 10.
