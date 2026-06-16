#!/usr/bin/env python3
# position_supervisor_coinw.py（最小可运行版 - 基于你测试过的 coinw_client.py）
import time
import logging
from coinw_client import CoinWClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SignalProcessor:
    def __init__(self):
        self.client = CoinWClient()
        self.symbol = "ETHUSDT"

    def process_signal(self, data: dict):
        action = data.get("action", "").upper()
        logger.info(f"[CoinW] 收到信号: {action}")

        if action == "CLOSE":
            self._close_position()
        elif action in ["LONG", "SHORT"]:
            self._open_position(action)

    def _open_position(self, side: str):
        try:
            # 先撤销所有挂单 + 平仓（保证干净）
            self.client.close_all_positions(self.symbol)
            time.sleep(1)

            # 获取余额计算仓位（80% * 5倍）
            balance_info = self.client.get_account_balance()
            available = float(balance_info.get("data", {}).get("availableUsdt", 0))
            price = self.client.get_current_price(self.symbol)  # 需要你在 coinw_client.py 里加上这个方法

            if available <= 0 or price <= 0:
                logger.warning("[CoinW] 余额或价格异常")
                return

            qty = round((available * 0.8 * 5) / price, 3)

            # 下单
            result = self.client.place_market_order(self.symbol, side, qty, 5)
            logger.info(f"[CoinW] 下单结果: {result}")

        except Exception as e:
            logger.error(f"[CoinW] 开仓失败: {e}")

    def _close_position(self):
        try:
            result = self.client.close_all_positions(self.symbol)
            logger.info(f"[CoinW] 平仓结果: {result}")
        except Exception as e:
            logger.error(f"[CoinW] 平仓失败: {e}")


# 全局实例，供 app.py 导入
coinw_processor = SignalProcessor()
