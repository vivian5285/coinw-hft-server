#!/usr/bin/env python3
# position_supervisor_coinw.py（动态80% + 双笔止盈生产版）
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
        self.risk_ratio = 0.80           # 使用可用余额的80%
        self.tp_fixed_usdt = 5.0         # 第一笔止盈：固定5U保底
        self.tp_percent = 0.03           # 第二笔止盈：本金3%

        logger.info("SignalProcessor 初始化完成")
        logger.info(f"风控参数: 余额{self.risk_ratio*100}% | 杠杆{self.leverage}x")
        logger.info(f"止盈参数: 固定保底{self.tp_fixed_usdt}U + 动态{self.tp_percent*100}%")

    def process_signal(self, data: dict):
        action = data.get("action", "").upper()
        logger.info(f"收到信号: {action}")

        if action in ["LONG", "SHORT", "CLOSE"]:
            self._refresh_position(action)

    def _refresh_position(self, side: str):
        """
        核心流程：
        新信号 → 撤销限价单 → 全平 → 等待余额恢复 → 计算80% → 开仓 → 挂双笔止盈
        """
        try:
            logger.info("=" * 60)
            logger.info(f"开始处理信号 → 目标方向: {side}")

            # 1. 撤销所有未成交限价单
            logger.info("步骤1: 撤销未成交限价单")
            self.client.cancel_all_open_orders(self.symbol)
            time.sleep(0.8)

            # 2. 全平当前仓位
            logger.info("步骤2: 执行全平")
            before_balance = self.client.get_available_balance()
            logger.info(f"平仓前可用余额: {before_balance:.2f} USDT")

            self.client.close_all_positions(self.symbol)

            # 3. 等待余额恢复（关键）
            logger.info("步骤3: 等待余额恢复...")
            time.sleep(3.0)

            available = before_balance
            for i in range(5):
                available = self.client.get_available_balance()
                logger.info(f"平仓后第 {i+1} 次查询余额: {available:.2f} USDT")
                if available > before_balance * 0.7:
                    logger.info("余额已基本恢复")
                    break
                time.sleep(1.2)

            if side == "CLOSE":
                logger.info("全平信号处理完成")
                logger.info("=" * 60)
                return

            # 4. 计算下单金额（可用余额 × 80%）
            usdt_amount = round(available * self.risk_ratio, 2)
            logger.info(f"最终下单金额: {usdt_amount:.2f} USDT（可用余额 {available:.2f} × 80%）")

            if usdt_amount < 10:
                logger.warning(f"可用余额不足，放弃开仓")
                logger.info("=" * 60)
                return

            # 5. 市价开仓（使用下午能成功的参数组合）
            logger.info("步骤4: 执行市价开仓")
            open_result = self.client.place_market_order(self.symbol, side, usdt_amount, self.leverage)
            logger.info(f"开仓结果: {open_result}")

            if open_result.get("code") != 0:
                logger.error("开仓失败，停止后续流程")
                logger.info("=" * 60)
                return

            time.sleep(2.0)

            # 6. 挂双笔限价止盈
            logger.info("步骤5: 挂双笔限价止盈单")
            self._place_dual_tp_orders(side, usdt_amount)

            logger.info("信号处理完成")
            logger.info("=" * 60)

        except Exception as e:
            logger.error(f"处理信号异常: {e}", exc_info=True)

    def _place_dual_tp_orders(self, side: str, position_usdt: float):
        """
        开仓后立即挂双笔限价止盈
        - 第一笔：固定5U保底
        - 第二笔：本金3%
        """
        try:
            current_price = self.client.get_current_price(self.symbol)
            if current_price <= 0:
                logger.error("无法获取当前价格，停止挂止盈单")
                return

            position_eth = position_usdt / current_price

            # ========== 第一笔：固定5U保底（平50%仓位） ==========
            tp1_profit = self.tp_fixed_usdt
            tp1_price_offset = tp1_profit / position_eth
            tp1_quantity = round(position_usdt * 0.5, 2)

            if side == "LONG":
                tp1_price = round(current_price + tp1_price_offset, 2)
                tp1_side = "CLOSE_LONG"
            else:
                tp1_price = round(current_price - tp1_price_offset, 2)
                tp1_side = "CLOSE_SHORT"

            logger.info(f"【第1笔止盈】{tp1_side} | 价格:{tp1_price} | 数量:{tp1_quantity}U | 目标≈{tp1_profit}U")
            result1 = self.client.place_limit_order(self.symbol, tp1_side, tp1_price, tp1_quantity)
            logger.info(f"第1笔止盈返回: {result1}")

            time.sleep(0.8)

            # ========== 第二笔：本金3%（平剩余50%仓位） ==========
            tp2_profit = round(position_usdt * self.tp_percent, 2)
            tp2_price_offset = tp2_profit / position_eth
            tp2_quantity = round(position_usdt * 0.5, 2)

            if side == "LONG":
                tp2_price = round(current_price + tp2_price_offset, 2)
                tp2_side = "CLOSE_LONG"
            else:
                tp2_price = round(current_price - tp2_price_offset, 2)
                tp2_side = "CLOSE_SHORT"

            logger.info(f"【第2笔止盈】{tp2_side} | 价格:{tp2_price} | 数量:{tp2_quantity}U | 目标≈{tp2_profit}U")
            result2 = self.client.place_limit_order(self.symbol, tp2_side, tp2_price, tp2_quantity)
            logger.info(f"第2笔止盈返回: {result2}")

        except Exception as e:
            logger.error(f"挂双笔止盈异常: {e}", exc_info=True)


coinw_processor = SignalProcessor()
