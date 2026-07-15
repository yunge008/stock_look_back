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


def execute(req, persist=True):
    data = get_history(req.symbol, req.start_date, req.end_date)
    metadata = dict(data.attrs.get("metadata", {}))
    metadata["requested_start"] = str(req.start_date)
    metadata["requested_end"] = str(req.end_date)
    metadata["requested_bars"] = int(((data["date"] >= req.start_date) & (data["date"] <= req.end_date)).sum())

    if req.strategy == StrategyType.QUALITY_GRID:
        metrics, trades, lots, curve, warnings = run_quality_grid(data, req, metadata.get("instrument_type", "unknown"))
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
        "execution_mode": "下一交易日开盘价" if req.strategy == StrategyType.QUALITY_GRID else "原策略口径",
        "metrics": metrics,
        "trades": [t.model_dump(mode="json") for t in trades],
        "lots": [lot.model_dump(mode="json") for lot in lots],
        "daily_equity": _records(curve),
        "charts": charts,
        "data_info": metadata,
        "warnings": warnings,
    }
