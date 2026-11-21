# vibe-groceries

A grocery and meal assistant for a household, built around No Frills. It plans meals around this week's
real deals and what's in the fridge, builds a shopping cart for you to review, and keeps your Notion
kitchen records up to date. It **can't check out, pay or book a pickup time**: you do that on nofrills.ca.

- **Server** (`server/`): a JSON API on a VPS behind Caddy (HTTPS, optional client certificates). It
  holds the shopping data, an LLM agent that works with Gemini, OpenAI, Claude, Groq, OpenRouter or a local
  model, and the Notion integration.
- **Firefox extension** (`extension/`): the only interface, for Ryan and Steph. Chat with the assistant
  (sidebar), review shopping runs and deals, mark meals cooked or rejected, and manage settings and keys.
  It also keeps the No Frills session connected by reading the session cookie when you visit nofrills.ca.

Design: [docs/](docs/README.md). v1 (LAN app + MCP, `ryarmst/grocery-assist`) keeps running until this is proven.

## How it works

1. **Deals.** Every day the server scans every aisle's sales (about 3 minutes) and ranks them against what
   you actually buy.
2. **Meals.** On flyer day (Thursday), or whenever you ask, the assistant proposes about 5 meals in Notion's
   **Suggested Meals**. They're built around the best protein and produce deals and anything about to
   expire, and each comes with cost, effort and a full recipe.
3. **Shopping.** It stages a **run**: the meals' ingredients, your grocery list, and regular items that
   are due. You approve or remove items in the extension; approved items go into your No Frills cart.
4. **Learning.** Your notes ("still have two jars", "prefer the sourdough"), ratings and leftovers feed
   the next plan.

**What needs your OK.** The assistant stages runs, suggests meals and flags deals on its own. Changes to
the pantry, grocery list or Cooking show a confirmation card first, and nothing goes into the cart unless
a person approved it.

## Deploy (VPS)

Requirements: a small VPS (1 GB RAM is plenty) with Docker, and a domain name pointing at it.

```bash
git clone git@github.com:ryarmst/vibe-groceries.git && cd vibe-groceries/deploy
cp .env.example .env          # DOMAIN, ACME_EMAIL, PUBLIC_URL, MASTER_KEY, PCX_API_KEY
docker compose up -d --build
```

Open only ports 80 and 443 (plus SSH, key-only). Caddy gets the HTTPS certificate automatically.

**Pair each browser** (once each, for Ryan and Steph):

```bash
docker compose exec app vibe pair --name "Steph laptop"
```

Then in the extension: **Settings → Pair this browser**. Enter the server URL and the code (valid 10
minutes, single use). The browser creates a signing key that can't be exported; the server keeps only
its public half.

**Client certificates (recommended).** With these on, the server refuses any connection that doesn't
present a certificate you issued, before the app even sees it.

```bash
docker compose exec app vibe ca                              # once
docker compose exec app vibe pair --name "Steph laptop" --cert
docker compose cp app:/data/certs/steph-laptop.p12 .          # import into Firefox, then delete it
docker compose exec app rm /data/certs/steph-laptop.p12
# in .env: MTLS_MODE=on and MTLS_REQUIRED=true, then:
docker compose up -d
```

Import the `.p12` into Firefox: Settings → Privacy & Security → Certificates → View Certificates →
Your Certificates → Import, using the printed password. Then pair the browser as above.

**Other operations**

| Task | Command |
|---|---|
| List devices | `docker compose exec app vibe devices` |
| Revoke a device (or use Settings → Paired browsers) | `docker compose exec app vibe revoke DEVICE_ID` |
| Backups | Nightly into the volume at `/data/backups` (7 kept). Copy them off the server, and keep `MASTER_KEY` safe: without it, stored API keys can't be decrypted (re-enter them) |
| Update | `git pull && docker compose up -d --build`. Database migrations run on start |

## Install the extension (Firefox)

Firefox only installs signed extensions permanently.

1. Zip the extension: `cd extension && zip -r ../vibe-groceries.zip . -x 'dev/*'`.
2. On [addons.mozilla.org/developers](https://addons.mozilla.org/developers/), choose **Submit a New
   Add-on → On your own** (unlisted, not public). Upload the zip, then download the signed `.xpi` and
   open it in Firefox. Each new version needs a higher `version` in `manifest.json`.
3. For a quick try without signing, use `about:debugging` → This Firefox → Load Temporary Add-on →
   `extension/manifest.json`. It's removed when Firefox restarts.

When Firefox asks, allow access to **nofrills.ca**. The extension reads only the `AccessToken`
cookie, to keep the cart working.

## Set up (in the extension, Settings)

- **API keys.** Paste a key and it goes straight to the server, encrypted. It's never stored in the
  browser or shown again.
  - Gemini (free tier): [aistudio.google.com](https://aistudio.google.com/) → Get API key. This is the
    default model; note that Google may use free-tier prompts to improve its products.
  - Optional paid "smart" model: OpenAI, Anthropic, Groq or OpenRouter.
- **LLM.**
  - Pick a provider and model for each tier: *Fast* for questions and pantry updates, *Smart* for
    shopping and meal plans.
  - Use **Load models** to see what your key can use, and **Test** to check it works.
- **Budget.** A monthly cap (the quick buttons change it in one click) and a daily request limit.
- **Notion.**
  1. Create an internal integration at notion.so/my-integrations.
  2. Share Kitchen Pantry and Storage, Groceries, Cooking and Suggested Meals with it.
  3. Save its token under API keys, and the four data-source ids in the Notion section. Suggested Meals
     can stay empty until that database exists; the design is in
     [docs/notion-suggested-meals.md](docs/notion-suggested-meals.md).
- **Schedule.** The weekly plan (off until you turn it on), daily meal check-ins, and evening order
  imports.

## Security model (short)

- **Exposed to the internet:** only Caddy on port 443. Every API route needs a signed-in, non-revoked
  device. With `MTLS_REQUIRED`, the device's own client certificate is also required (checked by Caddy,
  then matched to the device by the app).
- **Secrets:** the LLM keys, Notion token and No Frills session are encrypted with AES-GCM under
  `MASTER_KEY`, and are write-only over the API. Logs redact tokens.
- **No Frills:** the retailer client can call only a fixed allowlist of endpoints. There is no code path
  to checkout, payment or timeslots.
- **The assistant:**
  - Its tools are tiered (read / safe / confirm), with no tool that fetches arbitrary URLs or sends
    messages.
  - Tool output is treated as data, not instructions.
  - Confirm-tier changes wait for a person, and an unattended run (the weekly plan) can't make them at
    all.
  - Everything it does is in History → Assistant log.

## Development

```bash
cd server && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]" -c constraints.txt
.venv/bin/python -m pytest -q          # 140-odd tests: API, auth, vault, agent loop, providers, Notion, jobs
```

To run the extension pages in a normal tab against a local server, without installing it, use
`extension/dev/`:
- `harness.py` serves the pages with a `browser.*` shim and proxies `/api`;
- `fake_llm.py` is a scripted OpenAI-compatible model.

See the docstrings for usage.
