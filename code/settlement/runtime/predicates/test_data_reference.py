import unittest
from dataclasses import replace
from data_reference import Policy, FieldPolicy, Observation, compare

class DataReferenceTests(unittest.TestCase):
    def setUp(self):
        self.p=Policy(('a','b','c'),2,100,5,{'price':FieldPolicy('USD','0.01','0','0.02')})
        self.refs=[Observation('a',100,{'price':'10.00'},{'price':'USD'}),Observation('b',101,{'price':'10.02'},{'price':'USD'})]
    def test_exact_decimal_boundary(self):
        self.assertEqual(compare(self.p,{'price':'10.02'},self.refs).verdict,'PASS')
        self.assertEqual(compare(self.p,{'price':'10.0200000000000000000001'},self.refs).verdict,'FAIL')
    def test_reference_order_is_irrelevant(self):
        self.assertEqual(compare(self.p,{'price':'10.01'},self.refs),compare(self.p,{'price':'10.01'},self.refs[::-1]))
    def test_duplicates_cannot_form_quorum(self):
        self.assertEqual(compare(self.p,{'price':'10'},[self.refs[0],self.refs[0]]).verdict,'INCONCLUSIVE')
    def test_stale_future_units_and_missing_quorum(self):
        for changed in [replace(self.refs[1],observed_at=106),replace(self.refs[1],observed_at=94),replace(self.refs[1],units={'price':'EUR'}),replace(self.refs[1],values={})]:
            self.assertEqual(compare(self.p,{'price':'10'},[self.refs[0],changed]).verdict,'INCONCLUSIVE')
    def test_disagreement_is_not_seller_failure(self):
        bad=replace(self.refs[1],values={'price':'12'})
        self.assertEqual(compare(self.p,{'price':'11'},[self.refs[0],bad]).verdict,'INCONCLUSIVE')
    def test_missing_and_nonfinite_inputs(self):
        self.assertEqual(compare(self.p,None,self.refs).verdict,'INCONCLUSIVE')
        self.assertEqual(compare(self.p,{},self.refs).verdict,'FAIL')
        for value in ['NaN','Infinity','1e20','1/2']:
            self.assertEqual(compare(self.p,{'price':value},self.refs).verdict,'INCONCLUSIVE')
    def test_relative_tolerance_and_zero_reference(self):
        p=replace(self.p,fields={'price':FieldPolicy('USD','0','0.1','0')})
        refs=[replace(o,values={'price':'10'}) for o in self.refs]
        self.assertEqual(compare(p,{'price':'11'},refs).verdict,'PASS')
        self.assertEqual(compare(p,{'price':'11.0001'},refs).verdict,'FAIL')
        refs=[replace(o,values={'price':'0'}) for o in self.refs]
        self.assertEqual(compare(p,{'price':'0.0001'},refs).verdict,'FAIL')
    def test_policy_and_source_validation(self):
        for p in [replace(self.p,quorum=0),replace(self.p,source_ids=('a','a')),replace(self.p,fields={'price':FieldPolicy('USD','-1','0','0')})]:
            self.assertEqual(compare(p,{'price':'10'},self.refs).verdict,'INCONCLUSIVE')
        self.assertEqual(compare(self.p,{'price':'10'},[self.refs[0],replace(self.refs[1],source='unknown')]).verdict,'INCONCLUSIVE')
if __name__=='__main__':unittest.main()
