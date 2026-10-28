#!/usr/bin/env python3
# DEVELOPED BY CARROTSTUDIO software house
"""CarrotStudio's release keys, and the signature of each Campanile version. Run on the
maintainer's own computer, never on a server. Needs: pip install cryptography

  scripts/sign-release.py keygen --out ~/campanile-keys
  scripts/sign-release.py sign --key ~/campanile-keys/campanile-release-main.key \\
      dist/campanile-0.2.0.zip

keygen makes two keys, each locked by its own passphrase: the one in use, and a spare to keep
apart (a USB stick in a drawer). Their public parts go in KEYS, in campanile/release.py.

sign signs the package made by scripts/build-package.sh, so what is signed is what is
published, and writes campanile/release-signature.json here: commit it, then tag the version.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "campanile"))
import release
import signing

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parent.parent
MIN_PASSPHRASE = 12
LABELS = ("main", "spare")


def public_raw(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def new_passphrase(label: str) -> bytes:
    while True:
        first = getpass.getpass(
            f"Passphrase for the {label} key (at least {MIN_PASSPHRASE} characters): "
        )
        if len(first) < MIN_PASSPHRASE:
            print("Too short.")
        elif getpass.getpass("Once more: ") != first:
            print("They differ.")
        else:
            return first.encode()


def keygen(args) -> None:
    out = Path(args.out).expanduser()
    paths = {label: out / f"campanile-release-{label}.key" for label in LABELS}
    for path in paths.values():
        if path.exists():
            sys.exit(f"{path} already exists: not overwriting a private key.")
    out.mkdir(parents=True, exist_ok=True)
    lines = []
    for label, path in paths.items():
        key = Ed25519PrivateKey.generate()
        pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(new_passphrase(label)),
        )
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(pem)
        raw = public_raw(key)
        lines.append(f'    "{signing.key_id(raw)}": "{base64.b64encode(raw).decode()}",  # {label}')
        print(f"Private {label} key: {path}")
    print("\nPublic parts, for KEYS in campanile/release.py (nothing secret here):")
    print("\n".join(lines))
    print("\nKeep the spare key and its passphrase away from the main one.")


def sign(args) -> None:
    try:
        key = serialization.load_pem_private_key(
            Path(args.key).expanduser().read_bytes(),
            password=getpass.getpass("Passphrase: ").encode(),
        )
    except (OSError, ValueError, TypeError):
        sys.exit("Wrong passphrase, or not a key file.")
    if not isinstance(key, Ed25519PrivateKey):
        sys.exit("Not an Ed25519 private key.")
    raw = public_raw(key)
    key_id = signing.key_id(raw)
    if release.KEYS.get(key_id) != base64.b64encode(raw).decode():
        sys.exit(f"Key {key_id} is not in KEYS in campanile/release.py: add its public part first.")

    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(args.package) as package:
            package.extractall(tmp)
        folders = [p for p in Path(tmp).iterdir() if p.is_dir()]
        if len(folders) != 1:
            sys.exit("Not a package made by scripts/build-package.sh.")
        folder = folders[0]
        source = (folder / "campanile" / "server.py").read_text(encoding="utf-8")
        version = re.search(r'^VERSION = "(.+?)"', source, re.M)[1]
        body = {"version": version, "files": release.manifest(folder)}
        signed = {
            "format": release.FORMAT,
            "release": body,
            "key": key_id,
            "signature": base64.b64encode(key.sign(release.message(body))).decode(),
        }
        text = json.dumps(signed, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
        (folder / release.SIGNATURE).write_text(text, encoding="utf-8")
        try:
            release.check(folder)  # what the release workflow checks before publishing
        except release.ReleaseError as e:
            sys.exit(f"The signature does not hold: {e.args[0]}")
    (ROOT / release.SIGNATURE).write_text(text, encoding="utf-8")
    print(f"Signed Campanile {version}, {len(body['files'])} files. Now:")
    print(f"  git add {release.SIGNATURE} && git commit -m 'Campanile {version}: signature'")
    print(f"  git tag v{version} && git push origin main v{version}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    k = sub.add_parser("keygen", help="make the main and spare release keys")
    k.add_argument("--out", required=True, help="folder for the private keys, off any network")
    s = sub.add_parser("sign", help="sign a package made by scripts/build-package.sh")
    s.add_argument("--key", required=True, help="the private key file")
    s.add_argument("package", help="dist/campanile-VERSION.zip")
    args = parser.parse_args()
    if args.command == "keygen":
        keygen(args)
    else:
        sign(args)


if __name__ == "__main__":
    main()
