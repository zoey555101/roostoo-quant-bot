import io,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
import pandas as pd
from quant.live import atomic,plan,quantize,submit,recover,pending_check,Blocked,market_frames,cycle,cancel_known,short_check

class LiveTests(unittest.TestCase):
    def fixture(self):
        frames={s:pd.DataFrame({'close':[100.]}) for s in ['BTCUSDT','ETHUSDT','SOLUSDT']}
        exchange={'IsRunning':True,'TradePairs':{s[:-4]+'/USD':{'CanTrade':True,'AmountPrecision':4,'MiniOrder':1} for s in frames}}
        ticker={'Success':True,'Data':{pair:{'MaxBid':99.99,'MinAsk':100.01,'LastPrice':100} for pair in exchange['TradePairs']}}
        balance={'Success':True,'Wallet':{'USD':{'Free':100000,'Lock':0}}}
        return frames,exchange,ticker,balance
    def test_test_caps_precision(self):
        f,e,t,b=self.fixture();nav,orders=plan(e,t,b,{s:.001 for s in f},f)
        self.assertEqual(nav,100000);self.assertEqual(len(orders),3)
        self.assertTrue(all(o['estimated_notional']<=100 for o in orders))
        self.assertEqual(str(quantize(.123456,4)),'0.1234')
    def test_cash_reserve(self):
        f,e,t,b=self.fixture();b['Wallet']['BTC']={'Free':900,'Lock':0};b['Wallet']['USD']['Free']=10000
        _,orders=plan(e,t,b,{s:.001 for s in f},f)
        self.assertTrue(all(o['side']=='SELL' for o in orders))
    def test_spread_blocks(self):
        f,e,t,b=self.fixture();t['Data']['BTC/USD']['MinAsk']=110
        with self.assertRaises(Blocked):plan(e,t,b,{s:.001 for s in f},f)
    def test_basis_blocks(self):
        f,e,t,b=self.fixture();t['Data']['BTC/USD']['LastPrice']=110
        with self.assertRaises(Blocked):plan(e,t,b,{s:.001 for s in f},f)
    def test_locked_balance_blocks(self):
        f,e,t,b=self.fixture();b['Wallet']['USD']['Lock']=10
        with self.assertRaises(Blocked):plan(e,t,b,{s:.001 for s in f},f)
    def test_test_target_rejected(self):
        f,e,t,b=self.fixture()
        with self.assertRaises(Blocked):plan(e,t,b,{s:.15 for s in f},f)
    def test_nan_rejected(self):
        f,e,t,b=self.fixture();b['Wallet']['USD']['Free']=float('nan')
        with self.assertRaises(Blocked):plan(e,t,b,{s:0 for s in f},f)
    def test_minimum_order(self):
        f,e,t,b=self.fixture()
        for v in e['TradePairs'].values():v['MiniOrder']=200
        self.assertEqual(plan(e,t,b,{s:.001 for s in f},f)[1],[])
    def test_timeout_intent_is_durable(self):
        order={'pair':'BTC/USD','side':'BUY','quantity':'1','type':'MARKET','estimated_notional':100}
        client=Mock();client.timestamp.return_value='100000';client.request.side_effect=TimeoutError()
        with tempfile.TemporaryDirectory() as directory:
            state={'intent':None}
            with self.assertRaises(TimeoutError):submit(client,state,directory,order)
            disk=json.loads(Path(directory,'state.json').read_text());self.assertEqual(disk['intent']['quantity'],'1')
            client.request.side_effect=None;client.request.return_value={'Success':False,'ErrMsg':'no order matched'}
            with self.assertRaises(Blocked):recover(client,disk,directory)
            self.assertTrue(all(c.args[0]!='/v3/place_order' for c in client.request.call_args_list[1:]))
    def test_confirmed_order_recovery(self):
        client=Mock();client.timestamp.return_value='1';client.request.return_value={'Success':True,'OrderMatched':[{'OrderID':123,'Status':'FILLED','FilledQuantity':1,'FilledAverPrice':100,'CommissionChargeValue':.1}]}
        state={'intent':{'order_id':123}}
        with tempfile.TemporaryDirectory() as directory:
            recover(client,state,directory);self.assertIsNone(state['intent'])
    def test_pending_blocks(self):
        client=Mock();client.request.return_value={'Success':True,'OrderMatched':[{'OrderID':1,'Status':'PENDING'}]}
        with self.assertRaises(Blocked):pending_check(client)
    def test_pending_missing_schema_blocks(self):
        client=Mock();client.request.return_value={}
        with self.assertRaises(Blocked):pending_check(client)
    def test_atomic_private_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'state.json';atomic(p,{'intent':None});self.assertEqual(p.stat().st_mode & 0o777,0o600)
    def test_only_closed_bars(self):
        start=int(pd.Timestamp('2025-01-01',tz='UTC').timestamp()*1000);now=start+201*900000
        raw=[[start+i*900000,'100','101','99','100','1',start+(i+1)*900000-1,0,0,0,0,0] for i in range(202)]
        with patch('quant.live.urlopen',return_value=io.BytesIO(json.dumps(raw).encode())):
            result=market_frames(['BTCUSDT'],now)
        self.assertEqual(len(result['BTCUSDT']),201)
    def test_successful_submit_confirmed_query(self):
        client=Mock();client.timestamp.return_value='1'
        client.request.side_effect=[{'Success':True,'OrderDetail':{'OrderID':7,'Status':'FILLED'}},{'Success':True,'OrderMatched':[{'OrderID':7,'Status':'FILLED'}]}]
        state={'intent':None};order={'pair':'BTC/USD','side':'BUY','quantity':'1','type':'MARKET','estimated_notional':99}
        with tempfile.TemporaryDirectory() as directory:submit(client,state,directory,order)
        self.assertIsNone(state['intent']);self.assertEqual(client.request.call_count,2)

    def runner_fixture(self):
        frames,e,t,b=self.fixture()
        timestamp=int(pd.Timestamp('2025-01-01',tz='UTC').timestamp()*1000)
        for f in frames.values():f.index=pd.DatetimeIndex([pd.Timestamp('2025-01-01',tz='UTC')])
        t['ServerTime']=timestamp+900001
        client=Mock();client.timestamp.return_value=str(timestamp+900001)
        def request(path,*args,**kwargs):
            if path=='/v6/short_positions':return {'Success':True,'Positions':[]}
            if path=='/v3/exchangeInfo':return e
            if path=='/v3/ticker':return t
            if path=='/v3/balance':return b
            if path=='/v3/query_order':return {'Success':False,'ErrMsg':'no order matched'}
            raise AssertionError('Unexpected mutation '+path)
        client.request.side_effect=request
        return frames,client,b
    def test_dry_run_never_submits(self):
        frames,client,_=self.runner_fixture()
        with tempfile.TemporaryDirectory() as directory,patch('quant.live.market_frames',return_value=frames),patch('quant.live.targets',return_value=pd.DataFrame({s:[.001] for s in frames})),patch('quant.live.submit') as submitted:
            cycle(client,{'intent':None},directory,False)
            submitted.assert_not_called()
    def test_same_bar_not_repeated(self):
        frames,client,_=self.runner_fixture();state={'intent':None}
        with tempfile.TemporaryDirectory() as directory,patch('quant.live.market_frames',return_value=frames),patch('quant.live.targets',return_value=pd.DataFrame({s:[.001] for s in frames})),patch('quant.live.submit') as submitted:
            cycle(client,state,directory,True);cycle(client,state,directory,True)
            self.assertEqual(submitted.call_count,3)
    def test_large_wallet_absolute_target_cap(self):
        frames,client,b=self.runner_fixture();b['Wallet']['USD']['Free']=10000000
        with tempfile.TemporaryDirectory() as directory,patch('quant.live.market_frames',return_value=frames),patch('quant.live.targets',return_value=pd.DataFrame({s:[.001] for s in frames})):
            cycle(client,{'intent':None},directory,False)
            event=json.loads(Path(directory,'events.jsonl').read_text().splitlines()[0])
            self.assertTrue(all(w<=.00001 for w in event['weights'].values()))
    def test_cancel_only_known_id(self):
        client=Mock();client.timestamp.return_value='1'
        client.request.side_effect=[{'Success':True,'OrderMatched':[{'OrderID':7,'Status':'PENDING'}]},{'Success':True,'CanceledList':[7]},{'Success':True,'OrderMatched':[{'OrderID':7,'Status':'CANCELED'}]}]
        state={'intent':{'order_id':7}}
        with tempfile.TemporaryDirectory() as directory:cancel_known(client,state,directory)
        self.assertIsNone(state['intent']);call=client.request.call_args_list[1]
        self.assertEqual(call.args[0],'/v3/cancel_order');self.assertEqual(call.args[1]['order_id'],'7')
    def test_unknown_intent_cannot_cancel(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(Blocked):cancel_known(Mock(),{'intent':{'order_id':None}},directory)

    def test_open_short_blocks(self):
        client=Mock();client.request.return_value={'Success':True,'Positions':[{'ID':1}]}
        with self.assertRaises(Blocked):short_check(client)
    def test_short_schema_missing_blocks(self):
        client=Mock();client.request.return_value={'Success':True}
        with self.assertRaises(Blocked):short_check(client)

    def test_spot_wallet_schema(self):
        f,e,t,b=self.fixture();b['SpotWallet']=b.pop('Wallet')
        b['SpotWallet']['USD'].update(PendingOrders=0,ShortCollateral=0)
        nav,orders=plan(e,t,b,{s:.001 for s in f},f)
        self.assertEqual(nav,100000);self.assertEqual(len(orders),3)
    def test_short_collateral_blocks(self):
        f,e,t,b=self.fixture();b['SpotWallet']=b.pop('Wallet');b['SpotWallet']['USD']['ShortCollateral']=10
        with self.assertRaises(Blocked):plan(e,t,b,{s:.001 for s in f},f)
    def test_pending_reserve_blocks(self):
        f,e,t,b=self.fixture();b['Wallet']['USD']['PendingOrders']=10
        with self.assertRaises(Blocked):plan(e,t,b,{s:.001 for s in f},f)
    def test_missing_wallet_blocks(self):
        f,e,t,b=self.fixture();del b['Wallet']
        with self.assertRaises(Blocked):plan(e,t,b,{s:.001 for s in f},f)

    def test_invalid_spot_entry_blocks(self):
        f,e,t,b=self.fixture();b['SpotWallet']={'USD':100}
        with self.assertRaises(Blocked):plan(e,t,b,{s:0 for s in f},f)
    def test_invalid_spot_does_not_fallback(self):
        f,e,t,b=self.fixture();b['SpotWallet']=None
        with self.assertRaises(Blocked):plan(e,t,b,{s:0 for s in f},f)
    def test_margin_wallet_blocks(self):
        f,e,t,b=self.fixture();b['MarginWallet']={'USD':{'Free':10}}
        with self.assertRaises(Blocked):plan(e,t,b,{s:0 for s in f},f)
    def test_negative_reserved_blocks(self):
        f,e,t,b=self.fixture();b['Wallet']['USD']['PendingOrders']=-1
        with self.assertRaises(Blocked):plan(e,t,b,{s:0 for s in f},f)
    def test_full_cycle_spotwallet(self):
        frames,client,b=self.runner_fixture();b['SpotWallet']=b.pop('Wallet')
        b['SpotWallet']['USD'].update(PendingOrders=0,ShortCollateral=0);b['MarginWallet']={}
        with tempfile.TemporaryDirectory() as directory,patch('quant.live.market_frames',return_value=frames),patch('quant.live.targets',return_value=pd.DataFrame({s:[.001] for s in frames})),patch('quant.live.submit') as submit_mock:
            cycle(client,{'intent':None},directory,False)
            submit_mock.assert_not_called()

if __name__=='__main__':unittest.main()
