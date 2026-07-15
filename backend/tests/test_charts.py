import sys
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.charts.figures import build_charts


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


if __name__ == "__main__":
    unittest.main()
