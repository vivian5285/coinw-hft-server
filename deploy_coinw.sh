#!/bin/bash
# CoinW单系统部署脚本

set -e

echo "=== CoinW单系统部署 ==="
echo "版本: v16.22.1-coinw-init"
echo ""

# 检查环境变量
if [ -z "$COINW_API_KEY" ]; then
    echo "请设置 COINW_API_KEY"
    exit 1
fi

if [ -z "$COINW_API_SECRET" ]; then
    echo "请设置 COINW_API_SECRET"
    exit 1
fi

# 安装依赖
echo "安装依赖..."
pip install -r requirements.txt

# 静态检查
echo "运行静态检查..."
python3 check_vps_logic.py

# 重启服务
echo "重启服务..."
sudo systemctl restart coinw-engine.service

# 检查状态
echo "检查服务状态..."
sudo systemctl status coinw-engine.service

echo ""
echo "部署完成!"
echo "Webhook: http://$(hostname -I | awk '{print $1}'):5004/webhook"
echo "Console: http://$(hostname -I | awk '{print $1}'):5004/console"
