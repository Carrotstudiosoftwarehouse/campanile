# DEVELOPED BY CARROTSTUDIO software house
"""A route from here to there, on foot or by car, without internet.

The streets come from the map files the phones already see: the roads of the most detailed
tiles, with their junctions, one-way streets, footpaths and steps. A street the admin marks
as blocked is left out of every route. A map may come from another Campanile, so, as for the
search, building and using its streets costs a bounded amount whatever the file says.
"""

from __future__ import annotations

import contextlib
import heapq
import json
import math
import os
import re
import struct
import threading
import time
from array import array
from pathlib import Path

import places

MAP_NAME = re.compile(r"[A-Za-z0-9_-]+\.pmtiles")
FORMAT = 1
CHECK_EVERY = 10.0  # seconds between looks at the maps folder

# Car speeds by kind of road, km/h, with traffic lights and crossings: the time is a guide.
CAR = {
    "motorway": 100, "motorway_link": 50, "trunk": 70, "trunk_link": 40,
    "primary": 40, "primary_link": 30, "secondary": 35, "secondary_link": 30,
    "tertiary": 30, "tertiary_link": 25, "unclassified": 25, "road": 20,
    "residential": 20, "living_street": 10, "service": 10, "parking_aisle": 10,
    "alley": 10, "driveway": 10,
}  # fmt: skip
NO_FOOT = {"motorway", "motorway_link", "trunk", "trunk_link"}
FOOT = {
    "pedestrian", "footway", "cycleway", "steps", "crossing", "sidewalk", "path", "track",
    "corridor", "pier", "bridleway", "platform", "living_street",
}  # fmt: skip
WALK = 1.25  # metres a second, a steady walk; steps take twice as long
FASTEST = {"car": CAR["motorway"] / 3.6, "foot": WALK}  # for the estimate that guides the search

SNAP = 300  # metres: farther than this from any street, there is no route to give
ROUTE_MOST = 5.0  # seconds one route may take: longer, the phone is asked for nearer points
CLOSE = 25  # metres: how near a street must be to the point the admin touched
# A blocked place, not a single line: a bridge is two carriageways, sidewalks, a cycle lane,
# each its own line on the map. Everything within this distance of the point is blocked.
BLOCK = 20
# A bridge or a tunnel closes whole: the lines of the same structure running alongside within
# this distance (measured on Turin: the other tube of an underpass can be 22 m away).
STRUCTURE = 50
PARALLEL = 35  # degrees: how far apart the headings of two lines of one structure can be
NEARBY = 60  # metres: lines alongside, left open, that the admin is told about
RING = 600  # metres around, at most: a roundabout cut by tile borders, not a ring road
CELL = 0.002  # degrees, about 200 m: streets are found through the cells they cross
JOIN = 3  # map units (about a metre): the same street, cut by a tile border, joins again
TOUCH = 2  # map units: a street that ends this close to another one meets it there
SHORT = 25  # metres: a stretch shorter than this is no step of its own in the directions
# The most one map may cost, whatever the file says: a city and its surroundings fit.
MAX_TILES = 4_000  # of the most detailed zoom (an area framed on the setup page: 2,900)
MAX_POINTS = 4_000_000  # points of streets
TRIES = 3  # builds cut short (a crash, a power cut) before a map is given up
EXTENT = 4096  # tile units: what Protomaps and most map makers write; any other, no routes
# Finding where streets meet costs work: segments in cells, pairs compared. A file made to
# stack thousands of lines on one spot must cost no more than a real city. Measured on the
# Turin metropolitan area (440 tiles): at most 34,080 cells and 63,833 pairs in one tile,
# 3.2 and 1.9 million in all.
BUDGET = {"cells": 40_000_000, "pairs": 25_000_000}  # one map
TILE_BUDGET = {"cells": 400_000, "pairs": 1_000_000}  # one tile: what it holds in memory


class RouteError(Exception):
    """Ends a route; the key becomes a message on the page."""

    def __init__(self, key: str):
        super().__init__(key)
        self.key = key


# -- reading the streets ---------------------------------------------------------------------


def _ways(props) -> tuple[float, int, float] | None:
    """(car seconds a metre, direction for cars, foot seconds a metre); 0 where not allowed."""
    kind, detail = props.get("kind"), props.get("kind_detail")
    if kind in ("rail", "ferry") or props.get("access") in ("no", "private"):
        return None
    car = CAR.get(detail, 0) if kind in ("highway", "major_road", "minor_road", "other") else 0
    foot = 0.0
    if detail not in NO_FOOT and (car or detail in FOOT or kind == "path"):
        foot = (2 if detail == "steps" else 1) / WALK
    if props.get("is_tunnel") and kind == "major_road" and detail not in FOOT:
        foot = 0.0  # an underpass of a main road is no place to walk
    if not car and not foot:
        return None
    oneway = props.get("oneway")
    direction = 1 if oneway == "yes" else -1 if oneway == "-1" else 0
    return (3.6 / car if car else 0.0), direction, foot


def _road_lines(tile: bytes):
    """(properties, extent, lines in tile units) of the roads layer."""
    for number, layer in places._fields(tile):
        if number != 3:
            continue
        name, keys, values, features, extent = None, [], [], [], 4096
        for field, value in places._fields(layer):
            if field == 1:
                name = places._text(value)
                if name != "roads":
                    break
            elif field == 2:
                features.append(value)
            elif field == 3:
                keys.append(places._text(value))
            elif field == 4:
                values.append(_value(value))
            elif field == 5:
                extent = value or 4096
        if name != "roads":
            continue
        for feature in features:
            tags, geometry, shape = [], [], 0
            for field, value in places._fields(feature):
                if field == 2:
                    tags = places._packed(value)
                elif field == 3:
                    shape = value
                elif field == 4:
                    geometry = places._packed(value)
            if shape != 2:  # lines only
                continue
            props = {
                keys[tags[k]]: values[tags[k + 1]]
                for k in range(0, len(tags) - 1, 2)
                if tags[k] < len(keys) and tags[k + 1] < len(values)
            }
            yield props, extent, _lines(geometry)


def _value(buf):
    """A property's value; unlike the search, routes need the yes/no ones (a bridge)."""
    for number, value in places._fields(buf):
        if number == 7:
            return bool(value)
    return places._value(buf)


def _lines(geometry) -> list[list[tuple[int, int]]]:
    """The separate lines of a geometry: each MoveTo starts a new one."""
    lines: list[list[tuple[int, int]]] = []
    x = y = i = 0
    while i < len(geometry):
        command, count = geometry[i] & 7, geometry[i] >> 3
        i += 1
        if command == 7:
            continue
        if command not in (1, 2) or i + 2 * count > len(geometry):
            raise places.MapError("bad geometry")
        for _ in range(count):
            dx, dy = geometry[i], geometry[i + 1]
            x += (dx >> 1) ^ -(dx & 1)
            y += (dy >> 1) ^ -(dy & 1)
            i += 2
            if command == 1:
                lines.append([])
            if lines:
                lines[-1].append((x, y))
    return [line for line in lines if len(line) > 1]


def _clip(points, box):
    """The pieces of a line inside the box, cut exactly on its edges. Each point says whether
    it lies on an edge: there the same street goes on in the next tile."""
    x0, y0, x1, y1 = box

    def exact(p):  # a point computed on an edge lies exactly on it
        x, y = p
        x = x0 if abs(x - x0) < 1e-6 else x1 if abs(x - x1) < 1e-6 else x
        y = y0 if abs(y - y0) < 1e-6 else y1 if abs(y - y1) < 1e-6 else y
        return x, y

    def on_edge(p):
        return p[0] in (x0, x1) or p[1] in (y0, y1)

    pieces, current = [], []
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        dx, dy = bx - ax, by - ay
        t0, t1 = 0.0, 1.0
        for p, q in ((-dx, ax - x0), (dx, x1 - ax), (-dy, ay - y0), (dy, y1 - ay)):
            if p == 0:
                if q < 0:
                    t0, t1 = 1.0, 0.0
            elif p < 0:
                t0 = max(t0, q / p)
            else:
                t1 = min(t1, q / p)
        if t0 > t1:
            if current:
                pieces.append(current)
                current = []
            continue
        start = exact((ax + t0 * dx, ay + t0 * dy)) if t0 > 0 else (ax, ay)
        end = exact((ax + t1 * dx, ay + t1 * dy)) if t1 < 1 else (bx, by)
        if t0 > 0 and current:  # it left the box and came back
            pieces.append(current)
            current = []
        if not current:
            current = [(start, on_edge(start))]
        current.append((end, on_edge(end)))
        if t1 < 1:
            pieces.append(current)
            current = []
    if current:
        pieces.append(current)
    # A vertex right on an edge leaves a piece of no length: a loop on one point, never a way.
    return [piece for piece in pieces if any(p[0] != piece[0][0] for p in piece[1:])]


def _meet(pieces: list, work) -> None:
    """Streets meet where they cross or where one ends on the other, even without a point in
    common: maps are simplified, and that point is often dropped (measured on Turin: 7,053
    crossings and 5,523 of 7,641 dead ends had lost it). Bridges and tunnels meet nothing."""
    _cross(pieces, work)
    grid: dict[tuple[int, int], list] = {}  # cells of 64 units: the segments crossing them
    for i, (piece, *rest) in enumerate(pieces):
        if rest[-1]:  # a bridge meets the streets only where it shares their point
            continue
        for k in range(len(piece) - 1):
            (ax, ay), (bx, by) = piece[k][0], piece[k + 1][0]
            xs = range(int(min(ax, bx) - TOUCH) >> 6, (int(max(ax, bx) + TOUCH) >> 6) + 1)
            ys = range(int(min(ay, by) - TOUCH) >> 6, (int(max(ay, by) + TOUCH) >> 6) + 1)
            work.spend("cells", len(xs) * len(ys))
            for cx in xs:
                for cy in ys:
                    grid.setdefault((cx, cy), []).append((i, k))
    added: dict[int, list] = {}  # piece: [(segment, along, point)]
    for i, (piece, *rest) in enumerate(pieces):
        if rest[-1]:
            continue
        for end, edge in (piece[0], piece[-1]):
            # Even an end two side streets share may lie on a main road that lost the point.
            if edge:
                continue
            best, found = TOUCH, None
            near = grid.get((int(end[0]) >> 6, int(end[1]) >> 6), ())
            work.spend("pairs", len(near))
            for j, k in near:
                if j == i:
                    continue
                (ax, ay), (bx, by) = pieces[j][0][k][0], pieces[j][0][k + 1][0]
                if end in ((ax, ay), (bx, by)):  # that street already has the point
                    continue
                dx, dy = bx - ax, by - ay
                span = dx * dx + dy * dy
                t = 0.0 if span == 0 else ((end[0] - ax) * dx + (end[1] - ay) * dy) / span
                t = min(1.0, max(0.0, t))
                gap = math.hypot(ax + t * dx - end[0], ay + t * dy - end[1])
                if gap <= best:
                    best, found = gap, (j, k, t)
            if found is not None:
                j, k, t = found
                added.setdefault(j, []).append((k, t, end))
    _insert(pieces, added)


def _cross(pieces: list, work) -> None:
    """Where two streets on the ground cross, both get the crossing point."""
    grid: dict[tuple[int, int], list] = {}
    for i, (piece, *rest) in enumerate(pieces):
        if rest[-1]:  # a bridge or a tunnel
            continue
        for k in range(len(piece) - 1):
            (ax, ay), (bx, by) = piece[k][0], piece[k + 1][0]
            xs = range(int(min(ax, bx)) >> 6, (int(max(ax, bx)) >> 6) + 1)
            ys = range(int(min(ay, by)) >> 6, (int(max(ay, by)) >> 6) + 1)
            work.spend("cells", len(xs) * len(ys))
            for cx in xs:
                for cy in ys:
                    grid.setdefault((cx, cy), []).append((i, k))
    added: dict[int, list] = {}
    for cell, listed in grid.items():
        work.spend("pairs", len(listed) * (len(listed) - 1) // 2)
        for n, (i, k) in enumerate(listed):
            (ax, ay), (bx, by) = pieces[i][0][k][0], pieces[i][0][k + 1][0]
            for j, m in listed[n + 1 :]:
                if j == i:
                    continue
                (cx, cy), (dx, dy) = pieces[j][0][m][0], pieces[j][0][m + 1][0]
                rx, ry, sx, sy = bx - ax, by - ay, dx - cx, dy - cy
                den = rx * sy - ry * sx
                if den == 0:
                    continue
                t = ((cx - ax) * sy - (cy - ay) * sx) / den
                u = ((cx - ax) * ry - (cy - ay) * rx) / den
                if 0 < t < 1 and 0 < u < 1:  # strictly inside both: not already a shared point
                    point = (ax + t * rx, ay + t * ry)
                    if (int(point[0]) >> 6, int(point[1]) >> 6) != cell:
                        continue  # two segments share several cells: counted in the point's own
                    added.setdefault(i, []).append((k, t, point))
                    added.setdefault(j, []).append((m, u, point))
    _insert(pieces, added)


def _insert(pieces: list, added: dict) -> None:
    """Adds points inside segments: {piece: [(segment, along, point)]}."""
    for j, joins in added.items():
        piece = pieces[j][0]
        joins.sort()
        out, at = [], 0
        for k in range(len(piece) - 1):
            out.append(piece[k])
            while at < len(joins) and joins[at][0] == k:
                point = joins[at][2]
                if point != out[-1][0] and point != piece[k + 1][0]:
                    out.append((point, False))
                at += 1
        out.append(piece[-1])
        pieces[j] = (out, *pieces[j][1:])


def _root(parent: array, k: int) -> int:
    while parent[k] != k:
        parent[k] = parent[parent[k]]
        k = parent[k]
    return k


class Network:
    """The streets of one map: nodes (junctions, ends) joined by chains (stretches of one
    street), each with its length, its cost by car and on foot, and its points."""

    def __init__(self, name: str, path: Path):
        self.name = name
        self.names: list[str] = [""]  # street names; 0: none
        named: dict[str, int] = {"": 0}
        self.ends = array("I")  # two nodes a chain: where it starts, where it ends
        self.length = array("f")  # metres
        self.car = array("f")  # seconds; 0 where cars can't go
        self.direction = array("b")  # for cars: 0 both ways, 1 as drawn, -1 against
        self.foot = array("f")
        self.street = array("I")
        self.structure = array("b")  # 0 on the ground, 1 on a bridge, 2 in a tunnel
        self._ring = array("b")  # while building: 1 a closed ring, 2 an arc that may be one
        self.first = array("I", [0])  # where each chain's points start in lons and lats
        self.lons, self.lats = array("d"), array("d")
        self.node_lon, self.node_lat = array("d"), array("d")
        border: dict[tuple, list] = {}  # a border between tiles: [(position along it, node)]
        self.work = places._Work(BUDGET, TILE_BUDGET)
        self._read = 0  # points read from the tiles, before any is kept
        with open(path, "rb") as f:
            archive = places.PMTiles(f)
            top = archive.max_zoom
            if top < places.DETAIL_ZOOM or archive.count(top) > MAX_TILES:
                raise places.MapError("no streets in detail")
            self.made = _made(f, archive)  # a route is only as current as its map
            for (_, x, y), tile in archive.tiles(top, top):
                self._tile(tile, x, y, top, named, border)
        if not self.length:
            raise places.MapError("no streets in detail")
        self._stitch(border)
        self._rings()
        del self._ring
        self._index()
        # Where its streets really are, and a point can still reach them: a header can claim
        # the whole world for one street.
        west, south, east, north = min(self.lons), min(self.lats), max(self.lons), max(self.lats)
        pad = SNAP / 111_320  # degrees of latitude; of longitude, wider away from the equator
        wide = pad / max(0.01, math.cos(math.radians(max(abs(south), abs(north)))))
        self.extent = (west - wide, south - pad, east + wide, north + pad)

    def _tile(self, tile: bytes, x: int, y: int, zoom: int, named: dict, border: dict) -> None:
        """The streets of one tile. Inside a tile, streets meet where they share a point."""
        pieces = []
        for props, extent, lines in _road_lines(tile):
            if extent != EXTENT:  # the distances below are in units of this size
                raise places.MapError("tiles of an unusual size")
            self._read += sum(len(line) for line in lines)
            if self._read > MAX_POINTS:
                raise places.MapError("too many streets")
            ways = _ways(props)
            if ways is None:
                continue
            raw = props.get("name")
            name = raw[:120] if isinstance(raw, str) else ""
            if name not in named:
                named[name] = len(self.names)
                self.names.append(name)
            box = (x * extent, y * extent, (x + 1) * extent, (y + 1) * extent)
            car, direction, foot = ways
            level = props.get("level") if isinstance(props.get("level"), int) else 0
            structure = 1 if props.get("is_bridge") or level > 0 else 0
            structure = 2 if props.get("is_tunnel") or level < 0 else structure
            # On a bridge or in a tunnel, a street crosses the others without meeting them; a
            # motorway meets other roads only where the map says so, at its slip roads.
            apart = bool(structure) or props.get("kind_detail") in ("motorway", "trunk")
            for line in lines:
                points = [(x * extent + px, y * extent + py) for px, py in line]
                way, ring = direction, 0
                if way == 0 and car:
                    if len(points) > 3 and points[0] == points[-1]:
                        way, ring = 1, 1  # a roundabout, drawn in the direction of traffic
                    else:
                        ring = 2  # maybe an arc of one the tile's edge cut: see _rings
                for piece in _clip(points, box):
                    ways = (car, way, foot, named[name], structure, ring)
                    pieces.append((piece, ways, extent, box, apart))
        self.work.next_tile()
        _meet(pieces, self.work)
        seen: dict[tuple, int] = {}  # points inside the tile: how many pieces pass there
        for piece, *_ in pieces:
            for point, edge in piece:
                if not edge:
                    seen[point] = seen.get(point, 0) + 1
        nodes: dict[tuple, int] = {}
        for piece, ways, extent, box, _ in pieces:
            world = extent << zoom
            last = 0
            for k in range(1, len(piece)):
                point, edge = piece[k]
                if k == len(piece) - 1 or edge or seen.get(point, 0) > 1:
                    self._chain(piece[last : k + 1], ways, world, box, nodes, border)
                    last = k
        if len(self.lons) > MAX_POINTS:
            raise places.MapError("too many streets")

    def _node(self, point, edge: bool, world: int, box, nodes: dict, border: dict) -> int:
        node = None if edge else nodes.get(point)
        if node is None:
            node = len(self.node_lon)
            lon, lat = _lonlat(point, world)
            self.node_lon.append(lon)
            self.node_lat.append(lat)
            if edge:  # joined to the other side of the border in _stitch
                gx, gy = point
                if gx in (box[0], box[2]):
                    border.setdefault(("x", gx), []).append((gy, node))
                else:
                    border.setdefault(("y", gy), []).append((gx, node))
            else:
                nodes[point] = node
        return node

    def _chain(self, run, ways, world: int, box, nodes: dict, border: dict) -> None:
        car, direction, foot, street, structure, ring = ways
        start = self._node(run[0][0], run[0][1], world, box, nodes, border)
        end = self._node(run[-1][0], run[-1][1], world, box, nodes, border)
        metres, last = 0.0, None
        for point, _ in run:
            lon, lat = _lonlat(point, world)
            if last is not None:
                metres += places._km(last[0], last[1], lon, lat) * 1000
            self.lons.append(lon)
            self.lats.append(lat)
            last = (lon, lat)
        self.first.append(len(self.lons))
        self.ends.extend((start, end))
        self.length.append(metres)
        self.car.append(metres * car)
        self.direction.append(direction)
        self.foot.append(metres * foot)
        self.street.append(street)
        self.structure.append(structure)
        self._ring.append(ring)

    def _stitch(self, border: dict) -> None:
        """Joins the two sides of every tile border where a street crosses it."""
        parent = array("I", range(len(self.node_lon)))
        for crossings in border.values():
            crossings.sort()
            for (a, first), (b, second) in zip(crossings, crossings[1:]):
                if b - a <= JOIN:
                    parent[_root(parent, second)] = _root(parent, first)
        roots = [_root(parent, k) for k in range(len(parent))]
        number: dict[int, int] = {}
        for root in roots:
            number.setdefault(root, len(number))
        self.ends = array("I", (number[roots[node]] for node in self.ends))
        lons, lats = array("d", bytes(8 * len(number))), array("d", bytes(8 * len(number)))
        for node, root in enumerate(roots):
            lons[number[root]], lats[number[root]] = self.node_lon[node], self.node_lat[node]
        self.node_lon, self.node_lat = lons, lats

    def _rings(self) -> None:
        """A roundabout cut by tile borders arrives as arcs, each one two-way on its own map
        line. Joined again, they close a small ring of one street, every arc drawn the same
        way round: then they are one-way, as a roundabout closed inside one tile is."""
        at: dict[tuple[int, int], list[int]] = {}  # (street, node): its candidate chains
        candidates = [
            c
            for c in range(len(self.length))
            if self._ring[c] and self.ends[2 * c] != self.ends[2 * c + 1]
        ]
        for chain in candidates:
            for node in (self.ends[2 * chain], self.ends[2 * chain + 1]):
                at.setdefault((self.street[chain], node), []).append(chain)
        seen: set[int] = set()
        for first in candidates:
            if first in seen:
                continue
            street, part, stack = self.street[first], [], [first]
            seen.add(first)
            while stack:
                chain = stack.pop()
                part.append(chain)
                for node in (self.ends[2 * chain], self.ends[2 * chain + 1]):
                    for other in at[(street, node)]:
                        if other not in seen:
                            seen.add(other)
                            stack.append(other)
            starts = [self.ends[2 * c] for c in part]
            ends = [self.ends[2 * c + 1] for c in part]
            if (
                any(self._ring[c] == 2 for c in part)
                and sorted(starts) == sorted(ends)  # one way round: each node left once
                and len(set(starts)) == len(part)  # and entered once
                and all(len(at[(street, n)]) == 2 for n in starts)  # nothing else of it there
                and sum(self.length[c] for c in part) <= RING
            ):
                for chain in part:
                    self.direction[chain] = 1

    def _index(self) -> None:
        """Who leaves from each node, and which chains cross each cell (to find a street)."""
        count = len(self.node_lon)
        degree = array("I", bytes(4 * (count + 1)))
        for node in self.ends:
            degree[node + 1] += 1
        for k in range(count):
            degree[k + 1] += degree[k]
        self.out_start = degree
        self.out = array("i", bytes(4 * len(self.ends)))
        filled = array("I", degree[:-1])
        for chain in range(len(self.length)):
            start, end = self.ends[2 * chain], self.ends[2 * chain + 1]
            self.out[filled[start]] = chain + 1  # leaving from its start: along the chain
            filled[start] += 1
            self.out[filled[end]] = -(chain + 1)  # leaving from its end: against it
            filled[end] += 1
        # A route starts and ends only where one can go and come back: a courtyard, or a
        # one-way stretch a missing junction turned into a trap, is not such a place.
        self.reach = {mode: self._both_ways(mode) for mode in ("car", "foot")}
        self.cells: dict[tuple[int, int], array] = {}
        for chain in range(len(self.length)):
            for k in range(self.first[chain], self.first[chain + 1] - 1):
                a, b = (self.lons[k], self.lats[k]), (self.lons[k + 1], self.lats[k + 1])
                steps = int(max(abs(b[0] - a[0]), abs(b[1] - a[1])) / (CELL / 2)) + 1
                for s in range(steps + 1):  # along the segment, not only at its ends
                    lon = a[0] + (b[0] - a[0]) * s / steps
                    lat = a[1] + (b[1] - a[1]) * s / steps
                    listed = self.cells.setdefault((int(lon // CELL), int(lat // CELL)), array("I"))
                    if not listed or listed[-1] != chain:
                        listed.append(chain)

    def _both_ways(self, mode: str) -> array:
        """For each node, whether it belongs to the largest part where every node can reach
        every other (strongly connected, Kosaraju's way, without recursion)."""
        count = len(self.node_lon)

        def leaving(node, backwards):
            for k in range(self.out_start[node], self.out_start[node + 1]):
                signed = self.out[k]
                chain, forward = abs(signed) - 1, signed > 0
                if self.allowed(chain, forward != backwards, mode):
                    yield self.ends[2 * chain + (1 if forward else 0)]

        order, seen = [], array("b", bytes(count))
        for first in range(count):
            if seen[first]:
                continue
            seen[first] = 1
            stack = [(first, leaving(first, False))]
            while stack:
                node, ahead = stack[-1]
                for other in ahead:
                    if not seen[other]:
                        seen[other] = 1
                        stack.append((other, leaving(other, False)))
                        break
                else:
                    order.append(node)
                    stack.pop()
        part = array("i", [-1]) * count
        sizes = []
        for first in reversed(order):
            if part[first] >= 0:
                continue
            label, size, stack = len(sizes), 0, [first]
            part[first] = label
            while stack:
                node = stack.pop()
                size += 1
                for other in leaving(node, True):
                    if part[other] < 0:
                        part[other] = label
                        stack.append(other)
            sizes.append(size)
        largest = max(range(len(sizes)), key=sizes.__getitem__, default=-1)
        return array("b", (part[node] == largest for node in range(count)))

    # -- finding the way --------------------------------------------------------------------

    def cost(self, chain: int, mode: str) -> float:
        return self.car[chain] if mode == "car" else self.foot[chain]

    def allowed(self, chain: int, forward: bool, mode: str) -> bool:
        if mode == "foot":
            return self.foot[chain] > 0
        if self.car[chain] <= 0:
            return False
        direction = self.direction[chain]
        return direction == 0 or (direction == 1) == forward

    def snap(self, lon: float, lat: float, mode: str | None, closed=frozenset(), most=SNAP):
        """The nearest point on a street usable by mode: (chain, segment, fraction, metres
        from the chain's start, lon, lat), or None if every street is farther than most."""
        reach = int(most / 100) + 1  # cells are at least 150 m wide
        cx, cy = int(lon // CELL), int(lat // CELL)
        wide = math.cos(math.radians(lat))
        best, found = most / 1000, None
        seen = set()
        for gx in range(cx - reach, cx + reach + 1):
            for gy in range(cy - reach, cy + reach + 1):
                for chain in self.cells.get((gx, gy), ()):
                    if chain in seen or chain in closed:
                        continue
                    seen.add(chain)
                    if mode and not (
                        (self.allowed(chain, True, mode) or self.allowed(chain, False, mode))
                        and self.reach[mode][self.ends[2 * chain]]
                        and self.reach[mode][self.ends[2 * chain + 1]]
                    ):
                        continue
                    first = self.first[chain]
                    for k in range(first, self.first[chain + 1] - 1):
                        km, t, px, py = self._foot(k, lon, lat, wide)
                        if km < best:
                            best, found = km, (chain, k - first, t, px, py)
        if found is None:
            return None
        chain, segment, t, px, py = found
        metres = self._along(chain, segment) + t * self._segment(chain, segment)
        return chain, segment, t, metres, px, py

    def near(self, lon: float, lat: float, metres: float) -> set[int]:
        """Every chain passing within metres of the point, whoever may use it."""
        found = set()
        reach = int(metres / 100) + 1
        cx, cy = int(lon // CELL), int(lat // CELL)
        for gx in range(cx - reach, cx + reach + 1):
            for gy in range(cy - reach, cy + reach + 1):
                for chain in self.cells.get((gx, gy), ()):
                    if chain not in found and self._closest(chain, lon, lat)[0] <= metres:
                        found.add(chain)
        return found

    def place(self, lon: float, lat: float):
        """What one touch of the admin closes: (the point on the street touched, every chain
        closed, the lines alongside left open as {name: metres}), or None if no street is
        that close. The circle is drawn around the touch as well as around the street: a
        touch between the two carriageways of a bridge means both."""
        spot = self.snap(lon, lat, None, most=CLOSE)
        if spot is None:
            return None
        touched = spot[0]
        chains = self.near(lon, lat, BLOCK) | self.near(spot[4], spot[5], BLOCK)
        heading = self._heading(touched, spot[1])
        kind, street = self.structure[touched], self.street[touched]
        alongside: dict[str, int] = {}
        for chain in sorted(self.near(lon, lat, NEARBY) - chains):
            metres, segment = self._closest(chain, lon, lat)
            if abs((self._heading(chain, segment) - heading + 90) % 180 - 90) > PARALLEL:
                continue  # it crosses, or comes from elsewhere
            same_structure = kind and self.structure[chain] == kind
            if same_structure and metres <= STRUCTURE:
                chains.add(chain)  # the rest of the bridge: the other carriageway, the other tube
            elif same_structure or (street and self.street[chain] == street):
                name = self.names[self.street[chain]]
                alongside[name] = min(alongside.get(name, NEARBY), round(metres))
        return spot, chains, alongside

    def _closest(self, chain: int, lon: float, lat: float) -> tuple[float, int]:
        """How far the chain passes from the point, in metres, and on which of its segments."""
        wide = math.cos(math.radians(lat))
        best, segment = math.inf, 0
        for k in range(self.first[chain], self.first[chain + 1] - 1):
            km = self._foot(k, lon, lat, wide)[0]
            if km < best:
                best, segment = km, k - self.first[chain]
        return best * 1000, segment

    def _foot(self, k: int, lon: float, lat: float, wide: float):
        """The point of segment k nearest to lon, lat: (km away, how far along, lon, lat)."""
        ax, ay = self.lons[k] * wide, self.lats[k]
        bx, by = self.lons[k + 1] * wide, self.lats[k + 1]
        dx, dy = bx - ax, by - ay
        span = dx * dx + dy * dy
        t = 0.0 if span == 0 else ((lon * wide - ax) * dx + (lat - ay) * dy) / span
        t = min(1.0, max(0.0, t))
        px, py = (ax + t * dx) / wide, ay + t * dy
        return places._km(lon, lat, px, py), t, px, py

    def _heading(self, chain: int, segment: int) -> float:
        k = self.first[chain] + segment
        return _bearing((self.lons[k], self.lats[k]), (self.lons[k + 1], self.lats[k + 1]))

    def _segment(self, chain: int, segment: int) -> float:
        k = self.first[chain] + segment
        return places._km(self.lons[k], self.lats[k], self.lons[k + 1], self.lats[k + 1]) * 1000

    def _along(self, chain: int, segment: int) -> float:
        return sum(self._segment(chain, s) for s in range(segment))

    def route(self, start, end, mode: str, closed=frozenset()) -> dict:
        a = self.snap(*start, mode, closed)
        b = self.snap(*end, mode, closed)
        if a is None or b is None:
            raise RouteError("route_far")
        target = (b[4], b[5])

        def part(chain, metres, forward):
            length = self.length[chain] or 1.0
            share = (length - metres) / length if forward else metres / length
            return share * self.cost(chain, mode)

        best, best_end = math.inf, None
        if a[0] == b[0]:  # on the same street, between the same two junctions
            forward = b[3] >= a[3]
            if self.allowed(a[0], forward, mode):
                best = abs(b[3] - a[3]) / (self.length[a[0]] or 1.0) * self.cost(a[0], mode)
                best_end = ("same", forward)
        heap, score, came = [], {}, {}
        for forward in (True, False):
            if self.allowed(a[0], forward, mode):
                node = self.ends[2 * a[0] + (1 if forward else 0)]
                g = part(a[0], a[3], forward)
                if g < score.get(node, math.inf):
                    score[node], came[node] = g, (None, a[0] + 1 if forward else -(a[0] + 1))
                    heapq.heappush(heap, (g + self._guess(node, target, mode), g, node))
        b_start, b_end = self.ends[2 * b[0]], self.ends[2 * b[0] + 1]
        began, steps = time.monotonic(), 0
        while heap:
            if steps & 255 == 0 and time.monotonic() - began > ROUTE_MOST:
                raise RouteError("route_long")
            steps += 1
            f, g, node = heapq.heappop(heap)
            if f >= best:
                break
            if g > score.get(node, math.inf):
                continue
            for entry, forward in ((b_start, True), (b_end, False)):
                if node == entry and self.allowed(b[0], forward, mode):
                    cost = g + part(b[0], b[3], not forward)
                    if cost < best:
                        best, best_end = cost, (node, forward)
            for k in range(self.out_start[node], self.out_start[node + 1]):
                signed = self.out[k]
                chain, forward = abs(signed) - 1, signed > 0
                if chain in closed or not self.allowed(chain, forward, mode):
                    continue
                other = self.ends[2 * chain + (1 if forward else 0)]
                cost = g + self.cost(chain, mode)
                if cost < score.get(other, math.inf):
                    score[other], came[other] = cost, (node, signed)
                    heapq.heappush(heap, (cost + self._guess(other, target, mode), cost, other))
        if best_end is None:
            raise RouteError("route_none")
        found = self._describe(a, b, best_end, came, best, mode)
        # How far the start and the end were moved to reach a street: the page says so.
        found["moved"] = [
            round(places._km(*start, a[4], a[5]) * 1000),
            round(places._km(*end, b[4], b[5]) * 1000),
        ]
        return found

    def _guess(self, node: int, target, mode: str) -> float:
        km = places._km(self.node_lon[node], self.node_lat[node], target[0], target[1])
        return km * 1000 / FASTEST[mode]

    def _points(self, chain: int, forward: bool) -> list[tuple[float, float]]:
        span = range(self.first[chain], self.first[chain + 1])
        points = [(self.lons[k], self.lats[k]) for k in span]
        return points if forward else points[::-1]

    def _describe(self, a, b, best_end, came, seconds: float, mode: str) -> dict:
        """The line to draw, and the turns, street by street."""
        legs: list[tuple[int, list]] = []  # (street, points)

        def named(chain, whole):  # a nameless stretch: the name of the street alongside
            return self.street[chain] or self._named(_middle(whole))

        if best_end[0] == "same":
            forward = best_end[1]
            run = self._points(a[0], forward)
            sa, sb = (a[1], b[1]) if forward else (_flip(self, a), _flip(self, b))
            points = [(a[4], a[5]), *run[sa + 1 : sb + 1], (b[4], b[5])]
            legs.append((named(a[0], points), points))
        else:
            entry, forward_in = best_end
            chains = []
            node = entry
            while True:
                prev, signed = came[node]
                chains.append(signed)
                if prev is None:
                    break
                node = prev
            chains.reverse()
            first = chains[0]
            chain, forward = abs(first) - 1, first > 0
            run = self._points(chain, forward)
            cut = a[1] + 1 if forward else _flip(self, a) + 1
            points = [(a[4], a[5]), *run[cut:]]
            legs.append((named(chain, points), points))
            for signed in chains[1:]:
                chain, forward = abs(signed) - 1, signed > 0
                whole = self._points(chain, forward)
                legs.append((named(chain, whole), whole[1:]))
            run = self._points(b[0], forward_in)
            cut = b[1] + 1 if forward_in else _flip(self, b) + 1
            legs.append((named(b[0], [*run[:cut], (b[4], b[5])]), [*run[1:cut], (b[4], b[5])]))
        line: list[tuple[float, float]] = []
        for _, points in legs:
            for p in points:
                if not line or line[-1] != p:
                    line.append(p)
        return {
            "map": self.name,
            "made": self.made,
            "mode": mode,
            "metres": round(_metres(line)),
            "seconds": round(seconds),
            "line": [[round(lon, 6), round(lat, 6)] for lon, lat in line],
            "steps": self._steps(legs),
        }

    def _named(self, point, metres: float = 15) -> int:
        """The name of the street running next to a nameless stretch: a sidewalk, a crossing."""
        named = [c for c in self.near(*point, metres) if self.street[c]]
        if not named:
            return 0
        return self.street[min(named, key=lambda c: self._closest(c, *point)[0])]

    def _steps(self, legs) -> list[dict]:
        """Street by street: the turn onto it, its name, how far along it."""
        groups: list[list] = []  # [street, points]
        for street, points in legs:
            if not points:
                continue
            if groups and (street == groups[-1][0] or street == 0):
                groups[-1][1].extend(points)
            elif groups and _metres([groups[-1][1][-1], *points]) < SHORT and street != 0:
                groups.append([street, [groups[-1][1][-1], *points]])
            else:
                start = [groups[-1][1][-1]] if groups else []
                groups.append([street, [*start, *points]])
        merged: list[list] = []
        for group in groups:  # a few metres of another name: still the same way on
            if merged and (_metres(group[1]) < SHORT or group[0] == merged[-1][0]):
                merged[-1][1].extend(group[1][1:])
            else:
                merged.append(group)
        groups = merged
        steps = []
        for k, (street, points) in enumerate(groups):
            turn = "start" if k == 0 else _turn(groups[k - 1][1], points)
            steps.append(
                {"turn": turn, "name": self.names[street], "metres": round(_metres(points))}
            )
        steps.append({"turn": "arrive", "name": "", "metres": 0})
        return steps


def _made(f, archive) -> str:
    """The day of the map's data (OpenStreetMap's, as written by Protomaps), or else the day
    the file was saved here: shown with every route."""
    f.seek(24)
    offset, length = struct.unpack("<2Q", f.read(16))
    with contextlib.suppress(places.MapError, OSError, ValueError, TypeError, IndexError):
        if 0 < length <= 2**20:
            raw = places._unpack(places._read(f, offset, length), archive.internal, 2**20)
            when = json.loads(raw).get("planetiler:osm:osmosisreplicationtime")
            if isinstance(when, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}T.*", when):
                return when[:10]
    return time.strftime("%Y-%m-%d", time.localtime(os.fstat(f.fileno()).st_mtime))


def _flip(network: Network, snapped) -> int:
    """The segment of a snapped point counted from the chain's other end."""
    chain, segment = snapped[0], snapped[1]
    return network.first[chain + 1] - network.first[chain] - 2 - segment


def _lonlat(point, world: int) -> tuple[float, float]:
    gx, gy = point
    lon = gx / world * 360 - 180
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * gy / world))))
    return lon, lat


def _metres(points) -> float:
    return sum(places._km(a[0], a[1], b[0], b[1]) * 1000 for a, b in zip(points, points[1:]))


def _bearing(a, b) -> float:
    dx = (b[0] - a[0]) * math.cos(math.radians((a[1] + b[1]) / 2))
    return math.degrees(math.atan2(dx, b[1] - a[1]))


def _turn(before, after) -> str:
    """How the way bends where one street gives onto the next."""
    if len(before) < 2 or len(after) < 2:
        return "straight"
    a = _bearing(_back(before, 20), before[-1])
    b = _bearing(after[0], _ahead(after, 20))
    angle = (b - a + 540) % 360 - 180  # positive: to the right
    if abs(angle) < 30:
        return "straight"
    if abs(angle) > 150:
        return "uturn"
    side = "right" if angle > 0 else "left"
    return f"slight_{side}" if abs(angle) < 60 else side


def _middle(points):
    """The point halfway along a line, not its middle vertex: a straight line has only two."""
    half = _metres(points) / 2
    for a, b in zip(points, points[1:]):
        step = places._km(*a, *b) * 1000
        if step >= half and step > 0:
            t = half / step
            return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
        half -= step
    return points[-1]


def _back(points, metres: float):
    walked = 0.0
    for k in range(len(points) - 1, 0, -1):
        walked += places._km(*points[k - 1], *points[k]) * 1000
        if walked >= metres:
            return points[k - 1]
    return points[0]


def _ahead(points, metres: float):
    walked = 0.0
    for k in range(len(points) - 1):
        walked += places._km(*points[k], *points[k + 1]) * 1000
        if walked >= metres:
            return points[k + 1]
    return points[-1]


# -- the networks of the maps folder ------------------------------------------------------------


class Routes:
    """The street networks of the maps folder, built in the background, and the streets the
    admin has marked as blocked."""

    def __init__(self, maps: Path, cache: Path | None = None):
        self.maps = maps
        self.cache = cache
        self._networks: dict[str, Network] = {}
        self._stamps: dict[str, list[int]] = {}
        self._failed: dict[str, list[int]] = {}
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._checked = -CHECK_EVERY
        self._closed: list[dict] = []  # from the database: id, lon, lat, name, note, created
        self._blocked: dict[str, frozenset] = {}  # map: its chains blocked
        self._closing = threading.Lock()  # one reading of the blocked streets at a time
        self._store = None
        self._version = -1
        self._shown: list[dict] | None = None  # the blocked streets as drawn, made once

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
        """Notices new, changed or removed maps; building their streets happens in a thread."""
        if not now and time.monotonic() - self._checked < CHECK_EVERY:
            return
        self._checked = time.monotonic()
        self._catch_up()
        current = self._scan()
        with self._lock:
            for name in [n for n in self._networks if n not in current]:
                del self._networks[name], self._stamps[name]
                self._blocked.pop(name, None)
            todo = self._todo(current)
            if todo and not (self._worker and self._worker.is_alive()):
                self._worker = threading.Thread(target=self._build, args=(todo,), daemon=True)
                self._worker.start()

    def _build(self, todo: dict[str, list[int]]) -> None:
        for name, stamp in sorted(todo.items()):
            failed = self.cache / f"{name}.failed" if self.cache else None
            # Written before the work and removed after: a build that kills the Campanile
            # (out of memory, a power cut) is counted, and given up after TRIES.
            busy = self.cache / f"{name}.building" if self.cache else None
            network = None
            try:
                known = places._load(failed, stamp) if failed else None
                if known is not None:
                    raise places.MapError(known.get("failed", "failed before"))
                tries = places._tries(busy, stamp) if busy else 0
                if tries >= TRIES:
                    raise places.MapError(f"building it was cut short {tries} times")
                if busy:
                    places._save(
                        busy, {"format": places.FORMAT, "source": stamp, "tries": tries + 1}
                    )
                network = Network(name, self.maps / f"{name}.pmtiles")
            except places.MapError as e:  # a world map, or a map not made for it: no routes
                if failed:
                    places._save(
                        failed, {"format": places.FORMAT, "source": stamp, "failed": str(e)}
                    )
            except Exception as e:  # any damage: no routes on that map, nothing else
                print(f"[campanile] no routes on map {name}: {e!r}", flush=True)
                if failed and not isinstance(e, OSError):
                    places._save(
                        failed, {"format": places.FORMAT, "source": stamp, "failed": str(e)[:200]}
                    )
            if busy:
                with contextlib.suppress(OSError):
                    busy.unlink()
            if network is None:
                with self._lock:
                    self._failed[name] = stamp
                continue
            with self._closing:  # a network is offered only with its blocked streets
                blocked = self._blocks(network, self._closed)
                with self._lock:
                    self._networks[name] = network
                    self._stamps[name] = stamp
                    self._blocked[name] = blocked
                    self._shown = None  # a new map: draw them again
        self._checked = -CHECK_EVERY

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

    def available(self) -> set[str]:
        """The maps one can find a route on."""
        with self._lock:
            return set(self._networks)

    def route(self, start, end, mode: str) -> dict:
        self.refresh()
        with self._lock:
            networks = list(self._networks.values())
            blocked = dict(self._blocked)
        inside = [n for n in networks if _inside(n.extent, start) and _inside(n.extent, end)]
        if not inside:
            raise RouteError("route_outside" if networks or self.ready else "route_wait")
        # The smallest map holding both points: a city's, rather than a region's; if its
        # streets are too far from a point, the next one.
        for network in sorted(inside, key=lambda n: len(n.length)):
            if network.name not in blocked:  # never a route without its blocked streets
                raise RouteError("route_wait")
            try:
                return network.route(start, end, mode, blocked[network.name])
            except RouteError as e:
                if e.key != "route_far":
                    raise
        raise RouteError("route_far")

    # -- blocked streets ----------------------------------------------------------------------
    # The database is the only record of what is blocked. The networks never get a list from
    # outside: they read it again themselves, under one lock, so the last one to update has
    # always read the newest; and a version number lets them catch up by themselves.

    def _blocks(self, network: Network, entries: list[dict]) -> frozenset:
        chains: set[int] = set()
        for entry in entries:
            found = network.place(entry["lon"], entry["lat"])
            if found is not None:
                chains |= found[1]
        return frozenset(chains)

    def reload_closed(self, store) -> None:
        """Reads the blocked streets again from the database; every route avoids them."""
        with self._closing:
            self._store = store
            version, entries = store.closed_roads()
            with self._lock:
                networks = dict(self._networks)
            blocked = {name: self._blocks(n, entries) for name, n in networks.items()}
            with self._lock:
                self._closed, self._version = entries, version
                self._shown = None
                self._blocked.update(blocked)

    def _catch_up(self) -> None:
        store = self._store
        if store is not None and store.closed_version != self._version:
            self.reload_closed(store)

    def street_at(self, lon: float, lat: float) -> dict | None:
        """What a touch at this point would block: the street's name, and every stretch."""
        with self._lock:
            networks = list(self._networks.values())
        for network in sorted(networks, key=lambda n: len(n.length)):
            found = network.place(lon, lat)
            if found is not None:
                spot, chains, alongside = found
                street = network.street[spot[0]] or network._named((spot[4], spot[5]), BLOCK)
                return {
                    "map": network.name,
                    "name": network.names[street],  # a sidewalk: the street it runs along
                    "lines": [
                        [[round(x, 6), round(y, 6)] for x, y in network._points(chain, True)]
                        for chain in sorted(chains)
                    ],
                    # Lines alongside left open: the admin is told, and may touch them too.
                    "open": [
                        {"name": name, "metres": metres}
                        for name, metres in sorted(alongside.items(), key=lambda kv: kv[1])
                    ][:5],
                }
        return None

    def closed(self) -> list[dict]:
        """Every blocked place with the stretches to draw in red, for anyone on the map. Made
        once after each change: phones ask for it every minute, and anyone may ask."""
        with self._lock:
            shown, entries = self._shown, list(self._closed)
        if shown is not None:
            return shown
        shown = []
        for entry in entries:
            street = self.street_at(entry["lon"], entry["lat"])
            shown.append({**entry, "lines": street["lines"] if street else []})
        with self._lock:
            if self._closed == entries:
                self._shown = shown
        return shown


def _inside(bounds, point) -> bool:
    west, south, east, north = bounds
    return west <= point[0] <= east and south <= point[1] <= north
