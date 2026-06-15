#!/usr/bin/env python3
# position_supervisor.py (V12 绝对信号驱动 - 深度契合TV版)
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
        self.start_websocket_monitor()

    def start_websocket_monitor(self):
        """仅做辅助风控，绝对不干预TV的高优先指令"""
        def run_ws():
            ws = websocket.WebSocketApp(
                "wss://ws.futurescw.com/perpum",
                on_message=self.on_ws_message,
                on_close=lambda ws: time.sleep(5) or run_ws()
            )
            ws.run_forever()
        threading.Thread(target=run_ws, daemon=True).start()

    def on_ws_message(self, ws, message):
        # 仅在极端情况下自动平仓（例如单笔亏损超过 20%），平时一切听TV的
        data = json.loads(message)
        if data.get("type") == "position_change":
            profit = float(data.get("data", {}).get("profit", 0))
            if profit <= -50.0: # 极端熔断
                logger.warning(f"🚨 触发极端熔断保护: {profit}U")
                self.safe_close()

    def safe_close(self, retries=3):
        """强制全平，无视任何盈亏状态"""
        for i in range(retries):
            res = self.client.close_all_positions(self.symbol)
            if res and res.get("code") == 0:
                logger.info("✅ 强制平仓指令已执行")
                return True
            time.sleep(1)
        return False

    def process_signal(self, payload):
        """绝对执行TV指令逻辑"""
        action = payload.get("action", "").upper()
        logger.info(f"⚡ 接收 TV 绝对信号: {action}")
        
        try:
            # 【核心逻辑】：收到任何TV指令，第一步永远是先平旧仓
            self.safe_close()
            time.sleep(0.5)
            
            # 【核心逻辑】：CLOSE信号到此结束，LONG/SHORT则执行刷新
            if action in ["LONG", "SHORT"]:
                assets = self.client.get_account_balance()
                balance = float(assets.get("data", {}).get("availableUsdt", 10.0))
                amount = balance * 0.8
                
                logger.info(f"⚖️ 执行刷新式开单: {action} (本金: {amount:.2f}U)")
                self.client.place_market_order(self.symbol, action, amount, self.leverage)
            else:
                logger.info("✅ CLOSE 信号执行完毕，系统保持空仓")
                
        except Exception as e:
            logger.error(f"❌ 绝对指令执行异常: {e}")
