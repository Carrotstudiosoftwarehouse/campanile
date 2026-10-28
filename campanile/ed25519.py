# DEVELOPED BY CARROTSTUDIO software house
"""Checks an Ed25519 signature (RFC 8032), for computers without the `cryptography` package.

Only checking: no secrets live here, so neither speed nor timing matter. It follows the RFC's
reference code and answers like OpenSSL, the library behind `cryptography`, on the RFC's test
vectors and on Google's Wycheproof ones (tests/test_ed25519.py).
"""

from __future__ import annotations

import hashlib

P = 2**255 - 19
L = 2**252 + 27742317777372353535851937790883648493  # how many points the group has
D = -121665 * pow(121666, P - 2, P) % P
SQRT_M1 = pow(2, (P - 1) // 4, P)
NEUTRAL = (0, 1, 1, 0)  # points in extended coordinates: x, y, z, t with x*y = z*t


def _add(a, b):
    x1, y1, z1, t1 = a
    x2, y2, z2, t2 = b
    e = (y1 - x1) * (y2 - x2) % P
    f = (y1 + x1) * (y2 + x2) % P
    g = 2 * t1 * t2 * D % P
    h = 2 * z1 * z2 % P
    e, f, g, h = f - e, h - g, h + g, f + e
    return e * f % P, g * h % P, f * g % P, e * h % P


def _multiply(n: int, point):
    result = NEUTRAL
    while n:
        if n & 1:
            result = _add(result, point)
        point = _add(point, point)
        n >>= 1
    return result


def _encode(point) -> bytes:
    x, y, z, _ = point
    inverse = pow(z, P - 2, P)
    x, y = x * inverse % P, y * inverse % P
    return (y | (x & 1) << 255).to_bytes(32, "little")


def _decode(data: bytes):
    """The point these 32 bytes name, or None: a number past P names nothing."""
    y = int.from_bytes(data, "little")
    sign, y = y >> 255, y & ((1 << 255) - 1)
    if y >= P:
        return None
    xx = (y * y - 1) * pow(D * y * y + 1, P - 2, P) % P
    x = pow(xx, (P + 3) // 8, P)
    if (x * x - xx) % P:
        x = x * SQRT_M1 % P
    if (x * x - xx) % P:
        return None
    if x == 0 and sign:
        return None
    if x & 1 != sign:
        x = P - x
    return x, y, 1, x * y % P


BASE = _decode((4 * pow(5, P - 2, P) % P).to_bytes(32, "little"))


def is_public_key(data: bytes) -> bool:
    return isinstance(data, bytes) and len(data) == 32 and _decode(data) is not None


def verify(public_key: bytes, signature: bytes, message: bytes) -> bool:
    """True only if the owner of public_key signed exactly this message."""
    if len(public_key) != 32 or len(signature) != 64:
        return False
    a = _decode(public_key)
    s = int.from_bytes(signature[32:], "little")
    if a is None or s >= L:  # s past L: the same signature written another way
        return False
    k = int.from_bytes(hashlib.sha512(signature[:32] + public_key + message).digest(), "little")
    minus_a = ((P - a[0]) % P, a[1], a[2], (P - a[3]) % P)
    # [s]B - [k]A must give back R, compared as bytes like OpenSSL does
    return _encode(_add(_multiply(s, BASE), _multiply(k % L, minus_a))) == signature[:32]
