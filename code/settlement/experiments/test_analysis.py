import unittest
from analysis import paired_runs,wilson
class AnalysisTests(unittest.TestCase):
 def rows(self):
  return [dict(scenario='F1',run_id=r,method=m,observation_id=i,value=v) for r,m,i,v in [('1','B5',0,4),('1','B5',1,6),('1','B0',0,1),('2','B5',0,3),('2','B0',0,1)]]
 def test_equal_run_weight_not_purchase_weight(self):
  a=paired_runs(self.rows(),'B5','B0',seed=42)
  self.assertEqual(a['scenarios']['F1']['mean_run_difference'],3)
  self.assertEqual(a['scenarios']['F1']['independent_runs'],2)
  self.assertEqual(a,paired_runs(self.rows(),'B5','B0',seed=42))
 def test_missing_pair_rejected(self):
  with self.assertRaises(ValueError):paired_runs(self.rows()[:-1],'B5','B0')
 def test_duplicate_and_missing_value_rejected(self):
  rows=self.rows()
  with self.assertRaises(ValueError):paired_runs(rows+[rows[0]],'B5','B0')
  rows[0]['value']=None
  with self.assertRaises(ValueError):paired_runs(rows,'B5','B0')
 def test_zero_failures_have_positive_upper_bound(self):
  low,high=wilson(0,30)
  self.assertAlmostEqual(low,0);self.assertGreater(high,.1)
  self.assertLess(high,.12)
 def test_no_data_and_bad_counts_rejected(self):
  with self.assertRaises(ValueError):paired_runs([],'B5','B0')
  with self.assertRaises(ValueError):wilson(1,0)
if __name__=='__main__':unittest.main()
