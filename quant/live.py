"""Long/cash test-account runner. Default is read-only; never retry a submit."""
import argparse
from dataclasses import dataclass, replace
from decimal import Decimal, ROUND_DOWN
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import time
from urllib.parse import urlencode
from urllib.request import urlopen
import pandas as pd
from .roostoo import Roostoo
from .strategy import Config, targets

class Blocked(RuntimeError):
    pass


def atomic(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp')
    with open(tmp,'w') as f:
        os.chmod(tmp,0o600);json.dump(value,f,indent=2,allow_nan=False);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)
    directory=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(directory)
    finally:os.close(directory)


def audit(directory,event,**fields):
    # Caller supplies selected fields only; never requests/headers/credentials.
    path=Path(directory)/'events.jsonl'
    with open(path,'a') as f:
        os.chmod(path,0o600)
        f.write(json.dumps({'utc':pd.Timestamp.now(tz='UTC').isoformat(),'event':event,**fields},allow_nan=False)+'\n');f.flush();os.fsync(f.fileno())


def positive(value, name, zero=False):
    value=float(value)
    if not math.isfinite(value) or value<0 or (value==0 and not zero):raise Blocked(f'Invalid {name}')
    return value


def market_frames(symbols, now_ms):
    frames={}
    for symbol in symbols:
        query=urlencode({'symbol':symbol,'interval':'15m','limit':500,'endTime':int(now_ms)})
        with urlopen('https://data-api.binance.vision/api/v3/klines?'+query,timeout=15) as response:
            raw=json.load(response)
        if not isinstance(raw,list):raise Blocked('Invalid Binance response')
        rows=[]
        for bar in raw:
            if int(bar[6])>=now_ms:continue
            rows.append({'timestamp':pd.to_datetime(int(bar[0]),unit='ms',utc=True),
                         **{name:positive(bar[pos],name, name=='volume') for name,pos in [('open',1),('high',2),('low',3),('close',4),('volume',5)]}})
        if len(rows)<200:raise Blocked('Insufficient closed Binance bars')
        frame=pd.DataFrame(rows).set_index('timestamp').sort_index()
        if ((frame.high < frame[['open','close','low']].max(axis=1)) | (frame.low > frame[['open','close','high']].min(axis=1))).any():raise Blocked('Invalid OHLC values')
        if frame.index.has_duplicates or not (frame.index.to_series().diff().dropna()==pd.Timedelta('15min')).all():raise Blocked('Binance bars duplicated or missing')
        closed_at=frame.index[-1]+pd.Timedelta('15min')
        age=pd.to_datetime(now_ms,unit='ms',utc=True)-closed_at
        if age<pd.Timedelta(0) or age>pd.Timedelta('17min'):raise Blocked('Stale Binance bars')
        frames[symbol]=frame
    first=next(iter(frames.values())).index
    if not all(frame.index.equals(first) for frame in frames.values()):raise Blocked('Binance asset bars do not align')
    return frames


def quantize(quantity, precision):
    precision=int(precision)
    if not 0<=precision<=12:raise Blocked('Unsupported amount precision')
    return Decimal(str(quantity)).quantize(Decimal(1).scaleb(-precision),rounding=ROUND_DOWN)


def spot_wallet(balance):
    """Normalize documented Wallet and observed SpotWallet without masking errors."""
    if not isinstance(balance,dict) or balance.get('Success') is not True:
        raise Blocked('Balance query not confirmed')
    wallet=balance['SpotWallet'] if 'SpotWallet' in balance else balance.get('Wallet')
    if not isinstance(wallet,dict) or not isinstance(wallet.get('USD'),dict):
        raise Blocked('Missing spot wallet or USD balance')
    margin=balance.get('MarginWallet',{})
    if not isinstance(margin,dict):raise Blocked('Invalid margin wallet schema')
    if margin:raise Blocked('Margin wallet exists; this runner supports spot only')
    for coin,entry in wallet.items():
        if not isinstance(coin,str) or not isinstance(entry,dict):
            raise Blocked('Invalid spot wallet entry')
        for field in ('Free','Lock','PendingOrders','ShortCollateral'):
            positive(entry.get(field,0),field,True)
    return wallet


@dataclass(frozen=True)
class Limits:
    coin_cap: float = .001
    gross_cap: float = .003
    cash_reserve: float = .30
    min_trade_usd: float = 10
    band_weight: float = .0002
    band_usd_cap: float = 20
    max_spread: float = .005
    max_basis: float = .03


def plan(exchange,ticker,balance,weights,frames,max_order=99,limits=None,emergency=False):
    limits=limits or Limits()
    if exchange.get('IsRunning') is not True or ticker.get('Success') is not True or balance.get('Success') is not True:raise Blocked('Exchange/account not ready')
    pairs=exchange['TradePairs'];quotes=ticker['Data'];wallet=spot_wallet(balance)
    coins={s[:-4] for s in frames}
    for coin,entry in wallet.items():
        free=positive(entry.get('Free',0),'free balance',True);locked=positive(entry.get('Lock',0),'locked balance',True)
        reserved=sum(positive(entry.get(field,0),field,True) for field in ('PendingOrders','ShortCollateral'))
        if locked>1e-8 or reserved>1e-8:raise Blocked('Locked balance exists; pending orders/short collateral need review')
        if coin not in coins|{'USD'} and free>1e-8:raise Blocked('Account has assets outside selected universe')
    cash=positive(wallet.get('USD',{}).get('Free',0),'USD balance',True);nav=cash;marks={}
    for symbol in frames:
        coin=symbol[:-4];pair=coin+'/USD'
        if pair not in pairs or pairs[pair].get('CanTrade') is not True:raise Blocked(f'{pair} is not tradable')
        quote=quotes[pair];bid=positive(quote['MaxBid'],'bid');ask=positive(quote['MinAsk'],'ask');last=positive(quote['LastPrice'],'last')
        if ask<bid:raise Blocked('Crossed Roostoo market')
        mid=(bid+ask)/2
        if not emergency and (ask-bid)/mid>limits.max_spread:raise Blocked('Roostoo spread > 0.5%')
        if not emergency and abs(last/float(frames[symbol].close.iloc[-1])-1)>limits.max_basis:raise Blocked('Roostoo/Binance basis > 3%')
        quantity=positive(wallet.get(coin,{}).get('Free',0),'coin balance',True)
        marks[symbol]=(pair,bid,ask,last,quantity);nav+=quantity*last
    if nav<=0:raise Blocked('Empty account')
    orders=[]
    for symbol,(pair,bid,ask,last,held) in marks.items():
        target=positive(weights[symbol],'target weight',True)
        if target>limits.coin_cap+1e-12:raise Blocked('Target exceeds coin cap')
        delta=target*nav-held*last
        # No-trade band is at least $10 and 0.02% NAV. Sells beyond the test
        # budget are sliced on later bars; no blind liquidation of existing holdings.
        if not emergency and abs(delta)<max(limits.min_trade_usd,min(limits.band_usd_cap,nav*limits.band_weight)):continue
        side='BUY' if delta>0 else 'SELL';price=ask if side=='BUY' else bid
        notional=min(abs(delta),max_order)
        if side=='BUY':notional=min(notional,max(0,cash-nav*limits.cash_reserve)/(1.002))
        quantity=quantize(min(notional/price,held) if side=='SELL' else notional/price,pairs[pair]['AmountPrecision'])
        if quantity<=0 or float(quantity)*price<=positive(pairs[pair]['MiniOrder'],'minimum order',True):continue
        orders.append({'pair':pair,'side':side,'quantity':format(quantity,'f'),'type':'MARKET','estimated_notional':float(quantity)*price})
    if sum(float(weights[s]) for s in weights)>limits.gross_cap+1e-12:raise Blocked('Target exceeds gross cap')
    return nav,sorted(orders,key=lambda x:x['side']=='BUY')


def short_check(client):
    result=client.request('/v6/short_positions',{'timestamp':client.timestamp()},True)
    if result.get('Success') is not True or not isinstance(result.get('Positions'),list):raise Blocked('Cannot confirm short-position state')
    if result['Positions']:raise Blocked('Open shorts exist; this runner supports long/cash only')


def pending_check(client):
    result=client.request('/v3/query_order',{'timestamp':client.timestamp(),'pending_only':'TRUE','limit':'100'},True,'POST',True)
    if result.get('Success') is not True and not (result.get('Success') is False and ' '.join(str(result.get('ErrMsg','')).split()).casefold().rstrip('.')=='no order matched'):raise Blocked('Pending-order response not confirmed')
    if result.get('Success') is True and not isinstance(result.get('OrderMatched'),list):raise Blocked('Pending-order list missing')
    if result.get('OrderMatched'):raise Blocked('Pending orders exist; no new orders allowed')


def recover(client,state,directory):
    intent=state.get('intent')
    if not intent:return
    if intent.get('order_id') is None:
        # No exchange clientOrderId exists. A matching history row is evidence,
        # not a guarantee: retain the block, even when no row is found yet.
        recent=client.request('/v3/query_order',{'timestamp':client.timestamp(),'limit':'100'},True,'POST',True)
        matches=[o.get('OrderID') for o in recent.get('OrderMatched',[]) if o.get('Pair')==intent['pair'] and o.get('Side')==intent['side'] and abs(float(o.get('Quantity',-1))-float(intent['quantity']))<1e-10 and float(o.get('CreateTimestamp',0))>=intent['submitted_ms']-60000]
        audit(directory,'ambiguous_order',candidate_order_ids=matches)
        raise Blocked('Unconfirmed submission retained. Inspect order history; do not reset state or resend.')
    result=client.request('/v3/query_order',{'timestamp':client.timestamp(),'order_id':str(intent['order_id'])},True,'POST')
    if result.get('Success') is not True:raise Blocked('Order query not confirmed')
    matched=result.get('OrderMatched',[])
    exact=[o for o in matched if str(o.get('OrderID'))==str(intent['order_id'])]
    if len(exact)!=1:raise Blocked('Known order cannot be reconciled')
    order=exact[0];status=order.get('Status')
    audit(directory,'order_reconciled',order_id=intent['order_id'],status=status,filled_quantity=order.get('FilledQuantity'),filled_price=order.get('FilledAverPrice'),fee=order.get('CommissionChargeValue'))
    if status not in ('FILLED','CANCELED'):raise Blocked('Order remains pending or unknown; new orders blocked')
    if status=='FILLED':
        state['confirmed_fills']=int(state.get('confirmed_fills',0))+1
        state['last_fill']={'order_id':intent['order_id'],'pair':intent.get('pair'),'side':intent.get('side'),'quantity':order.get('FilledQuantity'),'price':order.get('FilledAverPrice'),'fee':order.get('CommissionChargeValue')}
        day=pd.Timestamp.now(tz='Asia/Hong_Kong').strftime('%Y-%m-%d')
        state['active_days']=sorted(set(state.get('active_days',[]))|{day})
    state['intent']=None;atomic(Path(directory)/'state.json',state)


def submit(client,state,directory,order):
    # Durable intent precedes ANY network mutation; on an unknown outcome the
    # next run performs read-only recovery, never a second POST.
    intent={**order,'submitted_ms':int(client.timestamp()),'order_id':None}
    state['intent']=intent;atomic(Path(directory)/'state.json',state)
    audit(directory,'submit_intent',**intent)
    params={k:order[k] for k in ('pair','side','quantity','type')};params['timestamp']=str(intent['submitted_ms'])
    result=client.request('/v3/place_order',params,True,'POST')
    if result.get('Success') is not True:raise Blocked('Submission not confirmed')
    detail=result.get('OrderDetail',{})
    if detail.get('OrderID') is None:raise Blocked('Submission response missing order id')
    intent['order_id']=detail['OrderID'];atomic(Path(directory)/'state.json',state)
    # Query the server even if submit response says FILLED.
    recover(client,state,directory)


def cycle(client,state,directory,execute=False):
    client.sync_time();recover(client,state,directory);short_check(client)
    exchange=client.request('/v3/exchangeInfo')
    ticker=client.request('/v3/ticker',{'timestamp':client.timestamp()})
    server=int(ticker.get('ServerTime',0))
    if abs(server-int(client.timestamp()))>15000:raise Blocked('Stale Roostoo ticker')
    pending_check(client)
    frames=market_frames(['BTCUSDT','ETHUSDT','SOLUSDT'],server)
    ticker=client.request('/v3/ticker',{'timestamp':client.timestamp()})
    if abs(int(ticker.get('ServerTime',0))-int(client.timestamp()))>15000:raise Blocked('Stale post-data ticker')
    c=replace(Config(),coin_cap=.001,gross_cap=.003,min_trade_weight=.0002)
    weights=targets(frames,c).iloc[-1].to_dict();bar=int(next(iter(frames.values())).index[-1].timestamp()*1000)
    balance=client.request('/v3/balance',{'timestamp':client.timestamp()},True)
    nav,_=plan(exchange,ticker,balance,weights,frames)
    # Also cap the test target at $100 per coin, including larger test wallets.
    weights={s:min(w,100/nav) for s,w in weights.items()}
    nav,orders=plan(exchange,ticker,balance,weights,frames)
    usd=positive(spot_wallet(balance)['USD'].get('Free',0),'USD balance',True)
    if nav-usd>max(315,nav*.00315):raise Blocked('Existing holdings exceed test scope; use a clean dedicated test account')
    state['high_water']=max(float(state.get('high_water',nav)),nav)
    if nav/state['high_water']-1<=-.06:state['halted']=True
    atomic(Path(directory)/'state.json',state)
    audit(directory,'cycle',mode='TEST_EXECUTE' if execute else 'DRY_RUN',nav=nav,weights=weights,orders=orders,halted=state.get('halted',False),bar_open_ms=bar)
    print(json.dumps({'mode':'TEST_EXECUTE' if execute else 'DRY_RUN','nav':round(nav,2),'orders':orders,'halted':state.get('halted',False)},ensure_ascii=False),flush=True)
    if state.get('halted'):raise Blocked('Drawdown guard latched. No automatic liquidation in this test runner.')
    if state.get('last_bar')==bar or bar//900000%4!=0:return
    if not execute:return
    # Mark bar BEFORE orders: crash/restart cannot repeat a completed bar's batch.
    state['last_bar']=bar;atomic(Path(directory)/'state.json',state)
    for order in orders:
        # Re-fetch balance/ticker and regenerate only this planned asset before
        # each order: selling never assumes fills, buying never assumes cash.
        pending_check(client)
        fresh=client.request('/v3/ticker',{'timestamp':client.timestamp()})
        if abs(int(fresh.get('ServerTime',0))-int(client.timestamp()))>15000:raise Blocked('Stale pre-trade ticker')
        current=client.request('/v3/balance',{'timestamp':client.timestamp()},True)
        _,replanned=plan(exchange,fresh,current,weights,frames)
        same=[o for o in replanned if o['pair']==order['pair'] and o['side']==order['side']]
        if same:submit(client,state,directory,same[0])


def cancel_known(client,state,directory):
    intent=state.get('intent')
    if not intent or intent.get('order_id') is None:raise Blocked('No confirmed runner-owned order to cancel')
    client.sync_time()
    result=client.request('/v3/query_order',{'timestamp':client.timestamp(),'order_id':str(intent['order_id'])},True,'POST')
    if result.get('Success') is not True:raise Blocked('Cannot confirm cancellation target')
    exact=[o for o in result.get('OrderMatched',[]) if str(o.get('OrderID'))==str(intent['order_id'])]
    if len(exact)!=1:raise Blocked('Cancellation target not found')
    if exact[0].get('Status') in ('FILLED','CANCELED'):
        recover(client,state,directory);return
    if exact[0].get('Status')!='PENDING':raise Blocked('Unknown order status')
    if intent.get('cancel_attempted'):raise Blocked('Previous cancellation outcome unresolved; query history, do not repeat')
    intent['cancel_attempted']=True;atomic(Path(directory)/'state.json',state)
    audit(directory,'cancel_intent',order_id=intent['order_id'])
    client.request('/v3/cancel_order',{'timestamp':client.timestamp(),'order_id':str(intent['order_id'])},True,'POST')
    recover(client,state,directory)


def main():
    p=argparse.ArgumentParser(description='Test-account long/cash runner; default read-only')
    p.add_argument('--profile',help='Local credential JSON; mode 0600 required')
    p.add_argument('--cancel-known',action='store_true',help='Cancel only the confirmed order retained in this runner state')
    p.add_argument('--execute-test',action='store_true');p.add_argument('--once',action='store_true');p.add_argument('--state-dir',default='runtime/test');p.add_argument('--poll-seconds',type=int,default=300)
    a=p.parse_args()
    if a.profile:
        profile_path=Path(a.profile)
        if profile_path.stat().st_mode & 0o077:raise SystemExit('Credential file must have mode 0600')
        profile=json.loads(profile_path.read_text())
        os.environ['ROOSTOO_API_KEY']=profile['api_key']
        os.environ['ROOSTOO_SECRET_KEY']=profile['secret']
        os.environ['ROOSTOO_ACCOUNT_MODE']=profile['account_mode']
    if a.poll_seconds<60:raise SystemExit('Polling must be >=60 seconds')
    if (a.execute_test or a.cancel_known) and os.getenv('ROOSTOO_ACCOUNT_MODE')!='TEST':raise SystemExit('Execution requires ROOSTOO_ACCOUNT_MODE=TEST and testing credentials')
    if not os.getenv('ROOSTOO_API_KEY') or not os.getenv('ROOSTOO_SECRET_KEY'):raise SystemExit('Missing credentials')
    os.umask(0o077)
    directory=Path(a.state_dir);directory.mkdir(parents=True,exist_ok=True)
    # Account lock in the home directory prevents two copies of this runner
    # trading the same key on this host, even with different state directories.
    account=hashlib.sha256(os.environ['ROOSTOO_API_KEY'].encode()).hexdigest()
    lock_dir=Path.home()/'.roostoo-locks';lock_dir.mkdir(mode=0o700,exist_ok=True)
    with open(lock_dir/(account+'.lock'),'w') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise SystemExit('Another runner already uses this account')
        state_path=directory/'state.json'
        state=json.loads(state_path.read_text()) if state_path.exists() else {'account_hash':account,'intent':None}
        if state.get('account_hash')!=account:raise SystemExit('State belongs to another account; do not reuse its directory')
        bound=lock_dir/(account+'.json')
        if bound.exists() and json.loads(bound.read_text())['state_dir']!=str(directory.resolve()):raise SystemExit('This account is bound to another state directory; retain its recovery state')
        atomic(bound,{'state_dir':str(directory.resolve())});atomic(state_path,state)
        client=Roostoo()
        while True:
            try:
                if a.cancel_known:
                    cancel_known(client,state,directory);return
                cycle(client,state,directory,a.execute_test)
            except Exception as e:
                # Do not log exception text: transport errors may contain URLs.
                audit(directory,'stopped',error_type=type(e).__name__,has_unresolved_intent=bool(state.get('intent')))
                reason=str(e) if isinstance(e,(Blocked,RuntimeError)) else ('Missing response field: '+str(e.args[0]) if isinstance(e,KeyError) else type(e).__name__)
                print('Stopped safely:',reason,flush=True)
                raise SystemExit(1)
            if a.once:return
            try:time.sleep(a.poll_seconds)
            except KeyboardInterrupt:return

if __name__=='__main__':main()
