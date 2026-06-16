#!/bin/bash
# deploy_coinw.sh（最终修正版 - 适配 ~/venv）

set -e

PROJECT_DIR="/home/coinw/coinw-hft-server"
VENV_PATH="/home/coinw/venv"
PORT=5002
LOG_DIR="$PROJECT_DIR/logs"

echo -e "\033[1;36m=== 🚀 开始部署币赢系统 (Port: $PORT) ===\033[0m"

cd $PROJECT_DIR || { echo "❌ 项目目录不存在"; exit 1; }

# 1. 清理旧进程
echo "[1/6] 正在清理旧进程..."
pkill -f "gunicorn -b 127.0.0.1:$PORT" || true
pkill -f "position_supervisor_coinw.py" || true
sleep 2

# 2. 拉取最新代码
echo "[2/6] 正在同步最新代码..."
git fetch --all
git reset --hard origin/main

# 3. 激活虚拟环境
echo "[3/6] 正在激活虚拟环境..."
if [ ! -f "$VENV_PATH/bin/activate" ]; then
    echo "❌ 虚拟环境不存在: $VENV_PATH"
    exit 1
fi
source "$VENV_PATH/bin/activate"

# 4. 安装依赖
echo "[4/6] 正在安装依赖..."
pip install -r requirements.txt --quiet

# 5. 创建日志目录并启动服务
echo "[5/6] 正在创建日志目录并启动服务..."
mkdir -p $LOG_DIR

# 启动 Gunicorn
nohup gunicorn -b 127.0.0.1:$PORT \
    --workers 2 \
    --timeout 120 \
    --access-logfile "$LOG_DIR/gunicorn_access.log" \
    --error-logfile "$LOG_DIR/gateway_coinw.log" \
    app:app > /dev/null 2>&1 &

# 启动交易大脑
nohup python3 -u position_supervisor_coinw.py > "$LOG_DIR/supervisor_coinw.log" 2>&1 &

sleep 3

# 6. 健康检查
echo "[6/6] 正在进行健康检查..."

if netstat -tuln | grep -q ":$PORT "; then
    echo "✅ 端口 $PORT 监听正常"
else
    echo "❌ 端口 $PORT 未监听，请检查日志"
    exit 1
fi

if pgrep -f "position_supervisor_coinw.py" > /dev/null; then
    echo "✅ 交易大脑运行中"
else
    echo "❌ 交易大脑未启动，请检查 $LOG_DIR/supervisor_coinw.log"
    exit 1
fi

echo -e "\033[1;32m=== ✅ 币赢系统部署完成 ===\033[0m"
echo ""
echo "常用查看命令："
echo "  tail -f $LOG_DIR/supervisor_coinw.log"
echo "  tail -f $LOG_DIR/gateway_coinw.log"
echo "  curl http://127.0.0.1:$PORT/health"
echo ""
