# DEVELOPED BY CARROTSTUDIO software house
"""A signed Campanile version: exactly the signed files pass, none more, none fewer, never an
older version. The tests sign with `cryptography`; checking works without it."""

import base64
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "campanile"))
import copying
import ed25519
import release
import signing

ROOT = Path(__file__).resolve().parent.parent
CAN_SIGN = importlib.util.find_spec("cryptography") is not None


def temporary_folder(test: unittest.TestCase) -> Path:
    folder = tempfile.TemporaryDirectory()
    test.addCleanup(folder.cleanup)
    return Path(folder.name)


def write(root: Path, files: dict[str, str]) -> None:
    for relative, text in files.items():
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_text(text, encoding="utf-8")


PROGRAM = {
    "campanile/server.py": 'VERSION = "0.2.0"\n',
    "campanile/web/index.html": "<h1>Campanile</h1>",
    "docs/LIMITS.md": "Our limits.",
    "README.md": "Campanile",
}


class TestWithoutSigning(unittest.TestCase):
    def setUp(self):
        self.root = temporary_folder(self)
        write(self.root, PROGRAM)

    def test_unsigned_and_unreadable_are_told_apart(self):
        with self.assertRaises(release.ReleaseError) as e:
            release.check(self.root)
        self.assertEqual(e.exception.args[0], "release_unsigned")
        for text in ("{", "[]", '{"format": "x"}', '{"a": 1, "a": 2}'):
            write(self.root, {release.SIGNATURE: text})
            with self.assertRaises(release.ReleaseError) as e:
                release.check(self.root)
            self.assertEqual(e.exception.args[0], "release_unreadable", text)

    def test_the_signature_covers_what_a_copy_carries(self):
        write(self.root, {"tests/test_x.py": "", "data/campanile.db": "", release.SIGNATURE: "{}"})
        carried = {relative for _, relative in copying.program_files(self.root)}
        self.assertEqual(set(release.manifest(self.root)), carried - {release.SIGNATURE})
        self.assertEqual(set(release.manifest(self.root)), set(PROGRAM))

    def test_versions(self):
        self.assertLess(release.version_number("0.9.9"), release.version_number("0.10.0"))
        for bad in ("1.0", "01.0.0", "1.0.0-rc1", " 1.0.0", 100, None):
            with self.assertRaises(release.ReleaseError):
                release.version_number(bad)

    def test_the_embedded_keys_are_real_public_keys(self):
        for key_id, public in release.KEYS.items():
            raw = base64.b64decode(public, validate=True)
            self.assertTrue(ed25519.is_public_key(raw), key_id)
            self.assertEqual(signing.key_id(raw), key_id)


@unittest.skipUnless(CAN_SIGN, "signing in the tests needs the cryptography package")
class TestSigned(unittest.TestCase):
    def setUp(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        self.root = temporary_folder(self)
        write(self.root, PROGRAM)
        self.key = Ed25519PrivateKey.generate()
        self.keys = {self.key_id(self.key): self.public(self.key)}

    @staticmethod
    def public(key) -> str:
        return base64.b64encode(key.public_key().public_bytes_raw()).decode()

    def key_id(self, key) -> str:
        return signing.key_id(key.public_key().public_bytes_raw())

    def sign(self, key=None, version="0.2.0", signed_bytes=None):
        key = key or self.key
        body = {"version": version, "files": release.manifest(self.root)}
        data = signed_bytes(body) if signed_bytes else release.message(body)
        signed = {
            "format": release.FORMAT,
            "release": body,
            "key": self.key_id(key),
            "signature": base64.b64encode(key.sign(data)).decode(),
        }
        write(self.root, {release.SIGNATURE: json.dumps(signed)})
        return signed

    def refused(self, reason, **check):
        with self.assertRaises(release.ReleaseError) as e:
            release.check(self.root, **{"keys": self.keys, **check})
        self.assertEqual(e.exception.args[0], reason)

    def test_a_signed_release_passes(self):
        self.sign()
        self.assertEqual(release.check(self.root, keys=self.keys), "0.2.0")

    def test_one_changed_added_or_missing_file_is_refused(self):
        self.sign()
        for change in (
            lambda: write(self.root, {"docs/LIMITS.md": "Our limits!"}),
            lambda: write(self.root, {"campanile/secrets.py": "steal()"}),  # runs before ours
            lambda: (self.root / "README.md").unlink(),
        ):
            write(self.root, PROGRAM)
            (self.root / "campanile" / "secrets.py").unlink(missing_ok=True)
            self.assertEqual(release.check(self.root, keys=self.keys), "0.2.0")
            change()
            self.refused("release_files_differ")

    def test_only_carrotstudio_keys_count(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        self.sign(key=Ed25519PrivateKey.generate())
        self.refused("release_unknown_key")
        self.sign()
        self.refused("release_unknown_key", keys={})

    def test_a_changed_signature_or_version_is_refused(self):
        signed = self.sign()
        signature = bytearray(base64.b64decode(signed["signature"]))
        signature[5] ^= 1
        forged = {**signed, "signature": base64.b64encode(bytes(signature)).decode()}
        write(self.root, {release.SIGNATURE: json.dumps(forged)})
        self.refused("release_tampered")
        newer = {**signed, "release": {**signed["release"], "version": "9.0.0"}}
        write(self.root, {release.SIGNATURE: json.dumps(newer)})
        self.refused("release_tampered")

    def test_never_back_to_an_older_version(self):
        self.sign(version="0.2.0")
        self.refused("release_not_newer", newer_than="0.2.0")
        self.refused("release_not_newer", newer_than="0.10.0")
        self.assertEqual(release.check(self.root, newer_than="0.1.9", keys=self.keys), "0.2.0")

    def test_a_notice_signature_never_passes_for_a_release(self):
        self.sign(signed_bytes=lambda body: signing.DOMAIN + signing.canonical(body))
        self.refused("release_tampered")

    def test_checked_by_our_ed25519_too(self):
        self.sign()
        without_openssl = mock.patch.object(signing, "Ed25519PublicKey", None)
        spy = mock.patch.object(signing.ed25519, "verify", wraps=signing.ed25519.verify)
        with without_openssl, spy as ours:
            self.assertEqual(release.check(self.root, keys=self.keys), "0.2.0")
        ours.assert_called_once()


@unittest.skipUnless(CAN_SIGN, "needs the cryptography package")
class TestSignReleaseScript(unittest.TestCase):
    """keygen and sign, end to end, with the passphrases typed by a mock."""

    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            "sign_release", ROOT / "scripts/sign-release.py"
        )
        self.script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.script)
        self.tmp = temporary_folder(self)
        self.script.ROOT = self.tmp / "repo"  # the signature is written here, not in our repo
        (self.tmp / "repo" / "campanile").mkdir(parents=True)

    def run_script(self, *argv, passphrases=()):
        typed = iter(passphrases)
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(sys, "argv", ["sign-release.py", *argv]))
            stack.enter_context(
                mock.patch.object(self.script.getpass, "getpass", lambda prompt="": next(typed))
            )
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            self.script.main()

    def test_keygen_then_sign_a_package(self):
        keys = self.tmp / "keys"
        self.run_script(
            "keygen", "--out", str(keys), passphrases=["short", *["a long passphrase"] * 4]
        )
        main = keys / "campanile-release-main.key"
        if os.name == "posix":  # Windows has no such permission bits
            self.assertEqual(main.stat().st_mode & 0o777, 0o600)
        self.assertIn(b"ENCRYPTED", main.read_bytes())

        package = self.tmp / "campanile-0.2.0.zip"
        with zipfile.ZipFile(package, "w") as z:
            for relative, text in PROGRAM.items():
                z.writestr(f"campanile-0.2.0/{relative}", text)
        with self.assertRaises(SystemExit):  # not in KEYS yet: refused before signing
            self.run_script(
                "sign", "--key", str(main), str(package), passphrases=["a long passphrase"]
            )

        from cryptography.hazmat.primitives import serialization

        private = serialization.load_pem_private_key(main.read_bytes(), b"a long passphrase")
        public = base64.b64encode(private.public_key().public_bytes_raw()).decode()
        key_id = signing.key_id(private.public_key().public_bytes_raw())
        with mock.patch.dict(release.KEYS, {key_id: public}):
            with self.assertRaises(SystemExit):
                self.run_script("sign", "--key", str(main), str(package), passphrases=["wrong"])
            self.run_script(
                "sign", "--key", str(main), str(package), passphrases=["a long passphrase"]
            )
            folder = self.tmp / "unzipped"
            zipfile.ZipFile(package).extractall(folder)
            write(
                folder / "campanile-0.2.0",
                {release.SIGNATURE: (self.tmp / "repo" / release.SIGNATURE).read_text()},
            )
            self.assertEqual(release.check(folder / "campanile-0.2.0"), "0.2.0")


if __name__ == "__main__":
    unittest.main()
