"""Unit/cash ledger. Bar t-1 close signal fills at bar t open with costs."""
from dataclasses import asdict
import numpy as np
import pandas as pd
from .strategy import targets


def metrics(nav, initial_cash, interval):
    # Daily research ratios; not a claim about the organizer's undisclosed formula.
    nav = pd.Series(nav)
    start = nav.index[0] - pd.Timedelta(interval)
    series = pd.concat([pd.Series([initial_cash],index=[start]),nav])
    daily = series.resample('1D').last().dropna()
    returns = daily.pct_change().dropna()
    mean = returns.mean() if len(returns) else 0
    std = returns.std(ddof=1) if len(returns) > 1 else 0
    downside = np.sqrt(np.mean(np.minimum(returns.to_numpy(),0)**2)) if len(returns) else 0
    mdd = float((series/series.cummax()-1).min())
    total = float(nav.iloc[-1]/initial_cash-1)
    years = (nav.index[-1]-start).total_seconds()/(365*86400)
    cagr = float((1+total)**(1/years)-1) if years and total > -1 else None
    def ratio(a,b):
        return float(a/b) if b > 1e-12 and np.isfinite(a/b) else None
    sharpe = ratio(mean*np.sqrt(365),std)
    sortino = ratio(mean*np.sqrt(365),downside)
    calmar = ratio(cagr,-mdd) if cagr is not None else None
    return {'return':total,'max_drawdown':mdd,'annualized_return':cagr,
            'sharpe_daily':sharpe,'sortino_daily':sortino,'calmar_annualized':calmar,
            'calmar_period':ratio(total,-mdd),'daily_observations':len(returns),
            'research_composite':0.3*sharpe+0.4*sortino+0.3*calmar if all(x is not None for x in [sharpe,sortino,calmar]) else None}


def run(frames, config, start=None, end=None):
    signals = targets(frames, config).shift(1).fillna(0)
    symbols = list(signals.columns)
    index = signals.index
    if start is not None:
        index = index[index >= pd.Timestamp(start)]
    if end is not None:
        index = index[index < pd.Timestamp(end)]
    if len(index) < 2:
        raise ValueError('Insufficient evaluation bars')
    units = np.zeros(len(symbols)); cash = config.initial_cash
    high_water = cash; halted = False; rows = []; trades = []
    slip = config.slippage_bps/10000; fee = config.fee_bps/10000
    if slip >= 1 or fee >= 1:
        raise ValueError('Invalid costs')
    for k,t in enumerate(index):
        op = np.array([frames[s].at[t,'open'] for s in symbols])
        cl = np.array([frames[s].at[t,'close'] for s in symbols])
        nav_open = cash + units @ op
        high_water = max(high_water,nav_open)
        if nav_open / high_water - 1 <= -config.drawdown_stop:
            halted = True
        turnover = 0.0
        if halted or k % config.rebalance_bars == 0:
            w = np.zeros(len(symbols)) if halted else signals.loc[t].to_numpy()
            desired = w * nav_open / op
            delta = desired-units
            # Execute sells before buys; fixed units drift between rebalances.
            for j in sorted(range(len(symbols)), key=lambda j: delta[j]):
                q = float(delta[j])
                if abs(q*op[j])/nav_open < config.min_trade_weight and not halted:
                    continue
                if abs(q) < 1e-12:
                    continue
                price = op[j]*(1+slip if q > 0 else 1-slip)
                if q > 0:
                    q = min(q, max(0,cash)/(price*(1+fee)))
                else:
                    q = max(q,-units[j])
                if abs(q) < 1e-12:
                    continue
                charge = abs(q)*price*fee
                cash -= q*price+charge; units[j] += q
                turnover += abs(q*op[j])/nav_open
                trades.append({'timestamp':t,'symbol':symbols[j],'quantity_delta':q,'price':price,'fee':charge,'reason':'drawdown_exit' if halted else 'rebalance'})
        nav = cash+units@cl
        if cash < -1e-6 or (units < -1e-9).any():
            raise AssertionError('Ledger violated cash/spot constraints')
        high_water = max(high_water,nav)
        # A close breach is liquidated next open, including gap risk.
        halted = halted or nav/high_water-1 <= -config.drawdown_stop
        rows.append({'timestamp':t+pd.Timedelta(config.interval),'nav':nav,'cash':cash,'gross_exposure':units@cl/nav,'turnover':turnover,'halted':halted})
    ledger = pd.DataFrame(rows).set_index('timestamp')
    stats = metrics(ledger.nav,config.initial_cash,config.interval)
    stats.update({'trades':len(trades),'total_fees':sum(x['fee'] for x in trades),
                  'active_trading_days':len(set(pd.Timestamp(x['timestamp']).date() for x in trades)),
                  'halted':bool(halted),'config':asdict(config)})
    return ledger,pd.DataFrame(trades,columns=['timestamp','symbol','quantity_delta','price','fee','reason']),stats
