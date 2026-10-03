# V3 比赛部署版：按顺序执行

这份代码补齐正式账户运行，沿用当前 momentum / EMA / inverse-volatility 策略。不是新的盈利验证，也不是已在你的正式账户完成部署。68 项自动测试通过；你的真实账户验证需要在 AWS 完成。

开赛：**2026 年 10 月 4 日 08:00 香港时间 = 2026-10-04 00:00 UTC**。每笔下单前检查 Roostoo 校时后的时间。正式程序可提前启动等待，开赛前不提交交易。默认信号再平衡时点第一次约为香港 08:15，且必须有有效信号才下单。

## 1. Mac：覆盖原项目并推送 GitHub

把更新包下载到 Desktop（桌面），名称保持 `roostoo-quant-bot-v3-update.zip`。不要再新建 `roostoo-quant-bot 3` 等副本；使用已有项目路径。

在 Mac VS Code 终端逐行执行：

```bash
cd /Users/mac/Desktop/roostoo-quant-bot
git status --short
```

如果还有你自己的未提交代码，先提交或备份再覆盖。ZIP 不含 `.git`、密钥、runtime、历史数据，解压会覆盖同名代码文件。

```bash
unzip -o /Users/mac/Desktop/roostoo-quant-bot-v3-update.zip -d /Users/mac/Desktop
cd /Users/mac/Desktop/roostoo-quant-bot
source .venv/bin/activate
python -m unittest discover -s tests -q
git add .gitignore quant tests scripts competition.json README.md RUN_V3.md V3_VALIDATION.md
git commit -m "Add gated competition runner and durable risk exits"
git push --ipv4 origin master
```

应显示 `Ran 68 tests ... OK`。如果 ZIP 被下载到 Downloads，把命令里的 ZIP 路径改为你实际位置。不要点击编辑器三角按钮直接运行 `quant/live.py`，应使用本文模块命令或脚本。

## 2. AWS：停止旧测试进程，再更新代码

如果每五分钟显示一行输出，按 **Ctrl+C** 停止；看到 `(.venv) ...$` 提示符后再粘贴命令。如果程序在 tmux 内，先 `tmux ls` 查看并进入原测试会话，按 Ctrl+C；不要新开另一份测试执行进程。

以下命令只在 AWS Session Manager 终端执行：

```bash
cd /home/ssm-user/roostoo-quant-bot
git status --short
```

如显示有本地源码修改，先保留：

```bash
git stash push -m "Preserve EC2 source before V3 update"
```

然后：

```bash
git pull --ff-only origin master
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -q
python -m quant.status
```

不要删除 `runtime/` 或旧 state 文件，它们保存账户绑定和订单恢复状态。新代码保留旧测试账户凭据。

## 3. AWS：真实测试成交验证

保持测试账户使用主办方 **For Testing** key/secret。

先在停止测试循环后执行：

```bash
python -m quant.verify_test
```

只有显示 `"verification": "PASSED"` 才完成这一步。验证器会重新向服务器查询日志里的一笔 FILLED 订单，并检查没有挂单、空头、锁定资金和未确认下单意图。验证只读，不会创建交易。

如果显示 `No confirmed test fill yet`，说明目前的 `orders: []` 确实尚未验证真实成交。运行测试程序：

```bash
bash scripts/run_test.sh
```

它只在已有策略产生信号时提交测试订单，单筆估算不超过 $99。`orders` 中出现计划订单仍不等于服务器成交。等到确认成交后，Ctrl+C 停止，再执行：

```bash
python -m quant.status
python -m quant.verify_test
```

如一直没有信号，验证仍未完成；把不含密钥的状态输出发来排查。不要为绕过验证删除状态、手改 verification 文件或用正式账户做这一步。正式执行代码会拒绝没有成功验证记录的首次启动。首次启动要求验证在 24 小时内，之后同一账户和配置的恢复保留验证记录。

## 4. AWS：保存 actual credentials，只读核对

可以现在配置 **For Actual Competition** key/secret；保存凭据本身不下单。

```bash
python -m quant.credentials --competition
```

在 `COMPETITION API key:` 提示后粘贴 actual key，回车；在 secret 提示后粘贴 actual secret，回车。隐藏输入看不见字符是正常的。最后输入大写 `COMPETITION` 确认。

```bash
bash scripts/run_competition_dry.sh --once
```

开赛前应显示 `COMPETITION_DRY_RUN`、`WAITING_START`，余额应与主办方正式账户一致。`orders` 是计划，尚未提交。程序拒绝测试与正式 profile 使用相同 key；凭据标签由你确认，API key 本身不会自动告诉程序属于哪一组。

遇到报错先处理，不继续启动服务。不要把 credentials.json、私有 snapshot 或 secret 发给别人。

## 5. AWS：验证通过后，启动正式后台服务

**完成第 3 步 PASSED 和第 4 步只读检查后执行。**

```bash
bash scripts/install_service.sh
sudo systemctl enable --now roostoo-competition
sudo systemctl status roostoo-competition --no-pager
sudo journalctl -u roostoo-competition -n 30 --no-pager
```

安装脚本本身不启动；`enable --now` 启动正式执行服务并设置开机启动。开赛前显示 `COMPETITION_EXECUTE` / `WAITING_START` 属于正常等待：执行权限已开启，但时间门禁禁止下单。

服务器没有停止，服务正常运行时，你可以关闭浏览器和电脑，不需要同时开 tmux 正式程序。不要同时启动 `run_competition.sh`；同账户进程锁会拒绝第二份程序。

正式启动命令会报缺少测试验证时，返回第 3 步完成，不要改掉门禁。服务采用 `Restart=no`：关键错误停机后不会反复重启、反复下单。

## 6. 开赛之后

开赛后服务自动检查信号，不需要重新输密钥或手动买币。最早常规再平衡约 08:15 香港时间；无信号、差额不足或当天同一轮已处理时，可能仍然没有订单。

首次检查：

```bash
sudo systemctl status roostoo-competition --no-pager
sudo journalctl -u roostoo-competition -n 50 --no-pager
python -m quant.status --competition
```

`READY` 表示已过时间门禁；`confirmed_fills` 和 `order_reconciled` 的 FILLED 才证明服务器确认成交。留意净值、`halted`、未确认意图和活跃日记录。之后每天查看一次服务和成交状态，比赛至少 8 个活跃交易日不能靠当前策略自动保证。

## 7. 风控和停机

默认比赛参数：BTC/ETH/SOL 现货 long/cash，单币目标 5%，合计目标 15%，每笔估算最多 $2,000，组合高水位回撤 3% 触发持久卖出退出，每五分钟检查。目标与估算不是成交后硬限额；价格漂移、滑点、手续费、API 中断可导致偏离和超出回撤阈值。该参数未单独完成实盘或跨月样本外收益验证。

要求停止新买入并逐轮减仓：

```bash
touch runtime/competition/STOP
```

下一个正常轮次锁定 `halted`，开赛后只卖不买，按 $2,000 估算分批退出，受 API 和交易所最小订单限制，可能剩零碎仓位。风险退出不依赖 Binance 信号接口，但仍需 Roostoo 新行情、余额和订单查询正常。删 STOP 不会自动解除 state 中的风控锁定。

要求立即停止进程：

```bash
sudo systemctl stop roostoo-competition
```

这会停止运行，**不会自动清仓**。如果恰好正在下单，保留 state 并核查服务器订单，不要重置或重复提交。

发生 `Stopped safely` 后先看 journal 和状态，保留全部 runtime。未知订单结果不会自动重试。已知 OrderID 在下一次人工重启时先对账；未知 OrderID 会持续阻止新下单，需人工核查。

比赛结束时间尚未写入门禁，程序不会自动在 Oct 17 某个未确认时间停止；按主办方确认的结束时刻处理持仓并停用：

```bash
sudo systemctl disable --now roostoo-competition
```

`STOP` 是减仓请求，`systemctl stop` 是停止进程，两者用途不同。
