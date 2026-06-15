#!/bin/bash
echo -e "\033[0;32m=== 正在维护：币赢 (CoinW) 系统 ===\033[0m"

# 1. 精确清理：只杀 coinw 目录下的进程
sudo pkill -f "gunicorn -b 127.0.0.1:5002"
sudo pkill -f "position_supervisor_coinw.py"

# 2. 同步与激活
cd /home/coinw/coinw-hft-server
git pull origin main
source venv/bin/activate

# 3. 部署
nohup gunicorn -b 127.0.0.1:5002 app:app > gateway_coinw.log 2>&1 &
nohup python3 -u position_supervisor_coinw.py > supervisor_coinw.log 2>&1 &

echo -e "\033[0;32m✅ 币赢系统已在 5002 端口就绪\033[0m"
