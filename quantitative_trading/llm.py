"""Small, read-only Ollama SDK client for the local DeepSeek-R1 GGUF model."""

from __future__ import annotations

import argparse
import json
import re

from .candles import load_csv
from .indicators import compute_features, usable_features

MODEL = "deepseek-r1-local"


def ask_json(prompt: str, *, max_tokens: int = 1024) -> dict:
    try:
        from ollama import Client
    except ImportError as exc:
        raise RuntimeError(
            "Install the Ollama Python SDK: python -m pip install -r requirements.txt"
        ) from exc

    response = Client(host="http://127.0.0.1:11434", timeout=180).chat(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        format="json",
        options={"temperature": 0, "num_predict": max_tokens},
    )
    if response.done_reason == "length" or not response.message.content:
        raise RuntimeError("Model stopped before producing an answer; increase max_tokens")
    content = response.message.content.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", content, flags=re.IGNORECASE)
    if fenced:
        content = fenced.group(1)
    try:
        result = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Model returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise RuntimeError("Model response must be a JSON object")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("probe", help="Run two short SDK calls")
    candles = commands.add_parser(
        "candles", help="Describe recent completed candles without placing orders"
    )
    candles.add_argument("--input", default="data/BTC-USDT-1m.csv")
    candles.add_argument("--count", type=int, default=5)
    features = commands.add_parser("features", help="Describe standardized MACD features")
    features.add_argument("--input", default="data/BTC-USDT-1m.csv")
    features.add_argument("--count", type=int, default=5)
    args = parser.parse_args()
    try:
        if args.command == "probe":
            prompts = [
                "计算 2+3。只返回 JSON 对象，字段 answer 为整数。",
                "将这条公告分类为 maintenance、listing 或 other，只返回 JSON 对象，字段 category 和 reason：交易所将于 10:00 维护现货系统一小时。",
            ]
            for prompt in prompts:
                print(
                    json.dumps({"prompt": prompt, "response": ask_json(prompt)}, ensure_ascii=True)
                )
        elif args.command == "candles":
            if not 1 <= args.count <= 20:
                raise ValueError("--count must be between 1 and 20")
            data = load_csv(args.input)[-args.count :]
            samples = [
                {
                    key: candle[key]
                    for key in ("datetime_utc", "open", "high", "low", "close", "volume")
                }
                for candle in data
            ]
            prompt = (
                "以下是已收盘的 1 分钟 K 线。只做客观数据描述，不预测未来、不提供买卖指令。"
                "只返回 JSON 对象，字段 observations 为字符串列表，字段 limitations 为字符串列表。"
                f"数据：{json.dumps(samples, ensure_ascii=False)}"
            )
            print(json.dumps(ask_json(prompt, max_tokens=1536), ensure_ascii=True, indent=2))
        else:
            if not 1 <= args.count <= 10:
                raise ValueError("--count must be between 1 and 10")
            rows = usable_features(compute_features(load_csv(args.input)))
            if len(rows) < args.count:
                raise ValueError("Not enough post-warmup MACD feature rows")
            fields = (
                "dif_pct",
                "dea_pct",
                "hist_pct",
                "hist_z",
                "hist_slope_pct",
                "hist_accel_pct",
                "zl_dif_pct",
                "zl_dea_pct",
                "zl_hist_pct",
                "zl_hist_z",
                "zl_hist_slope_pct",
                "zl_hist_accel_pct",
            )
            samples = [
                {
                    "datetime_utc": row["datetime_utc"],
                    **{
                        field: round(row[field], 6) if row[field] is not None else None
                        for field in fields
                    },
                }
                for row in rows[-args.count :]
            ]
            prompt = (
                "以下是已收盘的 1 分钟 K 线计算出的 MACD 特征，数值只反映历史数据。"
                "dif/dea/hist 已除以当前收盘价并乘 100，单位是百分比；z 为最近 100 根柱状图百分比的滚动 Z-Score；"
                "slope 和 accel 分别为柱状图百分比的一阶、二阶差分；zl 前缀使用 ZLEMA 价格平滑。"
                "请只做客观比较，指出普通 MACD 和零延迟版本是否一致、动量是否扩张或收缩、有哪些不确定性。"
                "不得预测下一根价格或给买卖指令。只返回 JSON 对象，字段 summary、observations、uncertainties。"
                f"数据：{json.dumps(samples, ensure_ascii=False)}"
            )
            commentary = ask_json(prompt, max_tokens=1536)
            print(
                json.dumps(
                    {
                        "computed_bar_count": len(samples),
                        "computed_features": samples,
                        "model_commentary_unverified": commentary,
                    },
                    ensure_ascii=True,
                    indent=2,
                )
            )
    except (OSError, ValueError, RuntimeError, ConnectionError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
