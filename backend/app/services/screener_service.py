"""Point-in-time A-share fundamental and price screener."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from threading import RLock
import time

import requests

import pandas as pd

from app.core.config import DATA_CACHE_DIR
from app.data.provider import MarketDataError
from app.domain.models import StockScreenerRequest

_SCREEN_LOCK = RLock()


def _quarter_ends(as_of: date, count: int = 9) -> list[date]:
    quarter_month = ((as_of.month - 1) // 3 + 1) * 3
    year = as_of.year
    quarter_day = 31 if quarter_month in {3, 12} else 30
    if date(year, quarter_month, quarter_day) > as_of:
        quarter_month -= 3
        if quarter_month <= 0:
            quarter_month += 12
            year -= 1
    result: list[date] = []
    month = quarter_month
    for _ in range(count):
        day = 31 if month in {3, 12} else 30
        result.append(date(year, month, day))
        month -= 3
        if month <= 0:
            month += 12
            year -= 1
    return result


def _screen_cache_dir() -> Path:
    path = DATA_CACHE_DIR / "stock_screener"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_csv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    return frame


def _fetch_report(period: date) -> pd.DataFrame:
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "sortColumns": "UPDATE_DATE,SECURITY_CODE", "sortTypes": "-1,-1", "pageSize": "500",
        "pageNumber": "1", "reportName": "RPT_LICO_FN_CPD", "columns": "ALL",
        "filter": f"(REPORTDATE='{period.isoformat()}')",
    }
    records: list[dict] = []
    pages = 1
    page = 1
    while page <= pages:
        params["pageNumber"] = str(page)
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
                response.raise_for_status()
                payload = response.json()
                result = payload.get("result") or {}
                if not result:
                    raise MarketDataError(payload.get("message") or f"{period} 业绩报表未返回数据")
                if page == 1:
                    pages = int(result.get("pages") or 1)
                records.extend(result.get("data") or [])
                last_error = None
                break
            except (requests.RequestException, ValueError, MarketDataError) as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.75 * (attempt + 1))
        if last_error is not None:
            raise MarketDataError(f"{period} 业绩报表第 {page} 页重试后仍失败：{last_error}")
        page += 1
    if not records:
        return pd.DataFrame()
    frame = pd.DataFrame(records).rename(columns={
        "SECURITY_CODE": "股票代码", "SECURITY_NAME_ABBR": "股票简称",
        "NOTICE_DATE": "公告日期", "UPDATE_DATE": "最新公告日期", "BASIC_EPS": "每股收益",
        "TOTAL_OPERATE_INCOME": "营业总收入-营业总收入", "YSTZ": "营业总收入-同比增长",
        "PARENT_NETPROFIT": "净利润-净利润", "WEIGHTAVG_ROE": "净资产收益率",
        "PUBLISHNAME": "所处行业",
    })
    required = [
        "股票代码", "股票简称", "公告日期", "最新公告日期", "每股收益",
        "营业总收入-营业总收入", "营业总收入-同比增长", "净利润-净利润",
        "净资产收益率", "所处行业",
    ]
    missing = [column for column in required if column not in frame]
    if missing:
        raise MarketDataError(f"{period} 业绩报表缺少字段：{', '.join(missing)}")
    frame = frame[required].copy()
    frame["股票代码"] = frame["股票代码"].astype(str).str.extract(r"(\d{1,6})", expand=False).str.zfill(6)
    for column in ("公告日期", "最新公告日期"):
        frame[column] = pd.to_datetime(frame[column], errors="coerce").dt.date
    for column in (
        "每股收益", "营业总收入-营业总收入", "营业总收入-同比增长", "净利润-净利润", "净资产收益率",
    ):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna(subset=["股票代码", "公告日期"])


def _load_report(period: date, as_of: date) -> pd.DataFrame:
    path = _screen_cache_dir() / f"yjbb_{period:%Y%m%d}.csv"
    recent_period = (as_of - period).days < 210
    fresh = path.exists() and (not recent_period or datetime.fromtimestamp(path.stat().st_mtime).date() >= date.today() - timedelta(days=1))
    frame = pd.DataFrame()
    if fresh:
        try:
            frame = _read_csv(path)
            if "公告日期" not in frame.columns:
                frame = pd.DataFrame()
        except Exception:
            frame = pd.DataFrame()
    if frame.empty:
        frame = _fetch_report(period)
        frame.to_csv(path, index=False, encoding="utf-8-sig")
    frame = frame.copy()
    frame["report_period"] = period.isoformat()
    frame["股票代码"] = frame["股票代码"].astype(str).str.extract(r"(\d{1,6})", expand=False).str.zfill(6)
    for column in ("公告日期", "最新公告日期"):
        frame[column] = pd.to_datetime(frame[column], errors="coerce").dt.date
    return frame[frame["公告日期"] <= as_of]

def _fetch_valuation_history(symbol: str) -> pd.DataFrame:
    """Fetch raw Eastmoney valuation history and handle symbols with no dataset."""
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "sortColumns": "TRADE_DATE", "sortTypes": "-1", "pageSize": "5000", "pageNumber": "1",
        "reportName": "RPT_VALUEANALYSIS_DET", "columns": "ALL", "quoteColumns": "",
        "source": "WEB", "client": "WEB", "filter": f'(SECURITY_CODE="{symbol}")',
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=30)
            response.raise_for_status()
            payload = response.json()
            result = payload.get("result") or {}
            records = result.get("data") or []
            if not records:
                if payload.get("code") == 9201 or payload.get("message") == "返回数据为空":
                    return pd.DataFrame(columns=["数据日期", "当日收盘价", "总市值", "PE(TTM)"])
                raise MarketDataError(payload.get("message") or "东方财富估值接口未返回数据")
            frame = pd.DataFrame(records).rename(columns={
                "TRADE_DATE": "数据日期", "CLOSE_PRICE": "当日收盘价",
                "TOTAL_MARKET_CAP": "总市值", "PE_TTM": "PE(TTM)",
            })
            required = ["数据日期", "当日收盘价", "总市值", "PE(TTM)"]
            missing = [column for column in required if column not in frame]
            if missing:
                raise MarketDataError(f"东方财富估值接口缺少字段：{', '.join(missing)}")
            frame = frame[required].copy()
            frame["数据日期"] = pd.to_datetime(frame["数据日期"], errors="coerce").dt.date
            for column in required[1:]:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
            return frame.dropna(subset=["数据日期", "当日收盘价"]).sort_values("数据日期").reset_index(drop=True)
        except (requests.RequestException, ValueError, MarketDataError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.75 * (attempt + 1))
    raise MarketDataError(f"{symbol} 历史估值请求重试后仍失败：{last_error}")

def _valuation_snapshot(symbol: str, request: StockScreenerRequest) -> dict | None:

    path = _screen_cache_dir() / "valuations" / f"{symbol}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame()
    if path.exists():
        try:
            frame = _read_csv(path)
            frame["数据日期"] = pd.to_datetime(frame["数据日期"], errors="coerce").dt.date
        except Exception:
            frame = pd.DataFrame()
    if frame.empty or frame["数据日期"].max() < request.as_of_date:
        frame = _fetch_valuation_history(symbol)
        if frame.empty:
            return None
        frame.to_csv(path, index=False, encoding="utf-8-sig")
    history = frame[frame["数据日期"] <= request.as_of_date].sort_values("数据日期")
    if history.empty:
        return None
    row = history.iloc[-1]
    closes = pd.to_numeric(history["当日收盘价"], errors="coerce").dropna()
    if len(closes) < request.sma_window:
        return None
    close = float(row["当日收盘价"])
    period_high = float(closes.tail(request.high_window_days).max())
    sma = float(closes.tail(request.sma_window).mean())
    market_cap = float(row["总市值"])
    pe = float(row["PE(TTM)"])
    drawdown = 1 - close / period_high if period_high > 0 else None
    below_sma = 1 - close / sma if sma > 0 else None
    if (
        market_cap < request.market_cap_min_usd * request.usd_cny_rate
        or not request.pe_min <= pe <= request.pe_max
        or drawdown is None or drawdown < request.high_drawdown_min_pct / 100
        or below_sma is None or below_sma < request.below_sma_min_pct / 100
    ):
        return None
    return {
        "valuation_date": str(row["数据日期"]),
        "close": close,
        "market_cap_cny": market_cap,
        "market_cap_usd": market_cap / request.usd_cny_rate,
        "pe_ttm": pe,
        "high_window_days": request.high_window_days,
        "period_high": period_high,
        "drawdown_from_high_pct": drawdown * 100,
        "sma": sma,
        "below_sma_pct": below_sma * 100,
    }


def run_stock_screener(request: StockScreenerRequest) -> dict:
    with _SCREEN_LOCK:
        try:
            reports = [_load_report(period, request.as_of_date) for period in _quarter_ends(request.as_of_date)]
        except Exception as exc:
            raise MarketDataError(f"历史业绩报表获取失败：{exc}") from exc
    all_reports = pd.concat(reports, ignore_index=True)
    if all_reports.empty:
        raise MarketDataError("所选日期之前没有可用的 A 股业绩报表。")
    all_reports["report_period"] = pd.to_datetime(all_reports["report_period"]).dt.date
    all_reports["股票代码"] = all_reports["股票代码"].astype(str).str.extract(r"(\d{1,6})", expand=False).str.zfill(6)
    all_reports = all_reports.dropna(subset=["股票代码", "report_period"])
    latest = all_reports.sort_values(["股票代码", "report_period", "公告日期"]).groupby("股票代码", as_index=False).tail(1).copy()
    previous_eps = all_reports[["股票代码", "report_period", "每股收益"]].copy()
    previous_eps["report_period"] = previous_eps["report_period"].apply(lambda value: value.replace(year=value.year + 1))
    previous_eps = previous_eps.rename(columns={"每股收益": "上年同期每股收益"})
    latest = latest.merge(previous_eps, on=["股票代码", "report_period"], how="left")

    numeric_columns = [
        "每股收益", "上年同期每股收益", "营业总收入-营业总收入", "营业总收入-同比增长",
        "净利润-净利润", "净资产收益率",
    ]
    for column in numeric_columns:
        latest[column] = pd.to_numeric(latest[column], errors="coerce")
    latest["net_margin_pct"] = latest["净利润-净利润"] / latest["营业总收入-营业总收入"] * 100
    valid_previous = latest["上年同期每股收益"] > 0
    latest["eps_growth_pct"] = None
    latest.loc[valid_previous, "eps_growth_pct"] = (
        latest.loc[valid_previous, "每股收益"] / latest.loc[valid_previous, "上年同期每股收益"] - 1
    ) * 100
    fundamental = latest[
        (latest["net_margin_pct"] >= request.net_margin_min_pct)
        & (latest["净资产收益率"] >= request.roe_min_pct)
        & (latest["营业总收入-同比增长"] >= request.revenue_growth_min_pct)
        & (latest["eps_growth_pct"] >= request.eps_growth_min_pct)
    ].copy()

    candidates = fundamental.to_dict(orient="records")
    valuation_results: dict[str, dict] = {}
    valuation_errors: list[str] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_valuation_snapshot, str(row["股票代码"]), request): str(row["股票代码"]) for row in candidates}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                snapshot = future.result()
                if snapshot:
                    valuation_results[symbol] = snapshot
            except Exception as exc:
                valuation_errors.append(f"{symbol}: {exc}")
    if candidates and len(valuation_errors) == len(candidates):
        raise MarketDataError(f"本次运行全部候选股的历史估值读取失败；首个错误：{valuation_errors[0]}")

    results: list[dict] = []
    for row in candidates:
        symbol = str(row["股票代码"])
        valuation = valuation_results.get(symbol)
        if not valuation:
            continue
        results.append({
            "symbol": symbol,
            "name": None if pd.isna(row.get("股票简称")) else str(row.get("股票简称")),
            "industry": None if pd.isna(row.get("所处行业")) else str(row.get("所处行业")),
            "report_period": str(row["report_period"]),
            "announcement_date": str(row["公告日期"]),
            "eps": float(row.get("每股收益")),
            "eps_growth_pct": float(row.get("eps_growth_pct")),
            "revenue_growth_pct": float(row.get("营业总收入-同比增长")),
            "net_margin_pct": float(row.get("net_margin_pct")),
            "roe_pct": float(row.get("净资产收益率")),
            **valuation,
        })
    results.sort(key=lambda item: (-item["drawdown_from_high_pct"], item["pe_ttm"]))
    warnings: list[str] = []
    if valuation_errors:
        warnings.append(f"本次运行有 {len(valuation_errors)} 只候选股的历史估值读取失败并被跳过；首个错误：{valuation_errors[0]}")
    return {
        "as_of_date": str(request.as_of_date),
        "universe_count": int(latest["股票代码"].nunique()),
        "fundamental_candidate_count": len(candidates),
        "matched_count": len(results),
        "results": results,
        "warnings": warnings,
        "methodology": "财务指标按公告日截断；PE、市值、区间高点和SMA均取所选日期当时或之前的历史估值序列。",
    }