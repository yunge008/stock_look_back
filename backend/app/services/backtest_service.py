import pandas as pd

from app.backtest.engine import run_backtest
from app.backtest.quality_grid import run_quality_grid
from app.charts.figures import build_charts
from app.data.provider import get_history
from app.db.repository import save_run
from app.domain.models import StrategyType


def _records(frame):
    result = []
    for _, row in frame.iterrows():
        item = {}
        for key, value in row.items():
            if isinstance(value, pd.Timestamp):
                value = value.date()
            if key == "date":
                item[key] = str(value)
            elif value is None or (not isinstance(value, str) and pd.isna(value)):
                item[key] = None
            elif hasattr(value, "item"):
                item[key] = value.item()
            else:
                item[key] = value
        result.append(item)
    return result


def _adapt_quality_request(req, data, metadata: dict):
    available_start = data["date"].min()
    available_end = data["date"].max()
    usable = data[data["date"] <= min(req.end_date, available_end)]
    available_bars = len(usable)
    if available_bars == 0:
        raise ValueError("指定区间没有可用交易数据。")
    effective_start = max(req.start_date, available_start)
    effective_end = min(req.end_date, available_end)
    effective_lookback = min(req.lookback_days, available_bars)
    effective_ma = min(req.ma_window, available_bars)
    adjusted = req.model_copy(update={
        "start_date": effective_start,
        "end_date": effective_end,
        "lookback_days": effective_lookback,
        "ma_window": effective_ma,
    })
    changes = []
    if effective_start != req.start_date:
        changes.append(f"开始日期 {req.start_date} → {effective_start}")
    if effective_lookback != req.lookback_days:
        changes.append(f"回撤回看 {req.lookback_days} → {effective_lookback} 个交易日")
    if effective_ma != req.ma_window:
        changes.append(f"MA 周期 {req.ma_window} → {effective_ma} 个交易日")
    metadata.update({
        "requested_start": str(req.start_date), "requested_end": str(req.end_date),
        "effective_start": str(effective_start), "effective_end": str(effective_end),
        "effective_lookback_days": effective_lookback, "effective_ma_window": effective_ma,
        "available_bars_for_parameters": available_bars,
    })
    warning = f"历史日线不足，已按可用数据自动调整：{'；'.join(changes)}。" if changes else None
    return adjusted, warning


def execute(req, persist=True):
    data = get_history(req.symbol, req.start_date, req.end_date)
    metadata = dict(data.attrs.get("metadata", {}))
    metadata["requested_bars"] = int(((data["date"] >= req.start_date) & (data["date"] <= req.end_date)).sum())

    if req.strategy == StrategyType.QUALITY_GRID:
        effective_req, adjustment_warning = _adapt_quality_request(req, data, metadata)
        metrics, trades, lots, curve, warnings = run_quality_grid(data, effective_req, metadata.get("instrument_type", "unknown"))
        if adjustment_warning:
            warnings.insert(0, adjustment_warning)
        req = effective_req
        if metadata.get("warning"):
            warnings.insert(0, metadata["warning"])
        charts = build_charts(
            curve, trades, lots, metadata.get("price_type", "收盘价"),
            entry_drawdown_pct=req.entry_drawdown_pct,
            ma_discount_pct=req.ma_discount_pct,
        )
    else:
        metrics, trades, curve = run_backtest(data, req)
        lots, warnings = [], [metadata["warning"]] if metadata.get("warning") else []
        charts = build_charts(curve, trades, price_label=metadata.get("price_type", "价格"))

    run_id = save_run(req, metrics, charts, trades, metadata, lots, curve, warnings) if persist else None
    return {
        "id": run_id,
        "symbol": req.symbol,
        "strategy": req.strategy,
        "execution_mode": ("下一交易日开盘价；期末按最后收盘价强制平仓" if req.force_close_at_end else "下一交易日开盘价") if req.strategy == StrategyType.QUALITY_GRID else ("原策略口径；期末强制平仓" if req.force_close_at_end else "原策略口径"),
        "metrics": metrics,
        "trades": [t.model_dump(mode="json") for t in trades],
        "lots": [lot.model_dump(mode="json") for lot in lots],
        "daily_equity": _records(curve),
        "charts": charts,
        "data_info": metadata,
        "warnings": warnings,
    }
