import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data import provider


class ProviderTests(unittest.TestCase):
    def test_instrument_name_uses_a_stock_short_name(self):
        info = pd.DataFrame({"item": ["股票简称", "行业"], "value": ["鸣志电器", "电机"]})
        with patch("akshare.stock_individual_info_em", return_value=info):
            self.assertEqual(provider.instrument_name("603728"), "鸣志电器")

    def test_instrument_name_uses_official_exchange_listing(self):
        listed = pd.DataFrame({"证券代码": ["603728"], "证券简称": ["鸣志电器"]})
        with patch("akshare.stock_individual_info_em", side_effect=RuntimeError("eastmoney down")), \
             patch("akshare.stock_info_sh_name_code", return_value=listed):
            self.assertEqual(provider.instrument_name("603728"), "鸣志电器")
    def test_instrument_name_falls_back_to_sina_a_stock_spot(self):
        spot = pd.DataFrame({"代码": ["603728"], "名称": ["鸣志电器"]})
        with patch("akshare.stock_individual_info_em", side_effect=RuntimeError("eastmoney down")), \
             patch("akshare.stock_zh_a_spot", return_value=spot):
            self.assertEqual(provider.instrument_name("603728"), "鸣志电器")
    def test_instrument_name_uses_etf_short_name(self):
        spot = pd.DataFrame({"基金代码": ["513500"], "基金简称": ["标普500ETF"]})
        with patch("akshare.fund_etf_spot_em", return_value=spot):
            self.assertEqual(provider.instrument_name("513500"), "标普500ETF")
    def test_etf_eastmoney_failure_uses_sina_with_exact_warning(self):
        sina = pd.DataFrame({
            "date": ["2024-01-02", "2024-01-03"], "open": [1.0, 1.1], "high": [1.2, 1.2],
            "low": [0.9, 1.0], "close": [1.1, 1.15], "volume": [100, 120],
        })
        with patch("akshare.fund_etf_hist_em", side_effect=RuntimeError("eastmoney down")), \
             patch("akshare.fund_etf_hist_sina", return_value=sina) as fallback:
            frame, meta = provider._fetch_akshare("513500", date(2024, 1, 1), date(2024, 1, 31))
        fallback.assert_called_once_with(symbol="sh513500")
        self.assertEqual(meta["source"], "AkShare / 新浪 ETF 备用")
        self.assertEqual(meta["price_type"], "未复权收盘价")
        self.assertEqual(meta["warning"], provider.SINA_FALLBACK_WARNING)
        self.assertEqual(len(frame), 2)

    def test_a_stock_eastmoney_failure_uses_sina_qfq(self):
        sina = pd.DataFrame({
            "date": ["2024-01-02", "2024-01-03"], "open": [20.0, 20.5], "high": [21.0, 21.0],
            "low": [19.8, 20.1], "close": [20.5, 20.8], "volume": [1000, 1200],
        })
        with patch("akshare.stock_zh_a_hist", side_effect=RuntimeError("eastmoney down")), \
             patch("akshare.stock_zh_a_daily", return_value=sina) as fallback:
            frame, meta = provider._fetch_akshare("603728", date(2024, 1, 1), date(2024, 1, 31))
        fallback.assert_called_once_with(symbol="sh603728", start_date="20240101", end_date="20240131", adjust="qfq")
        self.assertEqual(meta["source"], "AkShare / 新浪 A股备用")
        self.assertEqual(meta["price_type"], "前复权(qfq)")
        self.assertEqual(meta["warning"], provider.A_STOCK_SINA_WARNING)
        self.assertEqual(len(frame), 2)
    def test_us_ticker_detection_accepts_yahoo_class_shares(self):
        self.assertEqual(provider.instrument_type("AAPL"), "us_stock")
        self.assertEqual(provider.instrument_type("BRK.B"), "us_stock")

    def test_us_stock_uses_yahoo_finance_adjusted_history(self):
        raw = pd.DataFrame({
            "Open": [100.0, 101.0], "High": [101.0, 102.0], "Low": [99.0, 100.0],
            "Close": [100.5, 101.5], "Volume": [1000, 1200],
        }, index=pd.to_datetime(["2024-01-02", "2024-01-03"]))
        raw.index.name = "Date"
        with patch("yfinance.Ticker") as ticker:
            ticker.return_value.history.return_value = raw
            frame, meta = provider._fetch_akshare("AAPL", date(2024, 1, 1), date(2024, 1, 3))
        ticker.assert_called_once_with("AAPL")
        ticker.return_value.history.assert_called_once_with(
            start="2024-01-01", end="2024-01-04", auto_adjust=True, actions=False,
        )
        self.assertEqual(meta["source"], "Yahoo Finance / 美股")
        self.assertEqual(meta["price_type"], "复权 OHLC（auto_adjust）")
        self.assertEqual(list(frame["close"]), [100.5, 101.5])
    def test_history_is_cached_with_metadata(self):
        start, end = date(2024, 1, 1), date(2024, 1, 10)
        warmup = start - timedelta(days=1200)
        fresh = pd.DataFrame({
            "date": [start, end], "symbol": ["513500", "513500"], "open": [1.0, 1.1],
            "high": [1.0, 1.1], "low": [1.0, 1.1], "close": [1.0, 1.1],
            "adj_close": [1.0, 1.1], "volume": [100, 100],
        })
        meta = {"source": "test-source", "price_type": "test-price", "instrument_type": "etf", "warning": None, "last_updated": "now", "fetch_requested_start": str(warmup), "fetch_requested_end": str(end)}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(provider, "DATA_CACHE_DIR", Path(directory)), \
             patch.object(provider, "_fetch_akshare", return_value=(fresh, meta)) as fetch:
            first = provider.get_history("513500", start, end)
            second = provider.get_history("513500", start, end)
            self.assertTrue((Path(directory) / "513500.csv").exists())
            self.assertTrue((Path(directory) / "513500.meta.json").exists())
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(first.attrs["metadata"]["source"], "test-source")
        self.assertEqual(second.attrs["metadata"]["source"], "test-source")


if __name__ == "__main__":
    unittest.main()
