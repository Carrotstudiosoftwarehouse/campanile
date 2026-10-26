# DEVELOPED BY CARROTSTUDIO software house
"""Small PMTiles v3 maps written from scratch, for tests: vector tiles with chosen names.

Independent of campanile/places.py on purpose (written from the two specs, not from the
reader), so a mistake in the reader is not repeated here.
"""

import gzip
import math
import struct

EXTENT = 4096


def varint(n: int) -> bytes:
    out = bytearray()
    while True:
        byte = n & 0x7F
        n >>= 7
        out.append(byte | (0x80 if n else 0))
        if not n:
            return bytes(out)


def zigzag(n: int) -> int:
    return (n << 1) ^ (n >> 31)


def field(number: int, payload) -> bytes:
    if isinstance(payload, int):
        return varint(number << 3) + varint(payload)
    return varint(number << 3 | 2) + varint(len(payload)) + payload


def hilbert_id(z: int, x: int, y: int) -> int:
    """The PMTiles tile id: all tiles of the lower zooms, then the Hilbert curve position."""
    first = (4**z - 1) // 3
    n, d, s = 1 << z, 0, (1 << z) // 2
    while s > 0:
        rx = 1 if x & s else 0
        ry = 1 if y & s else 0
        d += s * s * ((3 * rx) ^ ry)
        if ry == 0:
            if rx == 1:
                x, y = n - 1 - x, n - 1 - y
            x, y = y, x
        s //= 2
    return first + d


def tile_of(lon: float, lat: float, z: int) -> tuple[int, int, int, int]:
    """Tile column and row, and the position inside the tile, of a point."""
    n = 1 << z
    fx = (lon + 180) / 360 * n
    fy = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    x, y = int(fx), int(fy)
    return x, y, round((fx - x) * EXTENT), round((fy - y) * EXTENT)


def _value(v) -> bytes:
    if isinstance(v, bool):  # before int: True is an int in Python
        return field(7, int(v))
    if isinstance(v, str):
        return field(1, v.encode())
    if isinstance(v, int) and v >= 0:
        return field(5, v)
    return field(6, zigzag(v))


def vector_tile(layers: dict) -> bytes:
    """layers: {name: [(properties, [(x, y), ...]), ...]}, one point = a point feature."""
    out = b""
    for name, features in layers.items():
        keys, values, body = [], [], b""
        for props, points in features:
            tags = []
            for k, v in props.items():
                if k not in keys:
                    keys.append(k)
                if v not in values:
                    values.append(v)
                tags += [keys.index(k), values.index(v)]
            geometry, cx, cy = [], 0, 0
            for i, (px, py) in enumerate(points):
                if i == 0:
                    geometry.append(1 | (1 << 3))  # MoveTo, one point
                elif i == 1:
                    geometry.append(2 | ((len(points) - 1) << 3))  # LineTo, the rest
                geometry += [zigzag(px - cx), zigzag(py - cy)]
                cx, cy = px, py
            feature = field(2, b"".join(varint(t) for t in tags))
            feature += field(3, 1 if len(points) == 1 else 2)
            feature += field(4, b"".join(varint(g) for g in geometry))
            body += field(2, feature)
        layer = field(15, 2) + field(1, name.encode()) + body
        layer += b"".join(field(3, k.encode()) for k in keys)
        layer += b"".join(field(4, _value(v)) for v in values)
        layer += field(5, EXTENT)
        out += field(3, layer)
    return out


def _directory(entries: list[tuple[int, int, int, int]]) -> bytes:
    """entries: (tile id, run length, offset, length), sorted by tile id."""
    out = varint(len(entries))
    last = 0
    for tile_id, *_ in entries:
        out += varint(tile_id - last)
        last = tile_id
    out += b"".join(varint(run) for _, run, _, _ in entries)
    out += b"".join(varint(length) for _, _, _, length in entries)
    end = None
    for _, _, offset, length in entries:  # 0: right after the previous tile, as pmtiles writes
        out += varint(0 if offset == end else offset + 1)
        end = offset + length
    return gzip.compress(out)


def pmtiles(tiles: dict, bounds=(7.0, 45.0, 8.0, 46.0), leaves: bool = False) -> bytes:
    """tiles: {(z, x, y): tile bytes, unpacked}. With leaves, the root only points to a leaf
    directory, as in large maps."""
    data, entries = b"", []
    for z, x, y in sorted(tiles, key=lambda t: hilbert_id(*t)):
        packed = gzip.compress(tiles[(z, x, y)])
        entries.append((hilbert_id(z, x, y), 1, len(data), len(packed)))
        data += packed
    if leaves:
        leaf = _directory(entries)
        root = _directory([(entries[0][0], 0, 0, len(leaf))])
    else:
        leaf, root = b"", _directory(entries)
    zooms = [z for z, _, _ in tiles] or [0]
    root_at = 127
    leaves_at = root_at + len(root)
    data_at = leaves_at + len(leaf)
    head = b"PMTiles" + bytes([3])
    head += struct.pack(
        "<8Q",
        root_at,
        len(root),
        root_at + len(root),
        0,
        leaves_at,
        len(leaf),
        data_at,
        len(data),
    )
    head += struct.pack("<3Q", len(entries), len(entries), len(entries))
    head += bytes([1, 2, 2, 1, min(zooms), max(zooms)])
    w, s, e, n = bounds
    head += struct.pack("<4i", *(round(v * 1e7) for v in (w, s, e, n)))
    head += bytes([max(zooms)]) + struct.pack(
        "<2i", round((w + e) / 2 * 1e7), round((s + n) / 2 * 1e7)
    )
    if len(head) != 127:
        raise ValueError("the header must be 127 bytes")
    return head + root + leaf + data
