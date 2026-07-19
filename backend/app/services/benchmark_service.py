"""Reference-index market data with a small local cache."""
from __future__ import annotations

from datetime import date, datetime, timedelta
import json
from pathlib import Path
from threading import RLock

import pandas as pd

from app.core.config import DATA_CACHE_DIR
from app.data.provider import MarketDataError


BENCHMARK_SPECS: dict[str, dict[str, str]] = {
    "csi300": {"name": "沪深300指数", "symbol": "sh000300", "market": "china"},
    "nasdaq100": {"name": "纳斯达克100", "symbol": "^NDX", "market": "us"},
    "sp500": {"name": "标普500", "symbol": "^GSPC", "market": "us"},
    "csi1000": {"name": "中证1000", "symbol": "sh000852", "market": "china"},
    "sse50": {"name": "上证50", "symbol": "sh000016", "market": "china"},
    "star50": {"name": "科创50", "symbol": "sh000688", "market": "china"},
    "chinext": {"name": "创业板指", "symbol": "sz399006", "market": "china"},
}

_BENCHMARK_LOCK = RLock()


def _paths(key: str) -> tuple[Path, Path]:
    DATA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data_path = DATA_CACHE_DIR / f"benchmark_{key}.csv"
    return data_path, data_path.with_suffix(".meta.json")


def _normalize(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    aliases = {
        "日期": "date", "date": "date", "Date": "date",
        "开盘": "open", "open": "open", "Open": "open",
        "最高": "high", "high": "high", "High": "high",
        "最低": "low", "low": "low", "Low": "low",
        "收盘": "close", "close": "close", "Close": "close",
        "成交量": "volume", "volume": "volume", "Volume": "volume",
    }
    frame = raw.rename(columns={column: aliases[column] for column in raw.columns if column in aliases}).copy()
    if "date" not in frame or "close" not in frame:
        raise MarketDataError(f"基准行情字段不完整：{list(raw.columns)}")
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.date
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    for column in ("open", "high", "low"):
        if column not in frame:
            frame[column] = frame["close"]
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if "volume" not in frame:
        frame["volume"] = 0.0
    frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce").fillna(0.0)
    frame = frame.dropna(subset=["date", "close"]).sort_values("date").drop_duplicates("date")
    frame["symbol"] = symbol
    return frame[["date", "symbol", "open", "high", "low", "close", "volume"]]


def _fetch(key: str, start: date, end: date) -> tuple[pd.DataFrame, dict]:
    spec = BENCHMARK_SPECS[key]
    try:
        if spec["market"] == "china":
            import akshare as ak
            try:
                raw = ak.stock_zh_index_daily_em(
                    symbol=spec["symbol"], start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"),
                )
                source = "AkShare / 东方财富指数"
            except Exception as eastmoney_error:
                try:
                    raw = ak.stock_zh_index_daily(symbol=spec["symbol"])
                    source = "AkShare / 新浪指数备用"
                except Exception as sina_error:
                    raise MarketDataError(
                        f"{spec['name']}行情不可用。东方财富：{eastmoney_error}；新浪：{sina_error}"
                    ) from sina_error
        else:
            import yfinance as yf
            raw = yf.Ticker(spec["symbol"]).history(
                start=start.isoformat(), end=(end + timedelta(days=1)).isoformat(),
                auto_adjust=False, actions=False,
            ).reset_index()
            source = "Yahoo Finance / 指数"
        frame = _normalize(raw, spec["symbol"])
        frame = frame[(frame["date"] >= start) & (frame["date"] <= end)].copy()
        if frame.empty:
            raise MarketDataError(f"{spec['name']}在所选区间没有可用行情。")
        metadata = {
            "key": key, "name": spec["name"], "symbol": spec["symbol"], "source": source,
            "price_type": "指数收盘点位", "last_updated": datetime.now().isoformat(timespec="seconds"),
            "fetch_requested_start": str(start), "fetch_requested_end": str(end),
        }
        return frame, metadata
    except MarketDataError:
        raise
    except Exception as exc:
        raise MarketDataError(f"获取{spec['name']}行情失败：{exc}") from exc


def get_benchmark_history(key: str, start: date, end: date) -> pd.DataFrame:
    if key not in BENCHMARK_SPECS:
        raise MarketDataError(f"不支持的参考基准：{key}")
    with _BENCHMARK_LOCK:
        data_path, meta_path = _paths(key)
        cached = pd.DataFrame()
        metadata: dict = {}
        if data_path.exists():
            try:
                cached = pd.read_csv(data_path)
                cached["date"] = pd.to_datetime(cached["date"]).dt.date
                metadata = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
            except (OSError, ValueError, json.JSONDecodeError):
                cached = pd.DataFrame()
                metadata = {}
        covered_start = metadata.get("fetch_requested_start")
        covered_end = metadata.get("fetch_requested_end")
        needs_fetch = (
            cached.empty or covered_start is None or covered_end is None
            or date.fromisoformat(covered_start) > start or date.fromisoformat(covered_end) < end
        )
        if needs_fetch:
            fresh, metadata = _fetch(key, start, end)
            cached = pd.concat([cached, fresh], ignore_index=True) if not cached.empty else fresh
            cached = cached.drop_duplicates("date", keep="last").sort_values("date")
            cached.to_csv(data_path, index=False, encoding="utf-8-sig")
            meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        result = cached[(cached["date"] >= start) & (cached["date"] <= end)].copy()
        if result.empty:
            raise MarketDataError(f"{BENCHMARK_SPECS[key]['name']}在所选区间没有可用行情。")
        result.attrs["metadata"] = metadata
        return result