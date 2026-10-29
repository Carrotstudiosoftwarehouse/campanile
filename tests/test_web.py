# DEVELOPED BY CARROTSTUDIO software house
"""The page texts: every key in every language, and the Italian in the HTML matching the catalog.

Pages are written in Italian and translated in the browser. If a key is missing, an English
phone would see the raw key; if the HTML drifts from the catalog, Italian and English phones
would read two different things. Both are caught here, without a browser.
"""

import json
import re
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "campanile"))
import places
import store

WEB = Path(__file__).resolve().parent.parent / "campanile" / "web"
PAGES = sorted(WEB.glob("*.html"))
SCRIPTS = sorted(p for p in WEB.glob("*.js") if p.name != "strings.js")


def catalog():
    source = (WEB / "strings.js").read_text(encoding="utf-8")
    return json.loads(source.split("export const STRINGS =", 1)[1].strip().rstrip(";"))


class Marked(HTMLParser):
    """Collects (key, Italian text) for each data-i18n* attribute of a page."""

    def __init__(self):
        super().__init__()
        self.found = []  # (attribute, key, Italian text)
        self.open = []  # [key, tag, collected text] of elements whose text is being read

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "data-i18n-ph" in attrs:
            self.found.append(("ph", attrs["data-i18n-ph"], attrs.get("placeholder", "")))
        if "data-i18n-aria" in attrs:
            self.found.append(("aria", attrs["data-i18n-aria"], attrs.get("aria-label", "")))
        if "data-emergency" in attrs:  # the page puts the number in: 112 in the HTML
            self.open.append([attrs["data-i18n"], tag, "", "emergency"])
            if attrs["data-emergency"]:
                self.found.append(("emergency-other", attrs["data-emergency"], ""))
        elif "data-i18n" in attrs:
            self.open.append([attrs["data-i18n"], tag, "", "text"])
        elif "data-i18n-title" in attrs:
            self.open.append([attrs["data-i18n-title"], tag, "", "text"])

    def handle_data(self, data):
        if self.open:
            self.open[-1][2] += data

    def handle_endtag(self, tag):
        if self.open and self.open[-1][1] == tag:
            key, tag, text, kind = self.open.pop()
            text = " ".join(text.split())
            if tag == "title":
                text = text.removesuffix(" · Campanile")
            self.found.append((kind, key, text))


def marked(page):
    parser = Marked()
    parser.feed(page.read_text(encoding="utf-8"))
    return parser.found


def keys_in_scripts():
    keys = set()
    for script in SCRIPTS:
        source = script.read_text(encoding="utf-8")
        keys |= set(re.findall(r'\bt\(\s*"([\w.]+)"', source))
        for key in re.findall(r'\btn\(\s*"([\w.]+)"', source):
            keys |= {key + "_one", key + "_other"}
        keys |= set(re.findall(r'\bbutton:\s*"([\w.]+)"', source))  # showMine's button label
    # Built from a value at runtime: listed here so they are checked too.
    for intent in ("need", "offer"):
        keys |= {f"board.{intent}.{part}" for part in ("title", "intro", "write", "form")}
    keys |= {f"cat.{c}" for c in store.CATEGORIES} | {f"kind.{k}" for k in store.POST_KINDS}
    # Every step and every error the setup can report is shown on the page.
    setup = (WEB.parent / "preparation.py").read_text(encoding="utf-8")
    keys |= {f"setup.step.{s}" for s in re.findall(r'step="(\w+)"', setup)} | {"setup.step.start"}
    keys |= {f"setup.error.{e}" for e in re.findall(r'SetupError\(\s*"(\w+)"', setup)}
    keys |= {"setup.error.cancelled", "setup.error.failed"}
    signature = (WEB.parent / "release.py").read_text(encoding="utf-8")  # can end the update job
    keys |= {f"setup.error.{e}" for e in re.findall(r'ReleaseError\(\s*"(\w+)"', signature)}
    copy = (WEB.parent / "copying.py").read_text(encoding="utf-8")
    keys |= {f"setup.error.{e}" for e in re.findall(r'CopyError\(\s*"(\w+)"', copy)} - {
        "setup.error.cancelled"
    }
    keys |= {f"setup.task.{t}" for t in ("map-world", "map-area", "wiki-it", "wiki-en")}
    keys |= {"setup.task.extras", "setup.task.copy", "setup.task.receive", "setup.task.update"}
    keys |= {"map.name.world", "map.name.area"}
    return keys


class TestStrings(unittest.TestCase):
    def setUp(self):
        self.strings = catalog()

    def test_every_language_has_every_key(self):
        reference = set(self.strings["it"])
        for lang, texts in self.strings.items():
            self.assertEqual(set(texts) ^ reference, set(), lang)

    def test_placeholders_match_across_languages(self):
        for key, italian in self.strings["it"].items():
            wanted = set(re.findall(r"\{(\w+)\}", italian))
            for lang, texts in self.strings.items():
                self.assertEqual(set(re.findall(r"\{(\w+)\}", texts[key])), wanted, (lang, key))

    def test_no_markup_and_no_empty_text(self):
        for lang, texts in self.strings.items():
            for key, text in texts.items():
                self.assertTrue(text.strip(), (lang, key))
                self.assertNotRegex(text, r"[<>]|&\w+;", (lang, key))

    def test_the_quick_buttons_search_a_kind_the_server_knows(self):
        # "Farmacia" must find the nearest pharmacies, not only places named so.
        words = {(lang, k): w for lang, texts in self.strings.items() for k, w in texts.items()}
        quick = {key: word for key, word in words.items() if key[1].startswith("search.q.")}
        self.assertEqual(len(quick), 4 * len(self.strings))
        for key, word in quick.items():
            self.assertIn(places.normalize(word), places.SYNONYMS, key)

    def test_every_key_used_by_the_pages_exists(self):
        used = {key for page in PAGES for _, key, _ in marked(page)} | keys_in_scripts()
        self.assertEqual(used - set(self.strings["it"]), set())

    def test_the_italian_in_the_html_is_the_italian_in_the_catalog(self):
        italian = self.strings["it"]
        for page in PAGES:
            for attribute, key, text in marked(page):
                if attribute == "emergency-other":
                    continue  # only in the catalog: for numbers other than 112
                with self.subTest(page=page.name, key=key, attribute=attribute):
                    wanted = italian[key]
                    if attribute == "emergency":
                        wanted = wanted.replace("{n}", store.EMERGENCY)
                    self.assertEqual(text, wanted)

    def test_a_sentence_with_a_number_is_one_the_page_fills(self):
        # translatePage() gives no values: a {n} there would show as nothing.
        italian = self.strings["it"]
        for page in PAGES:
            for attribute, key, _ in marked(page):
                if attribute == "text":
                    self.assertNotRegex(italian[key], r"\{\w+\}", (page.name, key))

    def test_every_page_with_a_script_translates_itself(self):
        for page in PAGES:
            scripts = re.findall(r'<script type="module" src="/(\w+\.js)"', page.read_text())
            for name in scripts:
                self.assertIn("translatePage()", (WEB / name).read_text(), name)

    def test_pages_and_server_agree_on_the_categories(self):
        source = (WEB / "common.js").read_text(encoding="utf-8")
        listed = re.search(r"CATEGORIES = \[(.*?)\]", source, re.S).group(1)
        self.assertEqual(tuple(re.findall(r'"(\w+)"', listed)), store.CATEGORIES)

    def test_every_action_in_the_log_has_its_words(self):
        source = (WEB.parent / "server.py").read_text(encoding="utf-8")
        actions = set(re.findall(r'self\._log\("(\w+)"', source))
        self.assertGreater(len(actions), 14)  # the search sees the calls
        for lang, strings in catalog().items():
            self.assertEqual(sorted(a for a in actions if f"log.{a}" not in strings), [], lang)

    def test_the_marker_finds_what_it_should(self):
        # Self-check of the parser above: a blind parser would make the tests pass on nothing.
        found = marked(WEB / "board.html")
        self.assertIn(("text", "board.page", "Bacheca"), found)
        self.assertIn(("ph", "board.form.area.ph", "Es.: piazza del mercato"), found)
        self.assertIn(("aria", "board.filter.kind", "Tipo"), found)
        self.assertGreater(sum(len(marked(p)) for p in PAGES), 150)
        self.assertGreater(len([k for k in keys_in_scripts() if k.startswith("setup.error.")]), 7)


class TestLayout(unittest.TestCase):
    def test_the_style_follows_the_reading_direction(self):
        # start and end, never left or right: so Arabic gets mirrored pages for free
        css = (WEB / "style.css").read_text(encoding="utf-8")
        one_sided = re.findall(
            r"(?:margin|padding|border)-(?:left|right)|(?:text-align|float):\s*(?:left|right)", css
        )
        self.assertEqual(one_sided, [])


if __name__ == "__main__":
    unittest.main()
