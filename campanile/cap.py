# DEVELOPED BY CARROTSTUDIO software house
"""Official alerts in CAP, the Common Alerting Protocol (OASIS, versions 1.1 and 1.2).

CAP is how public warnings travel between systems, in Italy too: the Italian profiles (the
civil protection's CAP-IT behind IT-alert, the fire brigade's) only add rules on top of CAP 1.1
and 1.2. Whoever runs the Campanile loads one alert and it becomes a notice. Only the fields a
notice needs are read; the rest of CAP is not used.

The file comes from outside, so: no DTD at all (no entities, nothing fetched), a size cap, and
anything this reader does not understand is refused with a reason, never guessed.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime

NAMESPACES = ("urn:oasis:names:tc:emergency:cap:1.2", "urn:oasis:names:tc:emergency:cap:1.1")
MAX_BYTES = 512 * 1024  # IT-alert's own, with the polygons of their areas: up to 108 kB seen
TITLE_MAX = 160  # CAP: "160 characters MAY be a useful target limit" for a headline
TEXT_MAX = 2000  # an official text is never shortened: longer is refused

VALUES = {
    "category": {
        "Geo",
        "Met",
        "Safety",
        "Security",
        "Rescue",
        "Fire",
        "Health",
        "Env",
        "Transport",
        "Infra",
        "CBRNE",
        "Other",
    },
    "urgency": {"Immediate", "Expected", "Future", "Past", "Unknown"},
    "severity": {"Extreme", "Severe", "Moderate", "Minor", "Unknown"},
    "certainty": {"Observed", "Likely", "Possible", "Unlikely", "Unknown"},
}
URGENT = {"Extreme", "Severe"}  # shown in red, at the top


class CapError(Exception):
    """A refusal: `key` is in messages.MESSAGES."""

    def __init__(self, key: str, **params):
        super().__init__(key)
        self.key, self.params = key, params


def read(document: str, languages: list[str], now: float) -> dict:
    """The alert as a notice: title, text, urgent, expires, source and key (sender, identifier).

    `languages`: the preferred ones, first; an alert can carry its text in several."""
    if len(document.encode("utf-8", "surrogatepass")) > MAX_BYTES:
        raise CapError("cap_too_big", max=MAX_BYTES // 1024)
    if re.search(r"<!DOCTYPE|<!ENTITY", document, re.IGNORECASE):
        raise CapError("cap_unsafe")
    try:
        root = ET.fromstring(document)  # noqa: S314 - no DTD can reach here: refused above
    except (ET.ParseError, ValueError):  # ValueError: an encoding it can't read
        raise CapError("cap_bad") from None
    ns = root.tag[1:].partition("}")[0] if root.tag.startswith("{") else ""
    if ns not in NAMESPACES or root.tag != f"{{{ns}}}alert":
        raise CapError("cap_not_cap")

    def field(parent, name: str) -> str:
        found = parent.find(f"{{{ns}}}{name}")
        return (found.text or "").strip() if found is not None else ""

    for name in ("identifier", "sender", "sent", "status", "msgType", "scope"):
        if not field(root, name):
            raise CapError("cap_missing", field=name)
    status, kind = field(root, "status"), field(root, "msgType")
    if status == "Exercise":
        raise CapError("cap_exercise")
    if status != "Actual":  # Test, System, Draft
        raise CapError("cap_not_actual", state=status)
    if kind == "Cancel":
        raise CapError("cap_cancel")
    if kind not in ("Alert", "Update"):  # Ack, Error
        raise CapError("cap_not_alert", kind=kind)
    if field(root, "scope") != "Public":
        raise CapError("cap_not_public")

    infos = root.findall(f"{{{ns}}}info")
    if not infos:
        raise CapError("cap_missing", field="info")
    for block in infos:  # one broken block, in any language, is a broken alert
        for name in ("category", "event", "urgency", "severity", "certainty"):
            if not field(block, name):
                raise CapError("cap_missing", field=name)
        for name, allowed in VALUES.items():
            values = [(v.text or "").strip() for v in block.findall(f"{{{ns}}}{name}")]
            if any(v not in allowed for v in values):
                raise CapError("cap_bad_value", field=name)
    info = _pick(infos, languages, field)

    expires = field(info, "expires")
    when = _time(expires) if expires else None
    if when is not None and when <= now:
        raise CapError("cap_expired")
    text = "\n\n".join(t for t in (field(info, "description"), field(info, "instruction")) if t)
    return {
        "title": field(info, "headline") or field(info, "event"),
        "text": text or field(info, "event"),
        "urgent": field(info, "severity") in URGENT,
        "expires": when,
        "source": field(info, "senderName") or field(root, "sender"),
        # CAP forbids spaces in both: one space keeps them apart.
        "key": f"{field(root, 'sender')} {field(root, 'identifier')}",
    }


def _pick(infos, languages: list[str], field):
    """The block in the first preferred language; else the first. No language means en-US."""

    def language(info) -> str:
        return (field(info, "language") or "en-US").split("-")[0].lower()

    for wanted in languages:
        for info in infos:
            if language(info) == wanted:
                return info
    return infos[0]


def _time(value: str) -> int:
    """CAP times carry their offset ("2011-03-25T13:00:07+02:00"; UTC is "-00:00"). CAP forbids
    a final Z, but it is plainly UTC: an alert is not refused over it."""
    try:
        when = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        raise CapError("cap_bad_time") from None
    if when.tzinfo is None:
        raise CapError("cap_bad_time")
    return int(when.timestamp())
