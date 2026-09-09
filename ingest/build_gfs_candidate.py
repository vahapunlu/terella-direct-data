"""Build a LOCAL weather candidate in Terella's existing shape, never upload it.

Three-hour forecast boundaries are supported, with metadata-checked
deaccumulation when needed. Deliberately not a live ingest.
"""
import argparse
import base64
import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re

import numpy as np

from noaa_grib import Grid, load_message, parse_index, read_url


def unique_field(grids, **expected):
    matches = [grid for grid in grids if all(grid.metadata.get(k) == v for k, v in expected.items())]
    if not matches:
        raise ValueError(f"Required scientific field absent: {expected}")
    first = matches[0]
    # NOAA can duplicate an accumulation record. Accept only exactly equal
    # scientific fields, not whichever index entry happened to appear first.
    for other in matches[1:]:
        if first.metadata != other.metadata or not np.array_equal(first.values, other.values):
            raise ValueError("Ambiguous duplicate field: decoded values or metadata differ")
    return first


def pack_rain(mm, scale=25):
    if not math.isfinite(mm) or mm < 0 or not math.isfinite(scale) or scale <= 0:
        raise ValueError("Invalid rain value/scale")
    return min(255, math.floor(255 * math.log1p(mm) / math.log1p(scale) + 0.5))


RAIN_ID = dict(discipline=0, parameterCategory=1, parameterNumber=8,
               typeOfLevel="surface", level=0, units="kg m**-2", stepType="accum",
               stepUnits=1, typeOfStatisticalProcessing=1)
SPATIAL_KEYS = ("gridType", "Ni", "Nj", "iDirectionIncrementInDegrees",
                "jDirectionIncrementInDegrees", "latitudeOfFirstGridPointInDegrees",
                "longitudeOfFirstGridPointInDegrees", "iScansNegatively",
                "jScansPositively", "jPointsAreConsecutive", "alternativeRowScanning")


def rain_window(grids, step, earlier=()):
    if type(step) is not int or step < 3 or step > 120 or step % 3:
        raise ValueError("Expected a three-hour forecast boundary within f003–f120")
    start = step - 3
    candidates = [g for g in grids if all(g.metadata.get(k) == v for k, v in RAIN_ID.items())
                  and g.metadata.get("endStep") == step]
    # Prefer a native three-hour field; other cumulative records are not duplicates.
    native = [g for g in candidates if g.metadata.get("startStep") == start]
    if native:
        result = unique_field(native, **RAIN_ID, startStep=start, endStep=step)
        method = "native-three-hour"
    else:
        starts = sorted({g.metadata["startStep"] for g in candidates
                         if 0 <= g.metadata["startStep"] < start}, reverse=True)
        if not starts:
            raise ValueError("No usable precipitation accumulation window")
        origin = starts[0]
        end = unique_field(candidates, **RAIN_ID, startStep=origin, endStep=step)
        begin = unique_field(earlier, **RAIN_ID, startStep=origin, endStep=start)
        if end.run_at != begin.run_at or any(end.metadata.get(k) != begin.metadata.get(k)
                                           for k in SPATIAL_KEYS):
            raise ValueError("Cannot subtract different model runs or spatial grids")
        if datetime.fromisoformat(begin.valid_at) - datetime.fromisoformat(begin.run_at) != timedelta(hours=start):
            raise ValueError("Earlier precipitation clock does not match its forecast step")
        if end.values.shape != begin.values.shape:
            raise ValueError("Different accumulation array shapes")
        if any(not np.isfinite(g.values).all() or np.min(g.values) < 0 for g in (end, begin)):
            raise ValueError("Invalid source accumulation")
        result = copy.copy(end)
        result.values = end.values - begin.values
        result.metadata = {**end.metadata, "startStep": start}
        method = f"difference-{origin}-{step}-minus-{origin}-{start}"
    # Even small negative differences fail closed pending packing-error validation.
    if not np.isfinite(result.values).all() or np.min(result.values) < 0:
        raise ValueError("Negative or non-finite accumulation; not dry weather")
    if datetime.fromisoformat(result.valid_at) - datetime.fromisoformat(result.run_at) != timedelta(hours=step):
        raise ValueError("Precipitation clock does not match its forecast step")
    return result, method


def make_weather(grids, fetched_at, step=3, earlier=()):
    common = {"discipline": 0, "stepUnits": 1, "startStep": step, "endStep": step,
              "stepType": "instant", "parameterCategory": 2, "units": "m s**-1",
              "uvRelativeToGrid": 0}
    u = unique_field(grids, **common, parameterNumber=2, typeOfLevel="heightAboveGround", level=10)
    v = unique_field(grids, **common, parameterNumber=3, typeOfLevel="heightAboveGround", level=10)
    ju = unique_field(grids, **common, parameterNumber=2, typeOfLevel="isobaricInhPa", level=250)
    jv = unique_field(grids, **common, parameterNumber=3, typeOfLevel="isobaricInhPa", level=250)
    rain, _ = rain_window(grids, step, earlier)
    used = [u, v, ju, jv, rain]
    if len({(g.run_at, g.valid_at) for g in used}) != 1:
        raise ValueError("Mixed model runs or validity times")
    if np.min(rain.values) < 0:
        raise ValueError("Negative accumulation; not dry weather")
    valid_at = u.valid_at
    if datetime.fromisoformat(valid_at) - datetime.fromisoformat(u.run_at) != timedelta(hours=step):
        raise ValueError("Wind clock does not match its forecast step")
    cells, jets = [], []
    for lat in range(-75, 76, 15):
        for lon in range(-180, 180, 15):
            # kg/m² of liquid-water equivalent equals mm. No arbitrary scaling.
            cells.append([lat, lon, round(u.sample(lat, lon), 2), round(v.sample(lat, lon), 2),
                          round(rain.sample(lat, lon), 2)])
            jets.append([lat, lon, round(ju.sample(lat, lon), 2), round(jv.sample(lat, lon), 2)])
    # Directly north → south: identical to the app's canonical texture order.
    rain_values = [rain.sample(86.25 - row * 7.5, -176.25 + col * 7.5)
                   for row in range(24) for col in range(48)]
    return {
        "cells": cells, "observedAt": valid_at, "fetchedAt": fetched_at,
        "jet": {"cells": jets, "levelHpa": 250, "approximateAltitudeKm": 10.4,
                "observedAt": valid_at, "fetchedAt": fetched_at},
        "rain": {"grid": base64.b64encode(bytes(pack_rain(v) for v in rain_values)).decode(),
                 "width": 48, "height": 24, "scaleMm": 25, "stepDegrees": 7.5,
                 "observedAt": valid_at, "fetchedAt": fetched_at},
    }


def main(date, cycle, resolution, output, step=3):
    day = datetime.strptime(date, "%Y-%m-%d").strftime("%Y%m%d")
    if cycle not in ("00", "06", "12", "18") or resolution not in ("1p00", "0p25"):
        raise ValueError("Unsupported cycle/resolution")
    if type(step) is not int or step < 3 or step > 120 or step % 3:
        raise ValueError("Expected a three-hour forecast boundary within f003–f120")
    prefix = (f"https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.{day}/{cycle}/atmos/"
              f"gfs.t{cycle}z.pgrb2.{resolution}.f")
    url = prefix + f"{step:03d}"
    records = parse_index(read_url(url + ".idx").decode())
    chosen = [r for r in records if re.search(
        r":(?:UGRD|VGRD):(?:10 m above ground|250 mb):|:APCP:surface:", r.line)]
    with ThreadPoolExecutor(max_workers=3) as pool:
        raw = list(pool.map(lambda r: load_message(url, r, ".cache/direct-weather/grib"), chosen))
    grids = [Grid(message) for message in raw]
    earlier, earlier_raw = [], []
    earlier_url = None
    if not any(all(g.metadata.get(k) == v for k, v in RAIN_ID.items())
               and g.metadata.get("startStep") == step - 3
               and g.metadata.get("endStep") == step for g in grids) and step > 3:
        earlier_url = prefix + f"{step - 3:03d}"
        previous = [r for r in parse_index(read_url(earlier_url + ".idx").decode())
                    if ":APCP:surface:" in r.line]
        with ThreadPoolExecutor(max_workers=3) as pool:
            earlier_raw = list(pool.map(lambda r: load_message(
                earlier_url, r, ".cache/direct-weather/grib"), previous))
        earlier = [Grid(message) for message in earlier_raw]
    expected_run = f"{date}T{cycle}:00:00Z"
    if not grids or any(g.run_at != expected_run for g in grids + earlier):
        raise ValueError("Source returned a different model cycle")
    weather = make_weather(grids, datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), step, earlier)
    _, rain_method = rain_window(grids, step, earlier)
    candidate = {"schema": 1, "status": "local-candidate-not-production", "publicationAllowed": False,
                 "source": {"model": "NOAA GFS", "url": url, "runAt": grids[0].run_at,
                            "sourceGridDegrees": grids[0].dx,
                            "sampling": "bilinear; no elevation downscaling",
                            "forecastHour": step, "rainWindowHours": [step - 3, step],
                            "rainMethod": rain_method, "earlierRainUrl": earlier_url,
                            "selectedBytes": sum(len(r) for r in raw + earlier_raw)}, "weather": weather}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(candidate, separators=(",", ":"), allow_nan=False) + "\n")
    print(f"Candidate: {len(weather['cells'])} wind, {len(weather['jet']['cells'])} jet, "
          f"{len(base64.b64decode(weather['rain']['grid']))} rain cells; {output.stat().st_size} bytes")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True)
    parser.add_argument("--cycle", required=True)
    parser.add_argument("--resolution", choices=["1p00", "0p25"], default="0p25")
    parser.add_argument("--step", type=int, default=3, help="Forecast hour: 3, 6, …, 120")
    parser.add_argument("--output", type=Path, default=Path(".cache/direct-weather/gfs-candidate.json"))
    args = parser.parse_args()
    main(args.date, args.cycle, args.resolution, args.output, args.step)
