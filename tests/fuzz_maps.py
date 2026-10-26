# DEVELOPED BY CARROTSTUDIO software house
"""Fuzzing of the map reader (search) and of the street builder (navigator).

A map can come from another Campanile, so whatever a file holds, reading it must end in a
result or in a clean refusal (MapError), within a few seconds. Starting from real tiles, each
case changes them the way a hostile file could (flipped bits, extreme numbers, a feature
repeated thousands of times, cut short, moved, multiplied), packs a valid PMTiles around them
and gives the file to both readers. Anything else, or a case slower than --slow, is a finding.

    python3 tests/fuzz_maps.py --cases 20000 [--seed 1] [--maps a.pmtiles ...]
    python3 tests/fuzz_maps.py --plant crash   # control: a guard removed, must be found
    python3 tests/fuzz_maps.py --plant slow    # control: the work budget removed

Each case is numbered: --only N runs case N again. Run it with a memory limit (a container):
a case that exhausts memory kills the process, and the last line printed names it.
"""

from __future__ import annotations

import argparse
import collections
import random
import struct
import sys
import tempfile
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent / "campanile"), str(HERE)]

import mapfixture as mf  # noqa: E402
import places  # noqa: E402
import routes  # noqa: E402


def seeds(extra: list[Path]) -> list[tuple[tuple[int, int, int], bytes]]:
    """Real tiles: the test towns, and any map given."""
    import test_routes

    found = []
    with tempfile.TemporaryDirectory() as tmp:
        files = []
        for name, data in (
            ("town", test_routes.town_map()),
            ("river", test_routes.town_map(test_routes.river())),
        ):
            path = Path(tmp, f"{name}.pmtiles")
            path.write_bytes(data)
            files.append(path)
        for path in [*files, *extra]:
            with open(path, "rb") as f:
                archive = places.PMTiles(f)
                top = archive.max_zoom
                found += [(key, tile) for key, tile in archive.tiles(top, top)]
    return found


# -- mutations ----------------------------------------------------------------------------------


def _varint(data: bytes, at: int) -> tuple[int, int]:
    value, shift = 0, 0
    while at < len(data):
        byte = data[at]
        value |= (byte & 0x7F) << shift
        at += 1
        if not byte & 0x80:
            return value, at
        shift += 7
    raise ValueError


def _fields(data: bytes):
    """Top-level protobuf fields: (start, end, number, kind)."""
    at, out = 0, []
    try:
        while at < len(data):
            start = at
            key, at = _varint(data, at)
            kind = key & 7
            if kind == 0:
                _, at = _varint(data, at)
            elif kind == 2:
                length, at = _varint(data, at)
                at += length
            elif kind == 5:
                at += 4
            elif kind == 1:
                at += 8
            else:
                break
            out.append((start, min(at, len(data)), key >> 3, kind))
    except ValueError:
        pass
    return out


def _enc(value: int) -> bytes:
    out = b""
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out += bytes([byte | 0x80])
        else:
            return out + bytes([byte])


EXTREMES = [0, 1, 2, 7, 64, 127, 128, 4095, 4096, 4097, 65535, 2**31 - 1, 2**31, 2**32, 2**63]


def mutate(tile: bytes, other: bytes, rng: random.Random) -> bytes:
    data = bytearray(tile)
    how = rng.randrange(10)
    if how == 0 and data:  # flip a few bits
        for _ in range(rng.randint(1, 8)):
            data[rng.randrange(len(data))] ^= 1 << rng.randrange(8)
    elif how == 1 and data:  # interesting bytes
        for _ in range(rng.randint(1, 4)):
            data[rng.randrange(len(data))] = rng.choice([0, 0x7F, 0x80, 0xFF, 0x01])
    elif how == 2:  # cut short
        del data[rng.randrange(len(data) + 1) :]
    elif how == 3 and data:  # a slice removed, or copied elsewhere
        a = rng.randrange(len(data))
        b = min(len(data), a + rng.randint(1, 64))
        if rng.random() < 0.5:
            del data[a:b]
        else:
            data[rng.randrange(len(data))] = data[a]
            data[a:a] = data[a:b]
    elif how == 4:  # spliced with another tile
        a, b = rng.randrange(len(data) + 1), rng.randrange(len(other) + 1)
        data = data[:a] + other[b:]
    else:  # structure-aware: inside a layer, its features, keys, values, extent
        layers = [f for f in _fields(bytes(data)) if f[2] == 3 and f[3] == 2]
        if not layers:
            return bytes(data)
        start, end, _, _ = rng.choice(layers)
        head = _varint(bytes(data), start)[1]
        _, body = _varint(bytes(data), head)
        layer = bytes(data[body:end])
        inner = _fields(layer)
        if not inner:
            return bytes(data)
        s, e, number, kind = rng.choice(inner)
        piece = layer[s:e]
        if how == 5:  # one field repeated many times: thousands of streets on one spot
            layer = layer[:e] + piece * rng.choice([2, 10, 100, 1000, 3000]) + layer[e:]
        elif how == 6 and kind == 0:  # a number at an extreme (the extent, a version)
            layer = layer[:s] + _enc((number << 3) | 0) + _enc(rng.choice(EXTREMES)) + layer[e:]
        elif how == 7 and kind == 2:  # a length that lies
            key_end = _varint(layer, s)[1]
            _, value_at = _varint(layer, key_end)
            lie = rng.choice(EXTREMES)
            layer = layer[:key_end] + _enc(lie) + layer[value_at:e] + layer[e:]
        elif how == 8 and kind == 2:  # inside a feature: its geometry or tags changed
            key_end = _varint(layer, s)[1]
            _, value_at = _varint(layer, key_end)
            feature = bytearray(layer[value_at:e])
            for _ in range(rng.randint(1, 6)):
                if feature:
                    at = rng.randrange(len(feature))
                    feature[at : at + 1] = _enc(rng.choice(EXTREMES))[:3]
            layer = layer[:key_end] + _enc(len(feature)) + bytes(feature) + layer[e:]
        else:  # a field removed
            layer = layer[:s] + layer[e:]
        data = data[:start] + _enc((3 << 3) | 2) + _enc(len(layer)) + layer + data[end:]
    return bytes(data)


def case(tiles, rng: random.Random) -> dict:
    """A map of a few tiles, some changed, sometimes moved or multiplied."""
    chosen = rng.sample(tiles, k=min(len(tiles), rng.randint(1, 4)))
    out = {}
    for (z, x, y), tile in chosen:
        if rng.random() < 0.8:
            tile = mutate(tile, rng.choice(tiles)[1], rng)
        out[(z, x, y)] = tile
    if rng.random() < 0.02:  # one tile copied on many squares: a big map
        (z, x, y), tile = rng.choice(list(out.items()))
        for k in range(rng.choice([10, 100, 1000])):
            out[(z, x + k % 64, y + k // 64)] = tile
    if rng.random() < 0.05:  # a tile at another zoom
        (z, x, y), tile = rng.choice(list(out.items()))
        z2 = rng.choice([0, 5, 12, 14, 16, 18])
        out[(z2, x % (1 << z2), y % (1 << z2))] = tile
    return out


def container(data: bytes, rng: random.Random) -> bytes:
    """Now and then, the header or the directory changed too."""
    if rng.random() < 0.9:
        return data
    data = bytearray(data)
    at = rng.randrange(min(len(data), 127 + 64))
    if rng.random() < 0.5 and at + 8 <= 127:
        data[at : at + 8] = struct.pack("<Q", rng.choice(EXTREMES))
    else:
        data[at] ^= 1 << rng.randrange(8)
    return bytes(data)


# -- running --------------------------------------------------------------------------------


def plant(kind: str) -> None:
    if kind == "crash":  # the geometry reader without its length check

        def lines(geometry):
            out, x, y, i = [], 0, 0, 0
            while i < len(geometry):
                command, count = geometry[i] & 7, geometry[i] >> 3
                i += 1
                for _ in range(count):
                    dx, dy = geometry[i], geometry[i + 1]  # may run past the end
                    x += (dx >> 1) ^ -(dx & 1)
                    y += (dy >> 1) ^ -(dy & 1)
                    i += 2
                    if command == 1:
                        out.append([])
                    if out:
                        out[-1].append((x, y))
            return [line for line in out if len(line) > 1]

        routes._lines = lines
    elif kind == "slow":  # the street builder with no budget of work
        routes.BUDGET.update(cells=10**15, pairs=10**15)
        routes.TILE_BUDGET.update(cells=10**15, pairs=10**15)


PER_TILE = 0.05  # seconds a tile may cost, on top of --slow: a real one costs about 0.007


def run_one(n: int, tiles, base: int, slow: float, folder: Path) -> tuple[str, float]:
    rng = random.Random(base * 1_000_003 + n)
    path = folder / "case.pmtiles"
    chosen = case(tiles, rng)
    path.write_bytes(container(mf.pmtiles(chosen), rng))
    slow += PER_TILE * len(chosen)  # a big map may take longer, in proportion
    worst, outcome = 0.0, "built"
    for label, read in (
        ("search", lambda: places.read_map(path)),
        ("routes", lambda: routes.Network("case", path)),
    ):
        started = time.monotonic()
        try:
            read()
        except places.MapError as e:
            outcome = f"refused: {str(e).split(':')[0][:40]}" if outcome == "built" else outcome
        except Exception:  # anything else is a finding
            return f"FINDING {label}: {traceback.format_exc(limit=3).strip().splitlines()[-1]}", 0
        took = time.monotonic() - started
        worst = max(worst, took)
        if took > slow:
            return f"FINDING {label}: slow, {took:.1f} s", took
    return outcome, worst


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--only", type=int)
    parser.add_argument("--slow", type=float, default=5.0)
    parser.add_argument("--maps", type=Path, nargs="*", default=[])
    parser.add_argument("--plant", choices=["crash", "slow"])
    args = parser.parse_args()
    if args.plant:
        plant(args.plant)
    tiles = seeds(args.maps)
    print(f"{len(tiles)} seed tiles; seed {args.seed}", flush=True)
    outcomes, findings = collections.Counter(), []
    numbers = [args.only] if args.only is not None else range(args.cases)
    started = time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        for n in numbers:
            print(f"case {n}", end="\r", flush=True)  # the last one shown, if memory runs out
            outcome, _ = run_one(n, tiles, args.seed, args.slow, Path(tmp))
            if outcome.startswith("FINDING"):
                findings.append((n, outcome))
                print(f"case {n}: {outcome}", flush=True)
                outcomes["FINDING"] += 1
            else:
                outcomes[outcome] += 1
    total = sum(outcomes.values())
    print(f"\n{total} cases in {time.monotonic() - started:.0f} s:")
    for outcome, count in outcomes.most_common():
        print(f"  {count:7d}  {outcome}")
    print(f"findings: {len(findings)}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
