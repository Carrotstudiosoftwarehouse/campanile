# DEVELOPED BY CARROTSTUDIO software house
"""Signed official notices, Ed25519.

The authority (e.g. civil protection) keeps its private key on its own computer and signs
with scripts/sign-notice.py. Campanile checks only against public keys installed beforehand,
never a key received over the network: whoever forges the notice would forge the key too.

The signature is checked by OpenSSL when the `cryptography` package is installed (as on the
Raspberry), by our ed25519.py otherwise: the two answer the same (tests/test_ed25519.py).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import time
from pathlib import Path

import ed25519
import strictjson

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
except ImportError:  # pragma: no cover - depends on the machine
    Ed25519PublicKey = None

FORMAT = "campanile-notice-v1"
# Signed bytes start with this, so a signature made for anything else can't be reused here.
DOMAIN = b"campanile-notice-v1\n"
NOTICE_FIELDS = {"title", "text", "urgent", "issued", "expires", "issuer"}
MAX_VALIDITY = 7 * 24 * 3600


class SignatureError(Exception):
    """A signed notice that must be refused. args[0] is a key of messages.MESSAGES."""


def canonical(notice: dict) -> bytes:
    return json.dumps(notice, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def message(notice: dict) -> bytes:
    return DOMAIN + canonical(notice)


def key_id(public_key_raw: bytes) -> str:
    return hashlib.sha256(public_key_raw).hexdigest()[:16]


def signed_by(public_key: bytes, signature: bytes, data: bytes) -> bool:
    if Ed25519PublicKey is None:
        return ed25519.verify(public_key, signature, data)
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, data)
    except InvalidSignature:
        return False
    return True


def _b64(value, length: int | None = None) -> bytes:
    if not isinstance(value, str):
        raise SignatureError("sig_bad_key")
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise SignatureError("sig_bad_key") from None
    if length is not None and len(raw) != length:
        raise SignatureError("sig_bad_key")
    return raw


class TrustedKeys:
    """Public keys of the authorities this Campanile trusts, read from a JSON file:

    {"keys": [{"name": "Protezione Civile Torino", "public_key": "<base64, 32 bytes>"}]}
    """

    def __init__(self, keys: dict[str, tuple[str, bytes]] | None = None):
        self._keys = keys or {}

    @classmethod
    def load(cls, path: Path | None) -> TrustedKeys:
        """A broken keys file only turns signed notices off: Campanile itself must keep running."""
        if path is None:
            return cls()
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            keys = {}
            for entry in data["keys"]:
                raw = _b64(entry["public_key"], 32)
                if not ed25519.is_public_key(raw):
                    raise SignatureError("sig_bad_key")
                keys[key_id(raw)] = (str(entry["name"]), raw)
        except (OSError, ValueError, KeyError, TypeError, SignatureError) as e:
            print(
                f"[campanile] trusted keys ignored, signed notices off: {path}: {e!r}", flush=True
            )
            return cls()
        return cls(keys)

    def __len__(self) -> int:
        return len(self._keys)

    def verify(self, signed, now: float | None = None) -> tuple[dict, str]:
        """Returns (notice, issuer name) or raises SignatureError."""
        if not self._keys:
            raise SignatureError("sig_no_keys")
        signed = _parse(signed)
        if not isinstance(signed, dict) or signed.get("format") != FORMAT:
            raise SignatureError("sig_format")
        notice = signed.get("notice")
        if not isinstance(notice, dict) or set(notice) != NOTICE_FIELDS:
            raise SignatureError("sig_incomplete")
        signature = _b64(signed.get("signature"), 64)

        trusted = self._keys.get(notice["issuer"]) if isinstance(notice["issuer"], str) else None
        if trusted is None:
            raise SignatureError("sig_unknown_key")
        name, public_key = trusted
        try:
            signed_message = message(notice)
        except UnicodeEncodeError:  # a lone surrogate: no authority signed that
            raise SignatureError("sig_bad_values") from None
        if not signed_by(public_key, signature, signed_message):
            raise SignatureError("sig_tampered")

        # Checked only after the signature: these values come from the authority.
        if not (
            isinstance(notice["urgent"], bool)
            and all(
                isinstance(notice[k], int) and not isinstance(notice[k], bool)
                for k in ("issued", "expires")
            )
        ):
            raise SignatureError("sig_bad_values")
        if not 0 < notice["expires"] - notice["issued"] <= MAX_VALIDITY:
            raise SignatureError("sig_validity")
        now = time.time() if now is None else now
        if notice["expires"] <= now:
            raise SignatureError("sig_expired")
        return notice, name


def _parse(signed):
    if not isinstance(signed, str):
        return signed
    try:
        return strictjson.loads(signed)
    except (ValueError, RecursionError):
        raise SignatureError("sig_unreadable") from None


def signature_b64(signed) -> str:
    return _parse(signed)["signature"]


def signature_hash(signed) -> str:
    """Identifies a signed notice, to refuse publishing the same one twice."""
    return hashlib.sha256(_b64(signature_b64(signed), 64)).hexdigest()
