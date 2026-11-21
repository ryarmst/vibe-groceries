"""`vibe` command-line tool for the server operator (run inside the container):

  vibe pair --name "Ryan laptop" [--cert]   one-time pairing code (and, with --cert, a client certificate)
  vibe devices                               list paired devices
  vibe revoke DEVICE_ID                      revoke a device immediately
  vibe ca                                    create the client-certificate CA (prints the path of ca.pem)
  vibe master-key                            print a new random MASTER_KEY value
"""

from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="vibe", description="vibe-groceries server administration")
    sub = p.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("pair", help="create a one-time pairing code")
    pp.add_argument("--name", required=True, help="device name, e.g. 'Steph laptop'")
    pp.add_argument("--cert", action="store_true", help="also issue an mTLS client certificate (.p12)")
    pp.add_argument("--out", default=None, help="where to write the .p12 (default: DATA_DIR/certs)")
    sub.add_parser("devices", help="list devices")
    pr = sub.add_parser("revoke", help="revoke a device")
    pr.add_argument("device_id")
    sub.add_parser("ca", help="create the client-certificate CA")
    sub.add_parser("master-key", help="print a new MASTER_KEY")
    args = p.parse_args(argv)

    if args.cmd == "master-key":
        print(base64.b64encode(os.urandom(32)).decode())
        return 0

    from shopping.auth import certs
    from shopping.auth import devices as dev
    from shopping.config import settings
    from shopping.database import run_migrations, session_scope

    run_migrations()
    ca_dir = settings.data_dir / "ca"
    if args.cmd == "ca":
        print(certs.init_ca(ca_dir))
        return 0
    if args.cmd == "pair":
        fingerprint = None
        if args.cert:
            certs.init_ca(ca_dir)
            p12, password, fingerprint = certs.issue_client_cert(ca_dir, args.name)
            out_dir = Path(args.out) if args.out else settings.data_dir / "certs"
            out_dir.mkdir(parents=True, exist_ok=True)
            os.chmod(out_dir, 0o700)
            path = out_dir / ("".join(c if c.isalnum() else "-" for c in args.name).strip("-").lower() + ".p12")
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(p12)
            print(f"Client certificate: {path}")
            print(f"Import password:    {password}")
            print("Import it in Firefox → Settings → Privacy & Security → Certificates → View Certificates → Your Certificates.")
            print("Then delete the .p12 from the server.")
        with session_scope() as session:
            code = dev.create_pairing_code(session, device_name=args.name, created_by="cli", cert_fingerprint=fingerprint)
        print(f"Pairing code (valid 10 minutes, single use): {code}")
        return 0
    if args.cmd == "devices":
        from sqlalchemy import select

        from shopping.models import Device

        with session_scope() as session:
            for d in session.scalars(select(Device).order_by(Device.created_at)):
                state = "REVOKED" if d.revoked_at else "active"
                print(f"{d.id}  {state:8}  cert={'yes' if d.cert_fingerprint else 'no ':3}  last seen {d.last_seen_at or '-'}  {d.name}")
        return 0
    if args.cmd == "revoke":
        with session_scope() as session:
            d = dev.revoke(session, args.device_id)
            print(f"Revoked {d.name} ({d.id}). Its sign-in stops working immediately.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
