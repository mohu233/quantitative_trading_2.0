"""Causal MACD features for closed one-minute candles.

The first warmup rows have empty feature values. No future bars are used.
"""

from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from pathlib import Path

from main import load_csv, validate_candles


@dataclass(frozen=True)
class MacdConfig:
    fast: int = 12
    slow: int = 26
    signal: int = 9
    z_window: int = 100

    def __post_init__(self) -> None:
        if not (1 < self.fast < self.slow and self.signal > 1 and self.z_window > 1):
            raise ValueError("Require 1 < fast < slow, signal > 1 and z_window > 1")

    @property
    def warmup(self) -> int:
        # EMA starts at the first observation; suppress the most seed-sensitive rows.
        return max(3 * self.slow, self.z_window - 1)


FEATURE_FIELDS = (
    "timestamp_ms", "datetime_utc", "close", "volume",
    "dif", "dea", "hist", "dif_pct", "dea_pct", "hist_pct", "hist_z",
    "hist_slope_pct", "hist_accel_pct",
    "zl_dif", "zl_dea", "zl_hist", "zl_dif_pct", "zl_dea_pct", "zl_hist_pct",
    "zl_hist_z", "zl_hist_slope_pct", "zl_hist_accel_pct",
)


def ema(values: list[float], period: int) -> list[float]:
    if period < 1 or not values:
        raise ValueError("EMA needs a positive period and at least one value")
    alpha = 2.0 / (period + 1)
    result = [values[0]]
    for value in values[1:]:
        result.append(alpha * value + (1 - alpha) * result[-1])
    return result


def zlema(values: list[float], period: int) -> list[float]:
    """EMA of 2*x[t] - x[t-lag], with lag=floor((period-1)/2)."""
    if period < 1 or not values:
        raise ValueError("ZLEMA needs a positive period and at least one value")
    lag = (period - 1) // 2
    adjusted = [2 * value - values[max(0, index - lag)]
                for index, value in enumerate(values)]
    return ema(adjusted, period)


def rolling_zscore(values: list[float], window: int) -> list[float | None]:
    if window < 2:
        raise ValueError("Z-score window must be at least 2")
    result: list[float | None] = []
    for index in range(len(values)):
        if index + 1 < window:
            result.append(None)
            continue
        sample = values[index + 1 - window:index + 1]
        mean = sum(sample) / window
        variance = sum((value - mean) ** 2 for value in sample) / window
        result.append((values[index] - mean) / math.sqrt(variance) if variance > 1e-24 else None)
    return result


def macd(values: list[float], config: MacdConfig, *, zero_lag: bool) -> tuple[list[float], list[float], list[float]]:
    smoother = zlema if zero_lag else ema
    fast_line = smoother(values, config.fast)
    slow_line = smoother(values, config.slow)
    dif = [fast - slow for fast, slow in zip(fast_line, slow_line)]
    # Keep the signal line as a conventional EMA in both variants so only
    # the price smoothing changes between baseline and zero-lag MACD.
    dea = ema(dif, config.signal)
    hist = [d - s for d, s in zip(dif, dea)]
    return dif, dea, hist


def compute_features(candles: list[dict], config: MacdConfig = MacdConfig()) -> list[dict]:
    if not candles:
        raise ValueError("No candles")
    validate_candles(candles)
    closes = [float(row["close"]) for row in candles]
    if any(not math.isfinite(value) or value <= 0 for value in closes):
        raise ValueError("Close prices must be finite and positive")
    standard = macd(closes, config, zero_lag=False)
    zero_lag = macd(closes, config, zero_lag=True)
    rows: list[dict] = []
    for index, candle in enumerate(candles):
        row = {"timestamp_ms": candle["timestamp_ms"],
               "datetime_utc": candle["datetime_utc"],
               "close": candle["close"], "volume": candle["volume"]}
        for prefix, (dif, dea, hist) in (("", standard), ("zl_", zero_lag)):
            row[f"{prefix}dif"] = dif[index]
            row[f"{prefix}dea"] = dea[index]
            row[f"{prefix}hist"] = hist[index]
            row[f"{prefix}dif_pct"] = 100 * dif[index] / closes[index]
            row[f"{prefix}dea_pct"] = 100 * dea[index] / closes[index]
            row[f"{prefix}hist_pct"] = 100 * hist[index] / closes[index]
        rows.append(row)
    for prefix in ("", "zl_"):
        values = [row[f"{prefix}hist_pct"] for row in rows]
        scores = rolling_zscore(values, config.z_window)
        for index, row in enumerate(rows):
            row[f"{prefix}hist_z"] = scores[index]
            row[f"{prefix}hist_slope_pct"] = values[index] - values[index - 1] if index >= 1 else None
            row[f"{prefix}hist_accel_pct"] = (
                values[index] - 2 * values[index - 1] + values[index - 2] if index >= 2 else None
            )
    for index, row in enumerate(rows):
        if index < config.warmup:
            for field in FEATURE_FIELDS[4:]:
                row[field] = None
    return rows


def usable_features(rows: list[dict]) -> list[dict]:
    return [row for row in rows if row["hist_pct"] is not None]


def export_csv(rows: list[dict], output: str) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FEATURE_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: "" if row[key] is None else row[key] for key in FEATURE_FIELDS})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="data/BTC-USDT-1m.csv")
    parser.add_argument("--output", default="data/BTC-USDT-1m-features.csv")
    parser.add_argument("--fast", type=int, default=12)
    parser.add_argument("--slow", type=int, default=26)
    parser.add_argument("--signal", type=int, default=9)
    parser.add_argument("--z-window", type=int, default=100)
    args = parser.parse_args()
    try:
        config = MacdConfig(args.fast, args.slow, args.signal, args.z_window)
        rows = compute_features(load_csv(args.input), config)
        export_csv(rows, args.output)
        usable = usable_features(rows)
        print(f"Saved {len(rows)} feature rows ({len(usable)} after warmup) to {args.output}")
        print(f"Warmup: {config.warmup} rows; last UTC bar: {rows[-1]['datetime_utc']}")
        print(f"Last normalized MACD histogram: {rows[-1]['hist_pct']:.6f}%, ZLEMA: {rows[-1]['zl_hist_pct']:.6f}%")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
