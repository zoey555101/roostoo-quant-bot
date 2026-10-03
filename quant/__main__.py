import argparse
from dataclasses import asdict,replace
import itertools,json
from pathlib import Path
import numpy as np
import pandas as pd
from .data import download,load
from .strategy import Config,targets
from .backtest import run
from .roostoo import Roostoo


def save(out,ledger,trades,stats):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    ledger.to_csv(out/'equity.csv');trades.to_csv(out/'trades.csv',index=False)
    (out/'metrics.json').write_text(json.dumps(stats,indent=2,allow_nan=False)+'\n')


def validate(frames,c,out):
    index=next(iter(frames.values())).index
    warm=max(c.slow,c.volatility_bars,int(pd.Timedelta(hours=48)/pd.Timedelta(c.interval)))+2
    available=index[warm:]
    if len(available)<800: raise ValueError('Need 800 evaluation bars after warmup')
    edges=np.linspace(0,len(available),5,dtype=int);results=[]
    candidates=[replace(c,lookback_hours=h,rebalance_bars=r,top_n=n) for h,r,n in itertools.product([12,24,48],[4,16],[2,3])]
    for fold in range(3):
        cutoff=available[edges[fold+1]]; scores=[]
        for candidate in candidates:
            _,_,m=run(frames,candidate,available[0],cutoff)
            scores.append((m['return']-2*abs(m['max_drawdown']),candidate))
        score,best=max(scores,key=lambda x:x[0])
        stop=available[edges[fold+2]] if edges[fold+2]<len(available) else index[-1]+pd.Timedelta(c.interval)
        ledger,trades,m=run(frames,best,cutoff,stop);save(Path(out)/f'fold_{fold+1}',ledger,trades,m)
        results.append({'fold':fold+1,'test_start':str(cutoff),'test_end_exclusive':str(stop),'selection_score':score,'config':asdict(best),'test_metrics':m})
    Path(out,'walk_forward.json').write_text(json.dumps({'method':'Expanding selection; 12 candidates; independent fold cash resets, not continuous live NAV','folds':results},indent=2,allow_nan=False))
    print(json.dumps([{'fold':x['fold'],'return':x['test_metrics']['return'],'mdd':x['test_metrics']['max_drawdown']} for x in results],indent=2))


def demo(out):
    path=Path(out)/'synthetic_data';path.mkdir(parents=True,exist_ok=True)
    rng=np.random.default_rng(23);index=pd.date_range('2025-01-01',periods=1800,freq='15min',tz='UTC')
    for s,base in [('BTCUSDT',90000),('ETHUSDT',3000),('SOLUSDT',150)]:
        close=base*np.exp(np.cumsum(rng.normal(.00003,.003,len(index))));op=np.r_[base,close[:-1]]
        pd.DataFrame({'timestamp':index,'open':op,'high':np.maximum(op,close)*1.001,'low':np.minimum(op,close)*.999,'close':close,'volume':100}).to_csv(path/f'{s}.csv',index=False)
    frames=load(path,'15min');c=Config();ledger,trades,m=run(frames,c)
    m['data_kind']='SYNTHETIC: plumbing test, no alpha evidence';save(Path(out)/'backtest',ledger,trades,m)
    validate(frames,c,Path(out)/'walk_forward')


def main():
    parser=argparse.ArgumentParser(description='Research MVP, no live order submission');sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('download');p.add_argument('--symbols',nargs='+',default=['BTCUSDT','ETHUSDT','SOLUSDT']);p.add_argument('--start',required=True);p.add_argument('--end',required=True);p.add_argument('--interval',default='15m');p.add_argument('--out',default='data/binance')
    for command in ['backtest','validate','signal']:
        p=sub.add_parser(command);p.add_argument('--data',required=True);p.add_argument('--config',default='config.json');p.add_argument('--out',default=f'reports/{command}')
    p=sub.add_parser('demo');p.add_argument('--out',default='reports/demo')
    p=sub.add_parser('snapshot');p.add_argument('--private',action='store_true');p.add_argument('--out',default='logs/snapshot.json')
    a=parser.parse_args()
    if a.command=='download': download(a.symbols,a.start,a.end,a.interval,a.out)
    elif a.command=='demo': demo(a.out)
    elif a.command=='snapshot':
        result=Roostoo().snapshot(a.private);out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,indent=2));out.chmod(0o600);print('Read-only snapshot saved')
    else:
        c=Config(**json.loads(Path(a.config).read_text()));frames=load(a.data,c.interval)
        if a.command=='backtest':
            ledger,trades,m=run(frames,c);save(a.out,ledger,trades,m);print(json.dumps(m,indent=2,allow_nan=False))
        elif a.command=='validate': validate(frames,c,a.out)
        else:
            last=next(iter(frames.values())).index[-1]
            if pd.Timestamp.now(tz='UTC')-(last+pd.Timedelta(c.interval))>pd.Timedelta(c.interval)*2: raise ValueError('Stale signal data')
            out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
            (out/'target.json').write_text(json.dumps({'signal_close_time':str(last+pd.Timedelta(c.interval)),'mode':'RESEARCH_ONLY','weights':targets(frames,c).iloc[-1].to_dict()},indent=2))

if __name__=='__main__': main()
