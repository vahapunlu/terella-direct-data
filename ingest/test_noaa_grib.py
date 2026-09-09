import unittest
from unittest.mock import patch

import eccodes as ec
import numpy as np

from noaa_grib import Grid, parse_index, read_url, stamp, validate_message


class NoaaTests(unittest.TestCase):
    def test_index_ranges_are_inclusive(self):
        records = parse_index("1:0:d=2026090500:UGRD:250 mb:anl:\n2:123:d=2026090500:VGRD:250 mb:anl:\n")
        self.assertEqual((records[0].start, records[0].end), (0, 122))
        self.assertIsNone(records[1].end)

    def test_bad_indices_rejected(self):
        for value in ("", "<html>error</html>", "1:10:d=x:T:S:A:",
                      "1:0:d=x:T:S:A:\n2:0:d=x:T:S:A:",
                      "1:0:d=x:T:S:A:\n2:-1:d=x:T:S:A:"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_index(value)

    def test_no_secrets_or_unknown_hosts(self):
        for url in ("http://noaa-gefs-pds.s3.amazonaws.com/x", "https://example.org/x",
                    "https://token@noaa-gefs-pds.s3.amazonaws.com/x"):
            with self.assertRaises(ValueError):
                read_url(url)

    def test_range_limits_before_network(self):
        with patch("urllib.request.urlopen") as request:
            for start, end in ((-1, 1), (2, 1), (0, 16 * 1024 * 1024), (0, None)):
                with self.assertRaises(ValueError):
                    read_url("https://noaa-gefs-pds.s3.amazonaws.com/x", start=start, end=end)
            request.assert_not_called()

    def test_rejects_truncated_or_extra_grib(self):
        for raw in (b"", b"GRIB" * 10, b"<html>unavailable</html>"):
            with self.assertRaises(ValueError):
                validate_message(raw, len(raw))

    def test_clock_is_utc_not_machine_timezone(self):
        self.assertEqual(stamp(20260905, 600), "2026-09-05T06:00:00Z")
        with self.assertRaises(ValueError):
            stamp(20260230, 0)

    def test_real_grib_roundtrip(self):
        handle = ec.codes_grib_new_from_samples("regular_ll_sfc_grib2")
        try:
            settings = {"Ni": 4, "Nj": 3, "latitudeOfFirstGridPointInDegrees": 90,
                        "longitudeOfFirstGridPointInDegrees": 0,
                        "latitudeOfLastGridPointInDegrees": -90,
                        "longitudeOfLastGridPointInDegrees": 270,
                        "iDirectionIncrementInDegrees": 90, "jDirectionIncrementInDegrees": 90,
                        "dataDate": 20260905, "dataTime": 600}
            for key, value in settings.items():
                ec.codes_set(handle, key, value)
            ec.codes_set_values(handle, np.array([0, 10, 20, 30] * 3, dtype=float))
            raw = ec.codes_get_message(handle)
        finally:
            ec.codes_release(handle)
        validate_message(raw, len(raw))
        grid = Grid(raw)
        self.assertEqual(grid.sample(0, 45), 5)
        self.assertEqual(grid.sample(45, 315), 15)
        self.assertEqual(grid.sample(0, -180), grid.sample(0, 180))
        self.assertEqual(grid.sample(-90, 0), 0)
        self.assertEqual(grid.run_at, "2026-09-05T06:00:00Z")
        with self.assertRaises(ValueError):
            grid.require(units="not-the-source-unit")
        for lat, lon in ((91, 0), (0, float("nan"))):
            with self.assertRaises(ValueError):
                grid.sample(lat, lon)


if __name__ == "__main__":
    unittest.main()
