#!/usr/bin/env python3
# position_supervisor.py (CoinW 交易大脑 - 高频执行版)
import logging
import time
from coinw_client import CoinWClient

logger = logging.getLogger(__name__)

class SignalProcessor:
    def __init__(self):
        # 挂载昨晚完美通关的 V6.2 引擎
        self.client = CoinWClient()
        
        # --- 高频风控参数 ---
        self.trade_amount = 10.0  # 每次开仓本金 10 U (可随时在代码里调大)
        self.leverage = 5         # 5倍杠杆
        self.symbol = "ETH"

    def process_signal(self, payload):
        """解析 TV 信号并扣动扳机"""
        action = payload.get("action", "").upper()
        
        try:
            if action == "CLOSE":
                logger.info(f"=== 🧠 大脑指令: 紧急撤退，全平 {self.symbol} ===")
                self.client.close_all_positions(self.symbol)
                
            elif action in ["LONG", "SHORT"]:
                logger.info(f"=== 🧠 大脑指令: 极速开仓 {action} ===")
                
                # 【高频核心防线】：在执行任何新方向开仓前，先发送一键全平，清空历史包袱
                self.client.close_all_positions(self.symbol)
                
                # 给交易所 0.5 秒的底层撮合消化时间，防止平仓还没完成就开仓导致保证金不足
                time.sleep(0.5) 
                
                # 瞬间砸入新订单
                self.client.place_market_order(
                    symbol=self.symbol,
                    direction=action,
                    usdt_amount=self.trade_amount,
                    leverage=self.leverage
                )
            else:
                logger.warning(f"⚠️ 收到未知动作指令: {action}")
                
        except Exception as e:
            logger.error(f"❌ 处理信号时发生严重异常: {e}")
