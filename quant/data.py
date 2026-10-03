"""Verified Binance daily spot archives; canonical bar-open UTC timestamps."""
import hashlib
import io
import re
import zipfile
from pathlib import Path
from urllib.request import urlopen
import numpy as np
import pandas as pd


def fetch(url):
    with urlopen(url, timeout=30) as response:
        return response.read()


def download(symbols, start, end, interval, destination):
    if interval not in ('5m', '15m', '30m', '1h', '4h'):
        raise ValueError('Unsupported interval')
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    days = pd.date_range(start, end, freq='D', tz='UTC')
    if len(days) == 0 or days[-1].date() >= pd.Timestamp.now(tz='UTC').date():
        raise ValueError('Use a nonempty range of completed UTC days')
    monthly = days[0].day == 1 and days[-1].is_month_end
    periods = pd.date_range(days[0], days[-1], freq='MS') if monthly else days
    frequency = 'monthly' if monthly else 'daily'
    for symbol in symbols:
        if not re.fullmatch('[A-Z0-9]+USDT', symbol):
            raise ValueError('Expected Binance spot USDT symbol')
        frames = []
        for day in periods:
            date_token = day.strftime('%Y-%m' if monthly else '%Y-%m-%d')
            name = f'{symbol}-{interval}-{date_token}.zip'
            url = f'https://data.binance.vision/data/spot/{frequency}/klines/{symbol}/{interval}/{name}'
            checksum = fetch(url + '.CHECKSUM').decode().split()[0]
            cache = destination / name
            blob = cache.read_bytes() if cache.exists() else fetch(url)
            if hashlib.sha256(blob).hexdigest() != checksum:
                raise ValueError(f'Checksum mismatch: {name}')
            cache.write_bytes(blob)
            with zipfile.ZipFile(io.BytesIO(blob)) as archive:
                raw = pd.read_csv(archive.open(name[:-4] + '.csv'), header=None)
            times = pd.to_numeric(raw.iloc[:, 0], errors='raise')
            unit = 'us' if times.median() > 1e14 else 'ms'
            frame = pd.DataFrame({'timestamp': pd.to_datetime(times, unit=unit, utc=True)})
            for col, pos in [('open',1), ('high',2), ('low',3), ('close',4), ('volume',5)]:
                frame[col] = pd.to_numeric(raw.iloc[:,pos], errors='raise')
            frames.append(frame)
        pd.concat(frames).to_csv(destination / f'{symbol}.csv', index=False)
        print(f'{symbol}: {len(periods)} verified {frequency} archives', flush=True)


def load(directory, interval):
    frames = {}
    step = pd.Timedelta(interval)
    for file in sorted(Path(directory).glob('*USDT.csv')):
        frame = pd.read_csv(file)
        frame['timestamp'] = pd.to_datetime(frame['timestamp'], utc=True)
        frame = frame.set_index('timestamp').sort_index()
        if frame.index.has_duplicates or frame.empty:
            raise ValueError(f'Duplicate/empty bars: {file}')
        if not (frame.index.to_series().diff().dropna() == step).all():
            raise ValueError(f'Missing or irregular bars: {file}; no forward filling')
        values = frame[['open','high','low','close','volume']]
        if not np.isfinite(values).all().all() or (values[['open','high','low','close']] <= 0).any().any():
            raise ValueError(f'Invalid OHLC: {file}')
        if ((frame.high < frame[['open','close','low']].max(axis=1)) | (frame.low > frame[['open','close','high']].min(axis=1)) | (frame.volume < 0)).any():
            raise ValueError(f'Inconsistent OHLCV: {file}')
        if frame.index[-1] + step > pd.Timestamp.now(tz='UTC'):
            raise ValueError('Incomplete/future bar')
        frames[file.stem] = frame
    if not frames:
        raise ValueError('No SYMBOLUSDT.csv files')
    first = next(iter(frames.values())).index
    if not all(f.index.equals(first) for f in frames.values()):
        raise ValueError('All assets must share exactly the same bar timestamps')
    return frames
