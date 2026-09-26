import contextlib
import csv
import io
import json
import math
import tempfile
import unittest
from argparse import Namespace
from datetime import datetime
from pathlib import Path

from quantitative_trading.candles import FIELDS, MINUTE_MS, utc_text, validate_candles
from quantitative_trading.backtest import backtest


class PaperBacktestTests(unittest.TestCase):
    def test_gap_is_rejected(self):
        candles = [
            {"timestamp_ms": 0, "confirm": "1"},
            {"timestamp_ms": 2 * MINUTE_MS, "confirm": "1"},
        ]
        with self.assertRaisesRegex(ValueError, "Missing"):
            validate_candles(candles)

    def test_signal_fills_at_next_open_and_pays_costs(self):
        with tempfile.TemporaryDirectory() as directory:
            prices = [1, 1, 2, 2, 2]
            csv_path = Path(directory) / "candles.csv"
            trades_path = Path(directory) / "trades.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=FIELDS)
                writer.writeheader()
                for index, close in enumerate(prices):
                    timestamp = index * MINUTE_MS
                    opening = 3 if index == 3 else close
                    writer.writerow(
                        {
                            "timestamp_ms": timestamp,
                            "datetime_utc": utc_text(timestamp),
                            "open": opening,
                            "high": max(opening, close),
                            "low": min(opening, close),
                            "close": close,
                            "volume": 1,
                            "volume_quote": 1,
                            "confirm": "1",
                        }
                    )
            args = Namespace(
                input=str(csv_path),
                fast=2,
                slow=3,
                initial_cash=100,
                fee_bps=10,
                slippage_bps=5,
                trades=str(trades_path),
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                backtest(args)
            summary = json.loads(output.getvalue())
            with trades_path.open(newline="", encoding="utf-8") as handle:
                trades = list(csv.DictReader(handle))
            self.assertEqual(summary["fills"], 1)
            self.assertEqual(trades[0]["signal_time_utc"], utc_text(2 * MINUTE_MS))
            self.assertEqual(trades[0]["time_utc"], utc_text(3 * MINUTE_MS))
            self.assertAlmostEqual(float(trades[0]["price"]), 3 * 1.0005)
            self.assertGreater(float(trades[0]["fee_usdt"]), 0)

    def test_macd_backtest_uses_previous_closed_bar(self):
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "candles.csv"
            trades_path = Path(directory) / "trades.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=FIELDS)
                writer.writeheader()
                for index in range(120):
                    timestamp = index * MINUTE_MS
                    close = 100 + 3 * math.sin(index / 4)
                    writer.writerow(
                        {
                            "timestamp_ms": timestamp,
                            "datetime_utc": utc_text(timestamp),
                            "open": close,
                            "high": close,
                            "low": close,
                            "close": close,
                            "volume": 1,
                            "volume_quote": close,
                            "confirm": "1",
                        }
                    )
            args = Namespace(
                input=str(csv_path),
                strategy="macd",
                macd_fast=3,
                macd_slow=7,
                macd_signal=3,
                z_window=10,
                initial_cash=100,
                fee_bps=10,
                slippage_bps=5,
                trades=str(trades_path),
            )
            with contextlib.redirect_stdout(io.StringIO()):
                backtest(args)
            with trades_path.open(newline="", encoding="utf-8") as handle:
                trades = list(csv.DictReader(handle))
            self.assertGreater(len(trades), 0)
            for trade in trades:
                signal_timestamp = int(
                    datetime.fromisoformat(trade["signal_time_utc"]).timestamp() * 1000
                )
                fill_timestamp = int(datetime.fromisoformat(trade["time_utc"]).timestamp() * 1000)
                self.assertEqual(fill_timestamp - signal_timestamp, MINUTE_MS)


if __name__ == "__main__":
    unittest.main()
