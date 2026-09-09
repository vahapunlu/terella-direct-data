import unittest
import numpy as np
from build_cams_candidate import dry_density
class TestDensity(unittest.TestCase):
 def test_dry_air_ideal_gas(self):
  self.assertAlmostEqual(float(dry_density(np.array(100000),np.array(300),np.array(0))),100000/(287.058*300))
 def test_humidity_reduces_dry_mass(self):
  dry=dry_density(np.array(100000),np.array(300),np.array(0));humid=dry_density(np.array(100000),np.array(300),np.array(.02))
  self.assertLess(humid,dry)
 def test_invalid_thermodynamics_rejected(self):
  for q in [float('nan'),-.01,.2]:
   with self.assertRaises(ValueError):dry_density(np.array(100000),np.array(300),np.array(q))
if __name__=='__main__':unittest.main()
