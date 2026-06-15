#!/usr/bin/env python3
# position_supervisor.py (V11 绝对执行版 - 拒绝加仓，单向净持仓)
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
        self.leverage = 5
        self.symbol = "ETH"
        # 启动 WebSocket 监控 (作为系统的备用观察者，不再作为主动决策者)
        self.start_websocket_monitor()

    def start_websocket_monitor(self):
        def run_ws():
            ws = websocket.WebSocketApp(
                "wss://ws.futurescw.com/perpum",
                on_message=lambda ws, msg: logger.debug(f"监控信息: {msg}"),
                on_close=lambda ws: time.sleep(5) or run_ws()
            )
            ws.run_forever()
        threading.Thread(target=run_ws, daemon=True).start()

    def safe_close(self, retries=3):
        """强制平仓，最高优先级"""
        for i in range(retries):
            res = self.client.close_all_positions(self.symbol)
            if res and res.get("code") == 0:
                logger.info("✅ 已执行绝对平仓指令")
                return True
            time.sleep(1)
        return False

    def get_dynamic_amount(self):
        assets = self.client.get_account_balance()
        balance = float(assets.get("data", {}).get("availableUsdt", 10.0))
        return balance * 0.8

    def process_signal(self, payload):
        """绝对执行逻辑：任何信号即平仓"""
        action = payload.get("action", "").upper()
        logger.info(f"⚡ 接收 TV 绝对信号: {action}")
        
        try:
            # 1. 不管是 LONG, SHORT 还是 CLOSE，第一步永远是彻底清仓
            # 这保证了“不同向加仓”，彻底抹除旧单
            self.safe_close()
            time.sleep(0.5)
            
            # 2. 如果信号是开仓，则根据新信号开单
            if action in ["LONG", "SHORT"]:
                amount = self.get_dynamic_amount()
                logger.info(f"⚖️ 执行开仓: {action} (规模: {amount:.2f}U)")
                self.client.place_market_order(self.symbol, action, amount, self.leverage)
            else:
                logger.info("✅ 信号为 CLOSE，已完成清仓，保持空仓状态")
                
        except Exception as e:
            logger.error(f"❌ 绝对指令执行异常: {e}")
