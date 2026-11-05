import base64,copy,unittest
from data_experiment import POLICY_ID,evaluate,parse
class CodecTests(unittest.TestCase):
    def fixture(self):
        return {'policyId':POLICY_ID,'policy':{'source_ids':['a','b'],'quorum':2,'reference_time':100,'max_skew':2,'fields':{'price':{'unit':'USD','absolute':'1','relative':'0','reference_spread':'0'}}},'responseBase64':base64.b64encode(b'{"price":"100"}').decode(),'observations':[{'source':s,'observed_at':100,'values':{'price':'100'},'units':{'price':'USD'}} for s in ['a','b']]}
    def test_policy_id(self):
        import hashlib
        self.assertEqual(POLICY_ID,'0x'+hashlib.sha256(b'fairbind/experimental/data-decimal-median/v1').hexdigest())
        d=self.fixture();d['policyId']='0xb1659e2eda6c17f24434be64972e5ce19d44b5b4154752bbe83418276831812f'
        with self.assertRaises(ValueError):evaluate(d)
    def test_pass_fail_boundary(self):
        d=self.fixture()
        for value,want in [('101','PASS'),('101.0001','FAIL')]:
            d['responseBase64']=base64.b64encode(('{"price":"'+value+'"}').encode()).decode();self.assertEqual(evaluate(d)['verdict'],want)
    def test_untrusted_codec_rejects(self):
        for raw in ['{"x":1,"x":2}','{"x":NaN}']:
            with self.assertRaises(ValueError):parse(raw)
        for field,value in [('quorum',True),('max_skew',-1)]:
            d=self.fixture();d['policy'][field]=value
            with self.assertRaises(ValueError):evaluate(d)
    def test_quorum_and_missing_fields(self):
        d=self.fixture();d['observations']=d['observations'][:1];self.assertEqual(evaluate(d)['verdict'],'INCONCLUSIVE')
        d=self.fixture();d['responseBase64']=base64.b64encode(b'{}').decode();self.assertEqual(evaluate(d)['verdict'],'FAIL')
if __name__=='__main__':unittest.main()
