#!/bin/bash
# system_monitor.sh (CoinW 引擎专属巡检守护神)

# 自动读取同一目录下的 .env 环境变量文件来获取钉钉机器人地址
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
if [ -f "$DIR/.env" ]; then
    export $(cat "$DIR/.env" | grep -v '#' | awk '/=/ {print $1}')
fi

WEBHOOK_URL=${DINGTALK_WEBHOOK}
SERVICE_NAME="coinw-engine"

# 获取服务状态
STATUS=$(systemctl is-active $SERVICE_NAME)

if [ "$STATUS" != "active" ]; then
    echo "$(date +'%Y-%m-%d %H:%M:%S') - 🚨 警告: $SERVICE_NAME 进程已离线，正在执行紧急重启..."
    
    # 执行抢救动作
    sudo systemctl restart $SERVICE_NAME
    sleep 3
    
    # 再次确认是否抢救成功
    NEW_STATUS=$(systemctl is-active $SERVICE_NAME)
    if [ "$NEW_STATUS" == "active" ]; then
        STATUS_TEXT="✅ **抢救成功**：守护脚本已自动执行 \`systemctl restart\`，系统现已恢复正常盯盘！"
    else
        STATUS_TEXT="❌ **抢救失败**：重启尝试无效，请立即使用 SSH 登入服务器排查日志！"
    fi
    
    # 如果配置了钉钉，则发送最高优先级的报警
    if [ -n "$WEBHOOK_URL" ]; then
        MSG=$(cat <<EOF
{
    "msgtype": "markdown",
    "markdown": {
        "title": "🚨 币赢引擎掉线警报",
        "text": "### 🚨 币赢(CoinW) 极速引擎意外宕机！\n\n> **发生时间**：$(date +'%Y-%m-%d %H:%M:%S')\n> **进程状态**：已终止 (Inactive)\n\n**自动应对措施**：\n$STATUS_TEXT\n\n*🛡️ 币赢系统底层巡检哨兵*"
    },
    "at": {"isAtAll": true}
}
EOF
)
        curl -s -H "Content-Type: application/json" -d "$MSG" $WEBHOOK_URL > /dev/null
    fi
else
    echo "$(date +'%Y-%m-%d %H:%M:%S') - ✅ 巡检正常: $SERVICE_NAME 运行健康中。"
fi
