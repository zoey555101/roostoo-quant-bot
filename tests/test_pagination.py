import unittest
from unittest.mock import patch
from quant.roostoo import Roostoo

class Pagination(unittest.TestCase):
    def snapshot(self,pages):
        client=Roostoo()
        with patch.object(client,'sync_time'),patch.object(client,'request',side_effect=[{}, {}, {'Success':True,'Wallet':{}}]+pages) as request:
            result=client.snapshot(True)
        queries=[call for call in request.call_args_list if call.args[0]=='/v3/query_order']
        return result,queries
    def test_first_page_omits_offset(self):
        result,calls=self.snapshot([{'Success':False,'ErrMsg':'no order matched'}])
        self.assertNotIn('offset',calls[0].args[1]);self.assertEqual(result['orders'],[])
    def test_second_page_positive_offset(self):
        first=[{'OrderID':i} for i in range(100)]
        result,calls=self.snapshot([{'OrderMatched':first},{'OrderMatched':[{'OrderID':100}]}])
        self.assertEqual(calls[1].args[1]['offset'],'100');self.assertEqual(len(result['orders']),101)
    def test_duplicate_page_rejected(self):
        first=[{'OrderID':i} for i in range(100)]
        with self.assertRaisesRegex(RuntimeError,'overlap'):
            self.snapshot([{'OrderMatched':first},{'OrderMatched':first}])

if __name__=='__main__':unittest.main()
