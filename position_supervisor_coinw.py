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
        self.contract_size = 0.01

    def process_signal(self, data: dict):
        action = data.get("action", "").upper()
        logger.info(f"收到信号: {action}")

        if action == "CLOSE":
            self._close()
        elif action in ["LONG", "SHORT"]:
            self._open(action)

    def _open(self, side: str):
        try:
            self.client.cancel_all_open_orders(self.symbol)
            self.client.close_all_positions(self.symbol)
            time.sleep(1.2)

            available = self.client.get_available_balance()
            price = self.client.get_current_price(self.symbol)

            if available <= 0 or price <= 0:
                logger.warning("余额或价格异常，放弃开仓")
                return

            usdt_value = available * 0.8 * self.leverage
            eth_amount = usdt_value / price
            contract_qty = max(1, int(eth_amount / self.contract_size))

            logger.info(f"下单合约张数: {contract_qty}")

            result = self.client.place_market_order(self.symbol, side, contract_qty, self.leverage)
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
