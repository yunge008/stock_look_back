import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.backtest.quality_grid import _buy_quantity, run_quality_grid
from app.domain.models import BacktestRequest, StrategyType


def bars(opens, closes):
    start = date(2024, 1, 1)
    return pd.DataFrame({
        "date": [start + timedelta(days=i) for i in range(len(closes))],
        "symbol": ["TEST"] * len(closes),
        "open": opens,
        "high": [max(a, b) for a, b in zip(opens, closes)],
        "low": [min(a, b) for a, b in zip(opens, closes)],
        "close": closes,
        "adj_close": closes,
        "volume": [1000] * len(closes),
    })


def request(**updates):
    base = dict(
        symbol="513500", strategy=StrategyType.QUALITY_GRID, start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31), quality_confirmed=True, max_strategy_cash=10_000,
        base_cash=1_000, lookback_days=2, ma_window=2, entry_drawdown_pct=0.10,
        ma_discount_pct=0.05, entry_condition_mode="all", grid_drop_pcts=[0.05, 0.10, 0.15, 0.20],
        grid_cash_multipliers=[1, 1, 1, 1], lot_take_profit_pct=0.05,
        basket_take_profit_enabled=False, basket_take_profit_pct=0.10, reentry_drop_pct=0.05,
        commission_rate=0, min_commission=0, sell_tax_rate=0, slippage_pct=0,
        allow_fractional_etf=True,
    )
    base.update(updates)
    return BacktestRequest(**base)


class QualityGridTests(unittest.TestCase):
    def test_each_lot_exits_once_and_in_full(self):
        data = bars(
            [120, 100, 100, 95, 99.75, 100, 105],
            [120, 100, 95, 99.75, 100, 105, 104],
        )
        metrics, trades, lots, _, _ = run_quality_grid(data, request(), "etf")
        buys = [t for t in trades if t.side == "BUY" and t.status == "FILLED"]
        sells = [t for t in trades if t.side == "SELL" and t.status == "FILLED"]
        self.assertEqual([round(t.price, 2) for t in buys], [100.00, 95.00])
        self.assertEqual(len(sells), 2)
        for lot in lots:
            lot_sells = [t for t in sells if t.lot_id == lot.lot_id]
            self.assertEqual(len(lot_sells), 1, f"{lot.lot_id} must have one sell only")
            self.assertAlmostEqual(lot_sells[0].quantity, lot.quantity)
            self.assertEqual(lot.status, "CLOSED")
        self.assertEqual(metrics["completed_rounds"], 1)
        self.assertFalse(any("50%" in t.reason for t in trades))

    def test_basket_exit_closes_only_remaining_lots(self):
        data = bars(
            [120, 100, 100, 95, 99.75, 100, 110],
            [120, 100, 95, 99.75, 100, 110, 109],
        )
        _, trades, lots, _, _ = run_quality_grid(
            data, request(basket_take_profit_enabled=True, basket_take_profit_pct=0.10), "etf"
        )
        basket_sells = [t for t in trades if t.side == "SELL" and t.status == "FILLED" and t.reason.startswith("组合")]
        lot_sells = [t for t in trades if t.side == "SELL" and t.status == "FILLED" and t.reason.startswith("Lot")]
        self.assertEqual(len(lot_sells), 1)
        self.assertEqual(lot_sells[0].lot_id, "R1-L1")
        self.assertEqual(len(basket_sells), 1)
        self.assertEqual(basket_sells[0].lot_id, "R1-L0")
        self.assertTrue(all(lot.status == "CLOSED" for lot in lots))

    def test_insufficient_cash_blocks_grid_buy(self):
        data = bars([120, 100, 100, 95, 95], [120, 100, 95, 94, 94])
        _, trades, lots, _, warnings = run_quality_grid(
            data, request(max_strategy_cash=1_000, base_cash=1_000), "etf"
        )
        filled_buys = [t for t in trades if t.side == "BUY" and t.status == "FILLED"]
        skipped_buys = [t for t in trades if t.side == "BUY" and t.status == "SKIPPED"]
        self.assertEqual(len(filled_buys), 1)
        self.assertGreaterEqual(len(skipped_buys), 1)
        self.assertEqual(len(lots), 1)
        self.assertTrue(any("资金不足" in warning for warning in warnings))

    def test_board_lot_order_raises_cash_to_one_lot_without_borrowing(self):
        req = request(max_strategy_cash=100_000, base_cash=20_000, commission_rate=0, min_commission=0)
        quantity, fee = _buy_quantity(20_000, 100_000, 300, 100, req)
        self.assertEqual(quantity, 100)
        self.assertEqual(fee, 0)
        insufficient_quantity, _ = _buy_quantity(20_000, 29_999, 300, 100, req)
        self.assertEqual(insufficient_quantity, 0)
    def test_open_lot_is_not_forced_closed_at_end(self):
        data = bars([120, 100, 100, 102], [120, 100, 101, 102])
        metrics, trades, lots, curve, _ = run_quality_grid(data, request(), "etf")
        self.assertEqual(len([t for t in trades if t.side == "SELL" and t.status == "FILLED"]), 0)
        self.assertEqual(lots[0].status, "OPEN")
        self.assertEqual(metrics["realized_profit"], 0)
        self.assertGreater(metrics["unrealized_profit"], 0)
        self.assertAlmostEqual(metrics["current_market_value"], curve.iloc[-1]["market_value"])
        self.assertEqual(metrics["incomplete_rounds"], 1)


if __name__ == "__main__":
    unittest.main()


