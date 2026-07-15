"""AkShare daily-bar adapter with source metadata and local CSV cache."""
from datetime import date, datetime, timedelta
from functools import lru_cache
import re
import json
from pathlib import Path

import pandas as pd

from app.core.config import DATA_CACHE_DIR

SINA_FALLBACK_WARNING = "当前使用新浪备用日线，未提供复权序列，回测以收盘价作为价格依据。"
A_STOCK_SINA_WARNING = "当前使用新浪备用 A 股日线（前复权 qfq）。请注意不同数据源的复权因子可能存在差异。"


class MarketDataError(RuntimeError):
    pass


def instrument_type(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if normalized.isdigit() and len(normalized) == 6:
        # Common Shanghai/Shenzhen ETF and listed-fund prefixes.
        return "etf" if normalized.startswith(("5", "15", "16", "18")) else "a_stock"
    # Yahoo Finance Hong Kong tickers require the .HK suffix, e.g. 0700.HK.
    if re.fullmatch(r"\d{4,5}\.HK", normalized):
        return "hk_stock"
    # Yahoo Finance US ticker symbols, including class shares such as BRK.B.
    return "us_stock" if re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,19}", normalized) else "unknown"
@lru_cache(maxsize=1024)
def instrument_name(symbol: str) -> str | None:
    """Best-effort display name lookup; failures must never block a backtest."""
    try:
        import akshare as ak
        kind = instrument_type(symbol)
        if kind == "a_stock":
            try:
                info = ak.stock_individual_info_em(symbol=symbol)
                if {"item", "value"}.issubset(info.columns):
                    match = info[info["item"].astype(str).str.contains("简称", na=False)]
                    if not match.empty:
                        return str(match.iloc[0]["value"]).strip() or None
            except Exception:
                pass
            try:
                if symbol.startswith(("6", "9")):
                    listed = ak.stock_info_sh_name_code(symbol="主板A股")
                elif symbol.startswith(("0", "3")):
                    listed = ak.stock_info_sz_name_code(symbol="A股列表")
                else:
                    listed = ak.stock_info_bj_name_code()
                code_column = next((c for c in ("证券代码", "A股代码", "code") if c in listed.columns), None)
                name_column = next((c for c in ("证券简称", "A股简称", "name") if c in listed.columns), None)
                if code_column and name_column:
                    match = listed[listed[code_column].astype(str).str.extract(r"(\d{6})", expand=False) == symbol]
                    if not match.empty:
                        return str(match.iloc[0][name_column]).strip() or None
            except Exception:
                pass
            # Sina's full A-share spot list is a final fallback only: it is heavier,
            # but remains useful when the official listing source is unavailable.
            spot = ak.stock_zh_a_spot()
            code_column = next((c for c in ("代码", "symbol") if c in spot.columns), None)
            name_column = next((c for c in ("名称", "name") if c in spot.columns), None)
            if code_column and name_column:
                match = spot[spot[code_column].astype(str).str.extract(r"(\d{6})", expand=False) == symbol]
                if not match.empty:
                    return str(match.iloc[0][name_column]).strip() or None
        elif kind in {"us_stock", "hk_stock"}:
            import yfinance as yf
            info = yf.Ticker(symbol).get_info()
            return str(info.get("longName") or info.get("shortName") or "").strip() or None
        elif kind == "etf":
            spot = ak.fund_etf_spot_em()
            code_column = next((c for c in ("代码", "基金代码", "symbol") if c in spot.columns), None)
            name_column = next((c for c in ("名称", "基金简称", "name") if c in spot.columns), None)
            if code_column and name_column:
                match = spot[spot[code_column].astype(str).str.extract(r"(\d{6})", expand=False) == symbol]
                if not match.empty:
                    return str(match.iloc[0][name_column]).strip() or None
    except Exception:
        return None
    return None

def _cache_file(symbol: str) -> Path:
    DATA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_CACHE_DIR / f"{symbol.replace('/', '_')}.csv"


def _meta_file(symbol: str) -> Path:
    return _cache_file(symbol).with_suffix(".meta.json")


def _normalize(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    aliases = {
        "日期": "date", "date": "date", "Date": "date", "开盘": "open", "open": "open", "Open": "open",
        "最高": "high", "high": "high", "High": "high", "最低": "low", "low": "low", "Low": "low",
        "收盘": "close", "close": "close", "Close": "close", "成交量": "volume", "volume": "volume", "Volume": "volume",
    }
    df = df.rename(columns={k: v for k, v in aliases.items() if k in df.columns}).copy()
    if "date" not in df or "close" not in df:
        raise MarketDataError(f"数据源返回字段不完整：{list(df.columns)}")
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    for col in ("open", "high", "low", "close", "volume"):
        if col not in df:
            df[col] = df["close"] if col == "open" else 0.0
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["date", "open", "close"]).sort_values("date").drop_duplicates("date")
    df["adj_close"] = df["close"]
    df["symbol"] = symbol
    return df[["date", "symbol", "open", "high", "low", "close", "adj_close", "volume"]]


def _fetch_yahoo_finance(symbol: str, start: date, end: date) -> tuple[pd.DataFrame, dict]:
    """Fetch adjusted US or Hong Kong daily bars from Yahoo Finance."""
    kind = instrument_type(symbol)
    market_label = "港股" if kind == "hk_stock" else "美股"
    try:
        import yfinance as yf
        raw = yf.Ticker(symbol).history(
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            auto_adjust=True,
            actions=False,
        )
        if raw.empty:
            raise MarketDataError(f"Yahoo Finance 未返回 {symbol} 的{market_label}日线。")
        normalized = _normalize(raw.reset_index(), symbol)
        if normalized.empty:
            raise MarketDataError(f"Yahoo Finance 返回的 {symbol} {market_label}日线为空。")
        metadata = {
            "source": f"Yahoo Finance / {market_label}",
            "price_type": "复权 OHLC（auto_adjust）",
            "instrument_type": kind,
            "warning": (
                "港股日线来自 Yahoo Finance；复权价格已包含拆股与分红调整。"
                "港股整手数因标的而异，当前回测按 1 股最小单位模拟。"
                if kind == "hk_stock"
                else "美股日线来自 Yahoo Finance；复权价格已包含拆股与分红调整。"
            ),
            "last_updated": datetime.now().isoformat(timespec="seconds"),
            "fetch_requested_start": str(start),
            "fetch_requested_end": str(end),
        }
        return normalized, metadata
    except MarketDataError:
        raise
    except Exception as exc:
        raise MarketDataError(f"Yahoo Finance 获取{market_label} {symbol} 失败：{exc}") from exc

def _fetch_akshare(symbol: str, start: date, end: date) -> tuple[pd.DataFrame, dict]:
    kind = instrument_type(symbol)
    if kind in {"us_stock", "hk_stock"}:
        return _fetch_yahoo_finance(symbol, start, end)
    try:
        import akshare as ak

        kind = instrument_type(symbol)
        warning = None
        if kind == "etf":
            try:
                raw = ak.fund_etf_hist_em(
                    symbol=symbol, period="daily", start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"), adjust="qfq",
                )
                source, price_type = "AkShare / 东方财富 ETF", "前复权(qfq)"
            except Exception as eastmoney_error:
                exchange = "sh" if symbol.startswith("5") else "sz"
                try:
                    raw = ak.fund_etf_hist_sina(symbol=f"{exchange}{symbol}")
                    if raw.empty:
                        raise ValueError("Sina returned no data")
                    source, price_type, warning = "AkShare / 新浪 ETF 备用", "未复权收盘价", SINA_FALLBACK_WARNING
                except Exception as sina_error:
                    raise MarketDataError(
                        f"ETF 行情不可用。东方财富：{eastmoney_error}；新浪：{sina_error}"
                    ) from sina_error
        elif kind == "a_stock":
            try:
                raw = ak.stock_zh_a_hist(
                    symbol=symbol, period="daily", start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"), adjust="qfq",
                )
                source, price_type = "AkShare / 东方财富 A股", "前复权(qfq)"
            except Exception as eastmoney_error:
                exchange = "sh" if symbol.startswith(("6", "9")) else "sz"
                try:
                    raw = ak.stock_zh_a_daily(
                        symbol=f"{exchange}{symbol}", start_date=start.strftime("%Y%m%d"),
                        end_date=end.strftime("%Y%m%d"), adjust="qfq",
                    )
                    if raw.empty:
                        raise ValueError("Sina returned no data")
                    source, price_type, warning = "AkShare / 新浪 A股备用", "前复权(qfq)", A_STOCK_SINA_WARNING
                except Exception as sina_error:
                    raise MarketDataError(
                        f"A 股行情不可用。东方财富：{eastmoney_error}；新浪：{sina_error}"
                    ) from sina_error
        else:
            raise MarketDataError("代码格式暂不支持；请使用 6 位 A 股/ETF、Yahoo Finance 美股或港股代码，例如 600519、513500、AAPL、0700.HK。")

        normalized = _normalize(raw, symbol)
        if normalized.empty:
            raise MarketDataError(f"{symbol} 数据源返回空行情。")
        metadata = {
            "source": source,
            "price_type": price_type,
            "instrument_type": kind,
            "warning": warning,
            "last_updated": datetime.now().isoformat(timespec="seconds"),
            "fetch_requested_start": str(start),
            "fetch_requested_end": str(end),
        }
        return normalized, metadata
    except MarketDataError:
        raise
    except Exception as exc:
        raise MarketDataError(f"AkShare 获取 {symbol} 失败：{exc}") from exc


def _read_metadata(symbol: str) -> dict:
    path = _meta_file(symbol)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {
        "source": "AkShare 本地缓存（旧缓存来源未记录）",
        "price_type": "历史缓存价格类型未记录",
        "instrument_type": instrument_type(symbol),
        "warning": "该缓存由旧版本生成，未记录数据源与复权类型；刷新行情后会补全元数据。",
        "last_updated": None,
    }


def get_history(symbol: str, start: date, end: date) -> pd.DataFrame:
    if start > end:
        raise MarketDataError("开始日期不能晚于结束日期。")
    requested_start = start - timedelta(days=1200)
    cache = _cache_file(symbol)
    cached = pd.DataFrame()
    metadata = _read_metadata(symbol)
    if cache.exists():
        try:
            cached = pd.read_csv(cache)
            cached["date"] = pd.to_datetime(cached["date"]).dt.date
        except Exception:
            cached = pd.DataFrame()

    covered_from = metadata.get("fetch_requested_start")
    has_start_coverage = (not cached.empty) and (
        cached["date"].min() <= requested_start
        or (covered_from is not None and date.fromisoformat(covered_from) <= requested_start)
    )
    needs_fetch = cached.empty or not has_start_coverage or cached["date"].max() < end - timedelta(days=2)
    if needs_fetch:
        fresh, metadata = _fetch_akshare(symbol, requested_start, end)
        combined = pd.concat([cached, fresh], ignore_index=True) if not cached.empty else fresh
        combined = combined.drop_duplicates("date", keep="last").sort_values("date")
        combined.to_csv(cache, index=False, encoding="utf-8-sig")
        _meta_file(symbol).write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        cached = combined

    result = cached[(cached["date"] >= requested_start) & (cached["date"] <= end)].copy()
    if result.empty:
        raise MarketDataError("指定区间没有可用交易数据。")
    metadata = {
        **metadata,
        "available_start": str(result["date"].min()),
        "available_end": str(result["date"].max()),
        "bars": int(len(result)),
        "cache_file": str(cache),
    }
    result.attrs["metadata"] = metadata
    return result
