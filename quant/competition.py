"""Competition runner: default read-only, exchange-clock gate, persistent risk exit."""
import argparse
from dataclasses import replace
import fcntl
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.error import URLError
import pandas as pd
from .live import (Blocked, Limits, atomic, audit, positive, spot_wallet, plan,
                   market_frames, pending_check, short_check, recover, submit)
from .roostoo import Roostoo
from .strategy import Config,targets

SYMBOLS=['BTCUSDT','ETHUSDT','SOLUSDT']


def config_load(path):
    c=json.loads(Path(path).read_text())
    start=pd.Timestamp(c['start_utc'])
    if start.tzinfo is None:raise Blocked('Start timestamp needs explicit timezone')
    if start!=pd.Timestamp('2026-10-04T12:00:00Z'):raise Blocked('Start must equal user-confirmed 20:00 Hong Kong Oct 4 2026')
    if not 0<float(c['coin_cap'])<=float(c['gross_cap'])<=.70:raise Blocked('Invalid exposure caps')
    if not 0<float(c['drawdown_stop'])<=.08:raise Blocked('Invalid drawdown guard')
    if not 1<=float(c['max_order_usd'])<=10000:raise Blocked('Invalid order cap')
    if not 60<=int(c['poll_seconds'])<=900 or int(c['rebalance_bars'])<1:raise Blocked('Invalid cadence')
    for key in ('min_trade_usd','band_weight','max_spread','max_basis'):
        positive(c[key],key)
    if float(c['band_weight'])>=1 or float(c['max_spread'])>.02 or float(c['max_basis'])>.10:raise Blocked('Invalid filters')
    return c


def gate(client,c):
    now=int(client.timestamp())
    # sync_time uses trusted exchange time, not user-local scheduling.
    return now>=int(pd.Timestamp(c['start_utc']).timestamp()*1000)


def quote(client):
    result=client.request('/v3/ticker',{'timestamp':client.timestamp()})
    if result.get('Success') is not True or abs(int(result.get('ServerTime',0))-int(client.timestamp()))>15000:raise Blocked('Roostoo ticker stale or invalid')
    return result


def valuation(balance,ticker):
    wallet=spot_wallet(balance);nav=positive(wallet['USD'].get('Free',0),'cash',True)
    # Locked/reserved sums are not added twice or silently omitted from NAV:
    # while account has locks the runner stops until reconciliation resolves them.
    for coin,entry in wallet.items():
        if any(positive(entry.get(k,0),k,True)>1e-8 for k in ('Lock','PendingOrders','ShortCollateral')):raise Blocked('Account reserved funds require reconciliation')
        free=positive(entry.get('Free',0),'coin units',True)
        if coin=='USD':continue
        if coin+'USDT' not in SYMBOLS and free>1e-8:raise Blocked('Unsupported account asset')
        if free:nav+=free*positive(ticker['Data'][coin+'/USD']['LastPrice'],'valuation price')
    if nav<=0:raise Blocked('Empty competition account')
    return nav


def limits(c):
    return Limits(coin_cap=float(c['coin_cap']),gross_cap=float(c['gross_cap']),
                  cash_reserve=1-float(c['gross_cap']),min_trade_usd=float(c['min_trade_usd']),
                  band_weight=float(c['band_weight']),band_usd_cap=float('inf'),
                  max_spread=float(c['max_spread']),max_basis=float(c['max_basis']))


def execute_guarded(client,state,directory,order,c,execute):
    if not execute:raise Blocked('Mutation blocked in read-only mode')
    if os.getenv('ROOSTOO_ACCOUNT_MODE')!='COMPETITION':raise Blocked('Mutation blocked for noncompetition profile')
    if not gate(client,c):raise Blocked('No trading before competition start')
    if state.get('halted') and order['side']!='SELL':raise Blocked('Risk exit only permits sells')
    submit(client,state,directory,order)


def cycle(client,state,directory,c,execute=False):
    client.sync_time()
    if abs(float(client.offset))>60000:raise Blocked('Host clock differs from exchange by >60 seconds')
    recover(client,state,directory);pending_check(client);short_check(client)
    exchange=client.request('/v3/exchangeInfo')
    ticker=quote(client);balance=client.request('/v3/balance',{'timestamp':client.timestamp()},True)
    nav=valuation(balance,ticker)
    started=gate(client,c)
    state['high_water']=max(nav,float(state.get('high_water',nav)))
    drawdown=nav/state['high_water']-1
    if started and drawdown<=-float(c['drawdown_stop']):state['halted']=True
    halted=bool(state.get('halted',False));weights={s:0.0 for s in SYMBOLS};bar=None
    if halted:
        # Independent of Binance availability when exiting risk. Avoid applying
        # entry spread/basis filters to an emergency sell. No stale-price orders.
        frames={s:pd.DataFrame({'close':[positive(ticker['Data'][s[:-4]+'/USD']['LastPrice'],'exit quote')]}) for s in SYMBOLS}
    else:
        frames=market_frames(SYMBOLS,int(ticker['ServerTime']))
        ticker=quote(client)
        nav=valuation(balance,ticker)
        c_signal=replace(Config(),coin_cap=float(c['coin_cap']),gross_cap=float(c['gross_cap']))
        weights=targets(frames,c_signal).iloc[-1].to_dict()
        bar=int(frames[SYMBOLS[0]].index[-1].timestamp()*1000)
    _,orders=plan(exchange,ticker,balance,weights,frames,float(c['max_order_usd']),limits(c),halted)
    phase='RISK_EXIT' if halted else ('READY' if started else 'WAITING_START')
    eligible=started and (halted or (bar//900000%int(c['rebalance_bars'])==0 and state.get('last_bar')!=bar))
    state.update(last_nav=nav,last_phase=phase,last_checked_utc=pd.Timestamp.now(tz='UTC').isoformat())
    atomic(Path(directory)/'state.json',state)
    summary={'mode':'COMPETITION_EXECUTE' if execute else 'COMPETITION_DRY_RUN','phase':phase,'nav':round(nav,2),'drawdown':round(drawdown,6),'orders':orders,'eligible_now':eligible,'start_utc':c['start_utc'],'confirmed_fills':state.get('confirmed_fills',0),'active_days':len(state.get('active_days',[]))}
    audit(directory,'cycle',**summary,weights=weights);print(json.dumps(summary),flush=True)
    if not execute or not eligible:return
    if not halted:
        state['last_bar']=bar;atomic(Path(directory)/'state.json',state)
    for order in orders:
        pending_check(client);short_check(client)
        fresh=quote(client);current=client.request('/v3/balance',{'timestamp':client.timestamp()},True)
        # Re-check risk immediately before every submit; drawdown may have changed
        # after a fill or during a long API response.
        latest_nav=valuation(current,fresh)
        state['high_water']=max(latest_nav,state['high_water'])
        if latest_nav/state['high_water']-1<=-float(c['drawdown_stop']):state['halted']=True
        risk_exit=bool(state.get('halted'));new_weights={s:0 for s in SYMBOLS} if risk_exit else weights
        _,new_orders=plan(exchange,fresh,current,new_weights,frames,float(c['max_order_usd']),limits(c),risk_exit)
        same=[o for o in new_orders if o['pair']==order['pair'] and o['side']==('SELL' if risk_exit else order['side'])]
        atomic(Path(directory)/'state.json',state)
        if same:execute_guarded(client,state,directory,same[0],c,execute)
    # Pull confirmed wallet after the complete batch, do not infer holdings from
    # order quantities (coin-vs-USD fees may differ).
    after=client.request('/v3/balance',{'timestamp':client.timestamp()},True)
    after_nav=valuation(after,quote(client));state['last_nav']=after_nav
    atomic(Path(directory)/'state.json',state);audit(directory,'post_batch_nav',nav=after_nav)


def require_test_verification():
    directory=Path('runtime/test')
    proof=json.loads((directory/'verification.json').read_text()) if (directory/'verification.json').exists() else {}
    profile=json.loads((directory/'credentials.json').read_text())
    account=hashlib.sha256(profile['api_key'].encode()).hexdigest()
    required={'confirmed_fill','separate_process_query','balance_schema','no_pending','no_short','no_unresolved_intent'}
    if profile.get('account_mode')!='TEST' or proof.get('test_account_hash')!=account or not required.issubset(set(proof.get('checks',[]))) or int(proof.get('confirmed_unique_fills',0))<1:
        raise Blocked('Test verification not passed; run python -m quant.verify_test first')
    verified=pd.Timestamp(proof['verified_utc'])
    age=pd.Timestamp.now(tz='UTC')-verified
    if age<pd.Timedelta(0) or age>pd.Timedelta('24h'):raise Blocked('Test verification expired (>24h)')
    state=json.loads((directory/'state.json').read_text())
    if state.get('intent') or state.get('halted'):raise Blocked('Test state unsafe after verification')
    return proof


def arm_execution(state):
    # Persist initial verification so a later server reboot can resume safely
    # using the same bound account/config without expiring its original proof.
    if not state.get('armed_verification'):
        proof=require_test_verification()
        state['armed_verification']={k:proof[k] for k in ('test_account_hash','verified_utc','confirmed_order_id')}


def reconcile_config(state,directory,c):
    current=hashlib.sha256(json.dumps(c,sort_keys=True).encode()).hexdigest()
    if state.get('config_hash')==current:return
    previous=dict(c,start_utc='2026-10-04T00:00:00Z')
    old_hash=hashlib.sha256(json.dumps(previous,sort_keys=True).encode()).hexdigest()
    if c['start_utc']!='2026-10-04T12:00:00Z' or state.get('config_hash')!=old_hash:
        raise Blocked('Config changed; retain state and review migration before changing risk')
    # Only the corrected start time may migrate automatically. Keep every
    # order intent, risk flag, account binding and fill record intact.
    backup=Path(directory)/'state.before_start_correction.json'
    if not backup.exists():atomic(backup,state)
    audit(directory,'start_time_corrected',old_start_utc=previous['start_utc'],new_start_utc=c['start_utc'])
    state['config_hash']=current


def main():
    p=argparse.ArgumentParser(description='Competition long/cash runner; read-only unless --execute')
    p.add_argument('--profile',default='runtime/competition/credentials.json');p.add_argument('--state-dir',default='runtime/competition');p.add_argument('--config',default='competition.json');p.add_argument('--execute',action='store_true');p.add_argument('--once',action='store_true')
    a=p.parse_args();c=config_load(a.config);profile_path=Path(a.profile)
    if profile_path.stat().st_mode&0o077:raise SystemExit('Credential file must be 0600')
    profile=json.loads(profile_path.read_text())
    if profile.get('account_mode')!='COMPETITION':raise SystemExit('Requires dedicated COMPETITION profile')
    for field,env in [('api_key','ROOSTOO_API_KEY'),('secret','ROOSTOO_SECRET_KEY')]:
        if not profile.get(field):raise SystemExit('Missing competition credential')
        os.environ[env]=profile[field]
    os.environ['ROOSTOO_ACCOUNT_MODE']='COMPETITION';os.umask(0o077)
    account=hashlib.sha256(profile['api_key'].encode()).hexdigest()
    test_profile=Path('runtime/test/credentials.json')
    if test_profile.exists() and json.loads(test_profile.read_text()).get('api_key')==profile['api_key']:raise SystemExit('Test and competition keys must differ')
    directory=Path(a.state_dir);directory.mkdir(parents=True,exist_ok=True)
    locks=Path.home()/'.roostoo-locks';locks.mkdir(mode=0o700,exist_ok=True)
    with open(locks/(account+'.lock'),'w') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise SystemExit('Another runner uses this account')
        bound=locks/(account+'.json')
        if bound.exists() and json.loads(bound.read_text())['state_dir']!=str(directory.resolve()):raise SystemExit('Retain the original account recovery directory')
        atomic(bound,{'state_dir':str(directory.resolve())})
        state_path=directory/'state.json';config_hash=hashlib.sha256(json.dumps(c,sort_keys=True).encode()).hexdigest()
        state=json.loads(state_path.read_text()) if state_path.exists() else {'account_hash':account,'intent':None,'mode':'COMPETITION','config_hash':config_hash}
        if state.get('account_hash')!=account or state.get('mode')!='COMPETITION':raise SystemExit('State/account mode mismatch')
        reconcile_config(state,directory,c)
        if a.execute:arm_execution(state)
        atomic(state_path,state);client=Roostoo();transient=0
        while True:
            # File kill switch is persistent and checked every cycle. It blocks
            # new entry and initiates sell-only exits after the start gate.
            if (directory/'STOP').exists():state['halted']=True;atomic(state_path,state)
            try:
                cycle(client,state,directory,c,a.execute);transient=0
            except (TimeoutError,URLError) as error:
                audit(directory,'transport_failure',error_type=type(error).__name__,unresolved=bool(state.get('intent')))
                if state.get('intent'):raise SystemExit('Submit outcome unresolved; stopped without retry')
                # Read failure only: bounded retry, no mutation in progress.
                transient+=1;print('Read transport failure; retry next poll',flush=True)
                if a.once or transient>=3:raise SystemExit('Repeated transport failures; stopped')
            except Exception as error:
                audit(directory,'stopped',error_type=type(error).__name__,unresolved=bool(state.get('intent')))
                reason=str(error) if isinstance(error,(Blocked,RuntimeError)) else type(error).__name__
                raise SystemExit('Stopped safely: '+reason)
            if a.once:return
            try:time.sleep(int(c['poll_seconds']))
            except KeyboardInterrupt:return

if __name__=='__main__':main()
