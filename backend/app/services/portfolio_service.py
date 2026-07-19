"""Portfolio aggregation for multiple independent Quality Grid backtests."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from app.backtest.quality_grid import run_quality_grid
from app.core.config import RISK_FREE_RATE, TRADING_DAYS_PER_YEAR
from app.data.provider import get_history, instrument_name
from app.domain.models import BacktestRequest, PortfolioBacktestRequest, StrategyType
from app.services.backtest_service import _adapt_quality_request
from app.services.benchmark_service import BENCHMARK_SPECS, get_benchmark_history


def _single_request(request: PortfolioBacktestRequest, symbol: str, allocation: float) -> BacktestRequest:
    total_multiplier = 1 + sum(request.grid_cash_multipliers)
    return BacktestRequest(
        symbol=symbol,
        strategy=StrategyType.QUALITY_GRID,
        start_date=request.start_date,
        end_date=request.end_date,
        initial_cash=allocation,
        max_strategy_cash=allocation,
        base_cash=allocation / total_multiplier,
        quality_confirmed=request.quality_confirmed,
        lookback_days=request.lookback_days,
        ma_window=request.ma_window,
        entry_drawdown_pct=request.entry_drawdown_pct,
        ma_discount_pct=request.ma_discount_pct,
        entry_condition_mode=request.entry_condition_mode,
        grid_drop_pcts=request.grid_drop_pcts,
        grid_cash_multipliers=request.grid_cash_multipliers,
        lot_take_profit_pct=request.lot_take_profit_pct,
        holding_profit_decay_days=request.holding_profit_decay_days,
        holding_profit_decay_pct=request.holding_profit_decay_pct,
        basket_take_profit_enabled=request.basket_take_profit_enabled,
        basket_take_profit_pct=request.basket_take_profit_pct,
        reentry_drop_pct=request.reentry_drop_pct,
        commission_rate=request.commission_rate,
        min_commission=request.min_commission,
        sell_tax_rate=request.sell_tax_rate,
        slippage_pct=request.slippage_pct,
        enforce_a_share_board_lot=request.enforce_board_lot,
        allow_fractional_etf=request.allow_fractional_etf,
        force_close_at_end=request.force_close_at_end,
    )


def _benchmark_result(request: PortfolioBacktestRequest) -> dict | None:
    if request.benchmark == "none":
        return None
    frame = get_benchmark_history(request.benchmark, request.start_date, request.end_date).copy()
    metadata = dict(frame.attrs.get("metadata", {}))
    frame = frame.sort_values("date").dropna(subset=["close"]).reset_index(drop=True)
    first_close = float(frame.iloc[0]["close"])
    if first_close <= 0:
        raise ValueError(f"{BENCHMARK_SPECS[request.benchmark]['name']}首个收盘点位无效。")
    frame["normalized_equity"] = request.total_cash * frame["close"] / first_close
    frame["drawdown"] = frame["normalized_equity"] / frame["normalized_equity"].cummax() - 1
    years = max((len(frame) - 1) / TRADING_DAYS_PER_YEAR, 1 / TRADING_DAYS_PER_YEAR)
    ending_equity = float(frame.iloc[-1]["normalized_equity"])
    total_return = ending_equity / request.total_cash - 1
    annualized_return = (ending_equity / request.total_cash) ** (1 / years) - 1 if ending_equity > 0 else -1.0
    trough = frame["drawdown"].idxmin()
    peak = frame.loc[:trough, "normalized_equity"].idxmax()
    spec = BENCHMARK_SPECS[request.benchmark]
    return {
        "key": request.benchmark,
        "name": spec["name"],
        "symbol": spec["symbol"],
        "source": metadata.get("source"),
        "start_date": str(frame.iloc[0]["date"]),
        "end_date": str(frame.iloc[-1]["date"]),
        "starting_close": first_close,
        "ending_close": float(frame.iloc[-1]["close"]),
        "ending_equity": ending_equity,
        "total_return": float(total_return),
        "annualized_return": float(annualized_return),
        "max_drawdown": float(frame.loc[trough, "drawdown"]),
        "max_drawdown_start": str(frame.loc[peak, "date"]),
        "max_drawdown_end": str(frame.loc[trough, "date"]),
        "daily": [
            {
                "date": str(row.date), "close": float(row.close),
                "normalized_equity": float(row.normalized_equity), "drawdown": float(row.drawdown),
            }
            for row in frame.itertuples(index=False)
        ],
    }

def run_portfolio_backtest(request: PortfolioBacktestRequest) -> dict:
    allocation = request.total_cash / len(request.symbols)
    runs: list[dict] = []
    warnings: list[str] = []
    all_lots: list[dict] = []
    all_trades: list[dict] = []

    for symbol in request.symbols:
        data = get_history(symbol, request.start_date, request.end_date)
        metadata = dict(data.attrs.get("metadata", {}))
        single_request, adjustment_warning = _adapt_quality_request(
            _single_request(request, symbol, allocation), data, metadata,
        )
        metrics, trades, lots, curve, run_warnings = run_quality_grid(
            data, single_request, metadata.get("instrument_type", "unknown"),
        )
        if adjustment_warning:
            run_warnings.insert(0, adjustment_warning)
        if metadata.get("warning"):
            run_warnings.insert(0, metadata["warning"])
        warnings.extend(f"{symbol}：{warning}" for warning in run_warnings)
        lot_records = [{"symbol": symbol, **lot.model_dump(mode="json")} for lot in lots]
        trade_records = [{"symbol": symbol, **trade.model_dump(mode="json")} for trade in trades]
        all_lots.extend(lot_records)
        all_trades.extend(trade_records)
        runs.append({
            "symbol": symbol,
            "name": instrument_name(symbol),
            "allocation": allocation,
            "metrics": metrics,
            "curve": curve,
            "lot_count": len(lot_records),
            "trade_count": len(trade_records),
            "data_info": metadata,
        })

    if not all_lots:
        raise ValueError("组合内没有标的触发网格首仓；请放宽入场条件或调整回测区间。")

    calendar = sorted(set().union(*(set(run["curve"]["date"]) for run in runs)))
    aggregate = pd.DataFrame(index=calendar, data={
        "cash": 0.0, "market_value": 0.0, "holding_market_value": 0.0, "invested_cost": 0.0, "equity": 0.0,
    })
    for run in runs:
        frame = run["curve"].set_index("date")[["cash", "market_value", "holding_market_value", "invested_cost", "equity"]]
        aligned = frame.reindex(calendar).ffill()
        before_start = aligned.index < frame.index.min()
        aligned.loc[before_start, "cash"] = run["allocation"]
        aligned.loc[before_start, "equity"] = run["allocation"]
        aligned.loc[before_start, ["market_value", "holding_market_value", "invested_cost"]] = 0.0
        aggregate += aligned.fillna(0.0)

    aggregate.insert(0, "date", [str(day) for day in calendar])
    aggregate["drawdown"] = aggregate["equity"] / aggregate["equity"].cummax() - 1
    aggregate["holding_ratio"] = np.where(
        aggregate["equity"] > 0, aggregate["market_value"] / aggregate["equity"], 0.0,
    )
    active_market_value = aggregate["holding_market_value"].where(aggregate["holding_market_value"] > 1e-9)
    aggregate["holding_drawdown"] = active_market_value / active_market_value.cummax() - 1

    daily_returns = aggregate["equity"].pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    years = max((len(calendar) - 1) / TRADING_DAYS_PER_YEAR, 1 / TRADING_DAYS_PER_YEAR)
    ending_equity = float(aggregate.iloc[-1]["equity"])
    annualized_return = (ending_equity / request.total_cash) ** (1 / years) - 1 if ending_equity > 0 else -1.0
    volatility = float(daily_returns.std(ddof=1) * math.sqrt(TRADING_DAYS_PER_YEAR)) if len(daily_returns) > 1 else 0.0
    sharpe = (float(daily_returns.mean()) * TRADING_DAYS_PER_YEAR - RISK_FREE_RATE) / volatility if volatility > 0 else None
    trough = aggregate["drawdown"].idxmin()
    peak = aggregate.loc[:trough, "equity"].idxmax()
    holding_trough = aggregate["holding_drawdown"].idxmin()
    holding_peak = aggregate.loc[:holding_trough, "holding_market_value"].idxmax()
    closed_lots = [lot for lot in all_lots if lot["status"] == "CLOSED"]
    benchmark = _benchmark_result(request)

    symbol_results = []
    for run in runs:
        metrics = run["metrics"]
        symbol_results.append({
            "symbol": run["symbol"],
            "name": run["name"],
            "allocation": run["allocation"],
            "ending_equity": metrics["ending_equity"],
            "total_return": metrics["total_return"],
            "annualized_return": metrics["annualized_return"],
            "win_rate": metrics["win_rate_all_lots"],
            "max_drawdown": metrics["max_drawdown"],
            "max_capital_used": metrics["max_strategy_cash_used"],
            "lot_count": run["lot_count"],
            "trade_count": run["trade_count"],
        })

    return {
        "metrics": {
            "requested_symbols": len(request.symbols),
            "invested_symbols": sum(run["lot_count"] > 0 for run in runs),
            "initial_cash": request.total_cash,
            "ending_equity": ending_equity,
            "total_profit": ending_equity - request.total_cash,
            "total_return": ending_equity / request.total_cash - 1,
            "annualized_return": annualized_return,
            "win_rate": sum(lot["realized_pnl"] > 0 for lot in closed_lots) / len(closed_lots) if closed_lots else None,
            "max_capital_used": float(aggregate["invested_cost"].max()),
            "max_drawdown": float(aggregate.loc[trough, "drawdown"]),
            "max_drawdown_start": aggregate.loc[peak, "date"],
            "max_drawdown_end": aggregate.loc[trough, "date"],
            "max_holding_drawdown": float(aggregate.loc[holding_trough, "holding_drawdown"]),
            "max_holding_drawdown_start": aggregate.loc[holding_peak, "date"],
            "max_holding_drawdown_end": aggregate.loc[holding_trough, "date"],
            "average_holding_ratio": float(aggregate["holding_ratio"].mean()),
            "max_holding_ratio": float(aggregate["holding_ratio"].max()),
            "annual_volatility": volatility,
            "sharpe_ratio": None if sharpe is None else float(sharpe),
            "lot_count": len(all_lots),
            "benchmark_annualized_excess": (
                annualized_return - benchmark["annualized_return"] if benchmark else None
            ),
        },
        "symbol_results": symbol_results,
        "benchmark": benchmark,
        "lots": all_lots,
        "trades": all_trades,
        "daily_equity": aggregate.astype(object).where(pd.notna(aggregate), None).to_dict(orient="records"),
        "warnings": list(dict.fromkeys(warnings)),
        "execution": "每只标的独立运行同一套质量网格参数；组合层汇总实际并发资金、现金、持仓市值和权益；期末强制平仓。",
    }