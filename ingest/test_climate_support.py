import json
from datetime import date, timedelta
from pathlib import Path
import tempfile
import unittest
import numpy as np
from refresh_climate_support import normal_days, calibration_days, build_normal, build_bias, plan, atomic_json


class ClimateSupportTest(unittest.TestCase):
    def test_normal_window_crosses_year_and_leap_day_without_missing_days(self):
        days = normal_days(date(2026, 1, 1), 2006)
        self.assertEqual(days[0], date(2005, 12, 27))
        self.assertEqual(days[-1], date(2006, 1, 6))
        self.assertEqual(len(set(days)), 11)
        self.assertEqual(normal_days(date(2028, 2, 29), 2023)[5], date(2023, 2, 28))
        self.assertEqual(normal_days(date(2028, 2, 29), 2024)[5], date(2024, 2, 29))

    def test_era5_latency_training_and_forward_holdout_are_disjoint(self):
        target = date(2027, 1, 5)
        train, holdout = calibration_days(target)
        self.assertEqual(len(train), 14)
        self.assertEqual(len(holdout), 3)
        self.assertLess(train[-1], holdout[0])
        self.assertEqual(holdout[-1], target - timedelta(days=7))
        self.assertEqual(train[0], target - timedelta(days=23))

    def test_renewal_leaves_time_before_existing_component_expiry(self):
        result = plan(date(2026, 9, 14), {'builtFor': '2026-09-10'}, {'lastDay': '2026-09-02'})
        self.assertTrue(result['normalDue'])
        self.assertTrue(result['biasDue'])
        result = plan(date(2026, 9, 9), {'builtFor': '2026-09-08'}, {'lastDay': '2026-09-02'})
        self.assertFalse(result['normalDue'])
        self.assertFalse(result['biasDue'])

    def test_normal_requires_twenty_complete_years(self):
        manifest = {'siteKey': 'test', 'sites': [{'iso3': 'TUR'}]}
        result = build_normal(date(2026, 9, 9), manifest, lambda days: np.full((len(days), 1), 18.0))
        self.assertEqual(result['daysPerSite'], 220)
        self.assertEqual(result['meansC'], [18.0])
        with self.assertRaises(ValueError):
            build_normal(date(2026, 9, 9), manifest, lambda days: np.full((10, 1), 18.0))

    def test_new_unseen_country_error_cannot_replace_accepted_bias(self):
        manifest = {'siteKey': 'test', 'sites': [{'iso3': 'TUR'}]}
        target = date(2026, 9, 9)
        training, holdout = calibration_days(target)
        observations = lambda days: np.full((len(days), 1), 20.0)
        good = build_bias(target, manifest, observations, lambda day: [22.0])
        self.assertTrue(good['countryValidation']['passed'])
        self.assertEqual(good['offsetsC'], [-2.0])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bias.json'
            atomic_json(path, good)
            with self.assertRaises(ValueError):
                atomic_json(path, build_bias(target, manifest, observations,
                                            lambda day: [22.0 if day in training else 35.0]))
            self.assertEqual(json.loads(path.read_text()), good)


if __name__ == '__main__':
    unittest.main()
