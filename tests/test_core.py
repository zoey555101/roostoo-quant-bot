import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from quant.backtest import run,metrics
from quant.strategy import Config,targets
from quant.data import load
from quant.roostoo import signature

def bars(n=240):
    index=pd.date_range('2025-01-01',periods=n,freq='15min',tz='UTC');close=100*np.exp(np.arange(n)*.001)
    return {'BTCUSDT':pd.DataFrame({'open':np.r_[100,close[:-1]],'high':close*1.01,'low':close*.99,'close':close,'volume':100},index=index)}

class Tests(unittest.TestCase):
    def test_signature(self):
        p={'pair':'BNB/USD','quantity':'2000','side':'BUY','timestamp':'1580774512000','type':'MARKET'}
        self.assertEqual(signature(p,'S1XP1e3UZj6A7H5fATj0jNhqPxxdSJYdInClVN65XAbvqqMKjVHjA7PZj4W12oep'),'20b7fd5550b67b3bf0c1684ed0f04885261db8fdabd38611e9e6af23c19b7fff')
    def test_next_open_exact_costs(self):
        f=bars(4);frame=f['BTCUSDT'];frame.loc[:,'open']=100.;frame.loc[:,'close']=100.
        with patch('quant.backtest.targets',return_value=pd.DataFrame({'BTCUSDT':[.5,0,0,0]},index=frame.index)):
            ledger,trades,m=run(f,Config(rebalance_bars=1,min_trade_weight=0,slippage_bps=0))
        self.assertEqual(trades.iloc[0].timestamp,frame.index[1]);self.assertAlmostEqual(ledger.nav.iloc[-1],99900);self.assertAlmostEqual(m['total_fees'],100)
    def test_no_future_leak(self):
        f=bars();prior=targets(f,Config());f['BTCUSDT'].iloc[180:,f['BTCUSDT'].columns.get_loc('close')]*=10
        pd.testing.assert_frame_equal(prior.iloc[:180],targets(f,Config()).iloc[:180])
    def test_cash_caps(self):
        f=bars();c=Config();w=targets(f,c);self.assertTrue((w<=c.coin_cap).all().all());self.assertTrue((w.sum(axis=1)<=c.gross_cap).all());ledger,_,_=run(f,c);self.assertTrue((ledger.cash>=0).all())
    def test_halt_latched(self):
        f=bars(8);frame=f['BTCUSDT'];frame.loc[:,'open']=100.;frame.loc[:,'close']=100.;frame.iloc[3:,frame.columns.get_loc('open')]=50.;frame.iloc[3:,frame.columns.get_loc('close')]=50.
        with patch('quant.backtest.targets',return_value=pd.DataFrame({'BTCUSDT':.5},index=frame.index)):
            ledger,trades,m=run(f,Config(rebalance_bars=1,fee_bps=0,slippage_bps=0))
        self.assertTrue(m['halted']);self.assertEqual(ledger.gross_exposure.iloc[-1],0);self.assertEqual(trades.iloc[-1].reason,'drawdown_exit')
    def test_gap_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=bars()['BTCUSDT'];f.drop(f.index[20]).rename_axis('timestamp').to_csv(Path(tmp)/'BTCUSDT.csv')
            with self.assertRaisesRegex(ValueError,'Missing'):load(tmp,'15min')
    def test_undefined_ratios(self):
        x=metrics(pd.Series(100000.,index=pd.date_range('2025-01-01',periods=200,freq='15min',tz='UTC')),100000,'15min');self.assertIsNone(x['research_composite'])

if __name__=='__main__': unittest.main()
