"""Offline spot backtest with next-bar execution and explicit costs."""

import argparse
import csv
import json
from pathlib import Path

from .candles import load_csv


def backtest(args: argparse.Namespace) -> None:
    strategy = getattr(args, "strategy", "sma")
    if strategy not in ("sma", "macd"):
        raise ValueError("Unknown strategy")
    if strategy == "sma" and not (0 < args.fast < args.slow):
        raise ValueError("Require 0 < --fast < --slow")
    if args.initial_cash <= 0 or args.fee_bps < 0 or args.slippage_bps <= 0:
        raise ValueError(
            "Cash must be positive; fee must be nonnegative; slippage must be positive"
        )
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
        from .indicators import MacdConfig, compute_features

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
            trades.append(
                {
                    "time_utc": candles[index]["datetime_utc"],
                    "side": "buy",
                    "signal_time_utc": candles[previous]["datetime_utc"],
                    "price": fill_price,
                    "quantity": quantity,
                    "fee_usdt": fee,
                }
            )
        elif leave and quantity > 0:
            fill_price = open_price * (1 - slip_rate)
            notional = quantity * fill_price
            fee = notional * fee_rate
            cash = notional - fee
            trades.append(
                {
                    "time_utc": candles[index]["datetime_utc"],
                    "side": "sell",
                    "signal_time_utc": candles[previous]["datetime_utc"],
                    "price": fill_price,
                    "quantity": quantity,
                    "fee_usdt": fee,
                }
            )
            quantity = 0.0
        equity = cash + quantity * float(candles[index]["close"])
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak)
    final_equity = cash + quantity * closes[-1]
    summary = {
        "candles": len(candles),
        "start_utc": candles[0]["datetime_utc"],
        "end_utc": candles[-1]["datetime_utc"],
        "strategy": strategy_label,
        "initial_cash_usdt": args.initial_cash,
        "final_equity_usdt": round(final_equity, 6),
        "return_pct": round((final_equity / args.initial_cash - 1) * 100, 4),
        "max_drawdown_pct": round(max_drawdown * 100, 4),
        "fills": len(trades),
        "open_position_base": round(quantity, 12),
        "fee_bps": args.fee_bps,
        "slippage_bps": args.slippage_bps,
    }
    if args.trades:
        output = Path(args.trades)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=("time_utc", "side", "signal_time_utc", "price", "quantity", "fee_usdt"),
            )
            writer.writeheader()
            writer.writerows(trades)
        summary["trades_csv"] = str(output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
