"""Read-only Roostoo client: no trade mutation endpoint exposed in MVP."""
import hashlib
import hmac
import json
import os
import time
from urllib.request import Request, urlopen


def canonical(params):
    for k,v in params.items():
        if any(c in str(k)+str(v) for c in '&=\r\n'):
            raise ValueError('Unsupported parameter character')
    return '&'.join(f'{k}={params[k]}' for k in sorted(params))


def signature(params, secret):
    return hmac.new(secret.encode(),canonical(params).encode(),hashlib.sha256).hexdigest()


class Roostoo:
    def __init__(self):
        self.base = 'https://mock-api.roostoo.com'
        self.offset = 0

    def request(self, path, params=None, signed=False, method='GET', allow_empty=False):
        params = dict(params or {})
        headers = {'Content-Type':'application/x-www-form-urlencoded'}
        if signed:
            key = os.environ.get('ROOSTOO_API_KEY','')
            secret = os.environ.get('ROOSTOO_SECRET_KEY','')
            if not key or not secret:
                raise RuntimeError('Set ROOSTOO_API_KEY and ROOSTOO_SECRET_KEY locally')
            headers.update({'RST-API-KEY':key,'MSG-SIGNATURE':signature(params,secret)})
        body = canonical(params).encode()
        url = self.base+path
        if method == 'GET' and body:
            url += '?' + body.decode()
        request = Request(url, data=body if method == 'POST' else None, headers=headers,method=method)
        with urlopen(request,timeout=15) as response:
            result = json.load(response)
        if result.get('Success') is False:
            message = str(result.get('ErrMsg') or 'No ErrMsg supplied')
            normalized = ' '.join(message.split()).casefold().rstrip('.')
            empty = path == '/v3/query_order' and normalized == 'no order matched'
            if not (allow_empty and empty):
                # Expose only the error message, redacting any echoed credentials
                # or signature. Escape control characters and limit output size.
                sensitive = [os.environ.get('ROOSTOO_API_KEY', ''),
                             os.environ.get('ROOSTOO_SECRET_KEY', ''),
                             headers.get('MSG-SIGNATURE', '')]
                for value in sorted(filter(None, sensitive), key=len, reverse=True):
                    message = message.replace(value, '[REDACTED]')
                safe_message = json.dumps(message[:500], ensure_ascii=True)
                raise RuntimeError(f'Roostoo API rejected {path}: ErrMsg={safe_message}')
        return result

    def sync_time(self):
        before = time.time()*1000
        server = self.request('/v3/serverTime')['ServerTime']
        self.offset = server-(before+time.time()*1000)/2

    def timestamp(self):
        return str(int(time.time()*1000+self.offset))

    def snapshot(self, private=False):
        self.sync_time()
        out = {'exchange':self.request('/v3/exchangeInfo'),
               'ticker':self.request('/v3/ticker',{'timestamp':self.timestamp()})}
        if private:
            out['balance'] = self.request('/v3/balance',{'timestamp':self.timestamp()},True)
            # Paginate all history; query_order is POST but is read-only.
            orders = []; offset = 0
            while True:
                params = {'timestamp': self.timestamp(), 'limit': '100'}
                # The live endpoint rejects an explicit zero offset. Let the
                # server select the first page; send offsets only thereafter.
                if offset > 0:
                    params['offset'] = str(offset)
                page = self.request('/v3/query_order',params,True,'POST',True)
                matched = page.get('OrderMatched',[])
                if not isinstance(matched, list):
                    raise RuntimeError('Invalid OrderMatched response')
                previous_ids = {order.get('OrderID') for order in orders}
                if orders and any(order.get('OrderID') in previous_ids for order in matched):
                    raise RuntimeError('Order history pages overlap; pagination needs verification')
                orders.extend(matched)
                if len(matched) < 100:
                    break
                offset += len(matched)
                if offset >= 10000:
                    raise RuntimeError('History exceeds snapshot safety bound')
            out['orders'] = orders
        return out
