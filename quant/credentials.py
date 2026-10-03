"""Interactive local-only test credential setup, never puts secrets in argv."""
import argparse
import getpass
from pathlib import Path
from .live import atomic

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--competition',action='store_true');args=parser.parse_args()
    mode='COMPETITION' if args.competition else 'TEST'
    print('Use Actual Competition credentials.' if args.competition else 'Use For Testing credentials only.')
    print('Input is hidden; configuration does not submit orders.')
    key=getpass.getpass(mode+' API key: ').strip()
    secret=getpass.getpass(mode+' secret: ').strip()
    if not key or not secret:raise SystemExit('Empty credentials; not saved')
    if input('Confirm credential mode: type '+mode+': ').strip()!=mode:raise SystemExit('Not saved')
    path=Path('runtime/competition/credentials.json' if args.competition else 'runtime/test/credentials.json')
    atomic(path,{'account_mode':mode,'api_key':key,'secret':secret})
    print(mode+' credentials saved locally with mode 0600. Do not share this file.')

if __name__=='__main__':main()
