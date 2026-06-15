#!/usr/bin/env python3
# position_supervisor.py (V10 完全体 - 信号优先与智能仓位版)
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
        self.leverage = 5  # 杠杆倍数
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
        logger.info("👂 高频耳目已开启，实时监控中...")

    def on_ws_message(self, ws, message):
        """WebSocket 盈亏监听回调"""
        data = json.loads(message)
        if data.get("type") == "position_change":
            profit = float(data.get("data", {}).get("profit", 0))
            # 自动止盈逻辑可在此处按需开启，目前设为辅助监控
            if profit >= 50.0: # 设个高位阈值防止意外
                logger.info(f"💰 触发自动止盈: 当前盈亏 {profit}U")
                self.safe_close()

    def safe_close(self, retries=3):
        """带重试机制的强制平仓（指令最高优先级）"""
        for i in range(retries):
            res = self.client.close_all_positions(self.symbol)
            if res and res.get("code") == 0:
                logger.info("✅ 斩仓指令已送达")
                return True
            logger.warning(f"⚠️ 斩仓尝试失败，第 {i+1} 次重试...")
            time.sleep(1)
        return False

    def get_dynamic_amount(self):
        """动态仓位管理：获取余额 * 80%"""
        assets = self.client.get_account_balance()
        balance = float(assets.get("data", {}).get("availableUsdt", 10.0))
        return balance * 0.8 # 你的 80% 本金逻辑

    def process_signal(self, payload):
        """最高优先级指令处理逻辑"""
        action = payload.get("action", "").upper()
        
        try:
            # 1. 信号优先：只要有动作，先平旧仓 (CLOSE 或 反转)
            logger.info(f"⚡ 接收 TV 指令: {action}")
            self.safe_close()
            time.sleep(0.5)
            
            # 2. 如果是换向指令，立即开仓
            if action in ["LONG", "SHORT"]:
                amount = self.get_dynamic_amount()
                logger.info(f"⚖️ 执行换向: {action}，仓位规模: {amount:.2f}U")
                self.client.place_market_order(self.symbol, action, amount, self.leverage)
                
        except Exception as e:
            logger.error(f"❌ 指令执行失败: {e}")
