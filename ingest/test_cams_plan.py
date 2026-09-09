from datetime import datetime, timezone
import copy
import unittest
from cams_plan import select_run, date_available


class CamsPlanTest(unittest.TestCase):
    def rows(self):
        base = {'date': ['2026-05-12/2026-09-08'], 'time': ['00:00', '12:00'],
                'type': ['forecast'], 'leadtime_hour': [str(i) for i in range(0, 121, 3)]}
        return [dict(base, variable=['particulate_matter_10um']),
                dict(base, variable=['temperature'], model_level=['137'])]

    def test_unpublished_new_date_selects_latest_complete_real_run(self):
        now = datetime(2026, 9, 9, 8, 30, tzinfo=timezone.utc)
        result = select_run(now, self.rows(), ['particulate_matter_10um', 'temperature'])
        self.assertEqual(result['run'].isoformat(), '2026-09-08T12:00:00+00:00')
        self.assertEqual(result['valid'].isoformat(), '2026-09-09T06:00:00+00:00')
        self.assertEqual(result['step'], 18)
        self.assertTrue(result['catalogueDeferred'])

    def test_all_variables_must_be_available_on_the_same_run(self):
        now = datetime(2026, 9, 9, 9, tzinfo=timezone.utc)
        rows = self.rows()
        rows[0]['date'] = ['2026-05-12/2026-09-09']
        result = select_run(now, rows, ['particulate_matter_10um', 'temperature'])
        self.assertTrue(result['catalogueDeferred'])
        self.assertEqual(result['step'], 21)
        rows[1]['date'] = ['2026-05-12/2026-09-09']
        self.assertFalse(select_run(now, rows, ['particulate_matter_10um', 'temperature'])['catalogueDeferred'])

    def test_pressure_level_data_cannot_stand_in_for_model_level_137(self):
        rows = self.rows()
        del rows[1]['model_level']
        rows[1]['pressure_level'] = ['1000']
        with self.assertRaises(ValueError):
            select_run(datetime(2026, 9, 9, 8, tzinfo=timezone.utc), rows, ['temperature'])

    def test_too_old_model_is_not_relabelled_as_a_current_forecast(self):
        with self.assertRaises(ValueError):
            select_run(datetime(2026, 9, 12, 8, tzinfo=timezone.utc), self.rows(), ['temperature'])
        self.assertTrue(date_available('2026-09-08', ['2026-05-12/2026-09-08']))
        self.assertFalse(date_available('2026-09-09', ['2026-05-12/2026-09-08']))


if __name__ == '__main__':
    unittest.main()
