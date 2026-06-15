#!/usr/bin/env python3
# position_supervisor.py (V7 高频终极自动化版)
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
        # 启动 WebSocket 监听耳目
        self.start_websocket_monitor()

    def start_websocket_monitor(self):
        """开启 WebSocket 盈亏监听，时刻守候平仓良机"""
        def on_message(ws, message):
            data = json.loads(message)
            # 监听持仓频道，当盈亏达到目标即触发
            if data.get("type") == "position_change":
                profit = data.get("data", {}).get("profit") 
                if profit and float(profit) >= 2.0: # 目标利润 2U
                    logger.info(f"💰 触发自动止盈: 当前盈亏 {profit}U")
                    self.client.close_all_positions(self.symbol)

        # 启动后台线程监听盈亏
        ws = websocket.WebSocketApp("wss://ws.futurescw.com/perpum", on_message=on_message)
        threading.Thread(target=ws.run_forever, daemon=True).start()
        logger.info("👂 高频耳目已开启，实时监控中...")

    def process_signal(self, payload):
        """解析 TV 信号并执行"""
        action = payload.get("action", "").upper()
        try:
            if action == "CLOSE":
                self.client.close_all_positions(self.symbol)
            elif action in ["LONG", "SHORT"]:
                # 策略：先全平旧仓，再开新仓，保证单向持仓
                self.client.close_all_positions(self.symbol)
                time.sleep(0.5) 
                self.client.place_market_order(self.symbol, action, self.trade_amount, self.leverage)
        except Exception as e:
            logger.error(f"❌ 交易指令执行异常: {e}")
