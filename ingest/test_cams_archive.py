from datetime import datetime, timezone, timedelta
import copy
import unittest
from refresh_cams import merge_archive

class CamsArchiveTest(unittest.TestCase):
 def candidate(self,valid,run):return {'aerosols':{'observedAt':valid},'source':{'runAt':run}}
 def test_same_validity_new_model_preserves_previous_bytes_without_duplicate_time(self):
  now=datetime(2026,9,9,8,tzinfo=timezone.utc)
  old=self.candidate('2026-09-09T06:00:00Z','2026-09-08T12:00:00Z')
  new=self.candidate('2026-09-09T06:00:00Z','2026-09-09T00:00:00Z')
  previous={'current':old,'entries':[old]};snapshot=copy.deepcopy(previous)
  result=merge_archive(previous,new,now)
  self.assertEqual(result['entries'],[new]);self.assertEqual(result['superseded'],[old])
  self.assertEqual(previous,snapshot)
  with self.assertRaises(ValueError):merge_archive(result,old,now)
  with self.assertRaises(ValueError):merge_archive(result,new,now)
 def test_expired_revision_disappears_with_its_timeline_window(self):
  old=self.candidate('2026-09-06T06:00:00Z','2026-09-05T12:00:00Z')
  newer=self.candidate('2026-09-06T06:00:00Z','2026-09-06T00:00:00Z')
  new=self.candidate('2026-09-09T06:00:00Z','2026-09-09T00:00:00Z')
  result=merge_archive({'current':newer,'entries':[newer],'superseded':[old]},new,datetime(2026,9,9,8,tzinfo=timezone.utc))
  self.assertEqual(result['entries'],[new]);self.assertEqual(result['superseded'],[])
if __name__=='__main__':unittest.main()
