import json
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.models import PortfolioBacktestRequest
from app.services.portfolio_service import run_portfolio_backtest


def history(symbol: str, closes: list[float]) -> pd.DataFrame:
    start = date(2024, 1, 2)
    return pd.DataFrame({
        "date": [start + timedelta(days=index) for index in range(len(closes))],
        "symbol": [symbol] * len(closes),
        "open": closes, "high": closes, "low": closes, "close": closes,
        "adj_close": closes, "volume": [1000] * len(closes),
    })


class PortfolioServiceTests(unittest.TestCase):
    @patch("app.services.portfolio_service.instrument_name", return_value=None)
    @patch("app.services.portfolio_service.get_history")
    def test_each_symbol_runs_quality_grid_and_portfolio_reports_holding_drawdown(self, get_history_mock, _):
        frames = {
            "600001": history("600001", [10, 10, 6, 6, 7]),
            "510300": history("510300", [10, 10, 6, 6, 4]),
        }
        get_history_mock.side_effect = lambda symbol, *_: frames[symbol]
        request = PortfolioBacktestRequest(
            symbols=["600001", "510300"], start_date=date(2024, 1, 2), end_date=date(2024, 1, 6),
            total_cash=20_000, lookback_days=2, ma_window=2,
            entry_drawdown_pct=0.30, ma_discount_pct=0.15,
            grid_drop_pcts=[0.10, 0.20, 0.30], grid_cash_multipliers=[1, 1, 1],
            lot_take_profit_pct=0.10, commission_rate=0, min_commission=0,
            sell_tax_rate=0, slippage_pct=0, force_close_at_end=True,
        )
        result = run_portfolio_backtest(request)
        self.assertEqual(result["metrics"]["invested_symbols"], 2)
        self.assertEqual(result["metrics"]["lot_count"], 2)
        self.assertAlmostEqual(result["metrics"]["win_rate"], 0.5)
        self.assertAlmostEqual(result["metrics"]["max_capital_used"], 5_000, places=4)
        self.assertLess(result["metrics"]["max_holding_drawdown"], 0)
        self.assertGreater(result["metrics"]["max_holding_ratio"], 0)
        self.assertEqual(result["daily_equity"][-1]["market_value"], 0)
        self.assertTrue(all(lot["exit_reason"] == "回测到期强制平仓" for lot in result["lots"]))
        self.assertEqual({lot["symbol"] for lot in result["lots"]}, {"600001", "510300"})
        self.assertNotIn("correlation_matrix", result)
        json.dumps(result, ensure_ascii=False, allow_nan=False)


    @patch("app.services.portfolio_service.instrument_name", return_value=None)
    @patch("app.services.portfolio_service.get_benchmark_history")
    @patch("app.services.portfolio_service.get_history")
    def test_selected_benchmark_is_normalized_to_portfolio_cash(self, get_history_mock, benchmark_mock, _):
        frames = {
            "600001": history("600001", [10, 10, 6, 6, 7]),
            "510300": history("510300", [10, 10, 6, 6, 4]),
        }
        get_history_mock.side_effect = lambda symbol, *_: frames[symbol]
        benchmark_frame = history("sh000300", [100, 110, 90, 120, 115])
        benchmark_frame.attrs["metadata"] = {"source": "测试指数源"}
        benchmark_mock.return_value = benchmark_frame
        request = PortfolioBacktestRequest(
            symbols=["600001", "510300"], start_date=date(2024, 1, 2), end_date=date(2024, 1, 6),
            total_cash=20_000, benchmark="csi300", lookback_days=2, ma_window=2,
            entry_drawdown_pct=0.30, ma_discount_pct=0.15,
            grid_drop_pcts=[0.10, 0.20, 0.30], grid_cash_multipliers=[1, 1, 1],
            lot_take_profit_pct=0.10, commission_rate=0, min_commission=0,
            sell_tax_rate=0, slippage_pct=0, force_close_at_end=True,
        )
        result = run_portfolio_backtest(request)
        benchmark = result["benchmark"]
        self.assertEqual(benchmark["name"], "沪深300指数")
        self.assertEqual(benchmark["symbol"], "sh000300")
        self.assertEqual(benchmark["source"], "测试指数源")
        self.assertAlmostEqual(benchmark["daily"][0]["normalized_equity"], 20_000)
        self.assertAlmostEqual(benchmark["total_return"], 0.15)
        self.assertLess(benchmark["max_drawdown"], 0)
        self.assertIsNotNone(result["metrics"]["benchmark_annualized_excess"])
        benchmark_mock.assert_called_once_with("csi300", request.start_date, request.end_date)
        json.dumps(result, ensure_ascii=False, allow_nan=False)
if __name__ == "__main__":
    unittest.main()