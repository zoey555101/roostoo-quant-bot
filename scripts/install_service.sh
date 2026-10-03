#!/usr/bin/env bash
# Creates an inactive service. Starting it is an explicit, separate command.
set -euo pipefail
project_dir="$(cd "$(dirname "$0")/.." && pwd)"
run_user="$(id -un)"
if [[ "$project_dir" != /home/ssm-user/roostoo-quant-bot || "$run_user" != ssm-user ]]; then
  echo "This installer requires /home/ssm-user/roostoo-quant-bot and user ssm-user"
  exit 1
fi
sudo tee /etc/systemd/system/roostoo-competition.service >/dev/null <<'UNIT'
[Unit]
Description=Roostoo competition bot with exchange-time gate
Wants=network-online.target
After=network-online.target
[Service]
Type=simple
User=ssm-user
WorkingDirectory=/home/ssm-user/roostoo-quant-bot
ExecStart=/home/ssm-user/roostoo-quant-bot/.venv/bin/python -u -m quant.competition --execute
# Operator review on unknown API outcomes; never blindly restart fatal errors.
Restart=no
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
echo 'Service installed but NOT started. Start only after test verification and actual-account read-only check.'
