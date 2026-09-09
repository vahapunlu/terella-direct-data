"""LOCAL GFS UTC daily-mean candidate. No climate anomaly or publication."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np

from build_gfs_candidate import SPATIAL_KEYS, unique_field
from noaa_grib import Grid, load_message, parse_index, read_url

ROOT = Path(__file__).resolve().parents[1]
TEMP_ID = dict(discipline=0, parameterCategory=0, parameterNumber=0,
               typeOfLevel="heightAboveGround", level=2, units="K", stepType="instant",
               stepUnits=1)


def utc_day(day):
    result = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if result.strftime("%Y-%m-%d") != day:
        raise ValueError("Expected canonical YYYY-MM-DD")
    return result


def forecast_hours(date, cycle, target):
    if cycle not in ("00", "06", "12", "18"):
        raise ValueError("Unsupported GFS cycle")
    run = utc_day(date) + timedelta(hours=int(cycle))
    first = int((utc_day(target) - run).total_seconds() / 3600)
    if first < 0 or first + 23 > 120:
        raise ValueError("Whole UTC day must fit within this run's hourly f000–f120 horizon")
    return run, list(range(first, first + 24))


def daily_mean(grids, sites, target, expected_run):
    start = utc_day(target)
    seen, samples, reference = set(), [], None
    for grid in grids:
        grid.require(**TEMP_ID)
        valid = datetime.fromisoformat(grid.valid_at)
        elapsed = (valid - start).total_seconds() / 3600
        if not elapsed.is_integer() or not 0 <= elapsed < 24 or int(elapsed) in seen:
            raise ValueError("Duplicate or out-of-day temperature hour")
        step = (valid - expected_run).total_seconds() / 3600
        if (grid.run_at != expected_run.isoformat().replace("+00:00", "Z")
                or not step.is_integer() or not 0 <= step <= 120
                or grid.metadata.get("startStep") != step or grid.metadata.get("endStep") != step):
            raise ValueError("Mixed model run or inconsistent forecast clock")
        spatial = {key: grid.metadata.get(key) for key in SPATIAL_KEYS}
        if reference is not None and spatial != reference:
            raise ValueError("Spatial grid changed within daily temperature")
        reference = spatial
        row = np.array([grid.sample(s["lat"], s["lon"]) for s in sites], dtype=float)
        if not row.size or not np.isfinite(row).all() or row.min() < 100 or row.max() > 400:
            raise ValueError("Missing or implausible Kelvin temperature")
        seen.add(int(elapsed))
        samples.append((int(elapsed), row))
    if seen != set(range(24)):
        raise ValueError("Daily mean needs all 24 distinct UTC hours; no partial-day fallback")
    hourly = np.array([row for _, row in sorted(samples)])
    return (hourly.mean(axis=0) - 273.15).tolist()


def main(date, cycle, target, output):
    run, steps = forecast_hours(date, cycle, target)
    manifest = json.loads((ROOT / "data/sample-sites.json").read_text())
    sites = manifest["sites"]
    prefix = (f"https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.{date.replace('-', '')}/{cycle}/atmos/"
              f"gfs.t{cycle}z.pgrb2.0p25.f")
    evidence = []

    def download(step):
        url = prefix + f"{step:03d}"
        try:
            records = [r for r in parse_index(read_url(url + ".idx").decode())
                       if ":TMP:2 m above ground:" in r.line]
            if not records:
                raise ValueError("Missing 2 m temperature")
            return step, url, [load_message(url, r, ROOT / ".cache/direct-weather/grib") for r in records]
        except Exception as error:
            raise RuntimeError(f"GFS temperature f{step:03d} unavailable: {type(error).__name__}") from error

    def decoded(downloads):
        for step, url, raw in downloads:
            # Decode serially and retain only 410 samples/hour, not 24 global grids.
            grid = unique_field([Grid(message) for message in raw], **TEMP_ID,
                                startStep=step, endStep=step)
            evidence.append({"url": url, "validAt": grid.valid_at,
                             "selectedBytes": sum(map(len, raw)),
                             "rawSha256": [hashlib.sha256(message).hexdigest() for message in raw]})
            print(f"Validated temperature f{step:03d}: {grid.valid_at}", flush=True)
            yield grid

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(download, step) for step in steps]
        try:
            temps = daily_mean(decoded(f.result() for f in as_completed(futures)), sites, target, run)
        finally:
            for future in futures:
                future.cancel()
    evidence.sort(key=lambda item: item["validAt"])
    fetched = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    countries = {}
    for site, temp in zip(sites, temps):
        countries.setdefault(site["iso3"], []).append(temp)
    result = {"schema": 1, "status": "local-candidate-not-production", "publicationAllowed": False,
              "source": {"model": "NOAA GFS", "runAt": run.isoformat().replace("+00:00", "Z"),
                         "sourceGridDegrees": 0.25, "method": "arithmetic mean of 24 hourly samples, 00–23 UTC",
                         "sampling": "bilinear; no terrain/elevation downscaling",
                         "siteCount": len(sites), "hours": evidence,
                         "selectedBytes": sum(e["selectedBytes"] for e in evidence)},
              "todayCache": {"date": target, "fetchedAt": fetched,
                             "siteKey": manifest["siteKey"], "temps": temps},
              "countryDailyMeansC": {iso: sum(values) / len(values) for iso, values in countries.items()},
              "climateAnomaly": None}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, separators=(",", ":"), allow_nan=False) + "\n")
    print(f"LOCAL daily mean: {len(sites)} sites, {len(countries)} countries, {output.stat().st_size} bytes")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="Model run date")
    parser.add_argument("--cycle", required=True)
    parser.add_argument("--target-day", required=True, help="Complete UTC day to average")
    parser.add_argument("--output", type=Path, default=ROOT / ".cache/direct-weather/temperature-candidate.json")
    args = parser.parse_args()
    main(args.date, args.cycle, args.target_day, args.output)
