import base64
import copy
import unittest

import numpy as np

from build_gfs_candidate import make_weather, pack_rain, rain_window, unique_field


class Field:
    def __init__(self, category, parameter, level_type, level, value, rain=False):
        self.metadata = {"discipline": 0, "parameterCategory": category,
                         "parameterNumber": parameter, "typeOfLevel": level_type, "level": level,
                         "units": "kg m**-2" if rain else "m s**-1",
                         "stepType": "accum" if rain else "instant", "stepUnits": 1,
                         "startStep": 0 if rain else 3, "endStep": 3, "uvRelativeToGrid": 0}
        if rain:
            self.metadata["typeOfStatisticalProcessing"] = 1
        self.values = np.array([[value]])
        self.run_at = "2026-09-05T00:00:00Z"
        self.valid_at = "2026-09-05T03:00:00Z"

    def sample(self, lat, lon):
        return float(self.values[0, 0])


def fields():
    return [Field(2, 2, "heightAboveGround", 10, 10), Field(2, 3, "heightAboveGround", 10, 0),
            Field(2, 2, "isobaricInhPa", 250, 40), Field(2, 3, "isobaricInhPa", 250, -5),
            Field(1, 8, "surface", 0, 2, rain=True)]


class CandidateTests(unittest.TestCase):
    def test_later_native_window_ignores_different_cumulative_period(self):
        rain = fields()[-1]
        rain.metadata.update(startStep=6, endStep=9)
        rain.valid_at = "2026-09-05T09:00:00Z"
        cumulative = copy.deepcopy(rain)
        cumulative.metadata["startStep"] = 0
        cumulative.values *= 3
        result, method = rain_window([rain, cumulative], 9)
        self.assertEqual(result.sample(0, 0), 2)
        self.assertEqual(method, "native-three-hour")

    def test_six_hour_total_is_subtracted_not_relabelled(self):
        earlier = fields()[-1]
        later = copy.deepcopy(earlier)
        later.metadata["endStep"] = 6
        later.valid_at = "2026-09-05T06:00:00Z"
        later.values = np.array([[7.]])
        result, method = rain_window([later], 6, [earlier])
        self.assertEqual(result.sample(0, 0), 5)
        self.assertEqual(result.metadata["startStep"], 3)
        self.assertEqual(later.metadata["startStep"], 0)
        self.assertEqual(method, "difference-0-6-minus-0-3")

    def test_later_weather_keeps_app_shape_and_actual_clock(self):
        source = fields()
        earlier = copy.deepcopy(source[-1])
        for field in source:
            field.metadata["endStep"] = 6
            field.valid_at = "2026-09-05T06:00:00Z"
            if field.metadata["stepType"] == "instant":
                field.metadata["startStep"] = 6
        source[-1].values = np.array([[7.]])
        result = make_weather(source, "2026-09-05T07:00:00Z", 6, [earlier])
        self.assertEqual(result["cells"][0], [-75, -180, 10, 0, 5])
        self.assertEqual(result["rain"]["observedAt"], "2026-09-05T06:00:00Z")
        self.assertEqual(set(base64.b64decode(result["rain"]["grid"])), {pack_rain(5)})

    def test_rolling_six_hour_origin_is_preserved(self):
        earlier = fields()[-1]
        earlier.metadata.update(startStep=6, endStep=9)
        earlier.valid_at = "2026-09-05T09:00:00Z"
        later = copy.deepcopy(earlier)
        later.metadata["endStep"] = 12
        later.valid_at = "2026-09-05T12:00:00Z"
        later.values = np.array([[7.]])
        result, method = rain_window([later], 12, [earlier])
        self.assertEqual(result.sample(0, 0), 5)
        self.assertEqual(method, "difference-6-12-minus-6-9")

    def test_subtraction_rejects_missing_incompatible_and_negative_fields(self):
        earlier = fields()[-1]
        later = copy.deepcopy(earlier)
        later.metadata["endStep"] = 6
        later.valid_at = "2026-09-05T06:00:00Z"
        later.values = np.array([[7.]])
        with self.assertRaises(ValueError):
            rain_window([later], 6)
        for kind in ("run", "grid", "clock", "period", "negative", "nan", "shape"):
            bad = copy.deepcopy(earlier)
            if kind == "run":
                bad.run_at = "2026-09-04T18:00:00Z"
            elif kind == "grid":
                bad.metadata["Ni"] = 123
            elif kind == "clock":
                bad.valid_at = "2026-09-05T02:00:00Z"
            elif kind == "period":
                bad.metadata["startStep"] = 1
            elif kind == "negative":
                bad.values[:] = 8
            elif kind == "nan":
                bad.values = np.array([[float("nan")]])
            else:
                bad.values = np.array([[1., 2.]])
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                rain_window([later], 6, [bad])

    def test_invalid_forecast_boundaries_rejected(self):
        for step in (0, 1, 4, 121, 123, -3, 3.0, True):
            with self.subTest(step=step), self.assertRaises(ValueError):
                rain_window(fields(), step)

    def test_existing_app_shape(self):
        result = make_weather(fields(), "2026-09-05T04:00:00Z")
        self.assertEqual(len(result["cells"]), 264)
        self.assertEqual(len(result["jet"]["cells"]), 264)
        self.assertEqual(result["cells"][0], [-75, -180, 10, 0, 2])
        self.assertEqual(result["jet"]["cells"][-1], [75, 165, 40, -5])
        self.assertEqual(len(base64.b64decode(result["rain"]["grid"])), 1152)
        self.assertEqual(result["observedAt"], "2026-09-05T03:00:00Z")

    def test_same_decoded_duplicate_allowed(self):
        source = fields()
        source.append(copy.deepcopy(source[-1]))
        make_weather(source, "now")

    def test_different_duplicate_rejected(self):
        source = fields()
        source.append(Field(1, 8, "surface", 0, 3, rain=True))
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            make_weather(source, "now")

    def test_mixed_clock_rejected(self):
        source = fields()
        source[0].valid_at = "2026-09-05T06:00:00Z"
        with self.assertRaisesRegex(ValueError, "Mixed"):
            make_weather(source, "now")

    def test_not_three_hour_rain_rejected(self):
        source = fields()
        source[-1].metadata["startStep"] = 1
        with self.assertRaises(ValueError):
            make_weather(source, "now")

    def test_pressure_height_units_and_rotation_are_not_interchangeable(self):
        for index, key, value in ((2, "level", 500), (0, "level", 100),
                                  (0, "units", "km h**-1"), (0, "uvRelativeToGrid", 1)):
            source = fields()
            source[index].metadata[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                make_weather(source, "now")

    def test_canonical_rain_rows(self):
        source = fields()
        source[-1].sample = lambda lat, lon: 25 if lat > 0 else 0
        data = base64.b64decode(make_weather(source, "now")["rain"]["grid"])
        self.assertEqual(set(data[:576]), {255})
        self.assertEqual(set(data[576:]), {0})

    def test_missing_is_not_dry(self):
        for value in (float("nan"), float("inf"), -1):
            with self.assertRaises(ValueError):
                pack_rain(value)
        self.assertEqual(pack_rain(0), 0)
        self.assertEqual(pack_rain(25), 255)
        self.assertEqual(pack_rain(100), 255)


if __name__ == "__main__":
    unittest.main()
