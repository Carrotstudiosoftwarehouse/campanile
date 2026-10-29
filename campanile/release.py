# DEVELOPED BY CARROTSTUDIO software house
"""A Campanile version signed by CarrotStudio.

What is signed is the hash of every program file, like a Sky spell approves the hash of its
code: exactly those files pass, none more, none fewer, and never an older version, which would
bring old bugs back. Check a copy where it will run, not on the stick, which can still change.

    python3 campanile/release.py FOLDER     says whether FOLDER is a signed release
"""

from __future__ import annotations

import base64
import binascii
import re
import sys
from pathlib import Path

import copying
import messages
import signing
import strictjson

FORMAT = "campanile-release-v1"
DOMAIN = b"campanile-release-v1\n"  # so a notice's signature can never pass for a release's
SIGNATURE = "campanile/release-signature.json"
# CarrotStudio's release keys (key id: base64): the one in use and a spare kept apart, so that
# losing one is no disaster. Only public parts here; the private ones never touch a network.
KEYS: dict[str, str] = {
    "bdd66487d5516868": "IbAeMUh1QwMAp2Wd7Zzn5MYUrYxOz12rPTL1oepkeBw=",  # in use
    "737dbf659b2ed7a3": "is0HCybd1tGJ3VpFJY7fz0kSJ6f4tHCS9bmm8rjjWTk=",  # spare, kept apart
}
_VERSION = re.compile(r"(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})")


class ReleaseError(Exception):
    """args[0] is a key of messages.MESSAGES."""


def version_number(version) -> tuple[int, int, int]:
    match = _VERSION.fullmatch(version) if isinstance(version, str) else None
    if match is None:
        raise ReleaseError("release_bad_version")
    return tuple(int(n) for n in match.groups())


def manifest(root: Path) -> dict[str, str]:
    """{path: sha256} of every program file under root, the signature file aside."""
    return {
        relative: copying.file_sha256(path)
        for path, relative in copying.program_files(root)
        if relative != SIGNATURE
    }


def message(release: dict) -> bytes:
    return DOMAIN + signing.canonical(release)


def check(root: Path, newer_than: str | None = None, keys: dict[str, str] | None = None) -> str:
    """The version of the signed release in root, or ReleaseError.

    newer_than: the installed version; the same or an older one is refused."""
    keys = KEYS if keys is None else keys
    try:
        text = (root / SIGNATURE).read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ReleaseError("release_unsigned") from None
    except (OSError, UnicodeDecodeError):
        raise ReleaseError("release_unreadable") from None
    try:
        signed = strictjson.loads(text)
    except (ValueError, RecursionError):
        raise ReleaseError("release_unreadable") from None
    if not isinstance(signed, dict) or set(signed) != {"format", "release", "key", "signature"}:
        raise ReleaseError("release_unreadable")
    release = signed["release"]
    if (
        signed["format"] != FORMAT
        or not isinstance(release, dict)
        or set(release) != {"version", "files"}
        or not isinstance(release["files"], dict)
    ):
        raise ReleaseError("release_unreadable")
    public = keys.get(signed["key"]) if isinstance(signed["key"], str) else None
    if public is None:
        raise ReleaseError("release_unknown_key")
    try:
        signature = base64.b64decode(signed["signature"], validate=True)
    except (binascii.Error, ValueError, TypeError):
        raise ReleaseError("release_unreadable") from None
    if len(signature) != 64:
        raise ReleaseError("release_unreadable")
    try:
        signed_bytes = message(release)
    except UnicodeEncodeError:  # a lone surrogate: nobody signed that
        raise ReleaseError("release_tampered") from None
    if not signing.signed_by(base64.b64decode(public), signature, signed_bytes):
        raise ReleaseError("release_tampered")

    # Read only after the signature holds: from here on these values are CarrotStudio's.
    version = release["version"]
    version_number(version)
    if manifest(root) != release["files"]:
        raise ReleaseError("release_files_differ")
    if newer_than is not None and version_number(version) <= version_number(newer_than):
        raise ReleaseError("release_not_newer")
    return version


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python3 campanile/release.py FOLDER")
        return 2
    try:
        version = check(Path(args[0]))
    except ReleaseError as e:
        print(messages.text(e.args[0], "en"))
        return 1
    print(f"Signed by CarrotStudio: Campanile {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
