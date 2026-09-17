import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'site-private/ingest'))
from audit_temperature_quality import evaluate_bias, main


class QualityAuditTest(unittest.TestCase):
    def setUp(self):
        self.sites={'siteKey':'fixed','sites':[{'iso3':'TUR','lat':39,'lon':35},
                                             {'iso3':'KAS','lat':35.29,'lon':77.21}]}
        self.bias={'siteKey':'fixed','lastDay':'2026-09-04','offsetsC':[-2,-2]}
        self.records=[{'day':f'2026-09-{d:02}','gfs':[22,22],'era5':[20,20]} for d in (8,9,10)]

    def test_previously_accepted_bias_can_fail_new_days(self):
        self.assertTrue(evaluate_bias(self.records,self.sites,self.bias)['passed'])
        self.records[1]['gfs'][1]=27
        result=evaluate_bias(self.records,self.sites,self.bias)
        self.assertFalse(result['passed'])
        self.assertEqual(result['countriesAboveMaxLimit'],['KAS'])
        self.assertEqual(result['worstCountries'][0]['differenceC'],5)
        self.assertEqual(result['siteCount'],2)

    def test_overlap_and_incomplete_days_never_pass(self):
        with self.assertRaises(ValueError):
            evaluate_bias(self.records,self.sites,{**self.bias,'lastDay':'2026-09-08'})
        with self.assertRaises(ValueError):
            evaluate_bias(self.records[:2],self.sites,self.bias)

    def test_nonfinite_offset_never_looks_healthy(self):
        with self.assertRaises(ValueError):
            evaluate_bias(self.records,self.sites,{**self.bias,'offsetsC':[float('nan'),-2]})

    def test_unavailable_reference_replaces_old_pass_with_incomplete_without_secret_text(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'data').mkdir()
            (root/'data/temperature-quality.json').write_text('{"status":"complete"}')
            with patch('sys.argv',['audit','--root',d]),patch('audit_temperature_quality.make_report',
                       side_effect=RuntimeError('private-api-key-must-not-appear')):
                self.assertEqual(main(),1)
            text=(root/'data/temperature-quality.json').read_text()
            self.assertNotIn('private-api-key',text)
            self.assertEqual(json.loads(text)['status'],'incomplete')


if __name__=='__main__':unittest.main()
