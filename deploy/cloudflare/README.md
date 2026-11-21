# Running behind a Cloudflare Tunnel (home server)

The app runs at home; `cloudflared` keeps an outbound connection to Cloudflare, which serves
`https://groceries.ryarmst.ca`. No ports are opened on the router. Cloudflare checks a client certificate on
every request, and the app also requires a signed-in, paired browser (and checks the certificate belongs to it).

The server side is already set up in `~/vibe-groceries/deploy/cloudflare` on the Plex box (`.env` holds a
generated `MASTER_KEY` and the No Frills API key; the database started from a copy of v1's). Below is the
Cloudflare side, then pairing.

## 1. Create the tunnel

1. Cloudflare dashboard → **Zero Trust** → **Networks** → **Tunnels** → **Create a tunnel** → **Cloudflared**.
2. Name it `vibe-groceries` → **Save tunnel**.
3. On "Install and run a connector", pick **Docker** and copy only the **token**: the long string after `--token`.
   Don't run the command shown; the compose file runs cloudflared.
4. **Next** → add a **public hostname**:
   - Subdomain `groceries`, Domain `ryarmst.ca`, Path empty
   - Service: Type **HTTP**, URL **`app:8000`**
   - **Save hostname**.
5. On the Plex box:
   ```bash
   cd ~/vibe-groceries/deploy/cloudflare
   nano .env                    # paste the token after TUNNEL_TOKEN=
   docker compose up -d
   ```
   The tunnel should show **Healthy** in the dashboard, and `https://groceries.ryarmst.ca/healthz` returns
   `{"ok":true}`. That's the only thing reachable without signing in.

## 2. Client certificates (one per browser)

1. Dashboard → the **ryarmst.ca** site → **SSL/TLS** → **Client Certificates** → **Create Certificate**.
2. Keep "Generate a private key and CSR with Cloudflare" (ECDSA is fine), validity e.g. 2 years → **Create**.
3. Copy the **Certificate** into `ryan-laptop.pem` and the **Private key** into `ryan-laptop.key` on your
   laptop. The key is shown only once. Repeat for Steph (`steph-laptop.pem` / `.key`).
4. On the same page, under **Hosts**, choose **Edit** → add `groceries.ryarmst.ca` → **Save**.
   This makes Cloudflare ask browsers for a certificate on that hostname.
5. Make a file Firefox can import (on the laptop; choose an export password):
   ```bash
   openssl pkcs12 -export -in ryan-laptop.pem -inkey ryan-laptop.key -out ryan-laptop.p12 -name "vibe-groceries Ryan"
   ```
   Firefox → **Settings** → **Privacy & Security** → **Certificates** → **View Certificates** →
   **Your Certificates** → **Import** → choose the `.p12`. Afterwards, delete the `.key` and `.p12` files, or
   keep them somewhere safe.

## 3. Make Cloudflare enforce and forward the certificate

1. **Rules** → **Transform Rules** (or **Settings**) → **Managed Transforms** → turn on
   **Add TLS client auth headers**. This passes the verified certificate's fingerprint to the app as
   `cf-cert-sha256`.
2. **Security** → **WAF** → **Custom rules** → **Create rule**:
   - Name: `Require client certificate`
   - Expression (Edit expression):
     ```
     (http.host eq "groceries.ryarmst.ca" and (not cf.tls_client_auth.cert_verified or cf.tls_client_auth.cert_revoked))
     ```
   - Action: **Block** → **Deploy**.

Now anything without one of your certificates gets a Cloudflare block page before it reaches home.

### Important: HTTP/3 breaks client certificates

Firefox reaches Cloudflare over HTTP/3 (QUIC) when it's on, and then **doesn't present the client
certificate**: every request gets Cloudflare's 403, with no certificate prompt. Turn HTTP/3 off for the zone:

- ryarmst.ca → **Speed** → **Optimization** → **Protocol Optimization** → **HTTP/3 (with QUIC)**: **Off**.
  Browsers fall back to HTTP/2 and send the certificate. This affects every hostname on the zone, harmlessly.
- Alternatively, per browser: `about:config` → `network.http.http3.enable` = `false`, then restart Firefox.

Other causes of a 403 without a certificate prompt:
- A connection from before the certificate was imported is being reused. Quit Firefox fully and reopen it.
- The certificate isn't under **Your Certificates**.

**Security → Events** in Cloudflare shows, for each blocked request, whether a certificate was presented and
whether it verified.

## 4. Pair each browser

1. On the Plex box, create a pairing code bound to that browser's certificate. Pass the certificate file
   (`.pem`), never the key:
   ```bash
   cd ~/vibe-groceries/deploy/cloudflare
   docker compose exec -T app vibe pair --name "Ryan laptop" --cert-pem - < ryan-laptop.pem
   ```
   (Copy the `.pem` to the Plex box first, or paste it: `... --cert-pem - <<'EOF'` … `EOF`.)
2. Install the extension: for now, `about:debugging` → **This Firefox** → **Load Temporary Add-on** →
   `extension/manifest.json`. For a permanent install, see the main README (signing).
3. Extension → **Settings** → server `https://groceries.ryarmst.ca`, the code, a name → **Pair**. When Firefox
   asks which certificate to present, choose the vibe-groceries one, and tick "remember".
4. Once both browsers are paired, turn on the app-side check, which ties each certificate to its own browser:
   ```bash
   sed -i 's/^MTLS_REQUIRED=false/MTLS_REQUIRED=true/' .env && docker compose up -d
   ```

## 5. Settings in the extension

- **API keys:** Gemini (aistudio.google.com → Get API key) and the Notion integration token.
- **Notion:** the four data-source ids. Suggested Meals can wait until that database exists.
- **LLM:** **Load models** → choose models → **Test**. The budget cap is under LLM budget.

## Day to day

| Task | Command |
|---|---|
| Logs | `docker compose logs -f app` |
| Update | `git pull && docker compose up -d --build` |
| Revoke a browser | In the extension (Settings → Paired browsers), or `docker compose exec app vibe revoke ID`. Also revoke its certificate in Cloudflare |
| Backups | Nightly into the `vibe-groceries_app-data` volume (`/data/backups`). Keep a copy of `.env` (MASTER_KEY) somewhere safe |

**Trust note:** Cloudflare ends HTTPS, so it can see the traffic, including keys typed into Settings and the
No Frills session.
