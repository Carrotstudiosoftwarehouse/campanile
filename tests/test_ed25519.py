# DEVELOPED BY CARROTSTUDIO software house
"""Our Ed25519 check against vectors we did not write: the RFC's and Google's Wycheproof.

Where `cryptography` is installed (as in CI) also against OpenSSL, case by case: the two must
always give the same answer, because a Campanile uses whichever it has."""

import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "campanile"))
import ed25519

VECTORS = Path(__file__).resolve().parent / "vectors"
HAS_OPENSSL = importlib.util.find_spec("cryptography") is not None
SMALL_ORDER = (  # the first is the curve's neutral point
    "0100000000000000000000000000000000000000000000000000000000000000",
    "ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f",
    "0000000000000000000000000000000000000000000000000000000000000000",
    "0000000000000000000000000000000000000000000000000000000000000080",
    "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05",
    "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc85",
    "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a",
    "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac03fa",
)


def rfc_vectors():
    return json.loads((VECTORS / "rfc8032-ed25519.json").read_text(encoding="utf-8"))


def wycheproof():
    data = json.loads((VECTORS / "wycheproof-ed25519.json").read_text(encoding="utf-8"))
    for group in data["testGroups"]:
        key = bytes.fromhex(group["publicKey"]["pk"])
        for case in group["tests"]:
            yield key, bytes.fromhex(case["sig"]), bytes.fromhex(case["msg"]), case


def openssl(key: bytes, signature: bytes, message: bytes) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        Ed25519PublicKey.from_public_bytes(key).verify(signature, message)
    except (InvalidSignature, ValueError):
        return False
    return True


class TestVectors(unittest.TestCase):
    def test_the_rfc_vectors_pass_and_any_change_fails(self):
        vectors = rfc_vectors()
        self.assertEqual(len(vectors), 5)
        for v in vectors:
            key, signature, message = (
                bytes.fromhex(v[k]) for k in ("public_key", "signature", "message")
            )
            self.assertTrue(ed25519.verify(key, signature, message), v["name"])
            self.assertFalse(ed25519.verify(key, signature, message + b"!"), v["name"])
            for byte in (0, 31, 32, 63):  # R and s, at both ends
                damaged = bytearray(signature)
                damaged[byte] ^= 1
                self.assertFalse(ed25519.verify(key, bytes(damaged), message), v["name"])

    def test_wycheproof_says_valid_or_invalid(self):
        counted = {"valid": 0, "invalid": 0}
        for key, signature, message, case in wycheproof():
            if case["result"] == "acceptable":
                continue  # the standard leaves these to each library: OpenSSL decides, below
            expected = case["result"] == "valid"
            got = ed25519.verify(key, signature, message)
            self.assertEqual(got, expected, f"{case['tcId']}: {case['flags']}")
            counted[case["result"]] += 1
        self.assertEqual(counted, {"valid": 117, "invalid": 64})

    def test_the_eight_points_of_small_order_are_not_keys(self):
        # libsodium's list. With one of these as a key, a signature anyone can build verifies.
        for key in SMALL_ORDER:
            point = ed25519._decode(bytes.fromhex(key))
            self.assertIsNotNone(point, key)  # a real point of the curve...
            eight = ed25519._encode(ed25519._multiply(8, point))
            self.assertEqual(eight, bytes.fromhex(SMALL_ORDER[0]), key)  # ...of small order
            self.assertFalse(ed25519.is_public_key(bytes.fromhex(key)), key)

    def test_a_public_key_must_name_a_point(self):
        key = bytes.fromhex(rfc_vectors()[0]["public_key"])
        self.assertTrue(ed25519.is_public_key(key))
        self.assertFalse(ed25519.is_public_key(b"\xff" * 32))  # past P: names nothing
        self.assertFalse(ed25519.is_public_key(key[:31]))


@unittest.skipUnless(HAS_OPENSSL, "needs the cryptography package")
class TestSameAnswerAsOpenSSL(unittest.TestCase):
    def test_every_wycheproof_case(self):
        cases = 0
        for key, signature, message, case in wycheproof():
            ours, theirs = ed25519.verify(key, signature, message), openssl(key, signature, message)
            self.assertEqual(ours, theirs, f"{case['tcId']}: {case['flags']}")
            cases += 1
        self.assertEqual(cases, 210)

    def test_random_signatures_and_damaged_ones(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        for i in range(300):
            private = Ed25519PrivateKey.generate()
            key = private.public_key().public_bytes_raw()
            message = os.urandom(i)
            signature = private.sign(message)
            self.assertTrue(ed25519.verify(key, signature, message))
            damaged = bytearray(signature)
            damaged[i % 64] ^= 1 << (i % 8)
            damaged = bytes(damaged)
            self.assertEqual(
                ed25519.verify(key, damaged, message), openssl(key, damaged, message), i
            )


if __name__ == "__main__":
    unittest.main()
