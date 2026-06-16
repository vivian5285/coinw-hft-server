#!/usr/bin/env python3
# position_supervisor_coinw.py（最终推荐版 - 通用接口 + 合约张数）
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
        self.contract_size = 0.01
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

            # 2. 全平 + 等待余额恢复
            before_balance = self.client.get_available_balance()
            logger.info(f"平仓前可用余额: {before_balance:.2f} USDT")

            self.client.close_all_positions(self.symbol)
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

            # 3. 计算合约张数
            current_price = self.client.get_current_price(self.symbol)
            usdt_value = available * self.risk_ratio * self.leverage
            eth_amount = usdt_value / current_price
            contract_qty = max(1, int(eth_amount / self.contract_size))

            logger.info(f"最终下单合约张数: {contract_qty} 张")

            # 4. 使用通用接口 + 完整参数开仓
            open_result = self.client.place_market_order(
                self.symbol, side, contract_qty, self.leverage
            )
            logger.info(f"开仓结果: {open_result}")

            if open_result.get("code") != 0:
                logger.error("开仓失败")
                logger.info("=" * 60)
                return

            time.sleep(2.0)

            # 5. 挂双笔止盈（可后续完善）
            self._place_dual_tp_orders(side, available * self.risk_ratio)

            logger.info("处理完成")
            logger.info("=" * 60)

        except Exception as e:
            logger.error(f"异常: {e}", exc_info=True)

    def _place_dual_tp_orders(self, side: str, position_usdt: float):
        # 暂时保留，后续可根据需要完善为合约张数止盈
        pass


coinw_processor = SignalProcessor()
