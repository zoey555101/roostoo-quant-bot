import contextlib,hashlib,io,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
import pandas as pd
from quant import competition as c
from quant.live import Blocked,atomic,plan,recover

CONFIG=json.loads(Path(__file__).resolve().parents[1].joinpath('competition.json').read_text())

class CompetitionTests(unittest.TestCase):
    def fixture(self,when='2026-10-04T12:15:01Z'):
        now=int(pd.Timestamp(when).timestamp()*1000)
        frames={s:pd.DataFrame({'close':[100.]},index=pd.DatetimeIndex([pd.Timestamp('2026-10-04T12:00:00Z')])) for s in c.SYMBOLS}
        exchange={'IsRunning':True,'TradePairs':{s[:-4]+'/USD':{'CanTrade':True,'AmountPrecision':4,'MiniOrder':1} for s in frames}}
        ticker={'Success':True,'ServerTime':now,'Data':{p:{'LastPrice':100,'MaxBid':99.99,'MinAsk':100.01} for p in exchange['TradePairs']}}
        balance={'Success':True,'SpotWallet':{'USD':{'Free':100000,'Lock':0}},'MarginWallet':{}}
        client=Mock();client.offset=0;client.timestamp.return_value=str(now)
        def request(path,*args,**kwargs):
            if path=='/v6/short_positions':return {'Success':True,'Positions':[]}
            if path=='/v3/query_order':return {'Success':False,'ErrMsg':'no order matched'}
            if path=='/v3/exchangeInfo':return exchange
            if path=='/v3/ticker':return ticker
            if path=='/v3/balance':return balance
            raise AssertionError('Unexpected endpoint: '+path)
        client.request.side_effect=request
        return frames,exchange,ticker,balance,client

    def run_cycle(self,client,state,frames,execute=False):
        with tempfile.TemporaryDirectory() as d,patch('quant.competition.market_frames',return_value=frames),patch('quant.competition.targets',return_value=pd.DataFrame({s:[.05] for s in frames})),patch('quant.competition.submit') as submit,patch.dict(os.environ,{'ROOSTOO_ACCOUNT_MODE':'COMPETITION'}),contextlib.redirect_stdout(io.StringIO()):
            c.cycle(client,state,d,CONFIG,execute)
            return submit.call_count,json.loads(Path(d,'state.json').read_text())

    def test_gate_exact_boundary(self):
        client=Mock();start=int(pd.Timestamp(CONFIG['start_utc']).timestamp()*1000)
        for delta,expected in [(-1,False),(0,True),(1,True)]:
            client.timestamp.return_value=str(start+delta);self.assertEqual(c.gate(client,CONFIG),expected)

    def test_before_start_no_mutation_even_execute(self):
        f,e,t,b,client=self.fixture('2026-10-04T11:59:59Z')
        n,state=self.run_cycle(client,{'intent':None},f,True)
        self.assertEqual(n,0);self.assertEqual(state['last_phase'],'WAITING_START')

    def test_read_only_after_start_no_mutation(self):
        f,e,t,b,client=self.fixture();n,state=self.run_cycle(client,{'intent':None},f)
        self.assertEqual(n,0);self.assertEqual(state['last_phase'],'READY')

    def test_scheduled_execute_and_no_duplicate_bar(self):
        f,e,t,b,client=self.fixture();state={'intent':None}
        n,state=self.run_cycle(client,state,f,True);self.assertEqual(n,3)
        n,state=self.run_cycle(client,state,f,True);self.assertEqual(n,0)

    def test_guard_rejects_wrong_mode(self):
        client=self.fixture()[-1]
        with patch.dict(os.environ,{'ROOSTOO_ACCOUNT_MODE':'TEST'}),patch('quant.competition.submit') as submit:
            with self.assertRaises(Blocked):c.execute_guarded(client,{},'.',{'side':'BUY'},CONFIG,True)
            submit.assert_not_called()

    def test_guard_rechecks_time_before_submit(self):
        client=self.fixture('2026-10-04T11:59:59Z')[-1]
        with patch.dict(os.environ,{'ROOSTOO_ACCOUNT_MODE':'COMPETITION'}),patch('quant.competition.submit') as submit:
            with self.assertRaises(Blocked):c.execute_guarded(client,{},'.',{'side':'BUY'},CONFIG,True)
            submit.assert_not_called()

    def test_guard_dry_and_halted_buy(self):
        client=self.fixture()[-1]
        with patch.dict(os.environ,{'ROOSTOO_ACCOUNT_MODE':'COMPETITION'}),patch('quant.competition.submit') as submit:
            with self.assertRaises(Blocked):c.execute_guarded(client,{},'.',{'side':'BUY'},CONFIG,False)
            with self.assertRaises(Blocked):c.execute_guarded(client,{'halted':True},'.',{'side':'BUY'},CONFIG,True)
            c.execute_guarded(client,{'halted':True},'.',{'side':'SELL'},CONFIG,True)
            self.assertEqual(submit.call_count,1)

    def test_production_caps_and_slicing(self):
        f,e,t,b,client=self.fixture();nav,orders=plan(e,t,b,{s:.05 for s in f},f,2000,c.limits(CONFIG))
        self.assertEqual(len(orders),3);self.assertTrue(all(o['estimated_notional']<=2000 for o in orders))
        with self.assertRaises(Blocked):plan(e,t,b,{s:.051 for s in f},f,2000,c.limits(CONFIG))

    def test_cash_reserve_blocks_buys_above_exposure(self):
        f,e,t,b,client=self.fixture();b['SpotWallet']['USD']['Free']=84000;b['SpotWallet']['BTC']={'Free':160}
        orders=plan(e,t,b,{s:.05 for s in f},f,2000,c.limits(CONFIG))[1]
        self.assertTrue(all(o['side']=='SELL' for o in orders))

    def test_drawdown_exit_independent_of_binance(self):
        f,e,t,b,client=self.fixture();b['SpotWallet']['USD']['Free']=90000;b['SpotWallet']['BTC']={'Free':100}
        t['Data']['BTC/USD']['MinAsk']=110
        state={'intent':None,'high_water':120000}
        with tempfile.TemporaryDirectory() as d,patch('quant.competition.market_frames',side_effect=AssertionError('Risk exit requested Binance')),contextlib.redirect_stdout(io.StringIO()):
            c.cycle(client,state,d,CONFIG,False)
            event=json.loads(Path(d,'events.jsonl').read_text().splitlines()[-1])
            self.assertTrue(state['halted']);self.assertEqual(event['phase'],'RISK_EXIT')
            self.assertEqual(event['orders'][0]['side'],'SELL')
            self.assertLessEqual(event['orders'][0]['estimated_notional'],2000)

    def test_halt_persists_after_nav_recovery(self):
        f,e,t,b,client=self.fixture();n,state=self.run_cycle(client,{'intent':None,'halted':True},f)
        self.assertTrue(state['halted']);self.assertEqual(n,0)

    def test_stale_quote_and_host_clock_block(self):
        f,e,t,b,client=self.fixture();t['ServerTime']-=16000
        with self.assertRaises(Blocked):c.quote(client)
        t['ServerTime']+=16000;client.offset=60001
        with self.assertRaises(Blocked):self.run_cycle(client,{'intent':None},f,True)

    def test_valuation_rejects_reserved_and_unsupported(self):
        f,e,t,b,client=self.fixture();b['SpotWallet']['USD']['PendingOrders']=1
        with self.assertRaises(Blocked):c.valuation(b,t)
        b['SpotWallet']['USD']['PendingOrders']=0;b['SpotWallet']['DOGE']={'Free':1}
        with self.assertRaises(Blocked):c.valuation(b,t)

    def test_fill_counter_not_duplicated_on_recovery(self):
        client=Mock();client.request.return_value={'Success':True,'OrderMatched':[{'OrderID':7,'Status':'FILLED'}]}
        state={'intent':{'order_id':7}}
        with tempfile.TemporaryDirectory() as d:
            recover(client,state,d);recover(client,state,d)
        self.assertEqual(state['confirmed_fills'],1);self.assertEqual(len(state['active_days']),1)

    def test_simulated_server_cycle_records_fills_and_wallet(self):
        f,e,t,b,client=self.fixture();original=client.request.side_effect;orders={}
        def server(path,*args,**kwargs):
            params=args[0] if args else {}
            if path=='/v3/place_order':
                order_id=len(orders)+1;qty=float(params['quantity']);coin=params['pair'].split('/')[0]
                b['SpotWallet']['USD']['Free']-=qty*100*1.001
                b['SpotWallet'][coin]={'Free':qty}
                orders[order_id]={'OrderID':order_id,'Pair':params['pair'],'Side':params['side'],'Status':'FILLED','FilledQuantity':qty,'FilledAverPrice':100,'CommissionChargeValue':qty*.1}
                return {'Success':True,'OrderDetail':orders[order_id]}
            if path=='/v3/query_order' and 'order_id' in params:
                return {'Success':True,'OrderMatched':[orders[int(params['order_id'])]]}
            return original(path,*args,**kwargs)
        client.request.side_effect=server;state={'intent':None}
        with tempfile.TemporaryDirectory() as d,patch('quant.competition.market_frames',return_value=f),patch('quant.competition.targets',return_value=pd.DataFrame({s:[.05] for s in f})),patch.dict(os.environ,{'ROOSTOO_ACCOUNT_MODE':'COMPETITION'}),contextlib.redirect_stdout(io.StringIO()):
            c.cycle(client,state,d,CONFIG,True)
            saved=json.loads(Path(d,'state.json').read_text())
            self.assertEqual(saved['confirmed_fills'],3);self.assertIsNone(saved['intent'])
            self.assertAlmostEqual(saved['last_nav'],c.valuation(b,t));self.assertLess(saved['last_nav'],100000)
            self.assertEqual(len(orders),3)

    def test_verifier_queries_real_order_id_and_writes_proof(self):
        from quant import verify_test
        client=Mock();client.request.side_effect=lambda path,*args: {'Success':True,'Positions':[]} if path=='/v6/short_positions' else ({'Success':True,'SpotWallet':{'USD':{'Free':50000}},'MarginWallet':{}} if path=='/v3/balance' else ({'Success':True,'OrderMatched':[{'OrderID':7,'Status':'FILLED'}]} if args and 'order_id' in args[0] else {'Success':False,'ErrMsg':'no order matched'}))
        with tempfile.TemporaryDirectory() as d:
            previous=os.getcwd();os.chdir(d)
            try:
                root=Path('runtime/test');root.mkdir(parents=True);key='unit-test-key'
                atomic(root/'credentials.json',{'account_mode':'TEST','api_key':key,'secret':'unit-test-secret'})
                atomic(root/'state.json',{'account_hash':hashlib.sha256(key.encode()).hexdigest(),'intent':None})
                (root/'events.jsonl').write_text(json.dumps({'event':'order_reconciled','status':'FILLED','order_id':7})+'\n')
                with patch('quant.verify_test.Roostoo',return_value=client),patch('quant.verify_test.Path.home',return_value=Path(d)),patch.dict(os.environ,{}),contextlib.redirect_stdout(io.StringIO()):verify_test.main()
                proof=json.loads((root/'verification.json').read_text());self.assertEqual(proof['confirmed_order_id'],7)
                self.assertIn('separate_process_query',proof['checks'])
            finally:os.chdir(previous)

    def test_start_correction_preserves_recovery_and_risk(self):
        previous=dict(CONFIG,start_utc='2026-10-04T00:00:00Z')
        state={'config_hash':hashlib.sha256(json.dumps(previous,sort_keys=True).encode()).hexdigest(),'intent':{'order_id':7},'halted':True,'confirmed_fills':3,'account_hash':'bound'}
        original=dict(state)
        with tempfile.TemporaryDirectory() as d:
            c.reconcile_config(state,d,CONFIG)
            self.assertEqual(json.loads(Path(d,'state.before_start_correction.json').read_text()),original)
            self.assertEqual(state['intent'],original['intent']);self.assertTrue(state['halted'])
            self.assertEqual(state['confirmed_fills'],3);self.assertEqual(state['account_hash'],'bound')
            c.reconcile_config(state,d,CONFIG)
            self.assertEqual(len(Path(d,'events.jsonl').read_text().splitlines()),1)

    def test_start_correction_rejects_unrelated_risk_change(self):
        previous=dict(CONFIG,start_utc='2026-10-04T00:00:00Z',coin_cap=.04)
        state={'config_hash':hashlib.sha256(json.dumps(previous,sort_keys=True).encode()).hexdigest()}
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(Blocked):c.reconcile_config(state,d,CONFIG)
        client=self.fixture('2026-10-04T00:00:00Z')[-1]
        self.assertFalse(c.gate(client,CONFIG))

    def test_wrong_start_configuration_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d,'config.json');bad=dict(CONFIG,start_utc='2026-10-04T08:00:00Z');path.write_text(json.dumps(bad))
            with self.assertRaises(Blocked):c.config_load(path)

    def test_requires_recent_real_test_proof(self):
        with tempfile.TemporaryDirectory() as d:
            previous=os.getcwd();os.chdir(d)
            try:
                root=Path('runtime/test');root.mkdir(parents=True)
                atomic(root/'credentials.json',{'account_mode':'TEST','api_key':'test-key'})
                atomic(root/'state.json',{'intent':None})
                with self.assertRaises(Blocked):c.require_test_verification()
                proof={'test_account_hash':hashlib.sha256(b'test-key').hexdigest(),'confirmed_unique_fills':1,'confirmed_order_id':7,'verified_utc':pd.Timestamp.now(tz='UTC').isoformat(),'checks':['confirmed_fill','separate_process_query','balance_schema','no_pending','no_short','no_unresolved_intent']}
                atomic(root/'verification.json',proof);self.assertEqual(c.require_test_verification()['confirmed_order_id'],7)
                proof['verified_utc']=(pd.Timestamp.now(tz='UTC')-pd.Timedelta('25h')).isoformat();atomic(root/'verification.json',proof)
                with self.assertRaises(Blocked):c.require_test_verification()
            finally:os.chdir(previous)

    def test_initial_arm_requires_proof_restart_retains_it(self):
        state={};proof={'test_account_hash':'abc','verified_utc':'2026-10-03T00:00:00Z','confirmed_order_id':7}
        with patch('quant.competition.require_test_verification',return_value=proof) as verify:
            c.arm_execution(state);c.arm_execution(state)
            self.assertEqual(verify.call_count,1);self.assertEqual(state['armed_verification']['confirmed_order_id'],7)

if __name__=='__main__':unittest.main()
