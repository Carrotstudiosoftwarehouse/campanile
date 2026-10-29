# DEVELOPED BY CARROTSTUDIO software house
"""Pages and maps from disk: never from outside their folder, a piece at a time when asked
(Range), and a whole map paced so one phone can't take the Wi-Fi."""

from __future__ import annotations

import re
import time
from pathlib import Path

from store import RequestError

CHUNK_SIZE = 64 * 1024
# A map viewer asks one tile at a time (322 kB at most in ours). Past MAP_FREE it's a whole map
# being downloaded: paced, so one phone can't take the Wi-Fi. nginx-site.sh too.
MAP_FREE = 8 * 2**20
MAP_RATE = 128 * 2**10

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/plain; charset=utf-8",
    ".pbf": "application/x-protobuf",
    ".pmtiles": "application/octet-stream",
}

_RANGE = re.compile(r"^bytes=([0-9]{0,15})-([0-9]{0,15})$")  # ASCII digits, a sane length
MAP_NAME = re.compile(r"[A-Za-z0-9_-]+\.pmtiles")


# On Windows "a:b" is the hidden stream b of file a (measured: we served a download's
# Zone.Identifier, which says where it came from), "\\" is a separator, and a trailing dot or
# space is dropped. None of our files has such names, so these paths are treated as missing.
_WINDOWS_TRICKS = re.compile(r"[:\\]|[. ](/|$)")


def safe_path(root: Path, relative: str) -> Path | None:
    """Nobody gets out of the root folder: no ../../etc/passwd tricks."""
    if "\x00" in relative or _WINDOWS_TRICKS.search(relative):
        return None
    candidate = (root / relative.lstrip("/")).resolve()
    return candidate if candidate.is_relative_to(root) else None


def parse_range(value: str, size: int):
    """Reads the Range header the map uses to fetch only the pieces it needs.

    One range at a time: if more are asked for we send the whole file, which is
    allowed. Returns (start, end), None, or "invalid".
    """
    m = _RANGE.match(value.strip())
    if not m or m.group(1) == m.group(2) == "":
        return None
    first, last = m.groups()
    if first == "":
        n = int(last)
        if n == 0 or size == 0:
            return "invalid"
        return max(0, size - n), size - 1
    start = int(first)
    if start >= size:
        return "invalid"
    end = size - 1 if last == "" else min(int(last), size - 1)
    return (start, end) if end >= start else None


class Files:
    """The pages and the maps: the request handler's part that reads files."""

    def _static(self, path: str):
        if path.startswith("/maps/"):
            name = path.removeprefix("/maps/")
            if not MAP_NAME.fullmatch(name):
                raise RequestError(404, "map_not_found")
            return self._file(safe_path(self.cfg.maps, name), rate=MAP_RATE, free=MAP_FREE)
        if path.endswith("/"):
            path += "index.html"
        return self._file(safe_path(self.cfg.web, path))

    def _file(self, file: Path | None, rate: int | None = None, free: int = 0):
        """The file, or the part asked for. Past `free` bytes, at most `rate` a second."""
        if file is None or not file.is_file():
            raise RequestError(404, "not_found")
        stat = file.stat()
        size = stat.st_size
        extra = {
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-cache",
            "ETag": f'"{stat.st_mtime_ns:x}-{size:x}"',
        }

        byte_range = None
        if "Range" in self.headers:
            byte_range = parse_range(self.headers["Range"], size)
            if byte_range == "invalid":
                return self._headers(416, None, 0, {"Content-Range": f"bytes */{size}"})

        if byte_range is None:
            start, end, status = 0, size - 1, 200
        else:
            (start, end), status = byte_range, 206
            extra["Content-Range"] = f"bytes {start}-{end}/{size}"
        length = end - start + 1

        mime = MIME_TYPES.get(file.suffix.lower(), "application/octet-stream")
        self._headers(status, mime, length, extra)
        if self.command == "HEAD":
            return
        self.server.responding(self)
        try:
            with open(file, "rb") as f:
                f.seek(start)
                began, sent = time.monotonic(), 0
                while length > 0 and (chunk := f.read(min(CHUNK_SIZE, length))):
                    self.wfile.write(chunk)
                    length -= len(chunk)
                    sent += len(chunk)
                    if rate and (ahead := (sent - free) / rate - (time.monotonic() - began)) > 0:
                        time.sleep(ahead)  # bytes per second, at most
        finally:
            self.server.done_responding(self)
