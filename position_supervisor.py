#!/usr/bin/env python3
# position_supervisor.py (V8 终极强化版 - 带重试、重连、精算逻辑)
import logging
import time
import threading
import json
import websocket
from coinw_client import CoinWClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SignalProcessor:
    def __init__(self):
        self.client = CoinWClient()
        self.trade_amount = 10.0
        self.leverage = 5
        self.symbol = "ETH"
        self.start_websocket_monitor()

    def start_websocket_monitor(self):
        """带自动重连机制的 WebSocket 守护进程"""
        def run_ws():
            ws = websocket.WebSocketApp(
                "wss://ws.futurescw.com/perpum",
                on_message=self.on_ws_message,
                on_close=lambda ws: (logger.warning("⚠️ WS 断开，5秒后重连..."), time.sleep(5), run_ws()),
                on_error=lambda ws, e: logger.error(f"❌ WS 异常: {e}")
            )
            ws.run_forever()
        
        threading.Thread(target=run_ws, daemon=True).start()

    def on_ws_message(self, ws, message):
        data = json.loads(message)
        if data.get("type") == "position_change":
            profit = float(data.get("data", {}).get("profit", 0))
            # 【精算模型】：利润需覆盖手续费 (估算值) + 预期纯利 2U
            fee_cost = self.trade_amount * self.leverage * 0.0015
            if profit >= (2.0 + fee_cost):
                logger.info(f"💰 精算达标: 盈亏{profit}U > 成本{fee_cost:.2f}U, 立即斩仓")
                self.safe_close()

    def safe_close(self, retries=3):
        """带重试机制的平仓保护"""
        for i in range(retries):
            res = self.client.close_all_positions(self.symbol)
            if res and res.get("code") == 0:
                logger.info("✅ 斩仓成功")
                return
            logger.warning(f"⚠️ 斩仓失败，第 {i+1} 次重试...")
            time.sleep(1)

    def process_signal(self, payload):
        """解析指令"""
        action = payload.get("action", "").upper()
        if action == "CLOSE":
            self.safe_close()
        elif action in ["LONG", "SHORT"]:
            self.safe_close() # 强制平旧
            time.sleep(1)
            self.client.place_market_order(self.symbol, action, self.trade_amount, self.leverage)
