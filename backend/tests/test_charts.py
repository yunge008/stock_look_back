import sys
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.charts.figures import _cash_flow_adjusted_nav, _position_cost_drawdown, build_charts


class ChartTests(unittest.TestCase):
    def test_price_chart_includes_both_entry_threshold_lines(self):
        curve = pd.DataFrame({
            "date": [date(2024, 1, 2), date(2024, 1, 3)],
            "price": [90.0, 80.0], "ma": [100.0, 90.0],
            "rolling_high": [120.0, 110.0], "equity": [1000.0, 990.0],
            "cash": [500.0, 500.0], "market_value": [500.0, 490.0],
            "drawdown": [0.0, -0.01], "invested_cost": [500.0, 500.0], "next_grid_price": [None, None],
        })
        charts = build_charts(curve, [], entry_drawdown_pct=0.30, ma_discount_pct=0.15)
        trace_names = {trace["name"] for trace in charts["price"]["data"]}
        self.assertIn("最高收盘回撤线（30%）", trace_names)
        self.assertIn("MA 下方幅度线（15%）", trace_names)
        drawdown = charts["drawdown"]
        self.assertEqual(drawdown["layout"]["title"]["text"], "持仓成本回撤曲线（相对持仓成本收益率高点）")
        self.assertEqual(drawdown["data"][0]["name"], "持仓成本回撤")
        self.assertIn("y", drawdown["data"][0])


    def test_cash_flow_adjusted_nav_removes_external_deposit_jump(self):
        curve = pd.DataFrame({
            "equity": [100.0, 120.0, 170.0],
            "external_cash_flow": [100.0, 0.0, 50.0],
        })
        self.assertEqual(_cash_flow_adjusted_nav(curve), [1.0, 1.2, 1.2])

    def test_position_cost_drawdown_never_uses_return_as_nav(self):
        curve = pd.DataFrame({
            "invested_cost": [100.0, 100.0, 100.0],
            "market_value": [100.0, 110.0, 90.0],
        })
        result = _position_cost_drawdown(curve)
        self.assertAlmostEqual(result.iloc[0], 0.0)
        self.assertAlmostEqual(result.iloc[1], 0.0)
        self.assertAlmostEqual(result.iloc[2], 90 / 110 - 1)
        self.assertGreaterEqual(result.min(), -1.0)
if __name__ == "__main__":
    unittest.main()
