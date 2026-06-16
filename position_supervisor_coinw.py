#!/usr/bin/env python3
# position_supervisor_coinw.py（最终一致版）
import logging
import time
import threading
from coinw_client import CoinWClient

logger = logging.getLogger(__name__)


class SignalProcessor:
    def __init__(self):
        self.client = CoinWClient()
        self.symbol = "ETHUSDT"
        self.leverage = 5
        self.is_monitoring = False
        self.monitor_thread = None
        self.PRICE_PRECISION = 2

    def process_signal(self, data):
        action = data.get("action", "").upper()
        logger.info(f"[CoinW] 收到信号: {action}")

        self._cancel_all_tp_orders()

        if action == "CLOSE":
            self._handle_close_signal()
        elif action in ["LONG", "SHORT"]:
            self._handle_entry_signal(action)

    def _cancel_all_tp_orders(self):
        try:
            self.client.cancel_all_open_orders(self.symbol)
        except Exception as e:
            logger.error(f"[CoinW] 撤销限价单失败: {e}")

    def _handle_entry_signal(self, action):
        try:
            pos = self.client.get_position_info(self.symbol)
            if pos and float(pos.get("positionAmt", 0)) != 0:
                self.client.close_all_positions(self.symbol)
                time.sleep(1.8)

            available = self.client.get_available_balance()
            price = self.client.get_current_price(self.symbol)
            if available <= 0 or price <= 0:
                return

            qty = round((available * 0.8 * 5) / price, 3)

            order = self.client.place_market_order(self.symbol, action, qty, self.leverage)
            if order and order.get("code") == 0:
                self._place_tp_limit_order_by_profit(action, qty, price)
                self._start_profit_monitor()
            else:
                logger.error(f"[CoinW] 开仓失败: {order}")
        except Exception as e:
            logger.error(f"[CoinW] 开仓处理异常: {e}")

    def _place_tp_limit_order_by_profit(self, side, qty, entry_price):
        try:
            target = self.get_target_profit()
            fee = qty * entry_price * 0.0006 * 2
            profit = max(target - fee, target * 0.7)

            tp_price = round(entry_price + (profit / qty) if side == "LONG" else entry_price - (profit / qty), self.PRICE_PRECISION)
            close_side = "CLOSE_LONG" if side == "LONG" else "CLOSE_SHORT"

            self.client.place_limit_order(self.symbol, close_side, tp_price, qty)
            logger.info(f"[CoinW] 挂限价止盈: {close_side} @ {tp_price}")
        except Exception as e:
            logger.error(f"[CoinW] 挂限价单失败: {e}")

    def get_target_profit(self):
        try:
            bal = self.client.get_available_balance()
            return max(4.0, bal * 0.03)
        except:
            return 4.0

    def _handle_close_signal(self):
        try:
            self.client.close_all_positions(self.symbol)
            self.is_monitoring = False
        except Exception as e:
            logger.error(f"[CoinW] 全平失败: {e}")

    def _start_profit_monitor(self):
        if self.is_monitoring: return
        self.is_monitoring = True
        self.monitor_thread = threading.Thread(target=self.monitor_profit_take, daemon=True)
        self.monitor_thread.start()

    def monitor_profit_take(self):
        while self.is_monitoring:
            try:
                res = self.client.get_position_info(self.symbol)
                if res and "data" in res:
                    profit = float(res["data"].get("profit", 0))
                    if profit >= self.get_target_profit():
                        self.client.close_all_positions(self.symbol)
                        self.is_monitoring = False
                        break
            except Exception as e:
                logger.error(f"监控异常: {e}")
            time.sleep(3)


coinw_processor = SignalProcessor()
