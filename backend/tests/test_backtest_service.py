import sys
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.models import BacktestRequest, StrategyType
from app.services.backtest_service import _adapt_quality_request


class BacktestServiceTests(unittest.TestCase):
    def test_quality_grid_adapts_start_and_windows_to_available_history(self):
        data = pd.DataFrame({
            "date": [date(2024, 6, 3), date(2024, 6, 4), date(2024, 6, 5)],
        })
        request = BacktestRequest(
            symbol="NEW", strategy=StrategyType.QUALITY_GRID,
            start_date=date(2018, 1, 1), end_date=date(2024, 12, 31),
            lookback_days=360, ma_window=120,
        )
        metadata = {}
        effective, warning = _adapt_quality_request(request, data, metadata)
        self.assertEqual(effective.start_date, date(2024, 6, 3))
        self.assertEqual(effective.lookback_days, 3)
        self.assertEqual(effective.ma_window, 3)
        self.assertIn("开始日期", warning)
        self.assertEqual(metadata["effective_lookback_days"], 3)


if __name__ == "__main__":
    unittest.main()