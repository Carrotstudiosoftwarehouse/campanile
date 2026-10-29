# DEVELOPED BY CARROTSTUDIO software house
"""JSON read strictly, in one place, for everything that comes from outside.

Refused: a key written twice (readers pick different ones: with signed text, one program could
check one value and another show a different one), NaN and Infinity (not JSON at all), and
nesting too deep to read. Every refusal is a ValueError, so no caller can miss one.
"""

from __future__ import annotations

import json


def loads(text: str):
    try:
        return json.loads(text, object_pairs_hook=_unique, parse_constant=_not_json)
    except RecursionError:
        raise ValueError("nested too deep") from None


def _unique(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key: {key}")
        result[key] = value
    return result


def _not_json(name: str):
    raise ValueError(f"{name} is not JSON")
