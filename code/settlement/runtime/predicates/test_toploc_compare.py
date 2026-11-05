import importlib.util
import unittest
from toploc_compare import Limits,compare

class InputTests(unittest.TestCase):
    def test_missing_proofs_are_inconclusive(self):
        self.assertEqual(compare([None],[],topk=4,batch_size=3,limits=Limits(0,0,0))['verdict'],'INCONCLUSIVE')
    def test_null_proof_never_reaches_native_modulo(self):
        self.assertEqual(compare([None],[bytes(10)],topk=4,batch_size=3,limits=Limits(0,0,0))['reason'],'null or invalid proof modulus')
    def test_invalid_threshold(self):
        self.assertEqual(compare([None],[bytes(10)],topk=4,batch_size=3,limits=Limits(-1,0,0))['verdict'],'INCONCLUSIVE')

@unittest.skipUnless(importlib.util.find_spec('torch') and importlib.util.find_spec('toploc'),'optional pinned TOPLOC CPU environment required')
class NativeTests(unittest.TestCase):
    def test_repeat_large_indices_and_missing_tail(self):
        import torch,toploc
        torch.manual_seed(42)
        acts=[torch.randn(80,2048,dtype=torch.bfloat16)]+[torch.randn(2048,dtype=torch.bfloat16) for _ in range(4)]
        proofs=toploc.build_proofs_bytes(acts,decode_batching_size=3,topk=16,skip_prefill=False)
        self.assertEqual(compare(acts,proofs,topk=16,batch_size=3,limits=Limits(0,0,0))['verdict'],'PASS')
        self.assertEqual(compare(acts,proofs[:-1],topk=16,batch_size=3,limits=Limits(0,0,0))['verdict'],'INCONCLUSIVE')
    def test_changed_values_fail_exact_policy(self):
        import torch,toploc
        torch.manual_seed(43);acts=[torch.randn(5,16,dtype=torch.bfloat16)]
        proofs=toploc.build_proofs_bytes(acts,decode_batching_size=3,topk=4,skip_prefill=False)
        self.assertEqual(compare([acts[0]*2],proofs,topk=4,batch_size=3,limits=Limits(0,0,0))['verdict'],'FAIL')
    def test_nonfinite_activation_is_inconclusive(self):
        import torch,toploc
        acts=[torch.ones(16,dtype=torch.bfloat16)]
        proofs=toploc.build_proofs_bytes(acts,decode_batching_size=3,topk=4,skip_prefill=False)
        acts[0][0]=float('nan')
        self.assertEqual(compare(acts,proofs,topk=4,batch_size=3,limits=Limits(0,0,0))['verdict'],'INCONCLUSIVE')
if __name__=='__main__':unittest.main()
