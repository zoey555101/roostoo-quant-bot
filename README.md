# Roostoo Quant Bot — Competition Deployment V3

正式部署请先阅读 [RUN_V3.md](RUN_V3.md)，验证范围见 [V3_VALIDATION.md](V3_VALIDATION.md)。正式执行默认关闭，必须通过独立测试成交验证和开赛时间门禁。

第二版实时测试账户运行请先阅读 [RUN_V2.md](RUN_V2.md)，默认只读，测试执行需明确开启。以下为保留的第一版研究说明。

Python 3.11+。默认 long/cash，不提交交易。第一版实现数据→信号→资金账本回测→时间顺序验证，以及 Roostoo 只读行情/账户/订单快照。

## 立即运行

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m quant demo
```

Demo 自动生成合成数据和三折验证报告，仅验证代码流程，不能证明策略有效。

## 真实历史数据

```bash
python -m quant download --symbols BTCUSDT ETHUSDT SOLUSDT --start 2026-08-01 --end 2026-08-31 --out data/august
python -m quant backtest --data data/august --out reports/august
python -m quant validate --data data/august --out reports/august_walk_forward
```

日期范围包括起止两天，UTC。完整月份使用 monthly archive，其他范围使用 daily archive；尚未发布的归档会报错，不会静默用合成数据代替。Binance 月数据通常在下月第一个周一发布，最近几天可用 daily 路径。所有 ZIP 都验证官方 SHA256；兼容毫秒和微秒。统一 CSV：`timestamp,open,high,low,close,volume`，timestamp 为 UTC K 线开盘时间。不同资产必须严格对齐；缺口、重复、未完成 K 线会报错。

## 策略及账本

- 用 24h momentum 排名，EMA20 > EMA50 且动量为正才入选；前 3 个资产按 inverse realized volatility 分配。
- 单币目标上限 15%，总目标上限 70%，裁剪剩余资金保留现金。3 个币最多分配 45%；70% 是上限，不是必须用满。
- 15min K 线，每 4 根（1h）再平衡；权重差低于 2% NAV 跳过，以减少换手。
- 收盘信号下一根开盘成交，市场费 10bps，每边滑点 5bps。先卖后买，现金不足限制买量；持仓数量在两次再平衡之间保持不变。
- 回撤 6% 触发永久停机：开盘发现则当期开盘卖出；收盘发现则下一开盘卖出。跳空和手续费意味着真实损失可能超过 6%。停机后不自动重新入场。
- 单币/总敞口是**目标**约束，价格漂移和小额交易过滤可能使实际权重偏离；没有声称严格逐时限仓。

最大回撤只采样每根 K 线 open/close，不能代表 intrabar 最坏跌幅。

输出：`equity.csv` 净值/现金/敞口/换手/停机状态，`trades.csv` 成交账本，`metrics.json` 参数及指标。

## 时间验证和评分

`validate` 排除预热区间，采用 expanding window：只用过去区间从 12 个参数组合选择，再测试下一连续区间，共 3 折。选择指标是净收益 − 2 × |最大回撤|，并非直接挑整个历史的最佳参数。每折从独立现金账户开始，所以不能把各折 NAV 直接当作连续实盘曲线。有限网格搜索仍可能过拟合，后续需要跨月/跨行情验证。

Sharpe：UTC 日收益均值/样本标准差 × sqrt(365)，无风险利率 0。Sortino：均值/所有日收益中负收益平方均值的平方根 × sqrt(365)，目标收益 0。Calmar 同时报告年化收益/最大回撤和期间收益/最大回撤；短区间年化非常不稳定。零波动/零回撤等无定义比率输出 null，不制造巨大评分。`research_composite` 使用 0.4 Sortino + 0.3 Sharpe + 0.3 年化 Calmar，仅用于研究：主办方采样/年化口径未确认，不能视作官方成绩。第一天和最后一天可能包含不足一天的收益。

## Roostoo 只读连通性

```bash
python -m quant snapshot
# 仅在本地 shell 设置真实凭据，不提交到 Git，也不用发给助手。
export ROOSTOO_API_KEY='your-local-key'
export ROOSTOO_SECRET_KEY='your-local-secret'
python -m quant snapshot --private
```

.env.example 仅为变量名称模板；程序读取 shell environment，不自动加载 .env。快照权限 0600；私有订单历史分页到最多 10000 条。签名按官方原始参数字符串（pair 中的 `/` 保留）排序，HMAC-SHA256，POST 使用 form body；通过 serverTime 校时。本段说明第一版 snapshot 路径；V2/V3 的执行入口、授权和验证要求见上方运行文档。

## 已确认规则与待完成项

上传规则截图：14 天交易期 Oct 4–17；至少 8 个 active trading days；$100000 模拟本金；spot 1x long/short、无杠杆；market 0.1%、limit 0.05%；禁止 HFT、market-making、arbitrage；要求自动执行证据及可追溯 commit。截图未显示年份/每日最低交易数量/评分年化细节，需核对主办方 FAQ。不得为了凑活跃日做无信号交易；当前策略可能不满足活跃日要求。

V2/V3 已实现实时轮询、订单持久化与恢复、余额规范化、测试账户与比赛账户隔离，以及正式比赛时间门禁和后台服务脚本。用户侧部署与真实成交验证按 RUN_V3 执行；不支持做空或限价撮合。公开 API 的 /v6 short endpoints 与普通现货 SELL 不同。

历史回测采用 Binance USDT 价格，Roostoo USD 账户价格、实际流动性、成交机制和费用可能不同；尚未加入最低订单额/数量精度/容量和延迟模型。回测末尾持仓按 close 标记，没有强制平仓，因此末尾没有额外平仓费用。固定交易宇宙存在选择偏差。任何回测结果都不保证比赛表现。

## 官方来源

- https://github.com/roostoo/Roostoo-API-Documents
- https://github.com/binance/binance-public-data
- https://data.binance.vision/
- FAQ（公开抓取未成功）：https://roostoo.notion.site/Roostoo-Quant-Trading-Hackathon-Official-FAQ-313ba22fed798042bab7c93c609d004e
