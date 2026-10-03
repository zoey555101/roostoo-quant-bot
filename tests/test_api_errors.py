import io,json,os,unittest
from unittest.mock import patch
from quant.roostoo import Roostoo,signature

class ApiErrors(unittest.TestCase):
    def request(self,payload,path='/v3/query_order',allow_empty=True):
        env={'ROOSTOO_API_KEY':'TEST-KEY-123','ROOSTOO_SECRET_KEY':'TEST-SECRET-456'}
        with patch.dict(os.environ,env),patch('quant.roostoo.urlopen',return_value=io.BytesIO(json.dumps(payload).encode())):
            return Roostoo().request(path,{'timestamp':'1'},True,'POST',allow_empty)
    def test_documented_empty_response(self):
        self.assertFalse(self.request({'Success':False,'ErrMsg':'no order matched'})['Success'])
    def test_empty_format_variation(self):
        self.assertFalse(self.request({'Success':False,'ErrMsg':'  No order matched.\n'})['Success'])
    def test_permission_error_not_swallowed(self):
        with self.assertRaisesRegex(RuntimeError,'permission denied'):
            self.request({'Success':False,'ErrMsg':'permission denied'})
    def test_empty_not_allowed_on_balance(self):
        with self.assertRaises(RuntimeError):
            self.request({'Success':False,'ErrMsg':'no order matched'},'/v3/balance')
    def test_redacts_credentials_signature_and_escapes(self):
        sig=signature({'timestamp':'1'},'TEST-SECRET-456')
        with self.assertRaises(RuntimeError) as error:
            self.request({'Success':False,'ErrMsg':'TEST-KEY-123 TEST-SECRET-456 '+sig+'\nDenied'})
        message=str(error.exception)
        for value in ['TEST-KEY-123','TEST-SECRET-456',sig]:self.assertNotIn(value,message)
        self.assertNotIn('\n',message);self.assertIn('[REDACTED]',message)

if __name__=='__main__':unittest.main()
