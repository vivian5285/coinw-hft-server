#!/bin/bash
# 存放路径: /home/coinw/coinw-hft-server/
LOG_FILE="supervisor_coinw.log"
PORT=5002

echo -e "\033[0;32m=== 正在全量部署：币赢系统 ===\033[0m"

# 1. 强力清理：只清理当前项目相关进程
sudo pkill -f "gunicorn -b 127.0.0.1:$PORT"
sudo pkill -f "position_supervisor_coinw.py"
sleep 2

# 2. 同步代码
git fetch --all && git reset --hard origin/main

# 3. 激活环境并启动
source venv/bin/activate
nohup gunicorn -b 127.0.0.1:$PORT app:app > gateway_coinw.log 2>&1 &
nohup python3 -u position_supervisor_coinw.py > $LOG_FILE 2>&1 &

# 4. 全域自检 (审计层)
sleep 3
if netstat -tuln | grep -q ":$PORT "; then
    echo -e "\033[0;32m✅ 币赢端口 $PORT 就绪\033[0m"
else
    echo -e "\033[0;31m❌ 币赢端口 $PORT 启动失败！请检查日志\033[0m"
fi

if pgrep -f "position_supervisor_coinw.py" > /dev/null; then
    echo -e "\033[0;32m✅ 币赢执行大脑运行中\033[0m"
else
    echo -e "\033[0;31m❌ 币赢大脑启动异常\033[0m"
fi
