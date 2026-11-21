import dataclasses
import json

import pytest
from fastapi.testclient import TestClient

from shopping.api import auth_routes, deps
from shopping.auth import devices as dev
from shopping.config import settings
from shopping.database import session_scope
from test_client import fake_jwt
from test_devices import keypair, webcrypto_sign


@pytest.fixture(scope="module")
def client():
    from shopping.app import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def fresh_limits():
    deps.auth_limiter._hits.clear()
    deps.api_limiter._hits.clear()


def pair_and_sign_in(client, name="Test device", headers=None):
    with session_scope() as session:
        code = dev.create_pairing_code(session, device_name=name)
    key, jwk = keypair()
    r = client.post("/api/pair", json={"code": code, "public_key": jwk}, headers=headers or {})
    assert r.status_code == 200, r.text
    device_id = r.json()["device_id"]
    ch = client.post("/api/auth/challenge", json={"device_id": device_id}, headers=headers or {}).json()["challenge"]
    sig = webcrypto_sign(key, dev.auth_message(device_id, ch))
    r = client.post("/api/auth/token", json={"device_id": device_id, "challenge": ch, "signature": sig}, headers=headers or {})
    assert r.status_code == 200, r.text
    return {"authorization": f"Bearer {r.json()['access_token']}", **(headers or {})}, device_id


def test_everything_needs_a_device(client):
    assert client.get("/healthz").json() == {"ok": True}
    for path in ("/api/inbox", "/api/settings", "/api/runs", "/api/chat/threads", "/api/cart", "/api/devices",
                 "/api/settings/secrets", "/api/retailer/session", "/api/meals", "/api/audit", "/api/llm/usage"):
        r = client.get(path)
        assert r.status_code == 401, path
    assert client.get("/api/inbox", headers={"authorization": "Bearer nope"}).status_code == 401
    r = client.get("/api/inbox")
    assert r.headers["cache-control"] == "no-store" and r.headers["x-frame-options"] == "DENY"


def test_pair_sign_in_and_use(client):
    h, device_id = pair_and_sign_in(client, "Ryan laptop")
    r = client.get("/api/inbox", headers=h)
    assert r.status_code == 200 and r.json()["device"]["name"] == "Ryan laptop"
    assert any(d["id"] == device_id for d in client.get("/api/devices", headers=h).json()["devices"])


def test_secrets_are_write_only(client):
    h, _ = pair_and_sign_in(client)
    secret = "AIzaSyD-not-a-real-key-9876"
    r = client.put("/api/settings/secrets/llm:gemini", json={"value": secret}, headers=h)
    assert r.status_code == 200 and secret not in r.text
    st = {s["name"]: s for s in client.get("/api/settings/secrets", headers=h).json()["secrets"]}
    assert st["llm:gemini"]["set"] and st["llm:gemini"]["last4"] == "9876"
    assert secret not in client.get("/api/settings", headers=h).text
    assert client.put("/api/settings/secrets/bogus", json={"value": "x" * 20}, headers=h).status_code == 400


def test_retailer_session_never_returned(client):
    h, _ = pair_and_sign_in(client)
    token = fake_jwt()
    r = client.put("/api/retailer/session", json={"access_token": token}, headers=h)
    assert r.json()["state"] == "connected" and token not in r.text
    assert token not in client.get("/api/retailer/session", headers=h).text
    bad = client.put("/api/retailer/session", json={"access_token": "x" * 40}, headers=h).json()
    assert bad["ok"] is False


def test_settings_validation_and_budget(client):
    h, _ = pair_and_sign_in(client)
    r = client.put("/api/settings/budget", json={"monthly_usd": 25}, headers=h)
    assert r.status_code == 200 and r.json()["budget"]["monthly_usd"] == 25
    assert client.put("/api/settings/budget", json={"monthly_usd": -1}, headers=h).status_code == 400
    assert client.put("/api/settings/llm", json={"tiers": {"fast": {"provider": "nope", "model": "x"}}}, headers=h).status_code == 400
    assert client.get("/api/llm/usage", headers=h).json()["summary"]["monthly_cap_usd"] == 25


def test_revoking_a_device_takes_effect_now(client):
    h, device_id = pair_and_sign_in(client)
    assert client.delete(f"/api/devices/{device_id}", headers=h).json()["was_you"] is True
    assert client.get("/api/inbox", headers=h).status_code == 401


def test_mtls_required(client, monkeypatch):
    on = dataclasses.replace(settings, mtls_required=True)
    for mod in (deps, auth_routes):
        monkeypatch.setattr(mod, "settings", on)
    with session_scope() as session:
        code = dev.create_pairing_code(session)
    r = client.post("/api/pair", json={"code": code, "public_key": keypair()[1]})
    assert r.status_code == 401  # no certificate presented
    fp = {"x-client-cert-sha256": "12" * 32}
    h, _ = pair_and_sign_in(client, headers=fp)
    assert client.get("/api/inbox", headers=h).status_code == 200
    swapped = {**h, "x-client-cert-sha256": "34" * 32}
    assert client.get("/api/inbox", headers=swapped).status_code == 401


def test_auth_endpoints_are_rate_limited(client):
    codes = [client.post("/api/auth/challenge", json={"device_id": "x" * 16}).status_code for _ in range(25)]
    assert codes[0] == 200 and codes[-1] == 429


def test_run_view_over_the_api(client):
    import asyncio

    from shopping.core import service
    from test_service import FakeClient

    h, _ = pair_and_sign_in(client)
    fake = FakeClient()

    async def build():
        with session_scope() as s:
            run = service.create_run(s, summary="API test", store_id="3728")
            ids = list(fake.products)
            await service.add_choice_group(s, fake, run.id, label="Peanut butter", recommended_index=0, options=[
                {"product_id": ids[0], "quantity": 1, "reasons": ["grocery_list"]}, {"product_id": ids[1], "quantity": 1}])
            await service.add_selection(s, fake, run.id, product_id=ids[2], reasons=["good_deal"], requirement="Jam")
            service.submit_run_for_review(s, run.id)
            return run.id

    run_id = asyncio.run(build())
    view = client.get(f"/api/runs/{run_id}", headers=h).json()
    assert view["summary"] == "API test" and len(view["cards"]) == 2
    group = next(c for c in view["cards"] if c["kind"] == "group")
    assert len(group["options"]) == 2 and group["main"]["product"]["name"]
    single = next(c for c in view["cards"] if c["kind"] == "single")
    r = client.post(f"/api/runs/{run_id}/selections/{single['main']['selection_id']}/triage",
                    json={"decision": "remove", "note": "have two jars"}, headers=h)
    assert r.status_code == 200
    fb = client.get("/api/history/feedback", headers=h).json()["records"]
    assert fb[0]["note"] == "have two jars" and fb[0]["device_id"]  # attributed to the device


def test_cloudflare_header_mode(client, monkeypatch):
    cf = dataclasses.replace(settings, mtls_required=True, cert_header="cf-cert-sha256", cert_verified_header="cf-cert-verified")
    for mod in (deps, auth_routes):
        monkeypatch.setattr(mod, "settings", cf)
    good = {"cf-cert-sha256": "ab" * 32, "cf-cert-verified": "true"}
    h, _ = pair_and_sign_in(client, headers=good)
    assert client.get("/api/inbox", headers=h).status_code == 200
    # Not verified by Cloudflare, or the Caddy-style header instead: treated as no certificate.
    assert client.get("/api/inbox", headers={**h, "cf-cert-verified": "false"}).status_code == 401
    caddy_style = {"authorization": h["authorization"], "x-client-cert-sha256": "ab" * 32}
    assert client.get("/api/inbox", headers=caddy_style).status_code == 401


def test_cli_pair_with_external_certificate(tmp_path, capsys):
    from shopping import cli
    from shopping.auth import certs
    from shopping.models import PairingCode

    ca = tmp_path / "ca"
    certs.init_ca(ca)
    p12, password, fp = certs.issue_client_cert(ca, "Elsewhere")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.serialization import pkcs12

    _, cert, _ = pkcs12.load_key_and_certificates(p12, password.encode())
    pem = tmp_path / "cert.pem"
    pem.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    assert cli.main(["pair", "--name", "CF browser", "--cert-pem", str(pem)]) == 0
    assert fp in capsys.readouterr().out
    with session_scope() as s:
        assert s.query(PairingCode).order_by(PairingCode.id.desc()).first().cert_fingerprint == fp
    colons = ":".join(fp[i:i + 2] for i in range(0, 64, 2)).upper()
    assert cli.main(["pair", "--name", "x", "--cert-fingerprint", colons]) == 0
    assert cli.main(["pair", "--name", "x", "--cert-fingerprint", "nope"]) == 2
    keyfile = tmp_path / "key.pem"
    keyfile.write_text("-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n")
    with pytest.raises(ValueError, match="private key"):
        cli.main(["pair", "--name", "x", "--cert-pem", str(keyfile)])


def test_cart_add_adds_on_top(client, monkeypatch):
    from shopping import context
    from test_service import FakeClient

    h, _ = pair_and_sign_in(client)
    fake = FakeClient()
    pid = list(fake.products)[0]
    fake.cart[pid] = 2
    monkeypatch.setattr(context, "client", lambda: fake)
    r = client.post(f"/api/cart/{pid}/add", json={"quantity": 1}, headers=h)
    assert r.status_code == 200 and r.json()["quantity"] == 3 and fake.cart[pid] == 3
    assert client.post(f"/api/cart/{pid}/add", json={"quantity": 0}, headers=h).status_code == 400
