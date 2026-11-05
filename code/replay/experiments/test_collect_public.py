import unittest
from unittest.mock import patch
import collect_public as c

class CollectTests(unittest.TestCase):
    def test_exact_inclusive_pages_and_no_x402_inference(self):
        calls=[]
        def fake(url,method,params):
            calls.append((method,params))
            return '0x2105' if method=='eth_chainId' else []
        with patch.object(c,'rpc',side_effect=fake):
            data=c.collect_logs('https://example.test','0x'+'1'*40,5,10,2)
        self.assertEqual([(p['from'],p['to']) for p in data['pages']],[(5,6),(7,8),(9,10)])
        self.assertEqual(data['classification'],'unclassified-contract-events')
        self.assertEqual(len(calls),4)
    def test_out_of_range_log_rejected(self):
        with patch.object(c,'rpc',side_effect=['0x1',[{'address':'0x'+'1'*40,'blockNumber':'0x3'}]]):
            with self.assertRaises(ValueError):c.collect_logs('https://example.test','0x'+'1'*40,5,6)
    def test_invalid_range_before_network(self):
        with patch.object(c,'rpc') as mock:
            with self.assertRaises(ValueError):c.collect_logs('https://example.test','0x'+'1'*40,9,5)
            mock.assert_not_called()
    def test_http_402_preserved(self):
        import io
        from urllib.error import HTTPError
        error=HTTPError('https://example.test',402,'payment required',{'PAYMENT-REQUIRED':'fixture'},io.BytesIO(b'offer'))
        with patch.object(c,'urlopen',side_effect=error):
            status,headers,body=c.fetch('https://example.test')
        self.assertEqual((status,body),(402,b'offer'))
    def test_rpc_error_rejected(self):
        with patch.object(c,'fetch',return_value=(200,{},b'{"error":{"code":-1}}')):
            with self.assertRaises(RuntimeError):c.rpc('https://example.test','eth_getLogs',[])

class RpcCliTests(unittest.TestCase):
    def test_error_body_and_request_are_retained(self):
        import tempfile,json,sys
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'result'
            argv=['collect','--output',str(out),'rpc','https://example.test','--method','eth_getBlockByNumber','--params','["0x1", false]']
            with patch.object(sys,'argv',argv),patch.object(c.subprocess,'check_output',side_effect=['','revision']),patch.object(c,'fetch',return_value=(403,{},b'blocked')) as fetch:
                c.main()
            m=json.loads((out/'manifest.json').read_text())
            self.assertEqual(m['http_status'],403)
            self.assertEqual((out/'raw.bin').read_bytes(),b'blocked')
            self.assertEqual(fetch.call_args.args[1]['params'],['0x1',False])
            self.assertNotIn('rpc_result_present',m)
    def test_object_parameters_fail_before_network(self):
        import tempfile,sys
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            argv=['collect','--output',str(Path(tmp)/'result'),'rpc','https://example.test','--method','eth_chainId','--params','{}']
            with patch.object(sys,'argv',argv),patch.object(c.subprocess,'check_output',side_effect=['','revision']),patch.object(c,'fetch') as fetch:
                with self.assertRaises(ValueError):c.main()
                fetch.assert_not_called()

if __name__=='__main__':unittest.main()
