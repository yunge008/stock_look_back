from datetime import date

import pandas as pd

from app.data.provider import get_history
from app.domain.models import TargetEntryRequest


def calculate_target_entry(data: pd.DataFrame, request: TargetEntryRequest) -> dict:
    frame = data.copy().sort_values("date")
    frame = frame[frame["date"] <= (request.as_of_date or date.today())]
    required = max(request.lookback_days, request.ma_window)
    if len(frame) < required:
        raise ValueError(f"可用日线不足：需要至少 {required} 个交易日，当前仅 {len(frame)} 个。")
    closes = pd.to_numeric(frame["close"], errors="coerce").dropna()
    if len(closes) < required:
        raise ValueError(f"有效收盘价不足：需要至少 {required} 个交易日。")
    latest_close = float(closes.iloc[-1])
    rolling_high = float(closes.iloc[-request.lookback_days:].max())
    ma_value = float(closes.iloc[-request.ma_window:].mean())
    drawdown_buy_price = rolling_high * (1 - request.entry_drawdown_pct)
    ma_buy_price = ma_value * (1 - request.ma_discount_pct)
    target_price = min(drawdown_buy_price, ma_buy_price)
    return {
        "symbol": request.symbol,
        "as_of_date": str(frame["date"].iloc[-1]),
        "latest_close": latest_close,
        "lookback_high_close": rolling_high,
        "ma_value": ma_value,
        "drawdown_buy_price": drawdown_buy_price,
        "ma_buy_price": ma_buy_price,
        "target_buy_price": target_price,
        "conditions_met": latest_close <= target_price,
        "distance_to_target_pct": latest_close / target_price - 1 if target_price > 0 else None,
    }


def get_target_entry(request: TargetEntryRequest) -> tuple[dict, dict]:
    as_of = request.as_of_date or date.today()
    data = get_history(request.symbol, as_of, as_of)
    return calculate_target_entry(data, request), dict(data.attrs.get("metadata", {}))
