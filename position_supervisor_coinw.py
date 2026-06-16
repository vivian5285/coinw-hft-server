#!/usr/bin/env python3
# position_supervisor_coinw.py（双笔止盈生产版）
import time
import logging
from coinw_client import CoinWClient

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(message)s')
logger = logging.getLogger(__name__)


class SignalProcessor:
    def __init__(self):
        self.client = CoinWClient()
        self.symbol = "ETH"
        self.leverage = 5
        self.risk_ratio = 0.80           # 永远用余额的80%
        self.tp_fixed_usdt = 5.0         # 第一笔：固定5U保底
        self.tp_percent = 0.03           # 第二笔：本金3%

    def process_signal(self, data: dict):
        action = data.get("action", "").upper()
        logger.info(f"收到信号: {action}")

        if action in ["LONG", "SHORT", "CLOSE"]:
            self._refresh_position(action)

    def _refresh_position(self, side: str):
        try:
            # 1. 撤销所有未成交的限价止盈单
            self.client.cancel_all_open_orders(self.symbol)
            time.sleep(0.8)

            # 2. 全平当前仓位
            self.client.close_all_positions(self.symbol)
            time.sleep(1.5)

            if side == "CLOSE":
                logger.info("收到全平信号，已全平，等待新信号")
                return

            # 3. 计算下单金额（余额80%）
            available = self.client.get_available_balance()
            usdt_amount = round(available * self.risk_ratio, 2)

            if usdt_amount < 10:
                logger.warning(f"可用余额不足（{usdt_amount} USDT），放弃开仓")
                return

            logger.info(f"下单 USDT 金额: {usdt_amount}")

            # 4. 市价开仓
            open_result = self.client.place_market_order(self.symbol, side, usdt_amount, self.leverage)
            logger.info(f"开仓结果: {open_result}")

            if open_result.get("code") != 0:
                logger.error("开仓失败，停止挂止盈单")
                return

            time.sleep(2.0)

            # 5. 开仓成功后立即挂**两笔**限价止盈单
            self._place_dual_tp_orders(side, usdt_amount)

        except Exception as e:
            logger.error(f"刷新仓位异常: {e}")

    def _place_dual_tp_orders(self, side: str, position_usdt: float):
        """开仓后挂双笔限价止盈"""
        try:
            current_price = self.client.get_current_price(self.symbol)
            if current_price <= 0:
                return

            position_eth = position_usdt / current_price

            # ========== 第一笔：固定5U保底 ==========
            tp1_profit = self.tp_fixed_usdt
            tp1_price_offset = tp1_profit / position_eth
            tp1_quantity = round(position_usdt * 0.5, 2)   # 先平一半

            if side == "LONG":
                tp1_price = round(current_price + tp1_price_offset, 2)
                tp1_side = "CLOSE_LONG"
            else:
                tp1_price = round(current_price - tp1_price_offset, 2)
                tp1_side = "CLOSE_SHORT"

            logger.info(f"挂第1笔止盈 | 价格: {tp1_price} | 数量USDT: {tp1_quantity} | 目标≈{tp1_profit}U")
            result1 = self.client.place_limit_order(self.symbol, tp1_side, tp1_price, tp1_quantity)
            logger.info(f"第1笔止盈结果: {result1}")

            time.sleep(0.8)

            # ========== 第二笔：本金3% ==========
            tp2_profit = position_usdt * self.tp_percent
            tp2_price_offset = tp2_profit / position_eth
            tp2_quantity = round(position_usdt * 0.5, 2)   # 剩余一半

            if side == "LONG":
                tp2_price = round(current_price + tp2_price_offset, 2)
                tp2_side = "CLOSE_LONG"
            else:
                tp2_price = round(current_price - tp2_price_offset, 2)
                tp2_side = "CLOSE_SHORT"

            logger.info(f"挂第2笔止盈 | 价格: {tp2_price} | 数量USDT: {tp2_quantity} | 目标≈{tp2_profit:.2f}U")
            result2 = self.client.place_limit_order(self.symbol, tp2_side, tp2_price, tp2_quantity)
            logger.info(f"第2笔止盈结果: {result2}")

        except Exception as e:
            logger.error(f"挂双笔止盈异常: {e}")


coinw_processor = SignalProcessor()
