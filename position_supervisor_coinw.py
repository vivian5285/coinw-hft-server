#!/usr/bin/env python3
# position_supervisor_coinw.py（调试增强版 - 双笔止盈）
import time
import logging
from coinw_client import CoinWClient

# ==================== 日志配置 ====================
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class SignalProcessor:
    def __init__(self):
        self.client = CoinWClient()
        self.symbol = "ETH"
        self.leverage = 5
        self.risk_ratio = 0.80           # 永远使用余额的 80%
        self.tp_fixed_usdt = 5.0         # 第一笔止盈：固定 5U 保底
        self.tp_percent = 0.03           # 第二笔止盈：本金 3%

        logger.info("SignalProcessor 初始化完成")
        logger.info(f"风控参数 → 风险比例: {self.risk_ratio*100}% | 杠杆: {self.leverage}x")
        logger.info(f"止盈参数 → 固定保底: {self.tp_fixed_usdt}U | 动态比例: {self.tp_percent*100}%")

    def process_signal(self, data: dict):
        """
        处理 TradingView 信号
        """
        action = data.get("action", "").upper()
        logger.info(f"【收到新信号】action = {action}")

        if action in ["LONG", "SHORT", "CLOSE"]:
            self._refresh_position(action)
        else:
            logger.warning(f"未知信号类型: {action}")

    def _refresh_position(self, side: str):
        """
        核心刷新仓位逻辑：
        新信号 → 撤销限价单 → 全平 → 开新仓 → 挂双笔止盈
        """
        try:
            logger.info("=" * 50)
            logger.info(f"开始刷新仓位流程 | 目标方向: {side}")

            # 1. 撤销所有未成交的限价止盈单
            logger.info("步骤1: 撤销所有未成交限价单")
            cancel_result = self.client.cancel_all_open_orders(self.symbol)
            logger.debug(f"撤销挂单返回: {cancel_result}")
            time.sleep(0.8)

            # 2. 全平当前仓位
            logger.info("步骤2: 执行全平操作")
            close_result = self.client.close_all_positions(self.symbol)
            logger.debug(f"全平返回: {close_result}")
            time.sleep(1.5)

            if side == "CLOSE":
                logger.info("收到 CLOSE 信号，仓位已全平，流程结束")
                logger.info("=" * 50)
                return

            # 3. 计算下单金额（余额的 80%）
            logger.info("步骤3: 计算下单金额")
            available = self.client.get_available_balance()
            usdt_amount = round(available * self.risk_ratio, 2)

            logger.info(f"可用余额: {available:.2f} USDT")
            logger.info(f"计划下单金额: {usdt_amount:.2f} USDT（{self.risk_ratio*100}%）")

            if usdt_amount < 10:
                logger.warning(f"可用余额过小（{usdt_amount} USDT），放弃开仓")
                return

            # 4. 市价开仓
            logger.info("步骤4: 执行市价开仓")
            open_result = self.client.place_market_order(self.symbol, side, usdt_amount, self.leverage)
            logger.info(f"开仓结果: {open_result}")

            if open_result.get("code") != 0:
                logger.error("开仓失败，停止后续止盈挂单流程")
                return

            # 等待成交
            time.sleep(2.0)

            # 5. 开仓成功后立即挂双笔限价止盈
            logger.info("步骤5: 挂双笔限价止盈单")
            self._place_dual_tp_orders(side, usdt_amount)

            logger.info("刷新仓位流程完成")
            logger.info("=" * 50)

        except Exception as e:
            logger.error(f"刷新仓位异常: {e}", exc_info=True)

    def _place_dual_tp_orders(self, side: str, position_usdt: float):
        """
        开仓后挂双笔限价止盈
        - 第一笔：固定 5U 保底
        - 第二笔：本金 3%
        """
        try:
            current_price = self.client.get_current_price(self.symbol)
            if current_price <= 0:
                logger.error("无法获取当前价格，停止挂止盈单")
                return

            logger.info(f"当前价格: {current_price}")
            position_eth = position_usdt / current_price
            logger.debug(f"仓位约 {position_eth:.4f} ETH")

            # ==================== 第一笔：固定5U保底 ====================
            tp1_profit = self.tp_fixed_usdt
            tp1_price_offset = tp1_profit / position_eth
            tp1_quantity = round(position_usdt * 0.5, 2)   # 先平一半

            if side == "LONG":
                tp1_price = round(current_price + tp1_price_offset, 2)
                tp1_side = "CLOSE_LONG"
            else:
                tp1_price = round(current_price - tp1_price_offset, 2)
                tp1_side = "CLOSE_SHORT"

            logger.info(f"【第1笔止盈】方向: {tp1_side} | 价格: {tp1_price} | 数量: {tp1_quantity} USDT | 目标利润≈{tp1_profit}U")
            result1 = self.client.place_limit_order(self.symbol, tp1_side, tp1_price, tp1_quantity)
            logger.info(f"第1笔止盈单返回: {result1}")

            time.sleep(0.8)

            # ==================== 第二笔：本金3% ====================
            tp2_profit = round(position_usdt * self.tp_percent, 2)
            tp2_price_offset = tp2_profit / position_eth
            tp2_quantity = round(position_usdt * 0.5, 2)

            if side == "LONG":
                tp2_price = round(current_price + tp2_price_offset, 2)
                tp2_side = "CLOSE_LONG"
            else:
                tp2_price = round(current_price - tp2_price_offset, 2)
                tp2_side = "CLOSE_SHORT"

            logger.info(f"【第2笔止盈】方向: {tp2_side} | 价格: {tp2_price} | 数量: {tp2_quantity} USDT | 目标利润≈{tp2_profit}U")
            result2 = self.client.place_limit_order(self.symbol, tp2_side, tp2_price, tp2_quantity)
            logger.info(f"第2笔止盈单返回: {result2}")

        except Exception as e:
            logger.error(f"挂双笔止盈异常: {e}", exc_info=True)


coinw_processor = SignalProcessor()
