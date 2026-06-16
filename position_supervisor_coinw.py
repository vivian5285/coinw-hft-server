import logging
import os
import requests
from coinw_client import coinw_client

logger = logging.getLogger(__name__)

class PositionSupervisorCoinW:
    def __init__(self):
        self.dingtalk_url = os.getenv("DINGTALK_WEBHOOK", "")

    def send_dingtalk_msg(self, msg: str):
        """钉钉警报播报"""
        if not self.dingtalk_url:
            return
        try:
            headers = {'Content-Type': 'application/json'}
            data = {"msgtype": "text", "text": {"content": f"🚨 币赢(CoinW)量化引擎 🚨\n{msg}"}}
            requests.post(self.dingtalk_url, json=data, headers=headers, timeout=5)
        except Exception as e:
            logger.error(f"[CoinW-DingTalk] 发送通知失败: {e}")

    def handle_signal(self, signal_data: dict):
        """处理来自 app.py 队列的信号"""
        try:
            # 兼容各种 key 的命名习惯 (action, side)
            action = signal_data.get("action") or signal_data.get("side", "")
            action = action.upper()
            symbol = signal_data.get("symbol", "ETHUSDT")
            quantity = float(signal_data.get("quantity", 0.01))

            logger.info(f"[CoinW-Supervisor] 收到核心信号: {action} {quantity} {symbol}")

            # 1. 资产与价格前置审查
            balance = coinw_client.get_available_balance("USDT")
            price = coinw_client.get_current_price(symbol)
            
            logger.info(f"[CoinW-Supervisor] 当前账户可用余额: {balance} USDT, 最新标的价: {price}")

            if balance <= 0 or price <= 0:
                logger.warning("[CoinW-Supervisor] ❌ 余额或价格异常获取失败，触发安全熔断，放弃开仓！")
                self.send_dingtalk_msg(f"安全熔断触发：\n未获取到有效余额或价格，已拦截 {action} 信号。")
                return

            # 2. 执行开仓
            order_result = coinw_client.place_market_order(action, quantity, symbol)
            
            # 3. 结果播报
            if order_result:
                msg = f"✅ 执行成功\n交易对: {symbol}\n方向: {action}\n数量: {quantity}\n当前余额: {balance} USDT"
                logger.info(msg.replace('\n', ' '))
                self.send_dingtalk_msg(msg)
            else:
                logger.error("[CoinW-Supervisor] ❌ 下单执行返回失败")
                self.send_dingtalk_msg(f"❌ 下单失败，请检查 API 权限或参数。信号: {action}")

        except Exception as e:
            logger.error(f"[CoinW-Supervisor] 信号处理遇到致命错误: {e}")

position_supervisor = PositionSupervisorCoinW()
