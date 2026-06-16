#!/usr/bin/env python3
# position_supervisor_coinw.py（最终完整版）
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

    def process_signal(self, data: dict):
        action = data.get("action", "").upper()
        logger.info(f"收到信号: {action}")

        if action == "CLOSE":
            self._close()
        elif action in ["LONG", "SHORT"]:
            self._open(action)

    def _open(self, side: str):
        try:
            # 先清理
            self.client.cancel_all_open_orders(self.symbol)
            self.client.close_all_positions(self.symbol)
            time.sleep(1.2)

            # 计算下单 USDT 金额（余额的 80%）
            available = self.client.get_available_balance()
            usdt_amount = round(available * 0.8, 2)

            if usdt_amount < 10:                    # 提高最小下单金额
                logger.warning(f"可用余额过小（{usdt_amount} USDT），放弃开仓")
                return

            logger.info(f"下单 USDT 金额: {usdt_amount}")

            result = self.client.place_market_order(self.symbol, side, usdt_amount, self.leverage)
            logger.info(f"开仓结果: {result}")

        except Exception as e:
            logger.error(f"开仓异常: {e}")

    def _close(self):
        try:
            result = self.client.close_all_positions(self.symbol)
            logger.info(f"平仓结果: {result}")
        except Exception as e:
            logger.error(f"平仓异常: {e}")


coinw_processor = SignalProcessor()
