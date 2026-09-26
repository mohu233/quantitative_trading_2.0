"""Project-local configuration; secrets remain outside version control."""

import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_config():
    config = {
        "mysql_host": "127.0.0.1",
        "mysql_port": 3306,
        "mysql_user": "root",
        "mysql_password": "",
        "mysql_database": "okx_market",
        "symbols": ["BTC-USDT", "ETH-USDT"],
        "poll_seconds": 5,
        "web_port": 8080,
    }
    path = Path(os.environ.get("QUANT_CONFIG", PROJECT_ROOT / ".local.json"))
    if path.exists():
        config.update(json.loads(path.read_text(encoding="utf-8")))
    if "QUANT_MYSQL_PASSWORD" in os.environ:
        config["mysql_password"] = os.environ["QUANT_MYSQL_PASSWORD"]
    if not config["symbols"] or config["poll_seconds"] <= 0:
        raise ValueError("symbols must be nonempty and poll_seconds must be positive")
    if not all(1 <= int(config[key]) <= 65535 for key in ("mysql_port", "web_port")):
        raise ValueError("Invalid MySQL or web port")
    return config
