#!/usr/bin/env bash
# 部署安全重启：轮询 /health 的 deploy_safe 字段，确认没有品种的pipeline
# 处于IDLE/MONITORING/FAILED以外的"处理中"阶段才重启，避免撞上"市价单
# 已成交但仓位查询/防线绑定尚未走完"的窗口——那个窗口内重启会把仓位
# 打成孤儿仓，靠接管兜底而非正常TV关联流程。
# 对齐 binance f162ede（binance 2026-08-10 实盘 BNBUSDT 开仓中途被部署
# 重启命中过一次，接管兜住了但走的是应急通道，故加这道显式的可轮询
# 安全阀）。
#
# 用法: ./deploy_safe_restart.sh
set -uo pipefail

PORT=5002
SERVICE=coinw-engine
MAX_WAIT_SEC=90
POLL_INTERVAL=3

wait_deploy_safe() {
    local port="$1"
    local waited=0
    while [ "$waited" -lt "$MAX_WAIT_SEC" ]; do
        local body safe
        body="$(curl -sf --max-time 3 "http://127.0.0.1:${port}/health" 2>/dev/null || echo "")"
        if [ -z "$body" ]; then
            echo "  端口 ${port} /health 无响应（可能尚未启动），视为安全跳过"
            return 0
        fi
        safe="$(echo "$body" | grep -o '"deploy_safe": *true' || true)"
        if [ -n "$safe" ]; then
            echo "  端口 ${port} deploy_safe=true，可以重启"
            return 0
        fi
        echo "  端口 ${port} 仍有品种pipeline处理中，等待 ${waited}/${MAX_WAIT_SEC}s..."
        sleep "$POLL_INTERVAL"
        waited=$((waited + POLL_INTERVAL))
    done
    echo "  端口 ${port} 等待超时(${MAX_WAIT_SEC}s)仍不安全，继续重启（避免无限卡死，请人工确认无异常）"
    return 1
}

echo "=== 部署安全重启：检查pipeline处理状态 ==="
wait_deploy_safe "$PORT"

echo ""
echo "=== 检查完毕，执行重启 ==="
systemctl restart "$SERVICE"
sleep 5
echo ""
echo "=== 重启后状态 ==="
systemctl is-active "$SERVICE"
