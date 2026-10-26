# DEVELOPED BY CARROTSTUDIO software house
"""The "I'm safe" registry in PFIF 1.4, the People Finder Interchange Format.

PFIF was made after Hurricane Katrina and carried Google Person Finder's records after the
earthquakes in Haiti and Japan. After an emergency, whoever runs the Campanile can hand its
names to a larger registry in this format. Only what PFIF asks for leaves: never a phone's
tag, never the codes that remove a name.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone

NS = "http://zesty.ca/pfif/1.4"
# Anyone can register any name: whoever reads the file elsewhere must know.
UNVERIFIED = (
    "Registered as safe on a Campanile, an offline neighborhood hub. Anyone there can register"
    " any name: not verified."
)
REGISTERED = "Registered as safe."


def _time(seconds: float) -> str:
    """PFIF times are UTC only, with a final Z."""
    return datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def export(people: list[dict], domain: str, now: float, keep: int) -> bytes:
    """`people`: the registry's rows (id, name, message, place, created). `domain` names this
    Campanile in the record ids; `keep`: seconds a name is kept here, 0 for ever."""
    ET.register_namespace("pfif", NS)

    def add(parent, name: str, text: str) -> None:
        ET.SubElement(parent, f"{{{NS}}}{name}").text = text

    root = ET.Element(f"{{{NS}}}pfif")
    for p in people:
        person_id = f"{domain}/person.{p['id']}"
        person = ET.SubElement(root, f"{{{NS}}}person")
        add(person, "person_record_id", person_id)
        add(person, "entry_date", _time(now))
        if keep:
            add(person, "expiry_date", _time(p["created"] + keep))
        add(person, "source_name", "Campanile")
        add(person, "source_date", _time(p["created"]))
        add(person, "full_name", p["name"])
        add(person, "description", UNVERIFIED)
        note = ET.SubElement(person, f"{{{NS}}}note")
        add(note, "note_record_id", f"{domain}/note.{p['id']}")
        add(note, "person_record_id", person_id)
        add(note, "entry_date", _time(now))
        add(note, "author_name", "Campanile")
        add(note, "source_date", _time(p["created"]))
        # Someone said this person is alive; that the person wrote it, no one can tell.
        add(note, "status", "believed_alive")
        if p["place"]:
            add(note, "last_known_location", p["place"])
        add(note, "text", p["message"] or REGISTERED)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
