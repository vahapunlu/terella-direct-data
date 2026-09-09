import unittest
from datetime import date,timedelta
from build_temperature_bias import fit
class BiasTest(unittest.TestCase):
 def records(self):
  return [{'day':str(date(2026,8,20)+timedelta(days=i)),'era5':[20+i/5,10],'gfs':[23+i/5,8]}for i in range(14)]
 def test_constant_model_bias_corrected_on_unseen_days(self):
  r=fit(self.records(),2);self.assertTrue(r['pilotAccepted']);self.assertEqual(r['offsetsC'],[-3,2]);self.assertAlmostEqual(r['validation']['correctedMaeC'],0)
 def test_holdout_shift_does_not_hide_behind_training_fit(self):
  rows=self.records()
  for r in rows[11:]:r['gfs']=[40,40]
  self.assertFalse(fit(rows,2)['pilotAccepted'])
 def test_missing_and_duplicate_days_rejected(self):
  with self.assertRaises(ValueError):fit(self.records()[:-1],2)
  rows=self.records();rows[-1]['day']=rows[-2]['day']
  with self.assertRaises(ValueError):fit(rows,2)
if __name__=='__main__':unittest.main()
