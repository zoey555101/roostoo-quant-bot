"""Interactive local-only test credential setup, never puts secrets in argv."""
import getpass
from pathlib import Path
from .live import atomic

def main():
    print('Use For Testing credentials only. Input is hidden.')
    key=getpass.getpass('Testing API key: ').strip()
    secret=getpass.getpass('Testing secret: ').strip()
    if not key or not secret:raise SystemExit('Empty credentials; not saved')
    if input('Confirm these are For Testing credentials: type TEST: ').strip()!='TEST':raise SystemExit('Not saved')
    path=Path('runtime/test/credentials.json')
    atomic(path,{'account_mode':'TEST','api_key':key,'secret':secret})
    print('Test credentials saved locally with mode 0600. Do not share this file.')

if __name__=='__main__':main()
