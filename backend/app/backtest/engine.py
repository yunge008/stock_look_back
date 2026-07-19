from dataclasses import dataclass
from datetime import date
import math
import numpy as np
import pandas as pd
from app.domain.models import BacktestRequest, StrategyType, Trade
from app.core.config import RISK_FREE_RATE, TRADING_DAYS_PER_YEAR

@dataclass
class Account:
    cash: float
    shares: float = 0.0
    borrowed: float = 0.0
    contributed: float = 0.0

def _is_contribution_day(day: date, target: int, seen: set[tuple[int, int]]) -> bool:
    key = (day.year, day.month)
    if key in seen or day.day < target: return False
    seen.add(key); return True

def _metrics(equity: pd.DataFrame, trades: list[Trade], contributed: float) -> dict:
    values = equity["equity"].astype(float)
    drawdown = values / values.cummax() - 1
    daily = values.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    years = max((len(equity) - 1) / TRADING_DAYS_PER_YEAR, 1 / TRADING_DAYS_PER_YEAR)
    cagr = (values.iloc[-1] / max(contributed, 1e-9)) ** (1 / years) - 1 if values.iloc[-1] > 0 else -1
    vol = daily.std(ddof=1) * math.sqrt(TRADING_DAYS_PER_YEAR) if len(daily) > 1 else 0.0
    sharpe = (cagr - RISK_FREE_RATE) / vol if vol > 0 else None
    trough = int(drawdown.idxmin())
    peak = int(values.iloc[:trough + 1].idxmax())
    return {"total_contributed": contributed, "ending_equity": float(values.iloc[-1]), "total_return": (float(values.iloc[-1]) - contributed) / max(contributed, 1e-9), "annualized_return": cagr, "cagr": cagr, "max_drawdown": float(drawdown.iloc[trough]), "max_drawdown_start": str(equity.loc[peak, "date"]), "max_drawdown_end": str(equity.loc[trough, "date"]), "annual_volatility": float(vol), "sharpe_ratio": sharpe, "buy_count": sum(t.side == "BUY" for t in trades), "sell_count": sum(t.side == "SELL" for t in trades), "capital_utilization": float((equity["market_value"] / equity["equity"].replace(0, np.nan)).mean())}

def run_backtest(data: pd.DataFrame, req: BacktestRequest) -> tuple[dict, list[Trade], pd.DataFrame]:
    data = data.copy().sort_values("date")
    data["ma"] = data["adj_close"].rolling(req.ma_window, min_periods=req.ma_window).mean()
    data["deviation"] = data["adj_close"] / data["ma"] - 1
    data = data[data["date"] >= req.start_date].reset_index(drop=True)
    if data.empty: raise ValueError("回测区间没有交易日。")
    account = Account(cash=req.initial_cash, contributed=req.initial_cash)
    trades: list[Trade] = []; rows = []; monthly_seen: set[tuple[int, int]] = set()
    previous_deviation = None
    for idx, bar in data.iterrows():
        day, price = bar["date"], float(bar["adj_close"])
        ma, deviation = bar["ma"], bar["deviation"]
        reason = None; order_value = 0.0
        contribution_day = _is_contribution_day(day, req.contribution_day, monthly_seen)
        external_cash_flow = 0.0
        if contribution_day:
            account.cash += req.monthly_contribution; account.contributed += req.monthly_contribution; external_cash_flow += req.monthly_contribution
        equity_before = account.cash + account.shares * price - account.borrowed
        if idx == 0 and account.cash > 0:
            order_value, reason = account.cash, "初始建仓"
        elif req.strategy == StrategyType.DCA and contribution_day:
            order_value, reason = min(req.monthly_contribution, account.cash), "月度定投"
        elif pd.notna(deviation):
            if req.strategy == StrategyType.MA_BAND:
                crossed_low = previous_deviation is not None and previous_deviation > req.lower_threshold and deviation <= req.lower_threshold
                crossed_high = previous_deviation is not None and previous_deviation < req.upper_threshold and deviation >= req.upper_threshold
                if crossed_low and req.extra_buy_amount:
                    account.cash += req.extra_buy_amount; account.contributed += req.extra_buy_amount; external_cash_flow += req.extra_buy_amount
                    order_value, reason = req.extra_buy_amount, "低估加仓"
                elif crossed_high:
                    order_value, reason = -account.shares * price * req.sell_ratio, "高估减仓"
                elif contribution_day and req.lower_threshold < deviation < req.upper_threshold:
                    order_value, reason = min(req.monthly_contribution, account.cash), "中性区间定投"
            elif req.strategy == StrategyType.DYNAMIC:
                weight = 1.5 if deviation <= -0.2 else 1.2 if deviation <= -0.1 else 1.0 if deviation < 0.1 else 0.8 if deviation < 0.2 else 0.6
                target_value = equity_before * weight; current_value = account.shares * price
                diff = target_value - current_value
                if abs(diff) >= max(abs(equity_before) * req.rebalance_tolerance, 1):
                    order_value, reason = diff, f"动态调仓至 {weight:.0%}"
        if order_value > 0:
            affordable = order_value
            if account.cash < affordable:
                if req.allow_margin:
                    account.borrowed += affordable - account.cash; account.cash = 0
                else: affordable = account.cash; account.cash = 0
            else: account.cash -= affordable
            if affordable > 0:
                qty = affordable / price; account.shares += qty
                trades.append(Trade(date=day, side="BUY", price=price, quantity=qty, notional=affordable, reason=reason or "买入"))
        elif order_value < 0 and account.shares > 0:
            value = min(-order_value, account.shares * price); qty = value / price
            account.shares -= qty; account.cash += value
            repayment = min(account.cash, account.borrowed); account.cash -= repayment; account.borrowed -= repayment
            trades.append(Trade(date=day, side="SELL", price=price, quantity=qty, notional=value, reason=reason or "卖出"))
        market_value = account.shares * price; equity = account.cash + market_value - account.borrowed
        rows.append({"date": day, "price": price, "ma": None if pd.isna(ma) else float(ma), "cash": account.cash, "borrowed_cash": account.borrowed, "shares": account.shares, "market_value": market_value, "equity": equity, "external_cash_flow": external_cash_flow})
        previous_deviation = None if pd.isna(deviation) else float(deviation)
    if req.force_close_at_end and account.shares > 0:
        final_day = rows[-1]["date"]
        final_price = float(rows[-1]["price"])
        quantity = account.shares
        notional = quantity * final_price
        account.shares = 0.0
        account.cash += notional
        repayment = min(account.cash, account.borrowed)
        account.cash -= repayment
        account.borrowed -= repayment
        trades.append(Trade(
            date=final_day, signal_date=final_day, side="SELL", price=final_price,
            quantity=quantity, notional=notional, reason="回测到期强制平仓",
        ))
        rows[-1].update({
            "cash": account.cash, "borrowed_cash": account.borrowed, "shares": 0.0,
            "market_value": 0.0, "equity": account.cash - account.borrowed,
        })
    curve = pd.DataFrame(rows); curve["drawdown"] = curve["equity"] / curve["equity"].cummax() - 1
    return _metrics(curve, trades, account.contributed), trades, curve
