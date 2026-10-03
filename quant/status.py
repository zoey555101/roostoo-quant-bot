"""Local status summary. Does not display credentials or submit orders."""
import argparse,json
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--competition',action='store_true');a=p.parse_args()
    directory=Path('runtime/competition' if a.competition else 'runtime/test')
    path=directory/'state.json'
    if not path.exists():raise SystemExit('No state yet')
    state=json.loads(path.read_text());last=[]
    events=directory/'events.jsonl'
    if events.exists():
        for line in events.read_text().splitlines()[-1000:]:
            try:event=json.loads(line)
            except json.JSONDecodeError:continue
            if event['event'] in ['order_reconciled','stopped','cycle','post_batch_nav','transport_failure']:last.append(event)
    unique_filled={x['order_id'] for x in last if x['event']=='order_reconciled' and x.get('status')=='FILLED'}
    print(json.dumps({'mode':state.get('mode','TEST'),'halted':state.get('halted',False),'unresolved_intent':bool(state.get('intent')),'confirmed_fills_state':state.get('confirmed_fills',0),'confirmed_fills_recent_log':len(unique_filled),'active_days':state.get('active_days',[]),'last_nav':state.get('last_nav'),'last_phase':state.get('last_phase'),'last_fill':state.get('last_fill'),'last_events':last[-5:]},indent=2))

if __name__=='__main__':main()
