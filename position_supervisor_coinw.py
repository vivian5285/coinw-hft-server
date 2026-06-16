#!/usr/bin/env python3
# position_supervisor_coinw.py（修复版 - 动态80% + 双笔止盈）
import time
import logging
from coinw_client import CoinWClient

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


class SignalProcessor:
    def __init__(self):
        self.client = CoinWClient()
        self.symbol = "ETH"
        self.leverage = 5
        self.risk_ratio = 0.80
        self.tp_fixed_usdt = 5.0
        self.tp_percent = 0.03

    def process_signal(self, data: dict):
        action = data.get("action", "").upper()
        logger.info(f"收到信号: {action}")

        if action in ["LONG", "SHORT", "CLOSE"]:
            self._refresh_position(action)

    def _refresh_position(self, side: str):
        try:
            logger.info("=" * 60)
            logger.info(f"开始处理信号 → 目标方向: {side}")

            # 1. 撤销限价单
            self.client.cancel_all_open_orders(self.symbol)
            time.sleep(0.8)

            # 2. 全平
            before_balance = self.client.get_available_balance()
            logger.info(f"平仓前可用余额: {before_balance:.2f} USDT")
            self.client.close_all_positions(self.symbol)

            # 3. 等待余额恢复
            logger.info("等待余额恢复...")
            time.sleep(3.0)
            for i in range(5):
                available = self.client.get_available_balance()
                logger.info(f"平仓后第 {i+1} 次查询余额: {available:.2f} USDT")
                if available > before_balance * 0.7:
                    break
                time.sleep(1.2)

            if side == "CLOSE":
                logger.info("全平完成")
                logger.info("=" * 60)
                return

            # 4. 计算下单金额
            usdt_amount = round(available * self.risk_ratio, 2)
            logger.info(f"最终下单金额: {usdt_amount:.2f} USDT")

            if usdt_amount < 10:
                logger.warning("可用余额不足，放弃开仓")
                return

            # 5. 市价开仓
            logger.info("执行市价开仓")
            open_result = self.client.place_market_order(self.symbol, side, usdt_amount, self.leverage)
            logger.info(f"开仓结果: {open_result}")

            if open_result.get("code") != 0:
                logger.error("开仓失败")
                return

            time.sleep(2.0)

            # 6. 挂双笔限价止盈（已修复 direction）
            logger.info("挂双笔限价止盈")
            self._place_dual_tp_orders(side, usdt_amount)

            logger.info("信号处理完成")
            logger.info("=" * 60)

        except Exception as e:
            logger.error(f"异常: {e}", exc_info=True)

    def _place_dual_tp_orders(self, side: str, position_usdt: float):
        try:
            current_price = self.client.get_current_price(self.symbol)
            if current_price <= 0:
                return

            position_eth = position_usdt / current_price

            # 第一笔：固定5U保底
            tp1_profit = self.tp_fixed_usdt
            tp1_price_offset = tp1_profit / position_eth
            tp1_quantity = round(position_usdt * 0.5, 2)

            # 修复 direction（使用小写 + 下划线）
            if side == "LONG":
                tp1_price = round(current_price + tp1_price_offset, 2)
                tp1_direction = "close_long"
            else:
                tp1_price = round(current_price - tp1_price_offset, 2)
                tp1_direction = "close_short"

            logger.info(f"【第1笔止盈】方向:{tp1_direction} 价格:{tp1_price} 数量:{tp1_quantity}U 目标≈{tp1_profit}U")
            result1 = self.client.place_limit_order(self.symbol, tp1_direction, tp1_price, tp1_quantity)
            logger.info(f"第1笔返回: {result1}")

            time.sleep(0.8)

            # 第二笔：本金3%
            tp2_profit = round(position_usdt * self.tp_percent, 2)
            tp2_price_offset = tp2_profit / position_eth
            tp2_quantity = round(position_usdt * 0.5, 2)

            if side == "LONG":
                tp2_price = round(current_price + tp2_price_offset, 2)
                tp2_direction = "close_long"
            else:
                tp2_price = round(current_price - tp2_price_offset, 2)
                tp2_direction = "close_short"

            logger.info(f"【第2笔止盈】方向:{tp2_direction} 价格:{tp2_price} 数量:{tp2_quantity}U 目标≈{tp2_profit}U")
            result2 = self.client.place_limit_order(self.symbol, tp2_direction, tp2_price, tp2_quantity)
            logger.info(f"第2笔返回: {result2}")

        except Exception as e:
            logger.error(f"挂止盈异常: {e}", exc_info=True)


coinw_processor = SignalProcessor()
