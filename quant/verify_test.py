"""Separate-process read-only reconciliation proving at least one test fill."""
import fcntl,hashlib,json,os
from pathlib import Path
import pandas as pd
from .live import atomic,spot_wallet,short_check,pending_check,Blocked
from .roostoo import Roostoo


def main():
    directory=Path('runtime/test');profile=json.loads((directory/'credentials.json').read_text())
    if profile.get('account_mode')!='TEST':raise SystemExit('Requires For Testing profile')
    for key,env in [('api_key','ROOSTOO_API_KEY'),('secret','ROOSTOO_SECRET_KEY')]:os.environ[env]=profile[key]
    account=hashlib.sha256(profile['api_key'].encode()).hexdigest()
    lock_dir=Path.home()/'.roostoo-locks';lock_dir.mkdir(mode=0o700,exist_ok=True)
    with open(lock_dir/(account+'.lock'),'w') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise SystemExit('Stop test runner with Ctrl+C before verification')
        state=json.loads((directory/'state.json').read_text())
        if state.get('account_hash')!=account or state.get('intent'):raise SystemExit('Account mismatch or unresolved order; verification refused')
        if state.get('halted'):raise SystemExit('Test account halted; review before verification')
        ids=[]
        path=directory/'events.jsonl'
        if path.exists():
            for line in path.read_text().splitlines():
                e=json.loads(line)
                if e.get('event')=='order_reconciled' and e.get('status')=='FILLED':ids.append(e['order_id'])
        if not ids:raise SystemExit('No confirmed test fill yet. Verification not passed.')
        client=Roostoo();client.sync_time();pending_check(client);short_check(client)
        response=client.request('/v3/query_order',{'timestamp':client.timestamp(),'order_id':str(ids[-1])},True,'POST')
        exact=[o for o in response.get('OrderMatched',[]) if str(o.get('OrderID'))==str(ids[-1]) and o.get('Status')=='FILLED']
        if response.get('Success') is not True or len(exact)!=1:raise SystemExit('Test fill not confirmed by server')
        wallet=spot_wallet(client.request('/v3/balance',{'timestamp':client.timestamp()},True))
        for entry in wallet.values():
            if any(float(entry.get(k,0))>1e-8 for k in ('Lock','PendingOrders','ShortCollateral')):raise SystemExit('Reserved balance still exists')
        proof={'test_account_hash':account,'confirmed_order_id':ids[-1],'confirmed_unique_fills':len(set(ids)),'verified_utc':pd.Timestamp.now(tz='UTC').isoformat(),'checks':['confirmed_fill','separate_process_query','balance_schema','no_pending','no_short','no_unresolved_intent']}
        atomic(directory/'verification.json',proof)
        print(json.dumps({'verification':'PASSED','order_id':ids[-1],'confirmed_fills':len(set(ids))}))

if __name__=='__main__':main()
