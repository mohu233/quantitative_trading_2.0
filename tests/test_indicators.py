import math
import unittest

from quantitative_trading.indicators import MacdConfig, compute_features, ema, zlema
from quantitative_trading.candles import MINUTE_MS, utc_text


def candles_from_closes(closes):
    return [
        {
            "timestamp_ms": index * MINUTE_MS,
            "datetime_utc": utc_text(index * MINUTE_MS),
            "close": str(close),
            "volume": "1",
            "confirm": "1",
        }
        for index, close in enumerate(closes)
    ]


class MacdFeatureTests(unittest.TestCase):
    def setUp(self):
        self.config = MacdConfig(fast=3, slow=7, signal=3, z_window=10)
        self.closes = [100 + index * 0.1 + 2 * math.sin(index / 4) for index in range(80)]

    def test_ema_and_zero_lag_example(self):
        self.assertEqual(ema([1, 2, 3], 3), [1, 1.5, 2.25])
        self.assertEqual(zlema([1, 2, 3], 3), [1, 2, 3])

    def test_future_bars_do_not_change_past_features(self):
        partial = compute_features(candles_from_closes(self.closes[:50]), self.config)
        full = compute_features(candles_from_closes(self.closes), self.config)
        for left, right in zip(partial, full):
            self.assertEqual(left, right)

    def test_price_scale_does_not_change_normalized_features(self):
        a = compute_features(candles_from_closes(self.closes), self.config)
        b = compute_features(
            candles_from_closes([value * 10 for value in self.closes]), self.config
        )
        for field in (
            "dif_pct",
            "hist_pct",
            "hist_z",
            "hist_slope_pct",
            "hist_accel_pct",
            "zl_dif_pct",
            "zl_hist_pct",
            "zl_hist_z",
        ):
            self.assertAlmostEqual(a[-1][field], b[-1][field], places=8)

    def test_slope_and_acceleration_are_backward_differences(self):
        rows = compute_features(candles_from_closes(self.closes), self.config)
        for prefix in ("", "zl_"):
            self.assertAlmostEqual(
                rows[-1][f"{prefix}hist_slope_pct"],
                rows[-1][f"{prefix}hist_pct"] - rows[-2][f"{prefix}hist_pct"],
            )
            self.assertAlmostEqual(
                rows[-1][f"{prefix}hist_accel_pct"],
                rows[-1][f"{prefix}hist_pct"]
                - 2 * rows[-2][f"{prefix}hist_pct"]
                + rows[-3][f"{prefix}hist_pct"],
            )

    def test_unclosed_candle_is_rejected(self):
        candles = candles_from_closes(self.closes)
        candles[-1]["confirm"] = "0"
        with self.assertRaisesRegex(ValueError, "Unclosed"):
            compute_features(candles, self.config)


if __name__ == "__main__":
    unittest.main()
