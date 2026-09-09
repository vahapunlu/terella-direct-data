"""Read-only, bounded NOAA public GRIB access. No credentials or publication.

The index is only a locator. Scientific identity is checked on decoded GRIB
metadata by the caller, never inferred from a filename or short index label.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import http.client
import math
from pathlib import Path
import re
import time
import urllib.parse
import urllib.error
import urllib.request

import eccodes as ec
import numpy as np

MAX_MESSAGE_BYTES = 16 * 1024 * 1024
ALLOWED_HOSTS = {"noaa-gfs-bdp-pds.s3.amazonaws.com", "noaa-gefs-pds.s3.amazonaws.com"}


def read_url(url, *, start=None, end=None):
    for attempt in range(3):
        try:
            return _read_url_once(url, start=start, end=end)
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
        except (TimeoutError, urllib.error.URLError, ConnectionError, http.client.IncompleteRead):
            if attempt == 2:
                raise
        time.sleep(2 ** (attempt + 1))
    raise RuntimeError("Unreachable download state")


def _read_url_once(url, *, start=None, end=None):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc not in ALLOWED_HOSTS:
        raise ValueError("Only anonymous NOAA public-data buckets are allowed")
    headers = {"User-Agent": "Terella-data-validation/1.0"}
    limit = 1024 * 1024
    if start is not None:
        if end is None or not 0 <= start <= end or end - start >= MAX_MESSAGE_BYTES:
            raise ValueError("Invalid or oversized byte range")
        headers["Range"] = f"bytes={start}-{end}"
        limit = end - start + 1
    began = time.monotonic()
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
        if response.url != url:
            raise ValueError("Unexpected source redirect")
        if start is not None:
            if response.status != 206:
                raise ValueError("Source ignored byte range; refusing full GRIB download")
            value = response.headers.get("Content-Range", "")
            if not re.fullmatch(rf"bytes {start}-{end}/\d+", value):
                raise ValueError("Mismatched Content-Range")
        elif response.status != 200:
            raise ValueError(f"Unexpected index response: {response.status}")
        parts, total = [], 0
        while True:
            chunk = response.read(min(65536, limit + 1 - total))
            if not chunk:
                break
            parts.append(chunk)
            total += len(chunk)
            if total > limit:
                raise ValueError("Source response exceeds size budget")
            if time.monotonic() - began > 60:
                raise TimeoutError("Source response exceeds time budget")
        result = b"".join(parts)
        if start is not None and len(result) != limit:
            raise ValueError("Truncated GRIB range")
        return result


@dataclass(frozen=True)
class IndexRecord:
    line: str
    start: int
    end: int | None


def parse_index(text):
    lines = [line for line in text.splitlines() if line.strip()]
    offsets = []
    for line in lines:
        fields = line.split(":")
        if len(fields) < 6 or not fields[1].isdigit() or not fields[2].startswith("d="):
            raise ValueError("Malformed NOAA index")
        offsets.append(int(fields[1]))
    if not offsets or offsets[0] != 0 or any(a >= b for a, b in zip(offsets, offsets[1:])):
        # Shared offsets denote multi-field messages; not supported silently.
        raise ValueError("Index offsets must be strictly increasing from zero")
    return [IndexRecord(line, offsets[i], offsets[i + 1] - 1 if i + 1 < len(lines) else None)
            for i, line in enumerate(lines)]


def load_message(url, record, cache_dir):
    if record.end is None:
        raise ValueError("Last index record needs an explicit object length")
    key = hashlib.sha256(f"{url}:{record.start}:{record.end}".encode()).hexdigest()
    path = Path(cache_dir) / f"{key}.grib2"
    if path.exists():
        raw = path.read_bytes()
    else:
        raw = read_url(url, start=record.start, end=record.end)
    validate_message(raw, record.end - record.start + 1)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return raw


def validate_message(raw, expected_length):
    if len(raw) != expected_length or len(raw) < 20 or raw[:4] != b"GRIB" or raw[7] != 2:
        raise ValueError("Not one complete GRIB2 message")
    if int.from_bytes(raw[8:16], "big") != len(raw) or raw[-4:] != b"7777":
        raise ValueError("GRIB message length/trailer mismatch")


META_KEYS = (
    "centre", "subCentre", "tablesVersion", "localTablesVersion",
    "shortName", "name", "units", "discipline", "parameterCategory", "parameterNumber",
    "typeOfLevel", "level", "stepType", "startStep", "endStep", "stepUnits",
    "dataDate", "dataTime", "validityDate", "validityTime", "gridType", "Ni", "Nj",
    "iDirectionIncrementInDegrees", "jDirectionIncrementInDegrees",
    "latitudeOfFirstGridPointInDegrees", "longitudeOfFirstGridPointInDegrees",
    "iScansNegatively", "jScansPositively", "jPointsAreConsecutive", "alternativeRowScanning",
    "uvRelativeToGrid", "numberOfMissing", "productDefinitionTemplateNumber",
    "typeOfStatisticalProcessing", "constituentType", "aerosolType",
    "typeOfSizeInterval", "typeOfWavelengthInterval",
    "scaledValueOfFirstSize", "scaleFactorOfFirstSize",
    "scaledValueOfSecondSize", "scaleFactorOfSecondSize",
    "scaledValueOfFirstWavelength", "scaleFactorOfFirstWavelength",
    "scaledValueOfSecondWavelength", "scaleFactorOfSecondWavelength",
)


def stamp(date, clock):
    return datetime.strptime(f"{int(date):08d}{int(clock):04d}", "%Y%m%d%H%M").replace(
        tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


class Grid:
    def __init__(self, raw):
        handle = ec.codes_new_from_message(raw)
        try:
            self.metadata = {}
            for key in META_KEYS:
                if ec.codes_is_defined(handle, key):
                    self.metadata[key] = ec.codes_get(handle, key)
            m = self.metadata
            if m.get("gridType") != "regular_ll" or any(m.get(k, 0) for k in (
                "iScansNegatively", "jScansPositively", "jPointsAreConsecutive", "alternativeRowScanning"
            )):
                raise ValueError("Unsupported grid orientation")
            if m.get("numberOfMissing", 0):
                raise ValueError("Missing model values; refusing to invent zeros")
            if not 1 <= int(m["Ni"]) * int(m["Nj"]) <= 2_000_000:
                raise ValueError("Decoded grid exceeds memory budget")
            self.values = ec.codes_get_values(handle).reshape(int(m["Nj"]), int(m["Ni"]))
            if not np.isfinite(self.values).all():
                raise ValueError("Non-finite model field")
            self.lat0 = float(m["latitudeOfFirstGridPointInDegrees"])
            self.lon0 = float(m["longitudeOfFirstGridPointInDegrees"])
            self.dx = float(m["iDirectionIncrementInDegrees"])
            self.dy = float(m["jDirectionIncrementInDegrees"])
            if self.dx <= 0 or self.dy <= 0 or not math.isclose(self.dx * int(m["Ni"]), 360):
                raise ValueError("Expected a complete periodic global grid")
            self.valid_at = stamp(m["validityDate"], m["validityTime"])
            self.run_at = stamp(m["dataDate"], m["dataTime"])
        finally:
            ec.codes_release(handle)

    def require(self, **expected):
        for key, value in expected.items():
            if self.metadata.get(key) != value:
                raise ValueError(f"Unexpected {key}: {self.metadata.get(key)!r}; expected {value!r}")
        return self

    def sample(self, lat, lon):
        """Bilinear interpolation, periodic at the date line, never nearest city."""
        if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90:
            raise ValueError("Invalid sample coordinate")
        y = (self.lat0 - lat) / self.dy
        if not 0 <= y <= self.values.shape[0] - 1:
            raise ValueError("Latitude outside source grid")
        x = ((lon - self.lon0) % 360) / self.dx
        x0, y0 = math.floor(x), math.floor(y)
        x1, y1 = (x0 + 1) % self.values.shape[1], min(y0 + 1, self.values.shape[0] - 1)
        fx, fy = x - x0, y - y0
        return float((1-fy)*((1-fx)*self.values[y0, x0] + fx*self.values[y0, x1]) +
                     fy*((1-fx)*self.values[y1, x0] + fx*self.values[y1, x1]))

    def summary(self):
        return {**self.metadata, "runAt": self.run_at, "validAt": self.valid_at,
                "min": float(self.values.min()), "max": float(self.values.max()),
                "sha256": hashlib.sha256(self.values.tobytes()).hexdigest()}
