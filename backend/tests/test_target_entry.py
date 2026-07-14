import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.models import TargetEntryRequest
from app.services.target_entry_service import calculate_target_entry


class TargetEntryTests(unittest.TestCase):
    def test_target_is_lower_of_drawdown_and_ma_thresholds(self):
        start = date(2024, 1, 1)
        closes = [100, 120, 90, 80]
        data = pd.DataFrame({
            "date": [start + timedelta(days=i) for i in range(4)],
            "close": closes,
        })
        request = TargetEntryRequest(
            symbol="513500", lookback_days=3, ma_window=2,
            entry_drawdown_pct=0.30, ma_discount_pct=0.15,
        )
        result = calculate_target_entry(data, request)
        self.assertAlmostEqual(result["lookback_high_close"], 120)
        self.assertAlmostEqual(result["drawdown_buy_price"], 84)
        self.assertAlmostEqual(result["ma_buy_price"], 72.25)
        self.assertAlmostEqual(result["target_buy_price"], 72.25)
        self.assertFalse(result["conditions_met"])


if __name__ == "__main__":
    unittest.main()
