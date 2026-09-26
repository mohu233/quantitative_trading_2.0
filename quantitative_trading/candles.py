"""Fetch, validate and export OKX one-minute spot candles.

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
FIELDS = (
    "timestamp_ms",
    "datetime_utc",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "volume_quote",
    "confirm",
)
API_BASE = "https://app.okx.com"


def utc_text(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc).isoformat(timespec="seconds")


def request_candles(
    api_base: str, symbol: str, after: int | None, retries: int = 3
) -> list[list[str]]:
    params = {"instId": symbol, "bar": "1m", "limit": "300"}
    if after is not None:
        params["after"] = str(after)
    url = f"{api_base.rstrip('/')}/api/v5/market/history-candles?{urlencode(params)}"
    for attempt in range(retries):
        try:
            request = Request(
                url, headers={"User-Agent": "OKX-paper-backtest/1.0", "Accept": "application/json"}
            )
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
        "open": raw[1],
        "high": raw[2],
        "low": raw[3],
        "close": raw[4],
        "volume": raw[5],
        "volume_quote": raw[7],
        "confirm": raw[8],
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
                raise ValueError(
                    f"Missing, duplicate or out-of-order minute between {utc_text(previous)} and {utc_text(timestamp)}"
                )
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
        raise ValueError(
            f"Only {len(candles)} completed candles collected; expected at least {expected}. Data not saved."
        )
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
        raw = [
            candle["timestamp_ms"],
            candle["open"],
            candle["high"],
            candle["low"],
            candle["close"],
            candle["volume"],
            candle["volume_quote"],
            candle["volume_quote"],
            candle["confirm"],
        ]
        parse_candle(raw)
        if candle["datetime_utc"] != utc_text(int(candle["timestamp_ms"])):
            raise ValueError("CSV UTC timestamp does not match timestamp_ms")
    validate_candles(candles)
    return candles
