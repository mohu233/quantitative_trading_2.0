"""Fetch OKX 1-minute spot candles and run an offline paper backtest.

Uses only Python's standard library. No API key or trading endpoint is used.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

MINUTE_MS = 60_000
FIELDS = ("timestamp_ms", "datetime_utc", "open", "high", "low", "close", "volume", "volume_quote", "confirm")
API_BASE = "https://app.okx.com"


def utc_text(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc).isoformat(timespec="seconds")


def request_candles(api_base: str, symbol: str, after: int | None, retries: int = 3) -> list[list[str]]:
    params = {"instId": symbol, "bar": "1m", "limit": "300"}
    if after is not None:
        params["after"] = str(after)
    url = f"{api_base.rstrip('/')}/api/v5/market/history-candles?{urlencode(params)}"
    for attempt in range(retries):
        try:
            request = Request(url, headers={"User-Agent": "OKX-paper-backtest/1.0", "Accept": "application/json"})
            with urlopen(request, timeout=15) as response:
                payload = json.load(response)
            if payload.get("code") != "0" or not isinstance(payload.get("data"), list):
                raise ValueError(f"OKX API error: {payload.get('code')} {payload.get('msg')}")
            return payload["data"]
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            retryable = not isinstance(exc, HTTPError) or exc.code in (429, 500, 502, 503, 504)
            if attempt == retries - 1 or not retryable:
                raise RuntimeError(f"Cannot fetch OKX candles: {exc}") from exc
            time.sleep(1.5 * (attempt + 1))
    raise AssertionError("unreachable")


def parse_candle(raw: list[str]) -> dict[str, str | int]:
    if len(raw) != 9:
        raise ValueError(f"Expected 9 OKX candle fields, got {len(raw)}")
    timestamp = int(raw[0])
    if timestamp % MINUTE_MS:
        raise ValueError(f"Candle timestamp is not minute-aligned: {timestamp}")
    o, h, low, c, volume, _, quote_volume = (Decimal(value) for value in raw[1:8])
    if min(o, h, low, c) <= 0 or volume < 0 or quote_volume < 0 or h < max(o, c) or low > min(o, c):
        raise ValueError(f"Invalid OHLCV at {timestamp}")
    return {
        "timestamp_ms": timestamp,
        "datetime_utc": utc_text(timestamp),
        "open": raw[1], "high": raw[2], "low": raw[3], "close": raw[4],
        "volume": raw[5], "volume_quote": raw[7], "confirm": raw[8],
    }


def validate_candles(candles: list[dict[str, str | int]], require_contiguous: bool = True) -> None:
    if not candles:
        raise ValueError("No completed candles available")
    previous = None
    for candle in candles:
        timestamp = int(candle["timestamp_ms"])
        if candle["confirm"] != "1":
            raise ValueError(f"Unclosed candle at {timestamp}")
        if previous is not None:
            difference = timestamp - previous
            if difference <= 0 or (require_contiguous and difference != MINUTE_MS):
                raise ValueError(f"Missing, duplicate or out-of-order minute between {utc_text(previous)} and {utc_text(timestamp)}")
        previous = timestamp


def fetch(args: argparse.Namespace) -> None:
    if args.days <= 0 or args.days > 30:
        raise ValueError("--days must be between 1 and 30")
    if not args.symbol.endswith("-USDT") or not args.symbol.replace("-", "").isalnum():
        raise ValueError("--symbol must be a spot pair such as BTC-USDT")
    # Cut off at the current UTC minute; the API's confirm flag excludes the open candle.
    start_ms = (int(time.time() * 1000) // MINUTE_MS - args.days * 1440) * MINUTE_MS
    by_timestamp: dict[int, dict[str, str | int]] = {}
    cursor = None
    while True:
        page = request_candles(args.api_base, args.symbol, cursor)
        if not page:
            break
        oldest = min(int(row[0]) for row in page)
        if cursor is not None and oldest >= cursor:
            raise ValueError("OKX pagination did not advance")
        for raw in page:
            candle = parse_candle(raw)
            timestamp = int(candle["timestamp_ms"])
            if timestamp >= start_ms and candle["confirm"] == "1":
                by_timestamp[timestamp] = candle
        if oldest <= start_ms:
            break
        cursor = oldest
        time.sleep(0.12)  # comfortably below OKX's history-candles rate limit
    candles = [by_timestamp[key] for key in sorted(by_timestamp)]
    validate_candles(candles)
    expected = args.days * 1440
    if len(candles) < expected:
        raise ValueError(f"Only {len(candles)} completed candles collected; expected at least {expected}. Data not saved.")
    candles = candles[-expected:]
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(candles)
    print(f"Saved {len(candles)} completed 1m {args.symbol} candles to {output}")
    print(f"UTC range: {candles[0]['datetime_utc']} through {candles[-1]['datetime_utc']}")


def load_csv(path: str) -> list[dict[str, str | int]]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not set(FIELDS).issubset(reader.fieldnames or []):
            raise ValueError(f"CSV must include: {', '.join(FIELDS)}")
        candles = list(reader)
    for candle in candles:
        raw = [candle["timestamp_ms"], candle["open"], candle["high"], candle["low"],
               candle["close"], candle["volume"], candle["volume_quote"], candle["volume_quote"], candle["confirm"]]
        parse_candle(raw)
        if candle["datetime_utc"] != utc_text(int(candle["timestamp_ms"])):
            raise ValueError("CSV UTC timestamp does not match timestamp_ms")
    validate_candles(candles)
    return candles


def backtest(args: argparse.Namespace) -> None:
    strategy = getattr(args, "strategy", "sma")
    if strategy not in ("sma", "macd"):
        raise ValueError("Unknown strategy")
    if strategy == "sma" and not (0 < args.fast < args.slow):
        raise ValueError("Require 0 < --fast < --slow")
    if args.initial_cash <= 0 or args.fee_bps < 0 or args.slippage_bps <= 0:
        raise ValueError("Cash must be positive; fee must be nonnegative; slippage must be positive")
    candles = load_csv(args.input)
    if strategy == "sma" and len(candles) <= args.slow:
        raise ValueError("Not enough candles for the slow moving average")
    closes = [float(candle["close"]) for candle in candles]
    if strategy == "sma":
        prefix = [0.0]
        for close in closes:
            prefix.append(prefix[-1] + close)
        first_fill_index = args.slow
        strategy_label = f"SMA {args.fast}/{args.slow}"
    else:
        from macd_features import MacdConfig, compute_features
        config = MacdConfig(args.macd_fast, args.macd_slow, args.macd_signal, args.z_window)
        features = compute_features(candles, config)
        first_fill_index = config.warmup + 1
        if len(candles) <= first_fill_index:
            raise ValueError("Not enough candles after MACD warmup")
        strategy_label = f"MACD {config.fast}/{config.slow}/{config.signal} + ZLEMA confirmation"
    cash = float(args.initial_cash)
    quantity = 0.0
    fee_rate = args.fee_bps / 10_000
    slip_rate = args.slippage_bps / 10_000
    trades = []
    peak = cash
    max_drawdown = 0.0
    for index in range(first_fill_index, len(candles)):
        previous = index - 1
        if strategy == "sma":
            fast_ma = (prefix[index] - prefix[index - args.fast]) / args.fast
            slow_ma = (prefix[index] - prefix[index - args.slow]) / args.slow
            enter = fast_ma > slow_ma
            leave = fast_ma < slow_ma
        else:
            row = features[previous]
            # Example rules, evaluated only after the previous bar has closed.
            enter = row["hist_pct"] > 0 and row["zl_hist_pct"] > 0 and row["hist_slope_pct"] > 0
            leave = row["hist_pct"] < 0 or row["zl_hist_pct"] < 0
        open_price = float(candles[index]["open"])
        if enter and quantity == 0:
            fill_price = open_price * (1 + slip_rate)
            quantity = cash / (fill_price * (1 + fee_rate))
            notional = quantity * fill_price
            fee = notional * fee_rate
            cash = 0.0
            trades.append({"time_utc": candles[index]["datetime_utc"], "side": "buy", "signal_time_utc": candles[previous]["datetime_utc"], "price": fill_price, "quantity": quantity, "fee_usdt": fee})
        elif leave and quantity > 0:
            fill_price = open_price * (1 - slip_rate)
            notional = quantity * fill_price
            fee = notional * fee_rate
            cash = notional - fee
            trades.append({"time_utc": candles[index]["datetime_utc"], "side": "sell", "signal_time_utc": candles[previous]["datetime_utc"], "price": fill_price, "quantity": quantity, "fee_usdt": fee})
            quantity = 0.0
        equity = cash + quantity * float(candles[index]["close"])
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak)
    final_equity = cash + quantity * closes[-1]
    summary = {
        "candles": len(candles), "start_utc": candles[0]["datetime_utc"],
        "end_utc": candles[-1]["datetime_utc"], "strategy": strategy_label,
        "initial_cash_usdt": args.initial_cash, "final_equity_usdt": round(final_equity, 6),
        "return_pct": round((final_equity / args.initial_cash - 1) * 100, 4),
        "max_drawdown_pct": round(max_drawdown * 100, 4), "fills": len(trades),
        "open_position_base": round(quantity, 12), "fee_bps": args.fee_bps,
        "slippage_bps": args.slippage_bps,
    }
    if args.trades:
        output = Path(args.trades)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=("time_utc", "side", "signal_time_utc", "price", "quantity", "fee_usdt"))
            writer.writeheader()
            writer.writerows(trades)
        summary["trades_csv"] = str(output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    fetch_parser = commands.add_parser("fetch", help="Download completed 1-minute OKX spot candles")
    fetch_parser.add_argument("--symbol", default="BTC-USDT")
    fetch_parser.add_argument("--days", type=int, default=1)
    fetch_parser.add_argument("--output", default="data/BTC-USDT-1m.csv")
    fetch_parser.add_argument("--api-base", default=API_BASE)
    fetch_parser.set_defaults(func=fetch)
    backtest_parser = commands.add_parser("backtest", help="Replay CSV with a sample SMA strategy")
    backtest_parser.add_argument("--input", default="data/BTC-USDT-1m.csv")
    backtest_parser.add_argument("--strategy", choices=("sma", "macd"), default="sma")
    backtest_parser.add_argument("--fast", type=int, default=5)
    backtest_parser.add_argument("--slow", type=int, default=20)
    backtest_parser.add_argument("--macd-fast", type=int, default=12)
    backtest_parser.add_argument("--macd-slow", type=int, default=26)
    backtest_parser.add_argument("--macd-signal", type=int, default=9)
    backtest_parser.add_argument("--z-window", type=int, default=100)
    backtest_parser.add_argument("--initial-cash", type=float, default=100.0, help="Starting paper cash in USDT")
    backtest_parser.add_argument("--fee-bps", type=float, default=10.0, help="Fee per fill in basis points")
    backtest_parser.add_argument("--slippage-bps", type=float, default=5.0, help="Adverse slippage per fill in basis points")
    backtest_parser.add_argument("--trades", default="data/trades.csv")
    backtest_parser.set_defaults(func=backtest)
    args = parser.parse_args()
    try:
        args.func(args)
    except (OSError, ValueError, RuntimeError, OverflowError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
