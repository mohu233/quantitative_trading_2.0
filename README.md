# Quantitative Trading 2.0

## 开发目录

项目位于 Git 根目录 `E:\\OKX\\quantitative_trading_2.0`。

```text
quantitative_trading/  Python 包：行情、回测、指标、模型、MySQL 面板
  web/                 HTML 页面
    static/            独立 JavaScript 与 CSS
scripts/               后台启动与停止脚本
tests/                 离线单元测试
docs/                  项目计划书
data/                  示例 K 线与本机生成结果
models/                本地 GGUF（不上传），可提交的 Modelfile
config.example.json    无密码配置模板
pyproject.toml         依赖、包信息与命令入口
```

新机器首次配置：

```powershell
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item config.example.json .local.json
# 编辑 .local.json，填写本机 MySQL 密码
python -m unittest discover -s tests -v
```

当前机器原有的 `.local.json` 和 MySQL 数据均保留。Git 排除密码配置、日志、PID、虚拟环境、模型权重和生成的特征/成交 CSV；保留 `data/BTC-USDT-1m.csv` 作为离线测试样本。文件迁移后，运行命令统一使用 Python 包入口。

## 实时 MySQL 行情面板

浏览器打开 `http://127.0.0.1:8080`。启动程序会创建 MySQL 数据库 `okx_market`，包含 `candles` 和 `tickers` 两张表。连接地址、账号、密码和币种保存在本地 `.local.json`，该文件已加入 Git 忽略。

```powershell
python -m pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File .\scripts\start-dashboard.ps1
# 停止网页服务和采集程序
powershell -ExecutionPolicy Bypass -File .\scripts\stop-dashboard.ps1
```

默认采集 BTC-USDT、ETH-USDT 的 1 分钟行情和 24 小时 ticker，每 5 秒一轮。首次补历史，重启按最后收盘时间补数；重复 K 线按唯一键更新，已收盘记录不会被未收盘缓存覆盖。服务运行时持续写 MySQL，关闭服务或关机后采集停止，重新启动会补历史。网页每 5 秒刷新，展示行情、成交量、普通 MACD 与 ZLEMA 指标；未收盘 K 线不参与指标。

采集错误自动重试并显示在页面，详细日志位于 `logs/dashboard.log`。前台运行可使用 `python -m quantitative_trading.dashboard`。只监听本机地址，不需要交易所密钥，不执行交易。

当前版本先完成计划书中的“获取历史行情 → 本地回放 → 记录模拟成交”链路。程序只访问 OKX 公开行情接口，无需 API Key，不会调用交易或下单接口。

## 快速开始

需要 Python 3.10 或更新版本。抓取、指标和离线回测使用标准库；面板与模型 SDK 依赖由 `pyproject.toml` 管理。在项目目录运行：

```powershell
python -m quantitative_trading fetch --symbol BTC-USDT --days 1 --output data/BTC-USDT-1m.csv
python -m quantitative_trading backtest --input data/BTC-USDT-1m.csv --trades data/trades.csv
```

第一条命令从 OKX 的历史 K 线接口抓取最近 1 天的 1 分钟现货数据。`--days` 支持 1～30 天；抓取时使用 `after` 翻页，只保存 `confirm=1` 的已收盘 K 线。程序检查时间戳、OHLC 关系和每分钟连续性；如果数据不完整，报错且不覆盖 CSV。

CSV 的时间为 UTC。`timestamp_ms` 为交易所返回的毫秒时间戳，`volume` 是基础币成交量，`volume_quote` 是报价币（此处为 USDT）成交量。再次抓取会覆盖指定的输出文件，因此如需保留某个历史样本，请使用不同文件名。

第二条命令离线回放 CSV，输出收益、最大回撤、成交次数，并将逐笔模拟成交写入 `data/trades.csv`。可调整参数，例如：

```powershell
python -m quantitative_trading backtest --input data/BTC-USDT-1m.csv --fast 10 --slow 30 --initial-cash 100 --fee-bps 10 --slippage-bps 5 --trades data/trades-10-30.csv
```

`--initial-cash` 的单位是 USDT，不能直接把计划书里的“300 元人民币”填成 300；本阶段使用 100 USDT 作为示例模拟余额，不涉及真实资金。

## 模拟规则与局限

- 示例策略为 5/20 根收盘价简单移动平均线；在一根 K 线收盘后产生信号，并在**下一根 K 线开盘价**加上不利滑点后成交。
- 只模拟现货做多和空仓；买入使用全部模拟余额，卖出卖掉全部持仓。
- 每次成交按参数扣手续费，默认手续费 10 bps、滑点 5 bps。这些是可修改的示例值，并非已核实的个人账户费率或真实盘口滑点。
- 未模拟交易所最小下单额、数量精度、盘口深度、部分成交、限价挂单、资金费率或网络延迟。末尾未平仓仓位按最后收盘价估值，不强制平仓。
- 本版本用于验证数据和回测流程，不用于证明策略有效。进入后续阶段前仍需更长时间跨度、样本外验证和更真实的撮合模型。

## 数据来源

OKX 官方 [历史 K 线接口文档](https://www.okx.com/docs-v5/en/#order-book-trading-market-data-get-candlesticks-history)：`GET /api/v5/market/history-candles`，支持 `bar=1m`，单次最多 300 条。当前默认请求域名为 `https://app.okx.com`；如需使用 OKX 的其他可用官方域名，可通过 `--api-base` 指定。

运行 `python -m unittest discover -s tests -v` 可检查数据缺口拦截和“信号下一根 K 线成交”的行为。

## 本地 DeepSeek 模型

模型文件位于 `models/deepseek-r1-0528-qwen3-8b-q4_k_m.gguf`。GGUF 元数据标识为 DeepSeek-R1-0528-Qwen3，参数量 8.2B，量化格式 Q4_K_M。需要本机 Ollama 服务在 `127.0.0.1:11434` 运行。

首次注册或重新注册模型：

```powershell
ollama create deepseek-r1-local -f models/Modelfile.deepseek-r1
python -m pip install -r requirements.txt
```

如 `ollama.exe` 尚未加入 `PATH`，请使用其完整安装路径运行同一命令。

通过 Python Ollama SDK 运行两个短探针，或让模型描述 CSV 中最后 5 根已收盘 K 线：

```powershell
python -m quantitative_trading.llm probe
python -m quantitative_trading.llm candles --input data/BTC-USDT-1m.csv --count 5
```

`quantitative_trading/llm.py` 对回复进行 JSON 解析和基本格式检查。DeepSeek 模型会先生成思考内容，输出长度过短时可能没有最终回复；模型描述也可能有事实错误，不能直接作为交易信号。模拟盘的 SMA 与 MACD 示例规则均独立于模型回复。

## MACD 特征与 AI 输入

从已收盘 K 线生成普通 MACD 和 ZLEMA 版本的特征表：

```powershell
python -m quantitative_trading.indicators --input data/BTC-USDT-1m.csv --output data/BTC-USDT-1m-features.csv
python -m quantitative_trading.llm features --input data/BTC-USDT-1m.csv --count 3
python -m quantitative_trading backtest --strategy macd --input data/BTC-USDT-1m.csv --trades data/trades-macd.csv
```

默认参数为 `fast=12`、`slow=26`、`signal=9`、`z_window=100`，单位都是 **1 分钟 K 线根数**。特征定义如下：

- 普通 MACD：`DIF = EMA12(close) - EMA26(close)`；`DEA = EMA9(DIF)`；`Hist = DIF - DEA`。这里柱状图没有乘 2。
- ZLEMA 版本：先对收盘价计算 `ZLEMA12` 和 `ZLEMA26`，再以二者之差计算 DIF；信号线仍为普通 `EMA9(DIF)`。ZLEMA 使用 `lag = floor((period - 1) / 2)`，即调整值 `2 × close[t] - close[t-lag]`。EMA 以第一条观测值初始化，递推系数为 `2/(period+1)`。
- 归一化：DIF、DEA、Hist 均除以**当前已收盘 K 线**的 close，再乘 100，得到百分比特征。`zl_` 前缀表示 ZLEMA 版本。
- `hist_z`：对最近 100 根已收盘 K 线的 `hist_pct` 计算滚动 Z-Score，窗口包含当前 K 线，标准差使用总体标准差；标准差为零时留空。`zl_hist_z` 同理。
- `hist_slope_pct`、`hist_accel_pct`：分别为 `hist_pct[t] - hist_pct[t-1]` 和 `hist_pct[t] - 2×hist_pct[t-1] + hist_pct[t-2]`，ZLEMA 版本同理。它们是历史柱状图的差分，不是未来价格的导数。

前 `max(3×slow, z_window-1)` 行作为预热留空，默认前 99 行不用于策略或 AI。`quantitative_trading/llm.py features` 会同时打印代码算出的特征和**未经核实的模型解读**；若模型把时间点或指标说错，应以特征表为准。

`--strategy macd` 是可复现的演示规则：上一根收盘时普通与 ZLEMA 柱状图均大于零、且普通柱状图斜率为正，则下一根开盘买入；任一柱状图小于零，则下一根开盘卖出。Z-Score 和加速度目前仅作为模型输入，尚未进入下单规则；任何阈值都应先做样本外验证。该策略与 AI 解读没有执行连接。

在当前 1,440 根 BTC-USDT 数据上的一次演示回测中，MACD 策略计入示例手续费和滑点后收益为 **−16.89%**。这段数据仅有一天，不能用于评价策略长期表现；“零延迟提高 30%～50%”也不是本项目已证实的结论。
