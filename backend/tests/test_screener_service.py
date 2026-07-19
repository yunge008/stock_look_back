import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.models import StockScreenerRequest
from app.services.screener_service import _fetch_report, _fetch_valuation_history, _quarter_ends, _valuation_snapshot


class ScreenerServiceTests(unittest.TestCase):
    def test_quarter_list_never_starts_after_selected_date(self):
        self.assertEqual(_quarter_ends(date(2026, 7, 17), 2), [date(2026, 6, 30), date(2026, 3, 31)])
        self.assertEqual(_quarter_ends(date(2026, 6, 30), 1), [date(2026, 6, 30)])

    @patch("app.services.screener_service._fetch_valuation_history")
    def test_high_window_days_changes_period_high_filter(self, valuation_history_mock):
        start = date(2024, 1, 1)
        dates = [start + timedelta(days=index) for index in range(150)]
        closes = [200.0] + [100.0] * 149
        valuation_history_mock.return_value = pd.DataFrame({
            "数据日期": dates, "当日收盘价": closes, "总市值": [1e12] * 150, "PE(TTM)": [10.0] * 150,
        })
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "app.services.screener_service._screen_cache_dir", return_value=Path(temp_dir)
        ):
            long_window = StockScreenerRequest(
                as_of_date=dates[-1], market_cap_min_usd=0, pe_min=0, pe_max=30,
                high_window_days=150, high_drawdown_min_pct=30, sma_window=20, below_sma_min_pct=0,
            )
            short_window = long_window.model_copy(update={"high_window_days": 120})
            matched = _valuation_snapshot("600001", long_window)
            rejected = _valuation_snapshot("600001", short_window)
        self.assertIsNotNone(matched)
        self.assertEqual(matched["high_window_days"], 150)
        self.assertAlmostEqual(matched["drawdown_from_high_pct"], 50.0)
        self.assertIsNone(rejected)


    @patch("app.services.screener_service.requests.get")
    def test_empty_eastmoney_result_is_a_normal_unavailable_symbol(self, get_mock):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "version": None, "result": None, "success": False, "message": "返回数据为空", "code": 9201,
        }
        get_mock.return_value = response
        frame = _fetch_valuation_history("603361")
        self.assertTrue(frame.empty)
        self.assertEqual(list(frame.columns), ["数据日期", "当日收盘价", "总市值", "PE(TTM)"])
    @patch("app.services.screener_service.requests.get")
    def test_report_uses_original_notice_date_instead_of_update_date(self, get_mock):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"result": {"pages": 1, "data": [{
            "SECURITY_CODE": "600519", "SECURITY_NAME_ABBR": "贵州茅台",
            "NOTICE_DATE": "2023-10-21", "UPDATE_DATE": "2024-10-26", "BASIC_EPS": 42.09,
            "TOTAL_OPERATE_INCOME": 105_315_900_448.1, "YSTZ": 17.29,
            "PARENT_NETPROFIT": 52_876_217_064.12, "WEIGHTAVG_ROE": 24.82,
            "PUBLISHNAME": "白酒",
        }]}}
        get_mock.return_value = response
        frame = _fetch_report(date(2023, 9, 30))
        self.assertEqual(frame.iloc[0]["股票代码"], "600519")
        self.assertEqual(frame.iloc[0]["公告日期"], date(2023, 10, 21))
        self.assertEqual(frame.iloc[0]["最新公告日期"], date(2024, 10, 26))
if __name__ == "__main__":
    unittest.main()