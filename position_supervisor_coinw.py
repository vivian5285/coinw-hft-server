#!/usr/bin/env python3
# position_supervisor_coinw.py（极致防御 + 详细日志版）
import logging
import time
from coinw_client import CoinWClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("logs/supervisor_coinw.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class SignalProcessor:
    def __init__(self):
        try:
            self.client = CoinWClient()
            self.symbol = "ETHUSDT"
            logger.info("[CoinW] SignalProcessor 初始化成功")
        except Exception as e:
            logger.error(f"[CoinW] 初始化失败: {e}")
            raise

    def process_signal(self, data: dict):
        try:
            action = data.get("action", "").upper()
            logger.info(f"[CoinW] 收到信号: {action}")

            if action == "CLOSE":
                self._safe_close()
            elif action in ["LONG", "SHORT"]:
                self._safe_open(action)
            else:
                logger.warning(f"[CoinW] 未知 action: {action}")

        except Exception as e:
            logger.error(f"[CoinW] process_signal 异常: {e}", exc_info=True)

    def _safe_open(self, side: str):
        try:
            logger.info("[CoinW] 开始执行开仓逻辑")

            # 1. 先清理
            self.client.cancel_all_open_orders(self.symbol)
            self.client.close_all_positions(self.symbol)
            time.sleep(1.2)

            # 2. 计算仓位
            available = self.client.get_available_balance()
            price = self.client.get_current_price(self.symbol)
            logger.info(f"[CoinW] 可用余额: {available}, 当前价格: {price}")

            if available <= 0 or price <= 0:
                logger.warning("[CoinW] 余额或价格异常，放弃开仓")
                return

            qty = round((available * 0.8 * 5) / price, 3)
            logger.info(f"[CoinW] 计算下单数量: {qty}")

            # 3. 下单
            result = self.client.place_market_order(self.symbol, side, qty, 5)
            logger.info(f"[CoinW] 下单返回: {result}")

        except Exception as e:
            logger.error(f"[CoinW] 开仓逻辑异常: {e}", exc_info=True)

    def _safe_close(self):
        try:
            result = self.client.close_all_positions(self.symbol)
            logger.info(f"[CoinW] 平仓返回: {result}")
        except Exception as e:
            logger.error(f"[CoinW] 平仓异常: {e}", exc_info=True)


coinw_processor = SignalProcessor()
