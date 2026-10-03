# 第二版运行指南（Mac 更新 → AWS 测试）

这版是 **测试账户用的 long/cash 自动执行程序**，默认只读。不支持比赛账户上线、做空或限价策略。保留第一版全部 research/backtest 命令。

## 1. 更新 Mac 项目

解压 `roostoo-quant-bot-v2-wallet-fix.zip`。如果 ZIP 保存在 Mac 的 Downloads，可在 VS Code 终端执行 `unzip -o ~/Downloads/roostoo-quant-bot-v2-wallet-fix.zip -d ~/Desktop`。包内只包含源码、测试和说明，不包含 `.git` 或 `.venv`。也可手动将其中 `roostoo-quant-bot/` 里的文件覆盖复制到已有 `/Users/mac/Desktop/roostoo-quant-bot/`，合并 quant、tests、scripts 文件夹。**不要删除整个旧项目，也不要删除 `.git`、`.venv`。**更新包没有密钥、运行状态、历史数据或 `.git`。

Mac 的 VS Code 终端：

```bash
cd /Users/mac/Desktop/roostoo-quant-bot
source .venv/bin/activate
python -m unittest discover -s tests -v
```

应有 49 项通过。若某一步失败先停止。成功后提交本次新增及修改文件：

```bash
git add .gitignore quant tests scripts RUN_V2.md V2_VALIDATION.md README.md
git status --short
git commit -m "Add test-account live runner with durable order recovery and dry run"
git push origin master
```

`git status` 只应包括源码、测试、说明文件；runtime、.env 和 logs 被忽略。Mac 仓库已知使用 master 分支。不要把 credentials.json 拷贝到源码文件夹外再上传。

## 2. AWS 更新

以下在 AWS Session Manager 浏览器终端执行：

```bash
cd /home/ssm-user/roostoo-quant-bot
git pull --ff-only origin master
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

若 pull 说本地有修改，不要使用 reset --hard；把报错发给助手，保留现有文件。

## 3. 在 AWS 保存测试凭据

```bash
python -m quant.credentials
```

依次粘贴 **For Testing** key、secret（屏幕不会显示），然后确认输入 `TEST`。只在 AWS 浏览器终端输入。保存到本机 `runtime/test/credentials.json`，0600 权限，Git 忽略。程序会读取此文件，不必反复 export，也不依赖 tmux 继承旧终端的环境变量。这个 JSON 是明文凭据文件，权限限制不等于加密，不要分享或提交。

**TEST 标签是你的声明，API 文档没有可用于验证“测试账户/比赛账户”身份的字段。程序无法识别误贴进去的比赛密钥，因此务必选择 For Testing。**profile 参数会整体覆盖当前 shell 的 key/secret/mode，避免混用两个来源。

## 4. 先执行一次只读演练

```bash
bash scripts/run_dry.sh --once
```

成功时打印 `mode: DRY_RUN`、NAV、建议订单。`orders: []` 可以是正常的无信号/小额变化。不会调用 place_order/cancel_order。日志位于 `runtime/test/events.jsonl`；里面有信号、目标权重、净值、拟交易及停机原因类型。不要分享凭据文件。

第一次私有账户读写端到端还需要由你的测试账户完成；交付前没有使用任何真实密钥或下任何交易单。

## 5. 持续只读演练

```bash
tmux new -s roostoo-dry
cd /home/ssm-user/roostoo-quant-bot
bash scripts/run_dry.sh
```

每 300 秒读一轮；最低轮询间隔 60 秒。退出显示但保持后台运行：按 Ctrl+B，松开，再按 D。重新进入：

```bash
tmux attach -t roostoo-dry
```

停止程序：在该 tmux 会话里按 Ctrl+C。不要同时运行两份 runner。程序给同账户设置主机级锁（存于用户 home），即使使用不同 state-dir 也会阻止第二份运行。它不能阻止另一台电脑上的 bot：实际执行只放在一台 EC2 上。

## 6. 测试账户自动执行

只读输出正常后，先停止只读进程（Ctrl+C），然后创建测试会话：

```bash
tmux new -s roostoo-test
cd /home/ssm-user/roostoo-quant-bot
bash scripts/run_test.sh
```

**这个命令会对测试账户真实提交模拟 MARKET 订单。**不是正式比赛账户，也不是 dry run。每小时处理一次已收盘信号（当前实现以 UTC :00 开盘的 15min bar 为再平衡 bar，通常在 :15 之后首次轮询执行）。没有信号不会为凑交易次数硬下单。

也可只运行一轮：

```bash
bash scripts/run_test.sh --once
```

一轮不保证有成交：可能没有信号，也可能不是再平衡窗口。不要为验证而绕过信号或缩短轮询。确认订单应查看 events.jsonl 中的 `order_reconciled` 及服务器快照，不把 submit 返回就直接视为成交。

## 风控、对账与停止

- 资产固定 BTC、ETH、SOL；15min 已收盘 K 线，约 499 根历史预热。Binance 数据只读；订单和账户走 Roostoo。
- 测试单币目标 min(0.1% NAV, $100)，总目标上限 0.3% NAV / $300；单笔估算金额最多 $99，为 $100 上限预留余量。market 成交价格变化可能使实际成交额超过估算，不能承诺硬上限。
- 目标未必用满；目标账户敞口会随行情漂移。保留至少 30% 现金预算；交易变化不足 $10–$20 跳过。使用市场费 0.1% 和额外预算余量，不做限价撮合。
- 动态读取 CanTrade、AmountPrecision、MiniOrder。订单量向下取整；最小金额采用严格大于 MiniOrder。
- spread >0.5%、Roostoo/Binance 最新已收盘价偏差 >3%、行情超过15秒、缺失 K 线、账户存在空仓、锁定余额、挂单或宇宙外资产都会停止。
- 既有持仓超过测试范围会停止，不擅自大额卖掉原有仓位。这个模块需要干净、没有其他 bot 并行交易的测试账户。
- NAV 高水位持久化；下跌 6% 永久阻止新单。**这版触发回撤后停止，不自动平仓**，所以已有仓位仍有价格风险；不是组合止损成交保证。
- 提交前原子保存 intent，收到 OrderID 后再保存并查询该 ID。确认 FILLED/CANCELED 才结束 intent。已成交数量、均价及手续费写入审计日志。
- 下单超时/断网/崩溃后重启先查单；有 OrderID 就查该单，没有 ID 则列出可能匹配的历史订单并继续停机。没有交易所 clientOrderId，无法证明一个历史匹配就是那次提交，因此绝不自动重发。
- 所有未知错误停止，不在网络失败后持续发新单；tmux 不会自动重启崩溃进程，也不会在 EC2 重启后自动启动。重新运行同一命令会读取原有状态恢复。不要删除 runtime/state.json 或改 state-dir 来绕过未确认订单。
- 若确认本程序订单停留 PENDING，可停止所有 runner 后执行：

```bash
python -m quant.live --profile runtime/test/credentials.json --cancel-known
```

只取消 state 中有明确 OrderID 的本程序订单，不提供 cancel-all；未知提交没有 ID 时不取消。取消请求超时也会保留状态，不反复提交。

## 范围与下一阶段

这次完善执行基础设施，没有声称 alpha 提升。V1 全月回测 +4.00% 不能当作本版测试仓位的收益；V1 样本外不稳定的问题仍存在。测试账户实盘尚待验证，比赛自动执行、活跃交易日监控、正式风险预算、多月低换手研究及重启自动服务还需后续实现。默认凭据/测试模式不能通过改一个标签就视作正式比赛版本。

官方参考：
- https://github.com/roostoo/Roostoo-API-Documents
- https://developers.binance.com/docs/binance-spot-api-docs/faqs/market_data_only
- https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints
