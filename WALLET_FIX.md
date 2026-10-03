# Wallet 修复更新

49 项测试通过。只修改兼容性和风险检查，不修改测试仓位、信号或开启正式比赛执行。

1. Mac 下载 ZIP 到 Downloads，然后执行：

```bash
unzip -o ~/Downloads/roostoo-quant-bot-v2-wallet-fix.zip -d ~/Desktop
cd ~/Desktop/roostoo-quant-bot
source .venv/bin/activate
python -m unittest discover -s tests -v
git add quant tests RUN_V2.md V2_VALIDATION.md WALLET_FIX.md
git commit -m "Normalize SpotWallet and validate reserved funds"
git push origin master
```

2. AWS：如果 dry run 正在前台运行，先 Ctrl+C 停止。若已从 tmux detach，先 `tmux attach -t roostoo-dry` 再 Ctrl+C。

```bash
cd /home/ssm-user/roostoo-quant-bot
git stash push -m "Preserve AWS temporary wallet patch" -- quant/live.py
git pull --ff-only origin master
source .venv/bin/activate
python -m unittest discover -s tests -v
bash scripts/run_dry.sh --once
```

stash 保留临时修改，不删除。不要 stash pop：新源码已包含完整修复。runtime/ 中的凭据、账户状态和订单记录不受该命令影响。如果 pull 或测试失败，停下并反馈。

3. 只读验证正常后可回到 tmux 内执行 `bash scripts/run_dry.sh`。测试执行见 RUN_V2.md，仍必须使用 For Testing。当前修复没有提交订单，也没有启用比赛账户。开赛时间的时区仍待主办方确认。
