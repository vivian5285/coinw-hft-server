#!/usr/bin/env python3
import time
import threading
import logging
from coinw_client import CoinWClient
from dingtalk_notifier import DingTalkNotifier

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

class SignalProcessor:
    def __init__(self):
        self.client = CoinWClient()
        self.notifier = DingTalkNotifier()
        self.symbol = "ETH"
        
        # 50%本金 / 20倍 / 13刀主动盯盘
        self.leverage = 20               
        self.risk_ratio = 0.50           
        self.tp_eth_price_diff = 13.0    
        
        self.monitor_thread = None
        self.status = "IDLE"

    def process_signal(self, data: dict):
        action = data.get("action", "").upper()
        logger.info(f"========== 收到新TV信号: {action} ==========")

        if action == "CLOSE":
            self._close_all("📡 接收到 TV 主动平仓信号")
            return

        if action in ["LONG", "SHORT"]:
            self._refresh_position(action)

    def _refresh_position(self, side: str):
        try:
            # 1. 焦土重置
            self._close_all(f"🔄 强制重置阵地：准备执行新方向 {side}")
            time.sleep(1.5) 

            # 2. 算子弹
            total_balance = self.client.get_available_balance()
            if total_balance < 10:
                self.notifier.send_markdown("报警: 余额不足", f"当前余额 `{total_balance:.2f} U` 不足！")
                return

            usdt_amount = round(total_balance * self.risk_ratio, 2)
            logger.info(f"💰 可用: {total_balance:.2f} U | 动用 50%: {usdt_amount:.2f} U")

            # 3. 发射开单指令 (使用还原的稳定参数)
            open_result = self.client.place_market_order(self.symbol, side, usdt_amount, self.leverage)
            if str(open_result.get("code")) not in ["200", "0"]:
                self.notifier.send_markdown("报警: 开仓失败", f"交易所拒单:\n\n`{open_result}`")
                return

            self.status = "OPEN"
            time.sleep(2.0) # 等待订单完全成交

            # 4. 激活 VPS 主动盯盘雷达
            tp_price, open_price = self._activate_vps_radar(side)

            # 5. 推送开仓战报
            report = (
                f"### 🚀 [CoinW] 短线刺客出击\n\n"
                f"| 项目 | 详情 |\n"
                f"| :--- | :--- |\n"
                f"| **方向** | <font color='#FF0000'>{side}</font> |\n"
                f"| **本金** | `{usdt_amount} USDT` (50%) |\n"
                f"| **杠杆** | 20x |\n"
                f"| **开仓** | `{open_price}` |\n\n"
                f"🎯 **VPS 主动盯盘目标**: `{tp_price}` *(13刀极速一刀切)*"
            )
            self.notifier.send_markdown(f"短线开仓 {side}", report)

        except Exception as e:
            logger.error(f"战场异常: {e}", exc_info=True)

    def _activate_vps_radar(self, side: str):
        """反推真实开仓价，并启动 VPS 主动监控线程"""
        pos_info = self.client.get_position_info(self.symbol)
        open_price = 0.0
        
        data = pos_info.get("data", [])
        if data and len(data) > 0:
            open_price = float(data[0].get("openPrice", 0))

        if open_price <= 0:
            open_price = self.client.get_current_price(self.symbol)

        if side == "LONG":
            tp_price = round(open_price + self.tp_eth_price_diff, 2)
        else:
            tp_price = round(open_price - self.tp_eth_price_diff, 2)

        # 启动每秒一次的极速雷达
        if self.monitor_thread is None or not self.monitor_thread.is_alive():
            self.monitor_thread = threading.Thread(
                target=self._price_monitor_daemon, 
                args=(side, tp_price)
            )
            self.monitor_thread.daemon = True
            self.monitor_thread.start()
            
        return tp_price, open_price

    def _price_monitor_daemon(self, side, tp_target_price):
        """VPS 上帝视角雷达：每 1.5 秒刷新现价，到达直接开枪全平"""
        logger.info(f"👁️‍🗨️ VPS 雷达已锁定目标价 {tp_target_price}，进入极速高频盯盘模式...")
        
        while self.status == "OPEN":
            try:
                current_price = self.client.get_current_price(self.symbol)
                if current_price <= 0:
                    time.sleep(1)
                    continue

                # 核心绝杀逻辑：涨破/跌破目标价，直接斩仓！
                if side == "LONG" and current_price >= tp_target_price:
                    logger.info(f"✨ 多单突破 {tp_target_price}! 执行斩仓！")
                    self._close_all("🎯 斩获 13U 盘口差价，VPS 主动极速落袋！")
                    break
                    
                elif side == "SHORT" and current_price <= tp_target_price:
                    logger.info(f"✨ 空单跌破 {tp_target_price}! 执行斩仓！")
                    self._close_all("🎯 斩获 13U 盘口差价，VPS 主动极速落袋！")
                    break
                    
            except Exception:
                pass
            
            time.sleep(1.5) # 极速高频雷达

    def _close_all(self, reason):
        logger.info(f"🧹 {reason}")
        was_open = (self.status == "OPEN")
        self.status = "CLOSING" 
        
        self.client.cancel_all_open_orders(self.symbol)
        time.sleep(0.5) 
        
        self.client.close_all_positions(self.symbol)
        
        if was_open: 
            msg = f"### 💥 [CoinW] 阵地清算\n\n**动作**: {reason}\n\n**状态**: 挂单与持仓已被 VPS 强制彻底抹除。"
            self.notifier.send_markdown("系统清场", msg)
            
        self.status = "CLOSED"

coinw_processor = SignalProcessor()
