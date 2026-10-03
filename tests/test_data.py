import hashlib,io,tempfile,unittest,zipfile
from unittest.mock import patch
import pandas as pd
from quant.data import download,load

class DataTests(unittest.TestCase):
    def fixture(self,scale):
        timestamp=int(pd.Timestamp('2025-01-02',tz='UTC').timestamp()*scale)
        rows='\n'.join(','.join(map(str,[timestamp+k*900*scale,100,102,99,101,1,timestamp+(k+1)*900*scale-1,101,1,1,101,0])) for k in range(96))
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as archive:
            archive.writestr('BTCUSDT-15m-2025-01-02.csv',rows)
        return data.getvalue()
    def check_scale(self,scale):
        blob=self.fixture(scale);checksum=hashlib.sha256(blob).hexdigest().encode()+b'  archive.zip'
        with tempfile.TemporaryDirectory() as directory,patch('quant.data.fetch',side_effect=lambda url:checksum if url.endswith('.CHECKSUM') else blob):
            download(['BTCUSDT'],'2025-01-02','2025-01-02','15m',directory)
            f=load(directory,'15min')['BTCUSDT']
            self.assertEqual(f.index[0],pd.Timestamp('2025-01-02',tz='UTC'));self.assertEqual(len(f),96)
    def test_milliseconds(self): self.check_scale(1000)
    def test_microseconds(self): self.check_scale(1000000)
    def test_checksum_rejection(self):
        with tempfile.TemporaryDirectory() as directory,patch('quant.data.fetch',side_effect=[b'0'*64,self.fixture(1000000)]):
            with self.assertRaisesRegex(ValueError,'Checksum mismatch'):
                download(['BTCUSDT'],'2025-01-02','2025-01-02','15m',directory)
