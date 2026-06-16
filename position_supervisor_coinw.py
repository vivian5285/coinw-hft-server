#!/usr/bin/env python3
# position_supervisor_coinw.py（调试版 - 带详细打印）
import logging
import time
from coinw_client import CoinWClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class SignalProcessor:
    def __init__(self):
        self.client = CoinWClient()
        self.symbol = "ETHUSDT"
        self.leverage = 5

    def process_signal(self, data):
        action = data.get("action", "").upper()
        print(f"[DEBUG] ========== 收到信号: {action} ==========")

        # 先撤销限价单
        try:
            self.client.cancel_all_open_orders(self.symbol)
            print("[DEBUG] 已撤销所有限价单")
        except Exception as e:
            print(f"[DEBUG] 撤销限价单异常: {e}")

        if action == "CLOSE":
            self._handle_close()
        elif action in ["LONG", "SHORT"]:
            self._handle_entry(action)

    def _handle_entry(self, action):
        try:
            print("[DEBUG] 进入开仓流程")

            # 检查持仓
            pos = self.client.get_position_info(self.symbol)
            print(f"[DEBUG] 当前持仓信息: {pos}")

            if pos and float(pos.get("positionAmt", 0)) != 0:
                print("[DEBUG] 发现持仓，先全平")
                self.client.close_all_positions(self.symbol)
                time.sleep(1.5)

            # 计算仓位
            available = self.client.get_available_balance()
            price = self.client.get_current_price(self.symbol)
            print(f"[DEBUG] 可用余额: {available}, 当前价格: {price}")

            if available <= 0 or price <= 0:
                print("[DEBUG] 余额或价格异常，放弃开仓")
                return

            qty = round((available * 0.8 * 5) / price, 3)
            print(f"[DEBUG] 计算下单数量: {qty}")

            # 下单
            order = self.client.place_market_order(self.symbol, action, qty, self.leverage)
            print(f"[DEBUG] 下单返回结果: {order}")

            if order and order.get("code") == 0:
                print("[DEBUG] 下单成功！")
                # 这里可以继续挂限价单（暂时先打日志）
            else:
                print("[DEBUG] 下单失败或返回结构异常")

        except Exception as e:
            print(f"[DEBUG] 开仓流程异常: {e}")

    def _handle_close(self):
        try:
            self.client.close_all_positions(self.symbol)
            print("[DEBUG] 全平成功")
        except Exception as e:
            print(f"[DEBUG] 全平异常: {e}")


coinw_processor = SignalProcessor()
