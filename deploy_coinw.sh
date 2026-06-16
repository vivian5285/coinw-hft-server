#!/bin/bash
# ==============================================
# 币赢系统全域部署脚本 (V3.0 终极实战版)
# 作用: 强力进程清理、环境挂载、全域自检
# ==============================================

# 定义路径和端口
PROJECT_DIR="/home/coinw/coinw-hft-server"
PORT=5002
LOG_FILE="gateway_coinw.log"

# 定义颜色
GREEN='\033[1;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}=== 🚀 正在执行币赢(CoinW)系统终极部署与审计 ===${NC}"

# 1. 目录校验
cd $PROJECT_DIR || { echo -e "${RED}❌ 目录 $PROJECT_DIR 不存在，请检查！${NC}"; exit 1; }

# 2. 强力清理进程
echo -e "${YELLOW}[1/4] 正在执行端口清理与残留进程剔除...${NC}"
# 杀掉所有监听 5002 端口的进程 (防死锁)
sudo fuser -k -n tcp $PORT >/dev/null 2>&1
# 杀掉残留的 gunicorn 进程
sudo pkill -f "gunicorn -b 127.0.0.1:$PORT" >/dev/null 2>&1
# 可选：如果之前有独立的监控脚本，也一并杀掉
# sudo pkill -f "position_supervisor_coinw.py" >/dev/null 2>&1
sleep 2

# 3. 日志清理
echo -e "${YELLOW}[2/4] 正在清理历史战报日志...${NC}"
rm -f $LOG_FILE

# 4. 激活环境与拉起网关
echo -e "${YELLOW}[3/4] 激活外层专属虚拟环境并启动守护进程...${NC}"
source venv/bin/activate
pip install -r requirements.txt --quiet  # 确保依赖完整 (如 python-dotenv)

# 后台拉起信号网关
echo -e "${YELLOW}[4/4] 启动信号网关 (端口 $PORT)...${NC}"
nohup gunicorn -b 127.0.0.1:$PORT app:app > $LOG_FILE 2>&1 &

# 5. 等待预热与自检
echo -e "${YELLOW}=== ⏳ 等待引擎预热 (3秒) ===${NC}"
sleep 3

if netstat -tuln | grep -q ":$PORT "; then
    echo -e "${GREEN}=== ✅ 币赢(CoinW)独立引擎启动完成 (Port $PORT) ===${NC}"
    echo -e "你可以通过 \`tail -f $LOG_FILE\` 查看实盘战报。"
else
    echo -e "${RED}❌ 启动失败！端口 $PORT 未监听，请查看 $LOG_FILE 排查错误。${NC}"
fi
