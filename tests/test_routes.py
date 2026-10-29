# DEVELOPED BY CARROTSTUDIO software house
"""Routes on foot and by car, and blocked streets: a small town on a river, with two bridges.

Bridge A is two one-way carriageways and two sidewalks, as bridges are on real maps; bridge B
is a single two-way street. The town crosses tile borders, a riverside street passes under
bridge A, a footpath and steps cut a corner, a motorway is faster than the streets around it.
"""

import contextlib
import io
import math
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "campanile"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mapfixture as mf
import messages
import routes
import store
from test_server import PASSWORD, CampanileTestCase, server_source

Z = 14
WEST, EAST = 7.674, 7.686  # the streets along the two banks; the river is between them
A, B = 45.065, 45.078  # the latitudes of the two bridges
A_MIDDLE, B_MIDDLE = (7.680, A), (7.680, B)
ON_WEST, ON_EAST = (7.6743, 45.0663), (7.6857, 45.0663)  # just north of bridge A

RESIDENTIAL = {"kind": "minor_road", "kind_detail": "residential"}
BRIDGE = {"kind": "major_road", "kind_detail": "secondary", "is_bridge": True}
SIDEWALK = {"kind": "path", "kind_detail": "sidewalk", "is_bridge": True}


def street(name, *points, **props):
    return ({"name": name, **RESIDENTIAL, **props} if name else props, list(points))


def town() -> list:
    bank = [45.060, A - 0.0001, A - 0.00005, A + 0.00005, A + 0.0001, 45.070, B, 45.082]
    return [
        street("Via Ovest", *[(WEST, lat) for lat in bank]),  # crosses the border at 45.0735
        street("Via Est", *[(EAST, lat) for lat in bank]),
        # Bridge A: one carriageway each way, a sidewalk on each side, all within 11 m.
        (
            {"name": "Ponte A", **BRIDGE, "oneway": "yes"},
            [(WEST, A + 0.00005), (EAST, A + 0.00005)],
        ),
        (
            {"name": "Ponte A", **BRIDGE, "oneway": "yes"},
            [(EAST, A - 0.00005), (WEST, A - 0.00005)],
        ),
        (SIDEWALK, [(WEST, A + 0.0001), (EAST, A + 0.0001)]),
        (SIDEWALK, [(WEST, A - 0.0001), (EAST, A - 0.0001)]),
        ({"name": "Ponte B", **BRIDGE}, [(WEST, B), (EAST, B)]),
        # Along the river, under bridge A: crossing it on the map, never meeting it.
        street("Lungofiume", (7.678, 45.061), (7.678, 45.069)),
        street("Raccordo Sud", (WEST, 45.061), (7.678, 45.061)),
        street("Raccordo Nord", (WEST, 45.069), (7.678, 45.069)),
        # West of Via Ovest: a footpath cuts the corner that cars go around.
        ({"kind": "path", "kind_detail": "footway"}, [(WEST, 45.070), (7.670, 45.074)]),
        street("Via Nord", (WEST, 45.076), (7.670, 45.076)),
        street("Via Angolo", (7.670, 45.076), (7.670, 45.074)),
        (
            {"kind": "path", "kind_detail": "steps", "name": "Scalinata"},
            [(7.670, 45.074), (7.670, 45.072)],
        ),
        # East: a one-way street across the tile border at 7.69043, and the way back.
        street("Via Senso Unico", (EAST, 45.070), (7.694, 45.070), oneway="yes"),
        street("Via Ritorno", (7.694, 45.070), (7.694, 45.0715), (EAST, 45.0715)),
        # South-east: a motorway, and the slower streets around it.
        (
            {"name": "A1", "kind": "highway", "kind_detail": "motorway"},
            [(EAST, 45.0605), (7.696, 45.0605)],
        ),
        street("Via Lenta", (EAST, 45.0605), (EAST, 45.0625), (7.696, 45.0625), (7.696, 45.0605)),
        # Crossing each other without a point in common, as maps often draw them.
        street("Via Croce", (7.688, 45.064), (7.692, 45.068)),
        street("Via Traversa", (7.688, 45.068), (7.692, 45.064)),
        street("Via Accesso", (EAST, 45.064), (7.688, 45.064)),
    ]


def local(lon, lat, tx, ty):
    n = 1 << Z
    fx = (lon + 180) / 360 * n
    fy = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return round((fx - tx) * mf.EXTENT), round((fy - ty) * mf.EXTENT)


def town_map(lines=None) -> bytes:
    """Each line goes, whole, into every tile it touches: like the borders of real tiles."""
    tiles: dict = {}
    for props, coords in lines or town():
        cells = [mf.tile_of(lon, lat, Z)[:2] for lon, lat in coords]
        for tx in range(min(c[0] for c in cells), max(c[0] for c in cells) + 1):
            for ty in range(min(c[1] for c in cells), max(c[1] for c in cells) + 1):
                points = [local(lon, lat, tx, ty) for lon, lat in coords]
                tiles.setdefault((Z, tx, ty), []).append((props, points))
    return mf.pmtiles({key: mf.vector_tile({"roads": lines}) for key, lines in tiles.items()})


def gap(route, point) -> float:
    """Metres between a route's line and a point."""
    best = math.inf
    wide = math.cos(math.radians(point[1]))
    line = route["line"]
    for (ax, ay), (bx, by) in zip(line, line[1:]):
        ax, bx, px = ax * wide, bx * wide, point[0] * wide
        dx, dy = bx - ax, by - ay
        span = dx * dx + dy * dy
        t = 0 if span == 0 else max(0, min(1, ((px - ax) * dx + (point[1] - ay) * dy) / span))
        best = min(best, math.hypot(ax + t * dx - px, ay + t * dy - point[1]) * 111_320)
    return best


class TownCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "maps").mkdir()
        (self.root / "maps" / "town.pmtiles").write_bytes(town_map())
        self.store = store.Store(self.root / "campanile.db")
        self.routes = self.start()

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def start(self) -> routes.Routes:
        """What a start of the Campanile does: the blocked streets from the database first."""
        found = routes.Routes(self.root / "maps", self.root / "routes")
        found.reload_closed(self.store)
        with contextlib.redirect_stdout(io.StringIO()):
            found.refresh(now=True)
            found.wait(60)
        return found

    def route(self, start, end, mode, found=None):
        return (found or self.routes).route(start, end, mode)

    def close(self, point):
        street = self.routes.street_at(*point)
        self.store.add_closed_road(point[0], point[1], street["name"], "")
        self.routes.reload_closed(self.store)
        return street


class TestWays(TownCase):
    def test_on_foot_the_short_way_across_bridge_a(self):
        r = self.route(ON_WEST, ON_EAST, "foot")
        self.assertLess(gap(r, A_MIDDLE), 15)
        self.assertLess(r["metres"], 1300)  # 950 m of bridge, a little of each bank
        self.assertEqual((r["steps"][0]["turn"], r["steps"][-1]["turn"]), ("start", "arrive"))
        self.assertIn("Ponte A", [s["name"] for s in r["steps"]])
        self.assertEqual(r["made"], r["made"][:10])  # the day of the map's data

    def test_by_car_each_way_on_its_own_carriageway(self):
        there = self.route(ON_WEST, ON_EAST, "car")
        back = self.route(ON_EAST, ON_WEST, "car")
        self.assertLess(gap(there, (7.680, A + 0.00005)), 2)  # the north one, eastbound
        self.assertLess(gap(back, (7.680, A - 0.00005)), 2)  # the south one, westbound
        self.assertGreater(gap(there, (7.680, A - 0.00005)), 4)

    def test_cars_respect_one_way_streets_and_walkers_dont_need_to(self):
        start, end = (7.6935, 45.0700), (7.6870, 45.0700)  # against Via Senso Unico
        on_foot = self.route(start, end, "foot")
        by_car = self.route(start, end, "car")
        self.assertLess(on_foot["metres"], 600)
        self.assertGreater(by_car["metres"], on_foot["metres"] + 250)  # round by Via Ritorno
        self.assertLess(gap(by_car, (7.690, 45.0715)), 3)

    def test_cars_never_take_footpaths_or_steps(self):
        start, end = (7.6745, 45.0700), (7.6700, 45.0735)
        on_foot = self.route(start, end, "foot")
        by_car = self.route(start, end, "car")
        self.assertLess(gap(on_foot, (7.672, 45.072)), 3)  # the footpath's middle
        self.assertGreater(gap(by_car, (7.672, 45.072)), 100)
        self.assertGreater(by_car["metres"], on_foot["metres"] * 1.5)

    def test_walkers_never_take_the_motorway(self):
        start, end = (7.6862, 45.0605), (7.6958, 45.0605)
        by_car = self.route(start, end, "car")
        on_foot = self.route(start, end, "foot")
        self.assertLess(gap(by_car, (7.691, 45.0605)), 2)  # along the A1
        self.assertGreater(gap(on_foot, (7.691, 45.0605)), 100)  # round by Via Lenta

    def test_a_street_under_a_bridge_never_meets_it(self):
        network = self.routes._networks["town"]
        crossing = (7.678, A)
        nodes = [
            k
            for k in range(len(network.node_lon))
            if math.hypot(
                (network.node_lon[k] - crossing[0]) * 78_700,
                (network.node_lat[k] - crossing[1]) * 111_320,
            )
            < 5
        ]
        self.assertEqual(nodes, [])
        r = self.route((7.6781, 45.0663), ON_EAST, "car")  # from the riverside street
        self.assertLess(gap(r, (7.676, 45.069)), 3)  # up to Via Ovest by the connector first

    def test_streets_meet_where_they_cross_without_a_shared_point(self):
        r = self.route((7.6895, 45.0645), (7.6905, 45.0645), "car")  # Croce then Traversa
        self.assertLess(r["metres"], 400)

    def test_streets_go_on_across_tile_borders(self):
        north = self.route((7.6743, 45.0700), (7.6743, 45.0800), "car")  # border at 45.0735
        self.assertLess(abs(north["metres"] - 1112), 30)
        east = self.route((7.6870, 45.0715), (7.6935, 45.0715), "foot")  # border at 7.69043
        self.assertLess(east["metres"], 560)

    def test_a_line_touching_a_tile_edge_leaves_no_piece_of_no_length(self):
        line = [(4200, 10), (4096, 10), (4200, 20)]  # out, one vertex on the edge, out again
        self.assertEqual(routes._clip(line, (0, 0, 4096, 4096)), [])

    def test_points_off_the_streets_or_off_the_map(self):
        with self.assertRaises(routes.RouteError) as e:
            self.route((7.6800, 45.0745), ON_EAST, "foot")  # in the river, 390 m from a street
        self.assertEqual(e.exception.key, "route_far")
        with self.assertRaises(routes.RouteError) as e:
            self.route((9.19, 45.46), ON_EAST, "foot")  # Milan: not on this map
        self.assertEqual(e.exception.key, "route_outside")


class TestBlocked(TownCase):
    """Bridge A is flooded: no route may cross it, whoever asks and in whichever direction."""

    def assert_avoids_a(self):
        for start, end in ((ON_WEST, ON_EAST), (ON_EAST, ON_WEST)):
            for mode in ("foot", "car"):
                with self.subTest(start=start, mode=mode):
                    r = self.route(start, end, mode)
                    self.assertGreater(gap(r, A_MIDDLE), 25)
                    self.assertLess(gap(r, B_MIDDLE), 15)  # the long way, by bridge B

    def test_one_touch_blocks_every_line_of_the_bridge(self):
        street = self.close((7.6801, A + 0.00003))  # touched a little off the middle
        self.assertEqual(street["name"], "Ponte A")
        self.assertEqual(len(street["lines"]), 4)  # two carriageways, two sidewalks
        self.assert_avoids_a()
        # The streets along the banks stay open, right next to the bridge.
        r = self.route((7.6743, 45.0620), (7.6743, 45.0680), "car")
        self.assertLess(r["metres"], 700)

    def test_both_bridges_blocked_no_route(self):
        self.close(A_MIDDLE)
        self.close(B_MIDDLE)
        for mode in ("foot", "car"):
            with self.assertRaises(routes.RouteError) as e:
                self.route(ON_WEST, ON_EAST, mode)
            self.assertEqual(e.exception.key, "route_none")

    def test_reopened_it_is_used_again(self):
        self.close(A_MIDDLE)
        road = self.store.closed_roads()[1][0]["id"]
        self.store.open_road(road)
        self.routes.reload_closed(self.store)
        self.assertLess(gap(self.route(ON_WEST, ON_EAST, "foot"), A_MIDDLE), 15)

    def test_still_blocked_after_a_restart(self):
        self.close(A_MIDDLE)
        self.routes = self.start()  # a new start on the same data
        self.assert_avoids_a()

    def test_a_missed_update_is_caught_up(self):
        street = self.routes.street_at(*A_MIDDLE)
        self.store.add_closed_road(*A_MIDDLE, street["name"], "")  # nobody told the routes
        self.routes.refresh(now=True)
        self.assert_avoids_a()

    def test_updates_at_the_same_time_end_as_the_database(self):
        points = [(WEST + 0.0002, 45.0605 + k * 0.002) for k in range(10)]
        threads = [threading.Thread(target=self.close, args=(p,)) for p in points]
        with mock.patch.object(routes.Network, "near", wraps_slowly(routes.Network.near)):
            for t in threads:
                t.start()
            for t in threads:
                t.join(30)
        network = self.routes._networks["town"]
        expected = self.routes._blocks(network, self.store.closed_roads()[1])
        self.assertEqual(self.routes._blocked["town"], expected)
        self.assertEqual(len(self.store.closed_roads()[1]), 10)

    def test_the_blocked_streets_are_shown_to_everyone(self):
        self.close(A_MIDDLE)
        shown = self.routes.closed()
        self.assertEqual((len(shown), shown[0]["name"], len(shown[0]["lines"])), (1, "Ponte A", 4))
        # Asked again and again by every phone: drawn once, until something changes.
        with mock.patch.object(self.routes, "street_at", side_effect=AssertionError("again")):
            self.assertEqual(self.routes.closed(), shown)
        self.close(B_MIDDLE)
        self.assertEqual(len(self.routes.closed()), 2)


def wraps_slowly(near):
    """Makes the update slower, so that updates run into each other if they can."""

    def slow(self, *args):
        threading.Event().wait(0.01)
        return near(self, *args)

    return slow


# A wider river: a bridge as wide as a real avenue, its own footbridge 55 m upstream, a
# narrow bridge far north for the detour, and a hill with a two-tube tunnel and a road over it.
WIDE, NARROW, HILL = 45.070, 45.080, 45.090
FOOTBRIDGE = WIDE + 0.0005  # 55 m from the middle of the wide bridge
ROAD = {"kind": "major_road", "kind_detail": "secondary"}


def river() -> list:
    carriageways, sidewalks, tubes = (0.00014, -0.00014), (0.00017, -0.00017), (0.0001, -0.0001)
    joins = sorted(
        {45.065, NARROW, FOOTBRIDGE, 45.095, 45.100}
        | {WIDE + d for d in carriageways + sidewalks}
        | {HILL + d for d in tubes}
    )
    lines = [
        street("Riva Ovest", *[(WEST, lat) for lat in joins]),
        street("Riva Est", *[(EAST, lat) for lat in joins]),
        ({"name": "Ponte Stretto", **BRIDGE}, [(WEST, NARROW), (EAST, NARROW)]),
        ({**SIDEWALK, "name": "Passerella"}, [(WEST, FOOTBRIDGE), (EAST, FOOTBRIDGE)]),
        # Over the hill, the long way round the tunnel.
        street("Strada del Colle", (WEST, 45.095), (7.680, 45.100), (EAST, 45.095)),
    ]
    for d, (a, b) in zip(carriageways, ((WEST, EAST), (EAST, WEST))):
        props = {"name": "Ponte Largo", **BRIDGE, "oneway": "yes"}
        lines.append((props, [(a, WIDE + d), (b, WIDE + d)]))
    for d in sidewalks:
        lines.append((SIDEWALK, [(WEST, WIDE + d), (EAST, WIDE + d)]))
    for d, (a, b) in zip(tubes, ((WEST, EAST), (EAST, WEST))):
        props = {"name": "Galleria", **ROAD, "is_tunnel": True, "oneway": "yes"}
        lines.append((props, [(a, HILL + d), (b, HILL + d)]))
    return lines


class TestWhichMap(TownCase):
    def add(self, name, lines, bounds=(-180.0, -85.0, 180.0, 85.0)):
        tiles: dict = {}
        for props, coords in lines:
            tx, ty = mf.tile_of(*coords[0], Z)[:2]
            points = [local(lon, lat, tx, ty) for lon, lat in coords]
            tiles.setdefault((Z, tx, ty), []).append((props, points))
        data = mf.pmtiles({k: mf.vector_tile({"roads": v}) for k, v in tiles.items()}, bounds)
        (self.root / "maps" / f"{name}.pmtiles").write_bytes(data)
        self.routes = self.start()

    def test_a_tiny_map_claiming_the_world_takes_no_route(self):
        self.add("aaa-tiny", [street("Via Alpina", (7.0, 45.9), (7.001, 45.9))])
        self.assertLess(gap(self.route(ON_WEST, ON_EAST, "foot"), A_MIDDLE), 15)

    def test_a_smaller_map_without_streets_near_the_points_gives_way(self):
        # Its streets surround the town, but none is within reach of a point in it.
        far = [
            street("Via Lontana", (7.60, 45.00), (7.601, 45.00)),
            street("Via Remota", (7.76, 45.14), (7.761, 45.14)),
        ]
        self.add("aaa-ring", far)
        self.assertLess(gap(self.route(ON_WEST, ON_EAST, "foot"), A_MIDDLE), 15)

    def test_never_a_route_without_its_blocked_streets(self):
        self.close(A_MIDDLE)
        del self.routes._blocked["town"]
        with self.assertRaises(routes.RouteError) as caught:
            self.route(ON_WEST, ON_EAST, "foot")
        self.assertEqual(caught.exception.key, "route_wait")

    def test_how_far_a_point_was_moved_is_said(self):
        off = (WEST - 0.0013, 45.0663)  # about 100 m west of Via Ovest, in a field
        r = self.route(off, (EAST, 45.0663), "foot")  # the end right on Via Est
        self.assertTrue(90 <= r["moved"][0] <= 110, r["moved"])
        self.assertLess(r["moved"][1], 5)


BUFFER = 64  # tile units beyond its edges that a real tile carries


def cut_map(lines) -> bytes:
    """Like real tiles: each tile holds only the part of a line within its edges and a narrow
    buffer, so a ring crossing a border arrives as open arcs."""
    tiles: dict = {}
    for props, coords in lines:
        cells = [mf.tile_of(lon, lat, Z)[:2] for lon, lat in coords]
        for tx in range(min(c[0] for c in cells), max(c[0] for c in cells) + 1):
            for ty in range(min(c[1] for c in cells), max(c[1] for c in cells) + 1):
                run: list = []
                for where in [*coords, None]:
                    point = local(*where, tx, ty) if where is not None else None
                    inside = point is not None and all(
                        -BUFFER <= v <= mf.EXTENT + BUFFER for v in point
                    )
                    if inside:
                        run.append(point)
                    elif len(run) > 1:
                        tiles.setdefault((Z, tx, ty), []).append((props, run))
                        run = []
                    else:
                        run = []
    return mf.pmtiles({key: mf.vector_tile({"roads": v}) for key, v in tiles.items()})


class TestRoundabouts(unittest.TestCase):
    """A roundabout on a tile border: cars go round it the way it is drawn, never back."""

    def test_cars_go_round_the_way_it_is_drawn(self):
        tx = mf.tile_of(7.69, 45.054, Z)[0] + 1
        lon = tx * 360 / (1 << Z) - 180  # on the border between two tiles
        lat, radius = 45.054, 0.00027  # about 30 m each way from the middle
        wide = radius / math.cos(math.radians(lat))
        ring = [
            (lon + wide * math.cos(math.radians(a)), lat + radius * math.sin(math.radians(a)))
            for a in range(180, 180 + 361, 5)  # from the west, anticlockwise, closed
        ]
        lines = [
            street("Rotonda", *ring),
            street("Via da Ovest", (lon - 0.003, lat), ring[0]),
            street("Via per Nord", ring[54], (lon, lat + 0.003)),  # 270 degrees on: the north
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "ring.pmtiles")
            path.write_bytes(cut_map(lines))
            network = routes.Network("ring", path)
        r = network.route((lon - 0.003, lat), (lon, lat + 0.003), "car")
        south = (lon, lat - radius)
        self.assertLess(gap(r, south), 5)  # three quarters round, by the south
        walk = network.route((lon - 0.003, lat), (lon, lat + 0.003), "foot")
        self.assertGreater(gap(walk, south), 20)  # on foot, the short way


class TestWideStructures(TownCase):
    """A bridge or a tunnel closes whole, across its width, wherever on it the admin touches."""

    def setUp(self):
        super().setUp()
        (self.root / "maps" / "town.pmtiles").write_bytes(town_map(river()))
        self.routes = self.start()

    def detour(self, point, start, end, mode):
        r = self.route(start, end, mode)
        self.assertGreater(gap(r, point), 30, (mode, start, end))

    def test_a_touch_between_the_carriageways_closes_the_whole_bridge(self):
        middle = (7.680, WIDE)
        self.close(middle)
        west, east = (WEST, WIDE - 0.002), (EAST, WIDE - 0.002)
        for mode in ("car", "foot"):
            with self.subTest(mode=mode):
                self.detour(middle, west, east, mode)
                self.detour(middle, east, west, mode)

    def test_a_touch_on_one_sidewalk_closes_the_other_side_too(self):
        self.close((7.680, WIDE + 0.00017))
        west, east = (WEST, WIDE - 0.002), (EAST, WIDE - 0.002)
        for mode in ("car", "foot"):
            with self.subTest(mode=mode):
                self.detour((7.680, WIDE), west, east, mode)
                self.detour((7.680, WIDE), east, west, mode)

    def test_a_touch_on_one_tube_closes_the_other(self):
        self.close((7.680, HILL + 0.0001))
        west, east = (WEST, HILL - 0.001), (EAST, HILL - 0.001)
        self.detour((7.680, HILL), west, east, "car")
        self.detour((7.680, HILL), east, west, "car")

    def test_the_footbridge_stays_open_and_the_admin_is_told(self):
        street = self.close((7.680, WIDE))
        self.assertEqual([o["name"] for o in street["open"]], ["Passerella"])
        self.assertTrue(routes.STRUCTURE < street["open"][0]["metres"] <= routes.NEARBY)
        r = self.route((WEST, WIDE - 0.002), (EAST, WIDE - 0.002), "foot")
        self.assertLess(gap(r, (7.680, FOOTBRIDGE)), 5)  # walkers cross on the footbridge

    def test_walkers_stay_out_of_a_main_road_tunnel(self):
        r = self.route((WEST, HILL - 0.001), (EAST, HILL - 0.001), "foot")
        self.assertGreater(gap(r, (7.680, HILL)), 300)  # over the hill
        r = self.route((WEST, HILL - 0.001), (EAST, HILL - 0.001), "car")
        self.assertLess(gap(r, (7.680, HILL)), 15)  # cars use it


class TestBudgets(unittest.TestCase):
    def test_a_map_too_big_for_routes_still_shows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "town.pmtiles")
            path.write_bytes(town_map())
            with (
                mock.patch.object(routes, "MAX_TILES", 1),
                self.assertRaises(routes.places.MapError),
            ):
                routes.Network("town", path)
            with (
                mock.patch.object(routes, "MAX_POINTS", 10),
                self.assertRaises(routes.places.MapError),
            ):
                routes.Network("town", path)

    def test_a_file_stacking_one_street_is_refused_at_once(self):
        # 3,000 copies of one street across one tile: a few KB that, built without limits,
        # take minutes or all the memory (as the review measured).
        tx, ty = mf.tile_of(7.68, 45.07, Z)[:2]
        copies = [({"name": "Via", **RESIDENTIAL}, [(0, 0), (mf.EXTENT, mf.EXTENT)])] * 3000
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "stack.pmtiles")
            path.write_bytes(mf.pmtiles({(Z, tx, ty): mf.vector_tile({"roads": copies})}))
            started = time.monotonic()
            with self.assertRaisesRegex(routes.places.MapError, "too much work"):
                routes.Network("stack", path)
        self.assertLess(time.monotonic() - started, 2)

    def test_tiles_of_an_unusual_size_are_refused(self):
        with mock.patch.object(mf, "EXTENT", 1 << 18):  # one street then covers a city of cells
            data = town_map()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "wide.pmtiles")
            path.write_bytes(data)
            with self.assertRaisesRegex(routes.places.MapError, "unusual size"):
                routes.Network("wide", path)

    def test_a_world_map_has_no_routes(self):
        world = mf.pmtiles(
            {(5, 16, 11): mf.vector_tile({"roads": [street("Via", (0, 0), (100, 100))]})}
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "world.pmtiles")
            path.write_bytes(world)
            with self.assertRaisesRegex(routes.places.MapError, "no streets in detail"):
                routes.Network("world", path)

    def test_a_map_that_kills_the_campanile_is_given_up(self):
        # Killed for real while building the streets, as out of memory would: three starts,
        # then the map is left alone and the Campanile stays up.
        start = (
            "import sys; sys.path[:0] = sys.argv[1:3]\n"
            "import os, routes\n"
            "if sys.argv[5] == 'kill': routes.Network = lambda *a: os._exit(137)\n"
            "found = routes.Routes(routes.Path(sys.argv[3]), routes.Path(sys.argv[4]))\n"
            "found.refresh(now=True); found.wait(60)\n"
            "print(sorted(found.available()))\n"
        )
        here = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as tmp:
            maps, cache = Path(tmp, "maps"), Path(tmp, "routes")
            maps.mkdir()
            town = maps / "town.pmtiles"
            town.write_bytes(town_map())
            args = [str(here.parent / "campanile"), str(here), str(maps), str(cache)]

            def run(how):
                command = [sys.executable, "-c", start, *args, how]
                return subprocess.run(command, capture_output=True, text=True, timeout=60)  # noqa: S603

            codes = [run("kill").returncode for _ in range(routes.TRIES)]
            self.assertEqual(codes, [137] * routes.TRIES)
            done = run("normal")  # the next start: not built again, not killed
            self.assertEqual((done.returncode, done.stdout.splitlines()[-1]), (0, "[]"))
            self.assertIn("cut short 3 times", (cache / "town.failed").read_text())
            later = town.stat().st_mtime_ns + 10**9
            os.utime(town, ns=(later, later))  # a new version of the map: tried again
            self.assertEqual(run("normal").stdout.splitlines()[-1], "['town']")


class TestFromThePhone(CampanileTestCase):
    def setUp(self):
        super().setUp()
        (self.data / "maps" / "test.pmtiles").unlink()  # not a map
        (self.data / "maps" / "town.pmtiles").write_bytes(town_map())
        with contextlib.redirect_stdout(io.StringIO()):
            self.cfg.routes.refresh(now=True)
            self.cfg.routes.wait(60)

    def ask(self, start, end, mode="foot"):
        query = f"from={start[0]},{start[1]}&to={end[0]},{end[1]}&by={mode}"
        return self.json("GET", "/api/route?" + query)

    def test_a_route(self):
        status, r = self.ask(ON_WEST, ON_EAST)
        self.assertEqual(status, 200)
        self.assertEqual(
            set(r), {"map", "made", "mode", "metres", "seconds", "line", "steps", "moved"}
        )
        self.assertTrue(self.json("GET", "/api/maps")[1]["maps"][0]["routes"])

    def maps(self, name):
        status, r = self.json("GET", "/api/maps")
        self.assertEqual(status, 200)
        return next(m for m in r["maps"] if m["name"] == name)["routes"], r["building"]

    def test_a_map_that_arrives_later_gets_its_streets(self):
        # From the setup page or from another Campanile, while it runs: the page asking which
        # maps there are is enough for its streets to be built, and it is told to wait.
        (self.data / "maps" / "later.pmtiles").write_bytes(town_map())
        with (
            mock.patch.object(routes, "CHECK_EVERY", 0),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            ready, building = self.maps("later")
            self.assertTrue(ready or building)  # never "no routes, and none coming"
            self.cfg.routes.wait(60)
            self.assertEqual(self.maps("later"), (True, False))

    def test_a_map_without_streets_is_not_waited_for(self):
        world = mf.pmtiles(
            {(5, 16, 11): mf.vector_tile({"roads": [street("Via", (0, 0), (100, 100))]})}
        )
        (self.data / "maps" / "world.pmtiles").write_bytes(world)
        with (
            mock.patch.object(routes, "CHECK_EVERY", 0),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.maps("world")
            self.cfg.routes.wait(60)
            self.assertEqual(self.maps("world"), (False, False))  # the pages stop asking

    def test_what_is_not_a_route_request(self):
        for query in (
            "from=7.674,45.066",
            "from=7.674,45.066&to=7.686,45.066&by=bike",
            "from=abc&to=7.686,45.066&by=foot",
            "from=nan,45&to=7.686,45.066&by=foot",
            "from=7.674,45.066&to=inf,45&by=car",
        ):
            with self.subTest(query=query):
                self.assertEqual(self.json("GET", "/api/route?" + query)[0], 400)

    def test_blocking_from_the_admin_page_only(self):
        close = {"password": PASSWORD, "lon": A_MIDDLE[0], "lat": A_MIDDLE[1], "note": "allagato"}
        self.assertEqual(
            self.json("POST", "/api/admin/roads/close", {**close, "password": "x"})[0], 403
        )
        status, r = self.json("POST", "/api/admin/roads/close", close)
        self.assertEqual((status, r["name"], len(r["lines"])), (201, "Ponte A", 4))
        self.assertGreater(gap(self.ask(ON_WEST, ON_EAST)[1], A_MIDDLE), 25)
        status, shown = self.json("GET", "/api/roads/closed")  # anyone sees it, in red
        self.assertEqual((status, shown["closed"][0]["note"]), (200, "allagato"))
        status, _ = self.json(
            "POST", "/api/admin/roads/open", {"password": PASSWORD, "id": r["id"]}
        )
        self.assertEqual(status, 200)
        self.assertLess(gap(self.ask(ON_WEST, ON_EAST)[1], A_MIDDLE), 15)

    def test_no_point_that_is_not_a_number(self):
        for lon, lat in (
            ("NaN", 45),
            ("Infinity", 45),
            ("-Infinity", 45),
            ("1" + "0" * 400, 45),
            (7.68, 1e999),
        ):
            with self.subTest(lon=lon, lat=lat):
                body = f'{{"password": "{PASSWORD}", "lon": {lon}, "lat": {lat}}}'.encode()
                status, _ = self.json("POST", "/api/admin/roads/close", body)
                self.assertEqual(status, 400)
        for bad in (True, "7.68", None, [7.68]):
            status, _ = self.json(
                "POST", "/api/admin/roads/close", {"password": PASSWORD, "lon": bad, "lat": 45}
            )
            self.assertEqual(status, 400, bad)

    def test_a_note_that_is_not_right_is_refused_not_a_crash(self):
        for note in ("x" * 121, 7, "\u0958" * 70):  # the last one grows to 140 once normalized
            with self.subTest(note=str(note)[:10]):
                body = {"password": PASSWORD, "lon": A_MIDDLE[0], "lat": A_MIDDLE[1], "note": note}
                status, r = self.json("POST", "/api/admin/roads/close", body)
                self.assertEqual(status, 400)
                self.assertIn("nota", r["error"])
        self.assertEqual(self.json("GET", "/api/roads/closed")[1]["closed"], [])

    def test_every_field_the_server_names_has_a_label(self):
        source = server_source()  # every module of the server
        used = set(re.findall(r'(?:clean_text|_unchanged)\([^,]+, "(\w+)"', source))
        self.assertIn("note", used)  # admin.py
        self.assertIn("description", used)  # api.py
        self.assertEqual(used - set(messages.FIELDS), set())

    def test_touching_where_there_is_no_street(self):
        body = {"password": PASSWORD, "lon": 7.680, "lat": 45.071}  # in the river
        self.assertEqual(self.json("POST", "/api/admin/roads/close", body)[0], 404)

    def test_routes_are_limited_per_phone(self):
        for _ in range(10):
            self.assertEqual(self.ask(ON_WEST, ON_EAST)[0], 200)
        self.assertEqual(self.ask(ON_WEST, ON_EAST)[0], 429)

    def test_a_phone_that_used_its_routing_time_waits(self):
        self.cfg.route_time.limit = 1e-9  # as if each route took long, on a slow Raspberry
        self.assertEqual(self.ask(ON_WEST, ON_EAST)[0], 200)
        self.assertEqual(self.ask(ON_WEST, ON_EAST)[0], 429)

    def test_the_time_is_counted_for_each_phone(self):
        seconds = store.RateLimiter(1.0, 10)
        seconds.record("a", 1.5)
        self.assertEqual((seconds.blocked("a"), seconds.blocked("b")), (True, False))

    def test_a_route_that_takes_too_long_stops(self):
        with mock.patch.object(routes, "ROUTE_MOST", -1):
            status, r = self.ask(ON_WEST, (7.6857, 45.079))  # far enough to need a search
        self.assertEqual(status, 503)
        self.assertIn("più vicini", r["error"])


if __name__ == "__main__":
    unittest.main()
