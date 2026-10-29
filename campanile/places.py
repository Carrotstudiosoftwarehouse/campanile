# DEVELOPED BY CARROTSTUDIO software house
"""Searching the maps without internet: towns, neighbourhoods, streets, useful places.

The names are already in the map files (Protomaps basemap, PMTiles v3 with vector tiles).
Each map is read once in the background and saved in data/places/ for the next start;
searching happens in memory.

Maps come from Protomaps through `pmtiles verify`, from whoever runs the Campanile, or from
another Campanile, so they are read with care: whatever a file says, reading it costs a
bounded amount of memory and work, and a map that can't be read is simply not searchable.
"""

from __future__ import annotations

import contextlib
import heapq
import json
import math
import os
import re
import struct
import sys
import threading
import time
import unicodedata
import zlib
from array import array
from bisect import bisect_left, bisect_right
from pathlib import Path

FORMAT = 2  # of the files in data/places/: a new format means reading the maps again
MAP_NAME = re.compile(r"[A-Za-z0-9_-]+\.pmtiles")
TILE_LIMIT = 8 * 2**20  # unpacked; vector tiles are rarely over 1 MB
DIRECTORY_LIMIT = 4 * 2**20  # unpacked; real maps stay under 30 KB
MAX_ENTRIES = 1_000_000  # in one directory; real maps have at most a few thousand
MAX_NAMES = 250_000  # per map: a big city has far fewer, and a Raspberry has little memory
TOTAL_NAMES = 1_000_000  # all the maps together: about 250 MB in memory
MAX_SAME = 256  # towns of one name and kind, or pieces of one street in one cell (real: 13)
MAX_PER_CELL = 512  # towns or neighbourhoods in one cell, to say where a street is (real: 198)
# The most one map may cost to read, several times the largest real maps we measured: past
# it the map still shows, but can't be searched, until the file changes. A shared map may
# have been made to keep a Campanile busy or to fill its memory.
BUDGET = {
    "entries": 20_000_000,  # directory entries (world map: 21,000)
    "tiles": 300_000,  # (world map: 9,500)
    "bytes": 2**30,  # tiles once unpacked (world map: 270 MB)
    "features": 5_000_000,  # named things in the tiles (a metropolitan area: 171,000)
    "steps": 300_000_000,  # comparisons between names (a metropolitan area: 10 million)
    "cells": 2_000_000,  # streets listed in the cells they cover (a metropolitan area: 63,000)
    "text": 30_000_000,  # characters of the names kept (a metropolitan area: 1.7 million)
}
MAX_CELLS = 1024  # covered by one street: about 60 km on a side (real: 180 at most)
TRIES = 3  # readings of a map cut short before it is given up
# Streets and points of interest come from the most detailed tiles, and only for maps of an
# area: a whole country would take hours on a Raspberry. Towns and neighbourhoods come from
# every map, read up to PLACE_ZOOM, where they have all appeared.
DETAIL_ZOOM = 13
DETAIL_TILES = 30_000
PLACE_ZOOM = 12
RESULTS = 10
CANDIDATES = 500  # per map, ranked one by one at most: a search always costs little
MAX_WORDS = 4  # of a search: names are found with fewer, and each one more costs more
COMMON = 30_000  # a word on more names than this is left to the whole text, typed so far
# The index of one map, kept in memory: bounded like the reading, whatever the map says.
MAX_ROW_WORDS = 24  # searchable words of one name, translations included (real: 19)
MAX_VOCABULARY = 250_000  # different words (real: 45,000 for the whole world)
MAX_KIND = 20_000  # places of one kind, for "the nearest pharmacy" (real: a few hundred)
CHECK_EVERY = 10.0  # seconds between looks at the maps folder

PLACE, STREET, POINT = 0, 1, 2
TYPES = ("place", "street", "poi")
LANGUAGES = ("it", "en")
STREET_KINDS = {"highway", "major_road", "minor_road", "path"}
OTHER_STREETS = {"living_street"}  # the map files them under "other", but people live there
# What people need and maps seldom name: found by kind, never by a name it hasn't got.
NAMELESS_KINDS = {"drinking_water", "toilets"}
APOSTROPHES = str.maketrans("", "", "'\u2019")  # "King's" is typed "kings" too
# Many, and named after the street they stand on: they would bury the street itself.
NOISY_POINTS = {"bus_stop", "tram_stop", "subway_entrance", "platform"}

# What people type when they look for a kind of place rather than a name, in every language
# of the pages. The kinds are those of the Protomaps basemap.
CATEGORIES = [
    ({"hospital"}, ["ospedale", "ospedali", "pronto soccorso", "hospital", "hospitals"]),
    ({"pharmacy"}, ["farmacia", "farmacie", "pharmacy", "pharmacies", "chemist"]),
    (
        {"clinic", "doctors"},
        ["medico", "medici", "ambulatorio", "guardia medica", "clinic", "doctor", "doctors"],
    ),
    ({"police"}, ["polizia", "carabinieri", "questura", "police"]),
    ({"fire_station"}, ["vigili del fuoco", "pompieri", "fire station", "firefighters"]),
    (
        {"drinking_water"},
        ["acqua", "acqua potabile", "fontanella", "fontanelle", "drinking water", "water"],
    ),
    ({"townhall"}, ["comune", "municipio", "town hall", "city hall"]),
    ({"school", "college", "university", "kindergarten"}, ["scuola", "scuole", "school"]),
    (
        {"supermarket", "convenience", "greengrocer", "bakery"},
        ["supermercato", "alimentari", "spesa", "supermarket", "groceries", "food"],
    ),
    ({"fuel"}, ["benzina", "distributore", "carburante", "fuel", "petrol", "gas station"]),
    ({"shelter"}, ["rifugio", "riparo", "shelter"]),
    ({"toilets"}, ["bagno", "bagni", "toilette", "toilets", "toilet", "restroom"]),
]


# Street words as the US Postal Service shortens them, so "Vashon Hwy SW" finds "Vashon
# Highway Southwest". Only where the short form doesn't already begin the word ("st", "ave").
SHORT_FORMS = {
    "highway": "hwy", "road": "rd", "drive": "dr", "boulevard": "blvd", "lane": "ln",
    "court": "ct", "parkway": "pkwy", "trail": "trl", "expressway": "expy", "freeway": "fwy",
    "mount": "mt", "mountain": "mtn", "fort": "ft", "saint": "st", "point": "pt",
    "center": "ctr", "heights": "hts", "junction": "jct", "harbor": "hbr", "creek": "crk",
    "crossing": "xing", "route": "rte",
    "northeast": "ne", "northwest": "nw", "southeast": "se", "southwest": "sw",
}  # fmt: skip


class MapError(Exception):
    """The file is not a map this module can read."""


def normalize(text: str) -> str:
    """'Città  Sant'Anna' -> 'citta sant anna': lower case, no accents, words only."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(c if c.isalnum() else " " for c in decomposed if not unicodedata.combining(c))
    return " ".join(plain.split())


SYNONYMS = {normalize(word): kinds for kinds, words in CATEGORIES for word in words}


# -- reading PMTiles v3 (https://github.com/protomaps/PMTiles/blob/main/spec/v3/spec.md) ---


def _varint(buf, i: int) -> tuple[int, int]:
    result = shift = 0
    while shift < 64:
        try:
            byte = buf[i]
        except IndexError:
            raise MapError("cut short") from None
        i += 1
        result |= (byte & 0x7F) << shift
        if byte < 0x80:
            if result >> 64:
                break
            return result, i
        shift += 7
    raise MapError("varint too long")


class _Work:
    """What reading one map has cost so far, against a budget for the whole map and, if
    given, one for each tile (what a single tile can hold in memory)."""

    def __init__(self, budget: dict | None = None, tile: dict | None = None):
        self.budget = BUDGET if budget is None else budget
        self.tile_budget = tile or {}
        self.spent = dict.fromkeys(self.budget, 0)
        self.tile = dict.fromkeys(self.budget, 0)

    def next_tile(self) -> None:
        self.tile = dict.fromkeys(self.budget, 0)

    def spend(self, kind: str, amount: int = 1) -> None:
        self.spent[kind] += amount
        self.tile[kind] += amount
        if self.spent[kind] > self.budget[kind] or self.tile[kind] > self.tile_budget.get(
            kind, self.budget[kind]
        ):
            raise MapError(f"too much work to read ({kind})")


def _unpack(data: bytes, compression: int, limit: int) -> bytes:
    if compression == 1:  # none
        return data
    if compression != 2:  # gzip: what Protomaps and pmtiles extract write
        raise MapError(f"compression {compression} not supported")
    unzip = zlib.decompressobj(31)
    try:
        out = unzip.decompress(data, limit)
    except zlib.error:
        raise MapError("damaged") from None
    if unzip.unconsumed_tail:
        raise MapError("too large once unpacked")
    if not unzip.eof:  # zlib returns what it could of a stream cut short, without a word
        raise MapError("incomplete")
    if unzip.unused_data:  # one stream read again and again, each time with a byte more
        raise MapError("more than the stream")
    return out


def _read(f, offset: int, length: int) -> bytes:
    """Bytes the header or a directory points to, which a hostile file can put anywhere."""
    size = f.seek(0, os.SEEK_END)
    if not (0 <= offset <= size and 0 <= length <= size - offset):
        raise MapError("the file ends too early")
    f.seek(offset)
    data = f.read(length)
    if len(data) != length:
        raise MapError("the file ends too early")
    return data


def _first_id(zoom: int) -> int:
    """Tile ids count every tile of the lower zooms first."""
    return (4**zoom - 1) // 3


_FIRST_IDS = [_first_id(z) for z in range(32)]


def _zxy(tile_id: int) -> tuple[int, int, int]:
    """Tile id (Hilbert curve order, zoom after zoom) to zoom, column, row."""
    z = bisect_right(_FIRST_IDS, tile_id) - 1
    d, x, y, s = tile_id - _FIRST_IDS[z], 0, 0, 1
    while s < (1 << z):
        rx = 1 & (d // 2)
        ry = 1 & (d ^ rx)
        if ry == 0:
            if rx == 1:
                x, y = s - 1 - x, s - 1 - y
            x, y = y, x
        x, y = x + s * rx, y + s * ry
        d //= 4
        s *= 2
    return z, x, y


class PMTiles:
    """Reads tiles by zoom, without ever holding the whole directory in memory."""

    def __init__(self, f, work: _Work | None = None):
        self.f = f
        self.work = work or _Work()
        head = f.read(127)
        if len(head) != 127 or head[:7] != b"PMTiles" or head[7] != 3:
            raise MapError("not a PMTiles v3 file")
        (self.root, self.root_length, _, _, self.leaves, _, self.data, _) = struct.unpack_from(
            "<8Q", head, 8
        )
        self.internal, self.compression = head[97], head[98]
        if head[99] != 1:
            raise MapError("not vector tiles")
        self.min_zoom, self.max_zoom = head[100], min(head[101], 26)
        self.bounds = tuple(v / 1e7 for v in struct.unpack_from("<4i", head, 102))

    def _directory(self, offset: int, length: int, until: int, depth=0, seen=None):
        """(tile id, offset, length) of the tiles before `until`, leaf directories included."""
        seen = set() if seen is None else seen
        if depth > 3 or length > DIRECTORY_LIMIT:
            raise MapError("directory too deep or too large")
        # Each directory is read once: entries pointing back to one already read would make
        # the reading endless (many entries, each re-reading the same directory).
        if (offset, length) in seen:
            raise MapError("directory read twice")
        seen.add((offset, length))
        buf = _unpack(_read(self.f, offset, length), self.internal, DIRECTORY_LIMIT)
        count, i = _varint(buf, 0)
        if count > MAX_ENTRIES or 4 * count > len(buf) - i:  # each entry takes 4 bytes or more
            raise MapError("directory size")
        self.work.spend("entries", count)
        columns = []
        for _ in range(4):
            column = array("Q")  # 8 bytes a number, not 36: a directory stays small in memory
            for _ in range(count):
                value, i = _varint(buf, i)
                column.append(value)
            columns.append(column)
        del buf
        ids, runs, lengths, offsets = columns
        tile_id = end = 0
        for k in range(count):
            tile_id += ids[k]
            if tile_id >= until:  # entries come in tile order: the rest is of higher zooms
                return
            start = end if offsets[k] == 0 and k > 0 else offsets[k] - 1
            end = start + lengths[k]
            if runs[k] == 0:
                yield from self._directory(self.leaves + start, lengths[k], until, depth + 1, seen)
            elif runs[k] == 1:
                # Longer runs repeat one tile over a uniform area (sea, fields): no names.
                yield tile_id, start, lengths[k]

    def count(self, zoom: int) -> int:
        first, end = _FIRST_IDS[zoom], _FIRST_IDS[zoom + 1]
        directory = self._directory(self.root, self.root_length, end)
        return sum(1 for tile_id, _, _ in directory if tile_id >= first)

    def tiles(self, low: int, high: int):
        """((z, x, y), unpacked tile) for the zooms from low to high."""
        first, end = _FIRST_IDS[low], _FIRST_IDS[high + 1]
        wanted = []
        for entry in self._directory(self.root, self.root_length, end):
            if entry[0] >= first and entry[2] <= TILE_LIMIT:
                self.work.spend("tiles")
                wanted.append(entry)
        for tile_id, offset, length in wanted:
            tile = _unpack(_read(self.f, self.data + offset, length), self.compression, TILE_LIMIT)
            self.work.spend("bytes", len(tile))
            yield _zxy(tile_id), tile


# -- reading vector tiles (https://github.com/mapbox/vector-tile-spec) ----------------------


def _text(value) -> str:
    """A field that should hold text. A number in its place makes the map unreadable: never
    bytes(number), which would fill that many bytes of memory (2**31: two gigabytes)."""
    if not isinstance(value, memoryview):
        raise MapError("a number where text should be")
    return bytes(value).decode("utf-8", "replace")


def _fields(buf):
    """(field number, value) of one protobuf message; a value is an int or a memoryview."""
    if isinstance(buf, int):
        raise MapError("a number where a message should be")
    buf = memoryview(buf)
    i, end = 0, len(buf)
    while i < end:
        key, i = _varint(buf, i)
        wire = key & 7
        if wire == 0:
            value, i = _varint(buf, i)
        elif wire == 2:
            size, i = _varint(buf, i)
            value, i = buf[i : i + size], i + size
        elif wire == 1:
            value, i = buf[i : i + 8], i + 8
        elif wire == 5:
            value, i = buf[i : i + 4], i + 4
        else:
            raise MapError(f"wire type {wire}")
        if i > end:
            raise MapError("field past the end")
        yield key >> 3, value


def _packed(buf) -> array:
    if isinstance(buf, int):
        raise MapError("a number where a list should be")
    out, i, end = array("Q"), 0, len(buf)
    while i < end:
        value, i = _varint(buf, i)
        out.append(value)
    return out


def _value(buf):
    for number, value in _fields(buf):
        if number == 1:
            return _text(value)
        if number in (4, 5, 6) and not isinstance(value, int):
            raise MapError("text where a number should be")
        if number in (4, 5):
            return value
        if number == 6:
            return (value >> 1) ^ -(value & 1)
    return None  # floats and booleans: nothing searched uses them


def _points(geometry: list[int]):
    """The vertices of a geometry, in tile units."""
    x = y = i = 0
    while i < len(geometry):
        command, count = geometry[i] & 7, geometry[i] >> 3
        i += 1
        if command == 7:  # ClosePath
            continue
        if command not in (1, 2) or i + 2 * count > len(geometry):
            raise MapError("bad geometry")
        for _ in range(count):
            dx, dy = geometry[i], geometry[i + 1]
            x += (dx >> 1) ^ -(dx & 1)
            y += (dy >> 1) ^ -(dy & 1)
            i += 2
            yield x, y


def _features(tile: bytes, wanted: set[str]):
    """(layer, properties, extent, geometry) of the named features of the wanted layers,
    and of the nameless points of NAMELESS_KINDS."""
    for number, layer in _fields(tile):
        if number != 3:
            continue
        name, extent, keys, values, features = None, 4096, [], [], []
        for field, value in _fields(layer):
            if field == 1:
                name = _text(value)
                if name not in wanted:
                    break  # the name comes first: the rest of the layer is skipped
            elif field == 2:
                features.append(value)
            elif field == 3:
                keys.append(_text(value))
            elif field == 4:
                values.append(_value(value))
            elif field == 5:
                if not isinstance(value, int):
                    raise MapError("a tile size that is not a number")
                extent = value or 4096
        if name not in wanted:
            continue
        for feature in features:
            tags, geometry = [], []
            for field, value in _fields(feature):
                if field == 2:
                    tags = _packed(value)
                elif field == 4:
                    geometry = _packed(value)
            props = {
                keys[tags[k]]: values[tags[k + 1]]
                for k in range(0, len(tags) - 1, 2)
                if tags[k] < len(keys) and tags[k + 1] < len(values)
            }
            name_tag = props.get("name")
            named = isinstance(name_tag, str) and name_tag.strip()
            if geometry and (named or (name == "pois" and props.get("kind") in NAMELESS_KINDS)):
                yield name, props, extent, geometry


def _lonlat(z: int, x: int, y: int, px: float, py: float, extent: int) -> tuple[float, float]:
    n = 1 << z
    lon = (x + px / extent) / n * 360 - 180
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + py / extent) / n))))
    return lon, lat


def _km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Good enough at a town's scale, and fast."""
    dx = (lon2 - lon1) * 111.32 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, (lat2 - lat1) * 110.57)


# -- what a map contains ------------------------------------------------------------------

PAD = 0.003  # degrees, about 300 m: pieces of a street closer than this are one street
CELL = 0.02  # degrees, about 2 km: a piece of street is compared only with those in its cells


def _touch(a, b) -> bool:
    return a[0] - PAD <= b[2] and b[0] - PAD <= a[2] and a[1] - PAD <= b[3] and b[1] - PAD <= a[3]


def _join(a, b) -> list[float]:
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def _span(box) -> tuple[int, int, int, int]:
    """The cells a box covers, widened by half of PAD: two boxes that touch share one."""
    half = PAD / 2
    x0, x1 = math.floor((box[0] - half) / CELL), math.floor((box[2] + half) / CELL)
    y0, y1 = math.floor((box[1] - half) / CELL), math.floor((box[3] + half) / CELL)
    return x0, x1, y0, y1


def _size(box) -> int:
    x0, x1, y0, y1 = _span(box)
    return (x1 - x0 + 1) * (y1 - y0 + 1)


class _Reader:
    """Collects the names of one map; the same street or town seen twice is kept once."""

    def __init__(self, work: _Work):
        self.work = work
        self.places: dict[tuple[str, str], list[list]] = {}
        self.streets: dict[str, list[list]] = {}  # name: its pieces, emptied once joined
        self.grid: dict[int, list | tuple] = {}  # hash of (name, cell): pieces covering it
        self.points: dict[tuple, list] = {}
        self.total = 0

    def full(self) -> bool:
        return self.total >= MAX_NAMES

    def place(self, props, lon, lat):
        name = props["name"].strip()[:120]
        kind = str(props.get("kind", ""))[:40]
        key = (normalize(name), kind)
        same = self.places.get(key, ())  # nothing is kept, not even an empty list, once full
        self.work.spend("steps", len(same))
        if self.full() or len(same) >= MAX_SAME or any(_km(lon, lat, p[0], p[1]) < 3 for p in same):
            return
        names = {
            lang: props[f"name:{lang}"][:120]
            for lang in LANGUAGES
            if isinstance(props.get(f"name:{lang}"), str) and props[f"name:{lang}"] != name
        }
        population = props.get("population")
        population = population if isinstance(population, int) and population > 0 else 0
        detail = str(props.get("kind_detail", ""))[:40]
        self.work.spend("text", len(name) + sum(map(len, names.values())))
        self.places.setdefault(key, []).append([lon, lat, name, names, detail, population])
        self.total += 1

    def street(self, props, box):
        """The same street cut by the tile borders is one: a piece joins the one it touches,
        and then whatever else that one now touches. No two pieces of a name ever touch."""
        if _size(box) > MAX_CELLS:
            return  # a piece from one tile can't be this large
        name = props["name"].strip()[:120]
        key = sys.intern(normalize(name))
        piece = self._touching(key, box)
        if piece is None:
            if not self.full() and not self._crowded(key, box):
                piece = [*box, name, str(props["kind"]), key]
                self.work.spend("text", len(name))
                self.streets.setdefault(key, []).append(piece)
                self._cover(key, piece, box, new=True)
                self.total += 1
            return
        self._cover(key, piece, _join(piece, box))
        while (other := self._touching(key, piece, besides=piece)) is not None:
            self._cover(key, piece, _join(piece, other))
            other.clear()  # joined: gone from the grid's point of view, and from the rows
            self.total -= 1

    def _near(self, key: str, x: int, y: int) -> tuple:
        here = self.grid.get(hash((key, x, y)), ())
        return here if isinstance(here, tuple) else (here,)

    def _touching(self, key: str, box, besides=None) -> list | None:
        """A piece of this name that touches box and can grow to cover it, if any."""
        x0, x1, y0, y1 = _span(box)
        self.work.spend("steps", (x1 - x0 + 1) * (y1 - y0 + 1))
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                near = self._near(key, x, y)
                self.work.spend("steps", len(near))
                for piece in near:  # an empty piece was joined; another key, a shared hash
                    same = piece and piece is not besides and piece[6] == key
                    if same and _touch(piece, box) and _size(_join(piece, box)) <= MAX_CELLS:
                        return piece
        return None

    def _crowded(self, key: str, box) -> bool:
        """This many pieces of one name in one place come from a map made to slow us down."""
        x0, x1, y0, y1 = _span(box)
        cells = ((x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1))
        return any(len(self._near(key, x, y)) >= MAX_SAME for x, y in cells)

    def _cover(self, key: str, piece: list, box, new: bool = False) -> None:
        """Gives piece the box, and lists it in the cells it didn't cover yet."""
        before = None if new else _span(piece)
        x0, x1, y0, y1 = _span(box)
        self.work.spend("steps", (x1 - x0 + 1) * (y1 - y0 + 1))
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                if before and before[0] <= x <= before[1] and before[2] <= y <= before[3]:
                    continue
                self.work.spend("cells")
                cell = hash((key, x, y))  # an int, not a tuple of tuples: a quarter of the memory
                here = self.grid.get(cell)
                if here is None:
                    self.grid[cell] = piece
                else:
                    self.grid[cell] = (*here, piece) if isinstance(here, tuple) else (here, piece)
        piece[:4] = box

    def point(self, props, lon, lat):
        name = props["name"].strip()[:120] if isinstance(props.get("name"), str) else ""
        kind = str(props.get("kind", ""))[:40]
        key = (normalize(name), kind, round(lon, 4), round(lat, 4))  # in two tiles at a border
        if key not in self.points and not self.full():
            self.work.spend("text", len(name))
            self.points[key] = [lon, lat, name, kind]
            self.total += 1

    def rows(self) -> list[list]:
        """[type, kind, detail, name, translations, lon, lat, box, near, population]"""
        rows = [
            [PLACE, kind, p[4], p[2], p[3], p[0], p[1], None, "", p[5]]
            for (_, kind), same in self.places.items()
            for p in same
        ]
        for pieces in self.streets.values():
            for w, s, e, n, name, kind, _ in filter(None, pieces):
                rows.append(
                    [STREET, kind, "", name, {}, (w + e) / 2, (s + n) / 2, [w, s, e, n], "", 0]
                )
        for lon, lat, name, kind in self.points.values():
            rows.append([POINT, kind, "", name, {}, lon, lat, None, "", 0])
        _add_context(rows, self.work)
        return rows


def _add_context(rows: list[list], work: _Work) -> None:
    """Each street and point gets the neighbourhood it is in, or else the town."""
    cells: dict[str, dict[tuple[int, int], list[list]]] = {"near": {}, "town": {}}
    size = {"near": 50, "town": 10}  # cells of 0.02 and 0.1 degrees
    for row in rows:
        if row[0] == PLACE and row[1] in ("neighbourhood", "macrohood", "locality"):
            grid = "town" if row[1] == "locality" else "near"
            cell = cells[grid].setdefault((int(row[5] * size[grid]), int(row[6] * size[grid])), [])
            if len(cell) < MAX_PER_CELL:
                cell.append(row)
    for row in rows:
        if row[0] == PLACE:
            continue
        for grid, limit in (("near", 2.0), ("town", 15.0)):
            cx, cy = int(row[5] * size[grid]), int(row[6] * size[grid])
            best, best_km = "", limit
            for gx in (cx - 1, cx, cx + 1):
                for gy in (cy - 1, cy, cy + 1):
                    near = cells[grid].get((gx, gy), ())
                    work.spend("steps", len(near))
                    for place in near:
                        km = _km(row[5], row[6], place[5], place[6])
                        if km < best_km:
                            best, best_km = place[3], km
            if best:
                row[8] = best
                break


def _box(z: int, x: int, y: int, geometry, extent: int) -> list[float] | None:
    """West, south, east, north of a line, without keeping its vertices."""
    xs = ys = None
    for px, py in _points(geometry):
        if xs is None:
            xs, ys = [px, px], [py, py]
        else:
            xs[0], xs[1] = min(xs[0], px), max(xs[1], px)
            ys[0], ys[1] = min(ys[0], py), max(ys[1], py)
    if xs is None:
        return None
    west, north = _lonlat(z, x, y, xs[0], ys[0], extent)  # rows grow southwards
    east, south = _lonlat(z, x, y, xs[1], ys[1], extent)
    return [west, south, east, north]


def read_map(path: Path) -> dict:
    """Everything searchable in one map, as plain lists: saved as JSON as it is."""
    work = _Work()
    reader = _Reader(work)
    with open(path, "rb") as f:
        archive = PMTiles(f, work)
        top = archive.max_zoom
        detail = top >= DETAIL_ZOOM and archive.count(top) <= DETAIL_TILES
        if detail:
            low, high, wanted = top, top, {"places", "roads", "pois"}
        else:
            low, wanted = archive.min_zoom, {"places"}
            high = max(low, min(top, PLACE_ZOOM))
        for (z, x, y), tile in archive.tiles(low, high):
            for layer, props, extent, geometry in _features(tile, wanted):
                work.spend("features")
                if layer == "roads":
                    if (
                        props.get("kind") in STREET_KINDS
                        or props.get("kind_detail") in OTHER_STREETS
                    ):
                        box = _box(z, x, y, geometry, extent)
                        if box:
                            reader.street(props, box)
                    continue
                first = next(_points(geometry), None)
                if first is None:
                    continue
                lon, lat = _lonlat(z, x, y, first[0], first[1], extent)
                if layer == "places":
                    reader.place(props, lon, lat)
                elif props.get("kind") not in NOISY_POINTS:
                    reader.point(props, lon, lat)
    return {
        "format": FORMAT,
        "bounds": list(archive.bounds),
        "max_zoom": top,
        "rows": reader.rows(),
    }


# -- searching ----------------------------------------------------------------------------


class MapIndex:
    """One map's names, ready to search: columns, plus an index of the words."""

    def __init__(self, name: str, content: dict):
        self.map = name
        self.max_zoom = int(content["max_zoom"])
        rows = content["rows"]
        self.types = array("B", (r[0] for r in rows))
        self.kinds = [sys.intern(r[1]) for r in rows]
        self.details = [sys.intern(r[2]) for r in rows]
        self.names = [r[3] for r in rows]
        self.translations = {i: r[4] for i, r in enumerate(rows) if r[4]}
        self.lons = array("d", (r[5] for r in rows))
        self.lats = array("d", (r[6] for r in rows))
        self.boxes = {i: r[7] for i, r in enumerate(rows) if r[7]}
        self.context = [sys.intern(r[8]) for r in rows]
        self.population = {i: r[9] for i, r in enumerate(rows) if r[9]}
        self.variants: list[tuple[str, ...]] = []  # every name, normalized
        words: dict[str, list[int]] = {}
        for i, r in enumerate(rows):
            names = (r[3], *r[4].values())
            variants = tuple(
                dict.fromkeys(
                    v for n in names for v in (normalize(n), normalize(n.translate(APOSTROPHES)))
                )
            )
            self.variants.append(variants)
            own = list(dict.fromkeys(w for v in variants for w in v.split()))
            own = list(dict.fromkeys(own + [SHORT_FORMS[w] for w in own if w in SHORT_FORMS]))
            own = own[:MAX_ROW_WORDS]
            for word in own:
                listed = words.get(word)
                if listed is None:
                    if len(words) >= MAX_VOCABULARY:  # a map made to fill the memory
                        continue
                    listed = words[word] = []
                listed.append(i)
        self.words = sorted(words)
        self.postings = [array("I", words.pop(w)) for w in self.words]
        # Every name, sorted: those beginning with what is typed sit next to each other.
        names = sorted((v, i) for i, variants in enumerate(self.variants) for v in variants)
        self.beginnings = [v for v, _ in names]
        self.beginning_ids = array("I", (i for _, i in names))
        del names
        self.listed = array("Q", [0])  # running total of the postings: what a prefix costs
        for posting in self.postings:
            self.listed.append(self.listed[-1] + len(posting))
        # What comes first when nothing else decides: countries, towns by size, streets, shops.
        self.order = array("I", bytes(4 * len(rows)))
        for position, i in enumerate(sorted(range(len(rows)), key=self._static_key)):
            self.order[i] = position
        self.by_kind: dict[str, array] = {}
        for i, (t, kind) in enumerate(zip(self.types, self.kinds)):
            if t == POINT:
                same = self.by_kind.setdefault(kind, array("I"))
                if len(same) < MAX_KIND:
                    same.append(i)

    def _static_key(self, i: int) -> tuple:
        place = self.types[i] == PLACE
        order = {"country": 0, "region": 1, "locality": 2}.get(self.kinds[i], 3) if place else 0
        return (self.types[i], order, -self.population.get(i, 0), self.variants[i][0])

    def best(self, ids, limit: int = CANDIDATES) -> list[int]:
        """At most `limit` entries, the best by the static order. Two letters can match tens of
        thousands of names (measured: 65 ms per search on a big city, 3 ms with this cap)."""
        if len(ids) <= limit:
            return list(ids)
        return heapq.nsmallest(limit, ids, key=self.order.__getitem__)

    def __len__(self) -> int:
        return len(self.names)

    def _range(self, prefix: str) -> range:
        """The words that start with prefix: they sit next to each other once sorted."""
        first = bisect_left(self.words, prefix)
        return range(first, bisect_left(self.words, prefix + "\U0010ffff", first))

    def _count(self, prefix: str) -> int:
        words = self._range(prefix)
        return self.listed[words.stop] - self.listed[words.start]

    def _with_prefix(self, prefix: str) -> set[int]:
        found: set[int] = set()
        for k in self._range(prefix):
            found.update(self.postings[k])
        return found

    def _starts(self, i: int, prefix: str) -> bool:
        words = (w for v in self.variants[i] for w in v.split())
        return any(w.startswith(prefix) or SHORT_FORMS.get(w, "").startswith(prefix) for w in words)

    def matching(self, words: list[str]) -> set[int]:
        """Entries where each word starts one of the words of a name, in any order. A word on
        more than COMMON names ("via", "v") would cost a set that large: it is left out, and
        the names beginning with the whole text (see starting) stand in for it."""
        words = sorted(set(words), key=self._count)[:MAX_WORDS]  # the rarest first
        words = [word for word in words if self._count(word) <= COMMON]
        found: set[int] | None = None
        for word in words:
            if found is None:
                found = self._with_prefix(word)
            elif len(found) * 32 < self._count(word):  # few left: look at them one by one
                found = {i for i in found if self._starts(i, word)}
            else:
                found &= self._with_prefix(word)
            if not found:
                break
        return found or set()

    def starting(self, text: str) -> list[int]:
        """Entries with a name that begins with the text: what someone typing is looking for."""
        first = bisect_left(self.beginnings, text)
        last = bisect_left(self.beginnings, text + "\U0010ffff", first)
        return list(self.beginning_ids[first : min(last, first + CANDIDATES)])

    def of_kinds(self, kinds: set[str]) -> list[int]:
        return [i for kind in kinds for i in self.by_kind.get(kind, ())]

    def distance(self, i: int, near: tuple[float, float] | None) -> float:
        return _km(near[0], near[1], self.lons[i], self.lats[i]) if near else 0.0

    def rank(self, i: int, text: str, near) -> tuple:
        variants = self.variants[i]
        quality = 0 if text in variants else 1 if any(v.startswith(text) for v in variants) else 2
        order = self.types[i] * 10
        if self.types[i] == PLACE:  # countries, regions, towns by size, then neighbourhoods
            order = {"country": 0, "region": 1, "locality": 2}.get(self.kinds[i], 3)
        return (quality, order, self.distance(i, near), -self.population.get(i, 0), variants[0])

    def result(self, i: int, lang: str, near) -> dict:
        local = self.names[i]
        name = self.translations.get(i, {}).get(lang, local)
        out = {
            "name": name,
            "type": TYPES[self.types[i]],
            "kind": self.kinds[i],
            "lon": round(self.lons[i], 6),
            "lat": round(self.lats[i], 6),
            "map": self.map,
        }
        if name != local:
            out["local"] = local
        if self.details[i]:
            out["detail"] = self.details[i]
        if self.context[i]:
            out["near"] = self.context[i]
        if i in self.boxes:
            out["bbox"] = [round(v, 6) for v in self.boxes[i]]
        if near:
            out["meters"] = round(self.distance(i, near) * 1000)
        return out


def _same(a: dict, b: dict) -> bool:
    """One thing under one name is shown once: a town in two maps (the world, and the area
    in detail), a street and its pedestrian area, a neighbourhood and its label point. Two
    shops of the same chain stay two."""
    if normalize(a.get("local", a["name"])) != normalize(b.get("local", b["name"])):
        return False
    if "place" in (a["type"], b["type"]):
        return _km(a["lon"], a["lat"], b["lon"], b["lat"]) < 3
    street = a if "bbox" in a else b if "bbox" in b else None
    if street is not None:  # a long street: anything of that name along it is the street
        other = b if street is a else a
        return _touch(street["bbox"], [other["lon"], other["lat"], other["lon"], other["lat"]])
    return _km(a["lon"], a["lat"], b["lon"], b["lat"]) < 0.05


def _load(path: Path, stamp: list[int]) -> dict | None:
    with contextlib.suppress(OSError, ValueError):
        content = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(content, dict) and content.get("format") == FORMAT:
            return content if content.get("source") == stamp else None
    return None


def _tries(path: Path, stamp: list[int]) -> int:
    """How many times reading this version of the map was started and never finished."""
    content = _load(path, stamp)
    tries = content.get("tries") if content else 0
    return tries if isinstance(tries, int) and not isinstance(tries, bool) else 0


def _save(path: Path, content: dict) -> None:
    """Only a convenience for the next start: if it can't be written, nothing is lost."""
    with contextlib.suppress(OSError):
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_name("." + path.name + ".partial")
        partial.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
        os.replace(partial, path)


class Places:
    """What can be searched in the maps folder, kept up to date in the background."""

    def __init__(self, maps: Path, cache: Path | None = None):
        self.maps = maps
        self.cache = cache
        self._indexes: dict[str, MapIndex] = {}
        self._stamps: dict[str, list[int]] = {}  # size and time of the files indexed
        self._failed: dict[str, list[int]] = {}
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._checked = -CHECK_EVERY

    def _scan(self) -> dict[str, list[int]]:
        found = {}
        with contextlib.suppress(OSError):
            for f in self.maps.glob("*.pmtiles"):
                if MAP_NAME.fullmatch(f.name) and f.is_file():
                    st = f.stat()
                    found[f.stem] = [st.st_size, st.st_mtime_ns]
        return found

    def _todo(self, current: dict[str, list[int]]) -> dict[str, list[int]]:
        return {
            name: stamp
            for name, stamp in current.items()
            if self._stamps.get(name) != stamp and self._failed.get(name) != stamp
        }

    def refresh(self, *, now: bool = False) -> None:
        """Notices new, changed or removed maps; reading them happens in a thread."""
        if not now and time.monotonic() - self._checked < CHECK_EVERY:
            return
        self._checked = time.monotonic()
        current = self._scan()
        with self._lock:
            for name in [n for n in self._indexes if n not in current]:
                del self._indexes[name]
                del self._stamps[name]
            todo = self._todo(current)
            if todo and not (self._worker and self._worker.is_alive()):
                self._worker = threading.Thread(target=self._read, args=(todo,), daemon=True)
                self._worker.start()

    def _read(self, todo: dict[str, list[int]]) -> None:
        for name, stamp in sorted(todo.items()):
            saved = self.cache / f"{name}.json" if self.cache else None
            # Written before the work and removed after: if reading the map or building its
            # index kills the Campanile (out of memory, a power cut), the next start knows.
            busy = self.cache / f"{name}.reading" if self.cache else None
            content = _load(saved, stamp) if saved else None
            try:
                if content is not None and "failed" in content:
                    raise MapError(content["failed"])  # already tried: not again at every start
                tries = _tries(busy, stamp) if busy else 0
                if tries >= TRIES:
                    raise MapError(f"reading it was cut short {tries} times")
                if busy:
                    _save(busy, {"format": FORMAT, "source": stamp, "tries": tries + 1})
                fresh = content is None
                if fresh:
                    content = read_map(self.maps / f"{name}.pmtiles")
                    content["source"] = stamp
                index = MapIndex(name, content)
                if fresh and saved:  # only once the index is built: a saved map is a safe one
                    _save(saved, content)
            except Exception as e:  # any damage: that map is not searchable, nothing else
                print(f"[campanile] map {name} can't be searched: {e!r}", flush=True)
                if saved and not isinstance(e, OSError):  # the file is at fault, not the disk
                    _save(saved, {"format": FORMAT, "source": stamp, "failed": str(e)[:200]})
                index = None
            if busy:
                with contextlib.suppress(OSError):
                    busy.unlink()
            with self._lock:
                others = sum(len(i) for n, i in self._indexes.items() if n != name)
                if index is not None and others + len(index) > TOTAL_NAMES:
                    print(f"[campanile] map {name} can't be searched: too many names", flush=True)
                    index = None  # many maps from a share: memory first
                if index is None:
                    self._failed[name] = stamp
                    continue
                self._indexes[name] = index
                self._stamps[name] = stamp
        self._checked = -CHECK_EVERY  # a map may have changed meanwhile: look again soon

    def wait(self, timeout: float | None = None) -> None:
        worker = self._worker
        if worker:
            worker.join(timeout)

    @property
    def ready(self) -> bool:
        current = self._scan()
        with self._lock:
            busy = self._worker is not None and self._worker.is_alive()
            return not busy and not self._todo(current)

    def search(self, query: str, near: tuple[float, float] | None, lang: str) -> dict:
        self.refresh()
        with self._lock:  # the most detailed maps first: their copy of a town wins
            indexes = sorted(self._indexes.values(), key=lambda index: -index.max_zoom)
        text = normalize(query)
        kinds = SYNONYMS.get(text)
        found: list[tuple[tuple, MapIndex, int]] = []
        for index in indexes:
            if kinds:  # a kind of place: only that kind, nearest first. A village called
                # "Farmacia" is no pharmacy, and in an emergency must never look like one.
                found += [
                    ((-1, 0, index.distance(i, near)), index, i) for i in index.of_kinds(kinds)
                ]
                continue
            matches = {*index.best(index.matching(text.split())), *index.starting(text)}
            found += [(index.rank(i, text, near), index, i) for i in matches]
        found.sort(key=lambda item: item[0])
        results: list[dict] = []
        for _, index, i in found:
            result = index.result(i, lang, near)
            if not any(_same(result, other) for other in results):
                results.append(result)
                if len(results) == RESULTS:
                    break
        # "missing": the maps have no place of that kind, and the page says so.
        return {"results": results, "ready": self.ready, "missing": bool(kinds) and not results}
