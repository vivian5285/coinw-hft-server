#!/usr/bin/env python3
# position_supervisor_coinw.py（币赢核心大脑 - 混合模式 + 固定盈利反推版）
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
        self.current_position_qty = 0.0
        self.entry_price = 0.0

    # ==================== 入口方法 ====================
    def process_signal(self, data: dict):
        action = data.get("action", "").upper()
        logger.info(f"[CoinW] 收到信号: {action}")

        # ========== 第一步：必须先撤销所有未成交限价单 ==========
        self._cancel_all_tp_orders()

        if action == "CLOSE":
            self._handle_close_signal()
        elif action in ["LONG", "SHORT"]:
            self._handle_entry_signal(action)

    # ==================== 撤销所有限价单 ====================
    def _cancel_all_tp_orders(self):
        try:
            self.client.cancel_all_open_orders(self.symbol)
            logger.info("[CoinW] 已撤销所有未成交限价单")
        except Exception as e:
            logger.error(f"[CoinW] 撤销限价单失败: {e}")

    # ==================== 处理开仓 ====================
    def _handle_entry_signal(self, action: str):
        try:
            # 检查是否有持仓，先平
            position = self.client.get_position_info(self.symbol)
            if position and float(position.get("positionAmt", 0)) != 0:
                logger.info("[CoinW] 检测到持仓，先执行平仓")
                self.client.close_all_positions(self.symbol)
                time.sleep(1.8)

            # 计算仓位（80% * 5倍）
            available = self.client.get_available_balance()
            current_price = self.client.get_current_price(self.symbol)

            if available <= 0 or current_price <= 0:
                logger.warning("[CoinW] 余额或价格异常，放弃开仓")
                return

            target_qty = round((available * 0.8 * 5) / current_price, 3)

            # 执行开仓
            order = self.client.place_market_order(
                symbol=self.symbol,
                side=action,
                amount=target_qty,
                leverage=self.leverage
            )

            if order and order.get("code") == 0:
                logger.info(f"[CoinW] {action} 开仓成功: {target_qty} ETH")
                self.current_position_qty = target_qty
                self.entry_price = current_price

                # 开仓后挂限价止盈单（固定盈利金额反推）
                self._place_tp_limit_order_by_profit(action, target_qty, current_price)

                # 启动辅助监控线程（可选）
                self._start_profit_monitor()

            else:
                logger.error(f"[CoinW] 开仓失败: {order}")

        except Exception as e:
            logger.error(f"[CoinW] 处理 {action} 信号异常: {e}")

    # ==================== 按固定盈利金额反推止盈价 ====================
    def _place_tp_limit_order_by_profit(self, side: str, qty: float, entry_price: float):
        try:
            target_profit = self.get_target_profit()   # 混合模式目标利润
            fee = qty * entry_price * 0.0006 * 2       # 粗略估算往返手续费

            actual_profit = target_profit - fee
            if actual_profit <= 0:
                actual_profit = target_profit

            # 反推止盈价格
            if side == "LONG":
                tp_price = round(entry_price + (actual_profit / qty), 2)
                close_side = "CLOSE_LONG"
            else:
                tp_price = round(entry_price - (actual_profit / qty), 2)
                close_side = "CLOSE_SHORT"

            # 挂限价止盈单
            self.client.place_limit_order(
                symbol=self.symbol,
                side=close_side,
                price=tp_price,
                amount=qty
            )
            logger.info(f"[CoinW] 已挂限价止盈单: {close_side} @ {tp_price} (目标利润≈{target_profit}U)")

        except Exception as e:
            logger.error(f"[CoinW] 挂限价止盈单失败: {e}")

    # ==================== 混合模式止盈目标 ====================
    def get_target_profit(self) -> float:
        """混合模式：max(保底4U, 可用余额 × 3%)"""
        try:
            balance = self.client.get_available_balance()
            dynamic = balance * 0.03
            return max(4.0, dynamic)
        except Exception as e:
            logger.error(f"[CoinW] 计算止盈目标失败: {e}")
            return 4.0

    # ==================== 处理 CLOSE 信号 ====================
    def _handle_close_signal(self):
        try:
            self.client.close_all_positions(self.symbol)
            self.current_position_qty = 0.0
            logger.info("[CoinW] 已执行全平")
        except Exception as e:
            logger.error(f"[CoinW] 全平失败: {e}")

    # ==================== 启动辅助止盈监控线程 ====================
    def _start_profit_monitor(self):
        if self.is_monitoring:
            return
        self.is_monitoring = True
        self.monitor_thread = threading.Thread(target=self.monitor_profit_take, daemon=True)
        self.monitor_thread.start()
        logger.info("[CoinW] 辅助止盈监控线程已启动")

    # ==================== 辅助止盈监控（保留你原来的逻辑） ====================
    def monitor_profit_take(self):
        """
        辅助止盈监控（当限价单未成交时作为兜底）
        """
        while self.is_monitoring:
            try:
                res = self.client._request("GET", "/v1/perpum/position/info", {"symbol": self.symbol})
                if res and "data" in res:
                    profit = float(res["data"].get("profit", 0))
                    target = self.get_target_profit()

                    if profit >= target:
                        logger.info(f"[CoinW] 辅助监控触发止盈: 当前{profit:.2f}U >= 目标{target:.2f}U")
                        self.client.close_all_positions(self.symbol)
                        self.is_monitoring = False
                        break
            except Exception as e:
                logger.error(f"[CoinW] 辅助监控异常: {e}")
            time.sleep(3)


# 全局实例
coinw_processor = SignalProcessor()
