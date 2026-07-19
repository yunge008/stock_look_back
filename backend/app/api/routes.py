from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query

from app.data.provider import MarketDataError, get_history, instrument_name
from app.db.repository import get_run, list_runs
from app.domain.models import (
    BacktestRequest, OptimizationRequest, PortfolioBacktestRequest, StockScreenerRequest, TargetEntryRequest,
)
from app.services.backtest_service import execute
from app.services.portfolio_service import run_portfolio_backtest
from app.services.screener_service import run_stock_screener
from app.services.target_entry_service import get_target_entry

router = APIRouter(prefix="/api/v1")


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/instruments/{symbol}/availability")
def availability(symbol: str):
    try:
        normalized = symbol.strip().upper()
        df = get_history(normalized, date.today() - timedelta(days=400), date.today())
        metadata = dict(df.attrs.get("metadata", {}))
        return {"symbol": normalized, "name": instrument_name(normalized), **metadata}
    except MarketDataError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/target-entry")
def target_entry(request: TargetEntryRequest):
    try:
        target, metadata = get_target_entry(request)
        return {"target": target, "data_info": metadata}
    except (MarketDataError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc

@router.post("/stock-screener")
def stock_screener(request: StockScreenerRequest):
    try:
        return run_stock_screener(request)
    except (MarketDataError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"选股执行失败：{exc}") from exc


@router.post("/portfolio-backtests")
def portfolio_backtest(request: PortfolioBacktestRequest):
    try:
        return run_portfolio_backtest(request)
    except (MarketDataError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"组合回测执行失败：{exc}") from exc

@router.post("/backtests")
def create_backtest(request: BacktestRequest):
    try:
        return execute(request)
    except (MarketDataError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"回测执行失败：{exc}") from exc


@router.post("/optimizations")
def optimize(request: OptimizationRequest):
    results = []
    for ma in request.ma_windows:
        for threshold in request.thresholds:
            item = request.model_copy(update={"ma_window": ma, "lower_threshold": -abs(threshold), "upper_threshold": abs(threshold)})
            try:
                result = execute(item, persist=False)
                results.append({"ma_window": ma, "threshold": threshold, **result["metrics"]})
            except (MarketDataError, ValueError) as exc:
                raise HTTPException(422, str(exc)) from exc
    results.sort(key=lambda r: (r["sharpe_ratio"] is not None, r["sharpe_ratio"] or -999, r["cagr"]), reverse=True)
    for rank, item in enumerate(results, 1):
        item["rank"] = rank
    return {"symbol": request.symbol, "best": results[0] if results else None, "results": results}


@router.get("/backtests")
def history(limit: int = Query(50, ge=1, le=200)):
    return list_runs(limit)


@router.get("/backtests/{run_id}")
def detail(run_id: str):
    result = get_run(run_id)
    if not result:
        raise HTTPException(404, "未找到该回测记录")
    return result


