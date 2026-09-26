"""Historical data and backtest command line entry point."""

import argparse

from .candles import API_BASE, fetch
from .backtest import backtest


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
    backtest_parser.add_argument(
        "--initial-cash", type=float, default=100.0, help="Starting paper cash in USDT"
    )
    backtest_parser.add_argument(
        "--fee-bps", type=float, default=10.0, help="Fee per fill in basis points"
    )
    backtest_parser.add_argument(
        "--slippage-bps", type=float, default=5.0, help="Adverse slippage per fill in basis points"
    )
    backtest_parser.add_argument("--trades", default="data/trades.csv")
    backtest_parser.set_defaults(func=backtest)
    args = parser.parse_args()
    try:
        args.func(args)
    except (OSError, ValueError, RuntimeError, OverflowError) as exc:
        parser.exit(1, f"Error: {exc}\n")
