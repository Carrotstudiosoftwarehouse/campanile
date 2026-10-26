#!/usr/bin/env python3
# DEVELOPED BY CARROTSTUDIO software house
"""Creates signing keys and signs official notices, on the authority's own computer.

  scripts/sign-notice.py keygen --name "Protezione Civile Torino" --out keys/
  scripts/sign-notice.py sign --key keys/protezione-civile-torino.key \\
      --title "Acqua non potabile" --text "Bollire l'acqua." --urgent --hours 24

The private key never goes on the Campanile. Its public part is added beforehand to the
trusted keys file of every Campanile (see docs/ADMIN.md). Needs: pip install cryptography
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "campanile"))
import signing

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def public_raw(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )


def keygen(args) -> None:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", args.name.lower()).strip("-") or "authority"
    key_file = out / f"{slug}.key"
    if key_file.exists():
        sys.exit(f"{key_file} already exists: not overwriting a private key.")
    private_key = Ed25519PrivateKey.generate()
    pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    raw = public_raw(private_key)
    entry = {"name": args.name, "public_key": base64.b64encode(raw).decode()}
    (out / f"{slug}.public.json").write_text(json.dumps(entry, ensure_ascii=False, indent=2) + "\n")
    print(f"Private key (keep it secret, never on a Campanile): {key_file}")
    print(f"Public key, to add to each Campanile's trusted keys: {out / f'{slug}.public.json'}")
    print(f"Fingerprint, to read out or print for checking: {signing.key_id(raw)}")


def sign(args) -> None:
    private_key = serialization.load_pem_private_key(Path(args.key).read_bytes(), password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        sys.exit("Not an Ed25519 private key.")
    now = int(time.time())
    notice = {
        "title": args.title,
        "text": args.text,
        "urgent": args.urgent,
        "issued": now,
        "expires": now + int(args.hours * 3600),
        "issuer": signing.key_id(public_raw(private_key)),
    }
    signature = private_key.sign(signing.message(notice))
    signed = {
        "format": signing.FORMAT,
        "notice": notice,
        "signature": base64.b64encode(signature).decode(),
    }
    print(json.dumps(signed, ensure_ascii=False))


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="command", required=True)
    k = sub.add_parser("keygen", help="create a new key pair")
    k.add_argument("--name", required=True, help='who signs, e.g. "Protezione Civile Torino"')
    k.add_argument("--out", required=True, help="folder for the key files")
    s = sub.add_parser("sign", help="sign a notice; prints it, ready to paste in the admin page")
    s.add_argument("--key", required=True, help="private key file made by keygen")
    s.add_argument("--title", required=True)
    s.add_argument("--text", required=True)
    s.add_argument("--urgent", action="store_true")
    s.add_argument(
        "--hours", type=float, default=24, help="validity in hours (max 168, default 24)"
    )
    args = p.parse_args()
    if args.command == "sign" and not 0 < args.hours <= 168:
        sys.exit("--hours must be between 0 and 168 (7 days).")
    keygen(args) if args.command == "keygen" else sign(args)


if __name__ == "__main__":
    main()
