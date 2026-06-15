#!/bin/bash
# 自动部署与全量自检脚本

echo "=== 🚀 开始全量系统部署与自检 ==="

# 1. 检查并重启信号网关 (Flask + Gunicorn)
if pgrep -f "gunicorn" > /dev/null; then
    echo "✅ 信号网关 (Gunicorn) 运行正常"
else
    echo "⚠️ 信号网关异常，正在重启..."
    pkill -f gunicorn
    nohup gunicorn -b 0.0.0.0:5002 app:app > gateway.log 2>&1 &
    sleep 2
fi

# 2. 检查 5002 端口是否开放
if netstat -tuln | grep -q ":5002 "; then
    echo "✅ 端口 5002 监听正常"
else
    echo "❌ 严重警告：端口 5002 未被监听！"
fi

# 3. 检查代码完整性 (Git 状态)
echo "--- 正在同步最新策略库 ---"
git fetch origin main
git reset --hard origin/main

# 4. 检查日志是否有严重错误 (大脑监控)
echo "--- 正在扫描大脑日志状态 ---"
if tail -n 20 gateway.log | grep -q "ERROR"; then
    echo "❌ 警告：日志中检测到错误！请查看 gateway.log"
else
    echo "✅ 大脑运行状态良好"
fi

echo "=== ✅ 自检完成，系统处于全自动作战状态 ==="
