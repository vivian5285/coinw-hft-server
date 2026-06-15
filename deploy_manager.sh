#!/bin/bash

# 定义颜色，方便查看状态
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}=== 🚀 正在执行全域量化系统维护 ===${NC}"

# 1. 清理旧进程 (彻底释放端口)
echo "--- 正在清理旧进程 ---"
pkill -f gunicorn
pkill -f python3
sleep 2

# 2. 清理临时冗余数据
echo "--- 正在清理旧日志与缓存 ---"
rm -f *.log
# 可选：如果代码有缓存文件，也可以在此添加清理命令

# 3. 同步最新代码 (如果使用了 Git)
echo "--- 正在同步代码库 ---"
git pull origin main

# 4. 重新部署系统
echo "--- 正在拉起信号网关 (Flask) ---"
nohup gunicorn -b 0.0.0.0:5002 app:app > gateway.log 2>&1 &

# 5. 启动执行大脑 (确保以后台方式运行)
echo "--- 正在激活交易执行大脑 ---"
nohup python3 -u position_supervisor.py > supervisor.log 2>&1 &

# 6. 全域健康自检 (审计层)
echo "--- 开始系统健康审计 ---"
sleep 3

# 检查端口
if netstat -tuln | grep -q ":5002 "; then
    echo -e "${GREEN}✅ 端口 5002 已就绪${NC}"
else
    echo -e "${RED}❌ 警告：端口 5002 未启动，请检查 app.py 错误日志${NC}"
fi

# 检查进程
if pgrep -f "gunicorn" > /dev/null && pgrep -f "position_supervisor" > /dev/null; then
    echo -e "${GREEN}✅ 核心模块运行正常${NC}"
else
    echo -e "${RED}❌ 警告：部分进程未能成功启动${NC}"
fi

echo -e "${GREEN}=== ✅ 全域部署完成，系统已进入全自动交易模式 ===${NC}"
echo "输入 tail -f gateway.log 或 supervisor.log 查看运行状态。"
0 * * * * /root/deploy_manager.sh >> /root/system_cron.log 2>&1
