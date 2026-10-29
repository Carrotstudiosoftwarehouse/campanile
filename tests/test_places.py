# DEVELOPED BY CARROTSTUDIO software house
"""Offline search in the maps: what is found, how it is ranked, and damaged maps."""

import contextlib
import gzip
import io
import os
import random
import struct
import subprocess
import sys
import tempfile
import tracemalloc
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "campanile"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mapfixture as mf
import places
import routes

Z = 14
CENTER = (7.68, 45.07)


def point(lon, lat):
    """The tile of a point, and the point inside it."""
    x, y, px, py = mf.tile_of(lon, lat, Z)
    return (Z, x, y), (px, py)


def town(far_street: bool = True) -> dict:
    """A small town: a street cut in two by a tile border, a namesake far away, a few
    useful places, and things that must not be found on their own."""
    tiles: dict = {}

    def add(lon, lat, layer, props, line_to=None):
        key, p = point(lon, lat)
        points = [p]
        if line_to is not None:
            points.append(line_to)
        tiles.setdefault(key, {}).setdefault(layer, []).append((props, points))
        return key

    add(
        *CENTER,
        "places",
        {
            "name": "Borgo Prova",
            "kind": "locality",
            "kind_detail": "town",
            "population": 5000,
            "name:en": "Test Town",
        },
    )
    add(7.682, 45.071, "places", {"name": "Quartiere Alfa", "kind": "neighbourhood"})
    # Via Roma, crossing the eastern border of the center's tile: one piece in each tile.
    (_, x, y), (px, py) = point(*CENTER)
    tiles[(Z, x, y)].setdefault("roads", []).append(
        ({"name": "Via Roma", "kind": "minor_road"}, [(px, py), (mf.EXTENT, py)])
    )
    tiles.setdefault((Z, x + 1, y), {}).setdefault("roads", []).append(
        ({"name": "Via Roma", "kind": "minor_road"}, [(0, py), (1500, py)])
    )
    if far_street:  # another Via Roma, in a town 20 km east
        add(7.94, 45.07, "roads", {"name": "Via Roma", "kind": "minor_road"}, line_to=(3000, 2000))
    add(
        7.681, 45.0705, "roads", {"name": "Corso Bianchi", "kind": "major_road"}, line_to=(100, 100)
    )
    add(7.681, 45.0702, "roads", {"name": "Ferrovia Prova", "kind": "rail"}, line_to=(50, 50))
    add(7.6812, 45.0708, "pois", {"name": "Farmacia Centrale", "kind": "pharmacy"})
    add(7.69, 45.075, "pois", {"name": "Dottor Bianchi", "kind": "pharmacy"})
    add(7.679, 45.069, "pois", {"name": "Fontanella", "kind": "drinking_water"})
    add(7.70, 45.08, "pois", {"name": "Ospedale Maggiore", "kind": "hospital"})
    add(7.6805, 45.0701, "pois", {"name": "Via Roma", "kind": "bus_stop"})
    add(7.6806, 45.0701, "pois", {"name": "Via Roma", "kind": "pedestrian"})
    add(7.6807, 45.0703, "pois", {"name": "Fermata Unica", "kind": "bus_stop"})
    return {key: mf.vector_tile(layers) for key, layers in tiles.items()}


def american_streets() -> dict:
    """Streets named in full, as the map has them, where people write addresses short."""
    tiles: dict = {}
    for n, name in enumerate(
        ("Vashon Highway Southwest", "Southwest 204th Street", "Saint John Road", "Beach Drive")
    ):
        key, p = point(7.683 + n * 0.001, 45.071)
        tiles.setdefault(key, {}).setdefault("roads", []).append(
            ({"name": name, "kind": "minor_road"}, [p, (p[0] + 50, p[1] + 50)])
        )
    return {key: mf.vector_tile(layers) for key, layers in tiles.items()}


def vector_map(tiles: dict) -> bytes:
    return mf.pmtiles({key: mf.vector_tile(layers) for key, layers in tiles.items()})


class PlacesTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.maps = self.root / "maps"
        self.maps.mkdir()
        self.cache = self.root / "places"

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name: str, content: bytes) -> Path:
        path = self.maps / name
        path.write_bytes(content)
        return path

    def places(self) -> places.Places:
        found = places.Places(self.maps, self.cache)
        with contextlib.redirect_stdout(io.StringIO()):
            found.refresh(now=True)
            found.wait()
        return found

    def search(self, query, near=CENTER, lang="it", found=None):
        return (found or self.places()).search(query, near, lang)["results"]


class TestSearch(PlacesTestCase):
    def setUp(self):
        super().setUp()
        self.write("town.pmtiles", mf.pmtiles(town()))
        self.found = self.places()

    def test_an_american_address_written_short_finds_the_street(self):
        self.write("us.pmtiles", mf.pmtiles(american_streets()))
        found = self.places()
        for typed, street in (
            ("Vashon Hwy SW", "Vashon Highway Southwest"),
            ("vashon highway", "Vashon Highway Southwest"),
            ("SW 204th St", "Southwest 204th Street"),
            ("St John Rd", "Saint John Road"),
            ("Beach Dr", "Beach Drive"),
        ):
            names = [r["name"] for r in self.search(typed, found=found)]
            self.assertIn(street, names, typed)

    def test_a_street_cut_by_a_tile_border_is_one_street(self):
        results = self.search("via roma", found=self.found)
        roma = [r for r in results if r["name"] == "Via Roma"]
        self.assertEqual([r["type"] for r in roma], ["street", "street"])  # here, and 20 km away
        here, far = roma
        _, x, _ = point(*CENTER)[0]
        border = x * 360 / 2**Z + 360 / 2**Z - 180  # the east edge of the center's tile
        self.assertLess(here["bbox"][0], border)
        self.assertGreater(here["bbox"][2], border)
        self.assertLess(here["meters"], far["meters"])
        self.assertGreater(far["meters"], 15000)

    def test_bus_stops_and_areas_named_after_the_street_dont_bury_it(self):
        results = self.search("via roma", found=self.found)
        self.assertEqual(sum(r["name"] == "Via Roma" for r in results), 2)
        self.assertNotIn("bus_stop", {r["kind"] for r in results})

    def test_bus_stops_are_left_out(self):
        self.assertEqual(self.search("fermata unica", found=self.found), [])

    def test_a_kind_of_place_finds_the_nearest_first(self):
        for word in ("farmacia", "Farmacie", "PHARMACY"):
            results = self.search(word, found=self.found)
            self.assertEqual(results[0]["name"], "Farmacia Centrale", word)
            self.assertEqual(results[1]["name"], "Dottor Bianchi", word)  # by distance, not name
            self.assertLess(results[0]["meters"], results[1]["meters"])
        self.assertEqual(self.search("acqua", found=self.found)[0]["kind"], "drinking_water")
        self.assertEqual(self.search("pronto soccorso", found=self.found)[0]["kind"], "hospital")

    def test_names_in_other_languages(self):
        it = self.search("test town", lang="it", found=self.found)[0]
        self.assertEqual((it["name"], it.get("local")), ("Borgo Prova", None))
        en = self.search("test town", lang="en", found=self.found)[0]
        self.assertEqual((en["name"], en["local"]), ("Test Town", "Borgo Prova"))
        self.assertEqual(en["detail"], "town")

    def test_accents_case_and_word_order_dont_matter(self):
        self.assertEqual(self.search("roma via", found=self.found)[0]["name"], "Via Roma")
        self.assertEqual(self.search("BÓRGO pro", found=self.found)[0]["name"], "Borgo Prova")

    def test_streets_and_points_say_where_they_are(self):
        pharmacy = self.search("farmacia centrale", found=self.found)[0]
        self.assertEqual(pharmacy["near"], "Quartiere Alfa")
        self.assertEqual(self.search("borgo prova", found=self.found)[0].get("near"), None)

    def test_railways_are_not_streets(self):
        self.assertEqual(self.search("ferrovia", found=self.found), [])

    def test_towns_before_streets_before_shops(self):
        self.write(
            "more.pmtiles",
            mf.pmtiles(
                {
                    point(7.70, 45.06)[0]: mf.vector_tile(
                        {
                            "pois": [
                                ({"name": "Bar Prova", "kind": "bar"}, [point(7.70, 45.06)[1]])
                            ],
                            "roads": [
                                ({"name": "Via Prova", "kind": "minor_road"}, [(1, 1), (90, 90)])
                            ],
                        }
                    )
                }
            ),
        )
        types = [r["type"] for r in self.search("prova")]
        self.assertEqual(types, sorted(types, key=["place", "street", "poi"].index))
        self.assertEqual(types[0], "place")

    def test_nothing_found_is_an_empty_list(self):
        self.assertEqual(self.search("zzzz", found=self.found), [])


class TestCost(PlacesTestCase):
    def test_a_short_query_ranks_a_bounded_number_of_names(self):
        # Two letters can match every street of a big city: only the best few are ranked.
        (z, x, y), _ = point(*CENTER)
        streets = [
            ({"name": f"Via Prova {n}", "kind": "minor_road"}, [(n % 4000, 10), (n % 4000, 90)])
            for n in range(1200)
        ]
        town = ({"name": "Viano", "kind": "locality", "population": 3000}, [(2000, 2000)])
        self.write(
            "city.pmtiles",
            mf.pmtiles({(z, x, y): mf.vector_tile({"roads": streets, "places": [town]})}),
        )
        found = self.places()
        ranked = []
        real = places.MapIndex.rank
        with mock.patch.object(
            places.MapIndex, "rank", lambda s, *a: ranked.append(1) or real(s, *a)
        ):
            results = self.search("vi", found=found)
        # The best by the words, and those whose name begins with what was typed.
        self.assertLessEqual(len(ranked), 2 * places.CANDIDATES)
        self.assertEqual(results[0]["name"], "Viano")  # towns still come first

    def test_repeated_or_many_words_dont_multiply_the_work(self):
        self.write("town.pmtiles", mf.pmtiles(town()))
        found = self.places()
        index = found._indexes["town"]
        with mock.patch.object(index, "_with_prefix", wraps=index._with_prefix) as looked:
            index.matching(["v"] * 40)  # one letter forty times: one look
            self.assertEqual(looked.call_count, 1)
            looked.reset_mock()
            index.matching(["v", "i", "a", "r", "o", "m", "s", "t", "u", "n"])
            self.assertLessEqual(looked.call_count, places.MAX_WORDS)
        self.assertEqual(self.search("via via via roma", found=found)[0]["name"], "Via Roma")

    def test_while_typing_the_name_that_begins_so_is_found(self):
        # 1,200 streets with a word in R come before Via Roma in every other order.
        (z, x, y), _ = point(*CENTER)
        streets = [
            (
                {"name": f"Via A{n:04d} Rossi", "kind": "minor_road"},
                [(n % 4000, 10), (n % 4000, 90)],
            )
            for n in range(1200)
        ]
        streets.append(({"name": "Via Roma", "kind": "minor_road"}, [(100, 3000), (300, 3000)]))
        self.write("city.pmtiles", vector_map({(z, x, y): {"roads": streets}}))
        found = self.places()
        self.assertEqual(self.search("via r", found=found)[0]["name"], "Via Roma")
        self.assertEqual(self.search("via ro", found=found)[0]["name"], "Via Roma")

    def test_a_word_on_too_many_names_is_left_to_the_whole_text(self):
        self.write("town.pmtiles", mf.pmtiles(town()))
        found = self.places()
        index = found._indexes["town"]
        with mock.patch.object(places, "COMMON", 1):  # every word is common here
            self.assertEqual(index.matching(["via", "roma"]), set())
            self.assertEqual(self.search("via roma", found=found)[0]["name"], "Via Roma")


class TestKinds(PlacesTestCase):
    """A kind of place ("farmacia", the nearest-pharmacy button) answers with that kind only."""

    def light_map(self) -> places.Places:
        # Like Italy at low zoom: no pharmacy, but a village called Farmacia 20 km away.
        tiles: dict = {}
        key, p = point(7.94, 45.07)
        village = {"name": "Farmacia", "kind": "locality", "kind_detail": "village"}
        tiles.setdefault(key, {}).setdefault("places", []).append((village, [p]))
        key, p = point(*CENTER)
        street = {"name": "Via della Farmacia", "kind": "minor_road"}
        tiles.setdefault(key, {}).setdefault("roads", []).append((street, [p, (p[0] + 50, p[1])]))
        self.write("light.pmtiles", vector_map(tiles))
        return self.places()

    def test_a_kind_the_map_lacks_is_said_never_a_namesake(self):
        answer = self.light_map().search("farmacia", CENTER, "it")
        self.assertEqual(answer["results"], [])
        self.assertTrue(answer["missing"])

    def test_with_real_pharmacies_only_pharmacies(self):
        self.write("town.pmtiles", mf.pmtiles(town()))
        answer = self.light_map().search("farmacia", CENTER, "it")
        self.assertEqual({r["kind"] for r in answer["results"]}, {"pharmacy"})
        self.assertFalse(answer["missing"])

    def test_a_name_with_the_word_is_still_found_when_typed(self):
        found = self.light_map()
        self.assertEqual(self.search("via della farmacia", found=found)[0]["type"], "street")
        self.assertFalse(found.search("via della farmacia", CENTER, "it")["missing"])


class TestIndexMemory(unittest.TestCase):
    """The index kept in memory is bounded like the reading, whatever the map says."""

    def rows(self, count: int, words: int) -> dict:
        unique = iter(range(10**9))
        rows = []
        for _ in range(count):
            names = [" ".join(f"w{next(unique)}" for _ in range(words)) for _ in range(3)]
            rows.append(
                [0, "locality", "", names[0], {"it": names[1], "en": names[2]}, 7, 45, None, "", 0]
            )
        return {"max_zoom": 12, "rows": rows}

    def test_a_name_of_many_words_gives_a_few(self):
        index = places.MapIndex("x", self.rows(10, 20))  # 60 different words a name
        per_row = [0] * 10
        for posting in index.postings:
            for i in posting:
                per_row[i] += 1
        self.assertEqual(max(per_row), places.MAX_ROW_WORDS)
        self.assertEqual(index.matching(["w0"]), {0})  # still found by its first words

    def test_a_map_of_different_words_stops_growing(self):
        with mock.patch.object(places, "MAX_VOCABULARY", 500):
            index = places.MapIndex("x", self.rows(100, 20))
        self.assertEqual(len(index.words), 500)

    def test_the_nearest_of_a_kind_among_a_bounded_number(self):
        rows = [[2, "pharmacy", "", f"F{i}", {}, 7, 45, None, "", 0] for i in range(50)]
        with mock.patch.object(places, "MAX_KIND", 20):
            index = places.MapIndex("x", {"max_zoom": 15, "rows": rows})
        self.assertEqual(len(index.of_kinds({"pharmacy"})), 20)


class TestMaps(PlacesTestCase):
    def test_the_index_is_saved_and_used_at_the_next_start(self):
        self.write("town.pmtiles", mf.pmtiles(town()))
        self.places()
        self.assertTrue((self.cache / "town.json").is_file())
        with mock.patch.object(places, "read_map", side_effect=AssertionError("read again")):
            self.assertEqual(self.search("fontanella")[0]["name"], "Fontanella")

    def test_a_changed_map_is_read_again(self):
        path = self.write("town.pmtiles", mf.pmtiles(town()))
        self.places()
        path.write_bytes(mf.pmtiles(town(far_street=False)))
        os.utime(path, ns=(path.stat().st_mtime_ns + 10**9,) * 2)
        roma = [r for r in self.search("via roma") if r["name"] == "Via Roma"]
        self.assertEqual(len(roma), 1)  # the far one is gone

    def test_a_removed_map_is_no_longer_searched(self):
        path = self.write("town.pmtiles", mf.pmtiles(town()))
        found = self.places()
        self.assertTrue(self.search("fontanella", found=found))
        path.unlink()
        found.refresh(now=True)
        self.assertEqual(self.search("fontanella", found=found), [])

    def test_large_maps_give_towns_only(self):
        self.write("town.pmtiles", mf.pmtiles(town()))
        with mock.patch.object(places, "DETAIL_TILES", 1):
            found = self.places()
        self.assertEqual(self.search("borgo prova", found=found)[0]["type"], "place")
        self.assertEqual(self.search("via roma", found=found), [])
        self.assertEqual(self.search("farmacia", found=found), [])

    def test_leaf_directories(self):
        self.write("town.pmtiles", mf.pmtiles(town(), leaves=True))
        self.assertEqual(self.search("farmacia")[0]["name"], "Farmacia Centrale")

    def test_tile_ids(self):
        rnd = random.Random(7)
        for z in range(0, 16):
            for _ in range(20):
                x, y = rnd.randrange(2**z), rnd.randrange(2**z)
                self.assertEqual(places._zxy(mf.hilbert_id(z, x, y)), (z, x, y))


class TestDamagedMaps(PlacesTestCase):
    """A map that can't be read is not searchable; nothing else is affected."""

    def hostile(self) -> dict:
        good = mf.pmtiles(town())
        (z, x, y), _ = point(*CENTER)
        # A valid tile with a name, swollen by a field nobody reads: tiny once packed.
        swollen = mf.vector_tile({"pois": [({"name": "Bomba", "kind": "bar"}, [(1, 1)])]})
        bomb = mf.pmtiles({(z, x, y): swollen + mf.field(9, b"\0" * places.TILE_LIMIT)})
        huge_root = bytearray(good)
        struct.pack_into("<Q", huge_root, 16, 2**40)
        loop = bytearray(mf.pmtiles(town(), leaves=True))  # the leaf points to itself
        root_at, root_length = struct.unpack_from("<2Q", loop, 8)
        root = mf._directory([(0, 0, 0, root_length)])
        loop[root_at : root_at + root_length] = root.ljust(root_length, b"\0")[:root_length]
        struct.pack_into("<Q", loop, 40, root_at)  # leaves are found where the root is
        garbage_tile = mf.pmtiles(
            {(z, x, y): bytes(random.Random(1).randrange(256) for _ in range(500))}
        )
        return {
            "noise.pmtiles": bytes(random.Random(2).randrange(256) for _ in range(5000)),
            "empty.pmtiles": b"",
            "cut.pmtiles": good[: len(good) // 2],
            "bomb.pmtiles": bomb,
            "huge.pmtiles": bytes(huge_root),
            "loop.pmtiles": bytes(loop),
            "garbage.pmtiles": garbage_tile,
        }

    def test_damaged_maps_are_skipped_and_good_ones_still_work(self):
        for name, content in self.hostile().items():
            self.write(name, content)
        self.write("town.pmtiles", mf.pmtiles(town()))
        output = io.StringIO()
        found = places.Places(self.maps, self.cache)
        with contextlib.redirect_stdout(output):
            found.refresh(now=True)
            found.wait(60)
        self.assertTrue(found.ready)
        self.assertEqual(self.search("farmacia", found=found)[0]["name"], "Farmacia Centrale")
        unreadable = {line.split()[2] for line in output.getvalue().splitlines()}
        self.assertTrue({"noise", "empty", "cut", "bomb", "huge", "loop"} <= unreadable, unreadable)

    def test_directories_pointing_back_are_refused_at_once(self):
        # 1,000 entries, each pointing to the root itself as if it were a leaf directory:
        # 1,000 x 1,000 x 1,000 readings if each were followed.
        length = 0
        while True:  # the root's length is written inside the root: find the fixed point
            root = mf._directory([(k, 0, 0, length) for k in range(1000)])
            if len(root) == length:
                break
            length = len(root)
        head = bytearray(mf.pmtiles(town())[:127])
        struct.pack_into("<2Q", head, 8, 127, length)
        struct.pack_into("<Q", head, 40, 127)  # leaf directories start where the root is
        path = self.write("fan.pmtiles", bytes(head) + root)
        with self.assertRaisesRegex(places.MapError, "read twice"):
            places.read_map(path)

    def test_a_damaged_map_is_not_read_again_and_again(self):
        self.write("noise.pmtiles", b"not a map at all")
        found = self.places()
        with mock.patch.object(places, "read_map") as read:
            found.refresh(now=True)
            found.wait()
        read.assert_not_called()
        self.assertTrue(found.ready)


class TestHostileMaps(PlacesTestCase):
    """A shared map may be made to keep a Campanile busy or to fill its memory: whatever it
    says, reading it costs a bounded amount, and a failure is remembered."""

    def raw(self, root: bytes, leaves: bytes = b"", data: bytes = b"") -> bytes:
        head = bytearray(mf.pmtiles(town())[:127])
        at = 127 + len(root)
        struct.pack_into("<8Q", head, 8, 127, len(root), at, 0, at, len(leaves), 0, 0)
        struct.pack_into("<2Q", head, 56, at + len(leaves), len(data))
        return bytes(head) + root + leaves + data

    def test_one_stream_read_again_with_a_byte_more_is_refused(self):
        # Each length makes another directory to read once: a million of them would mean
        # unpacking the same stream a million times.
        leaf = mf._directory([(mf.hilbert_id(Z, 0, 0), 1, 0, 10)])
        root = mf._directory([(k, 0, 0, len(leaf) + k) for k in range(50)])
        path = self.write("again.pmtiles", self.raw(root, leaf + bytes(50), bytes(10)))
        with self.assertRaisesRegex(places.MapError, "more than the stream"):
            places.read_map(path)

    def test_a_directory_with_too_many_entries_is_refused_before_reading_them(self):
        count = places.MAX_ENTRIES + 1
        root = gzip.compress(mf.varint(count) + bytes(4 * count))  # the smallest entries
        path = self.write("crowd.pmtiles", self.raw(root))
        with self.assertRaisesRegex(places.MapError, "directory size"):
            places.read_map(path)

    def test_a_number_where_text_should_be_is_refused_without_filling_memory(self):
        # Found by tests/fuzz_maps.py: a layer's name written as a number. bytes() of it
        # would have filled two gigabytes of memory, in the search and in the navigator.
        layer = mf.field(15, 2) + mf.field(1, 2**31) + mf.field(5, 4096)
        path = self.write("number.pmtiles", mf.pmtiles({(Z, 8538, 5862): mf.field(3, layer)}))
        tracemalloc.start()
        try:
            for read in (places.read_map, lambda p: routes.Network("number", p)):
                with self.assertRaisesRegex(places.MapError, "a number where"):
                    read(path)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 50 * 2**20)

    def test_a_tile_cut_short_or_damaged_is_refused_cleanly(self):
        # Also found by the fuzzer: these ended in IndexError and zlib.error, not a refusal.
        cut = self.write("cut.pmtiles", mf.pmtiles({(Z, 8538, 5862): bytes([0x1A, 0x80])}))
        data = bytearray(mf.pmtiles(town()))
        start = struct.unpack_from("<Q", data, 56)[0]  # where the tiles begin
        data[start + 12] ^= 0xFF  # inside the first tile's compressed stream
        damaged = self.write("damaged.pmtiles", bytes(data))
        for path in (cut, damaged):
            with self.subTest(path.name), self.assertRaises(places.MapError):
                places.read_map(path)

    def test_text_where_a_number_should_be_is_refused_cleanly(self):
        # Found by the fuzzer, case 28,945: a signed number written as bytes ended in TypeError.
        value = mf.field(6, b"xy")
        layer = mf.field(15, 2) + mf.field(1, b"roads") + mf.field(4, value) + mf.field(5, 4096)
        path = self.write("value.pmtiles", mf.pmtiles({(Z, 8538, 5862): mf.field(3, layer)}))
        for read in (places.read_map, lambda p: routes.Network("value", p)):
            with self.assertRaisesRegex(places.MapError, "where a number should be"):
                read(path)

    def test_a_header_pointing_outside_the_file_is_refused_cleanly(self):
        # Found by the fuzzer: offsets past the end, or too big for the system, ended in
        # OSError and ValueError instead of a refusal.
        for offset in (2**64 - 1, 2**63):  # past what the system can even seek to
            data = bytearray(mf.pmtiles(town()))
            struct.pack_into("<Q", data, 8, offset)  # where the root directory would be
            path = self.write("far.pmtiles", bytes(data))
            with self.subTest(offset=offset), self.assertRaises(places.MapError):
                places.read_map(path)

    def test_past_its_budget_a_map_is_given_up(self):
        path = self.write("town.pmtiles", mf.pmtiles(town()))
        self.assertTrue(places.read_map(path)["rows"])  # within every budget
        for kind in places.BUDGET:
            with (
                self.subTest(kind),
                mock.patch.dict(places.BUDGET, {kind: 1}),
                self.assertRaisesRegex(places.MapError, rf"too much work to read \({kind}\)"),
            ):
                places.read_map(path)

    def test_a_thousand_towns_of_one_name_keep_a_few(self):
        tiles: dict = {}
        for k in range(1000):  # all called the same, each 4 km from the next
            key, p = point(7.0 + k % 40 * 0.05, 45.0 + k // 40 * 0.04)
            same = ({"name": "Borgo Uguale", "kind": "locality"}, [p])
            tiles.setdefault(key, {}).setdefault("places", []).append(same)
        path = self.write("same.pmtiles", vector_map(tiles))
        rows = places.read_map(path)["rows"]
        self.assertEqual(sum(r[3] == "Borgo Uguale" for r in rows), places.MAX_SAME)

    def test_past_the_last_name_nothing_more_is_kept(self):
        # A million different names would otherwise each leave something in memory.
        reader = places._Reader(places._Work())
        with mock.patch.object(places, "MAX_NAMES", 10):
            for k in range(1000):
                reader.place({"name": f"Borgo {k}", "kind": "locality"}, 7.0, 45.0 + k / 100)
                reader.street({"name": f"Via {k}", "kind": "minor_road"}, [7, 45, 7, 45 + k])
                reader.point({"name": f"Bar {k}", "kind": "bar"}, 7.0, 45.0 + k / 100)
        kept = sum(map(len, (reader.places, reader.streets, reader.points)))
        self.assertEqual((reader.total, kept), (10, 10))

    def test_a_street_seen_again_takes_no_more_room(self):
        reader = places._Reader(places._Work())
        road = {"name": "Via Roma", "kind": "minor_road"}
        reader.street(road, [7.0, 45.01, 7.05, 45.01])  # in the middle of a row of cells
        listed = sum(len(p) if isinstance(p, tuple) else 1 for p in reader.grid.values())
        for box in (
            [7.0, 45.01, 7.05, 45.01],
            [7.01, 45.01, 7.02, 45.01],
            [7.04, 45.01, 7.06, 45.01],
        ):
            reader.street(road, box)  # the same, a piece inside it, one that reaches out a bit
        grown = sum(len(p) if isinstance(p, tuple) else 1 for p in reader.grid.values())
        self.assertEqual((reader.total, grown - listed), (1, 1))  # one street, one cell more

    def test_one_street_name_everywhere_costs_little(self):
        tiles: dict = {}
        for i in range(30):  # 900 short streets of one name, none touching another
            for j in range(30):
                key, (px, py) = point(7.0 + i * 0.01, 45.0 + j * 0.01)
                road = ({"name": "Via Uguale", "kind": "minor_road"}, [(px, py), (px + 1, py)])
                tiles.setdefault(key, {}).setdefault("roads", []).append(road)
        path = self.write("one.pmtiles", vector_map(tiles))
        work = places._Work()
        with mock.patch.object(places, "_Work", return_value=work):
            rows = places.read_map(path)["rows"]
        self.assertEqual(sum(r[3] == "Via Uguale" for r in rows), 900)
        # Compared only with the neighbours: comparing each with all would be 400,000 steps.
        self.assertLess(work.spent["steps"], 100 * 900)

    def test_a_map_that_failed_is_not_read_again_at_the_next_start(self):
        self.write("noise.pmtiles", b"not a map at all")
        self.places()  # tried, failed, remembered
        with mock.patch.object(places, "read_map") as read:
            self.assertTrue(self.places().ready)  # the next start
        read.assert_not_called()
        self.write("noise.pmtiles", b"not a map at all, changed")  # until the file changes
        with mock.patch.object(places, "read_map", side_effect=places.MapError("bad")) as read:
            self.places()
        read.assert_called_once()

    def test_a_map_that_kills_the_campanile_is_given_up(self):
        # Killed for real while building the index, as out of memory would: three starts,
        # then the map is left alone and the Campanile stays up.
        self.write("town.pmtiles", mf.pmtiles(town()))
        start = (
            "import sys; sys.path[:0] = sys.argv[1:3]\n"
            "import os, places\n"
            "if sys.argv[5] == 'kill': places.MapIndex = lambda *a: os._exit(137)\n"
            "found = places.Places(places.Path(sys.argv[3]), places.Path(sys.argv[4]))\n"
            "found.refresh(now=True); found.wait(60)\n"
            "print(sorted(found._indexes))\n"
        )
        here = Path(__file__).resolve().parent
        args = [str(here.parent / "campanile"), str(here), str(self.maps), str(self.cache)]

        def run(how):
            command = [sys.executable, "-c", start, *args, how]
            return subprocess.run(command, capture_output=True, text=True, timeout=60)  # noqa: S603

        codes = [run("kill").returncode for _ in range(places.TRIES)]
        self.assertEqual(codes, [137] * places.TRIES)
        self.assertFalse((self.cache / "town.json").exists())  # nothing saved halfway
        done = run("normal")  # the next start: not built again, not killed
        self.assertEqual((done.returncode, done.stdout.splitlines()[-1]), (0, "[]"))
        self.assertIn("cut short 3 times", (self.cache / "town.json").read_text())
        self.write("town.pmtiles", mf.pmtiles(town(far_street=False)))  # a new version: tried
        self.assertEqual(run("normal").stdout.splitlines()[-1], "['town']")

    def test_all_the_maps_together_have_a_ceiling(self):
        self.write("a.pmtiles", mf.pmtiles(town()))
        self.write("b.pmtiles", mf.pmtiles(town()))
        names = len(places.read_map(self.maps / "a.pmtiles")["rows"])
        with mock.patch.object(places, "TOTAL_NAMES", names + 1):
            found = self.places()
        self.assertEqual(sorted(found._indexes), ["a"])


if __name__ == "__main__":
    unittest.main()
