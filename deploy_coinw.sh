#!/bin/bash

PORT=5002
echo "=== 正在执行币赢(CoinW)系统部署与审计 ==="

# 1. 强力清理旧进程与端口占用
echo "[1/4] 正在执行端口清理与残留进程剔除..."
fuser -k $PORT/tcp 2>/dev/null
pkill -f "gunicorn.*5002"
pkill -f "position_supervisor_coinw.py"
sleep 2

# 2. 激活专属虚拟环境
echo "[2/4] 激活虚拟环境..."
source venv/bin/activate

# 3. 【核心修复】强制将 .env 注入全局环境变量，彻底根治 API 找不到的问题
echo "[3/4] 挂载环境密钥凭证..."
export $(grep -v '^#' .env | xargs)

# 4. 启动网关守护进程
echo "[4/4] 启动守护进程 (端口 $PORT)..."
# 注意：使用 app:app 前提是你的入口文件叫 app.py
nohup gunicorn -b 127.0.0.1:$PORT --workers 2 --timeout 120 app:app > logs/gateway_coinw.log 2>&1 &

echo "=== ✅ 币赢(CoinW)独立引擎启动完成 (Port $PORT) ==="
