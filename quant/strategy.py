from dataclasses import dataclass, asdict
import numpy as np
import pandas as pd

@dataclass(frozen=True)
class Config:
    interval: str = '15min'
    lookback_hours: int = 24
    fast: int = 20
    slow: int = 50
    volatility_bars: int = 96
    top_n: int = 3
    gross_cap: float = 0.70
    coin_cap: float = 0.15
    rebalance_bars: int = 4
    min_trade_weight: float = 0.02
    fee_bps: float = 10
    slippage_bps: float = 5
    drawdown_stop: float = 0.06
    initial_cash: float = 100000

    def __post_init__(self):
        if not 0 < self.coin_cap <= self.gross_cap <= 1 or not 0 < self.drawdown_stop < 1:
            raise ValueError('Invalid risk caps')
        if not 0 <= self.min_trade_weight < 1 or min(self.fee_bps,self.slippage_bps) < 0 or self.initial_cash <= 0:
            raise ValueError('Invalid costs/capital')
        if min(self.fast,self.slow,self.volatility_bars,self.top_n,self.rebalance_bars,self.lookback_hours) < 1 or self.fast >= self.slow:
            raise ValueError('Invalid strategy windows')
        if pd.Timedelta(self.interval) <= pd.Timedelta(0):
            raise ValueError('Invalid bar interval')


def targets(frames, config):
    close = pd.DataFrame({s:f.close for s,f in frames.items()})
    bars = int(pd.Timedelta(hours=config.lookback_hours) / pd.Timedelta(config.interval))
    if bars < 1:
        raise ValueError('Lookback shorter than a bar')
    momentum = close.pct_change(bars, fill_method=None)
    fast = close.ewm(span=config.fast, adjust=False, min_periods=config.slow).mean()
    slow = close.ewm(span=config.slow, adjust=False, min_periods=config.slow).mean()
    vol = close.pct_change(fill_method=None).rolling(config.volatility_bars).std()
    eligible = (momentum > 0) & (fast > slow) & (vol > 1e-8)
    ranked = momentum.where(eligible).rank(axis=1, ascending=False, method='first')
    inv = (1/vol).where(eligible & (ranked <= config.top_n), 0).fillna(0)
    weights = inv.div(inv.sum(axis=1).replace(0,np.nan),axis=0).fillna(0) * config.gross_cap
    # Clipping intentionally leaves excess as cash, rather than increasing other risks.
    return weights.clip(upper=config.coin_cap)
