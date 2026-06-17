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
        
        # 极速快进快出核心风控配置
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
            # 1. 焦土重置：无论是多接多，还是多接空，一律无差别先撤单再全平！
            self._close_all(f"🔄 强制重置阵地：准备执行新方向 {side}")
            time.sleep(1.5) 

            # 2. 盘点子弹
            total_balance = self.client.get_available_balance()
            if total_balance < 10:
                msg = f"❌ **资金枯竭**\n\n当前余额 `{total_balance:.2f} U` 不足，系统拒绝开仓！"
                self.notifier.send_markdown("报警: 余额不足", msg)
                return

            usdt_amount = round(total_balance * self.risk_ratio, 2)
            logger.info(f"💰 账户可用: {total_balance:.2f} USDT | 动用 50%: {usdt_amount:.2f} USDT")

            # 3. 闪电市价开仓 (20倍)
            open_result = self.client.place_market_order(self.symbol, side, usdt_amount, self.leverage)
            if str(open_result.get("code")) not in ["200", "0"]:
                self.notifier.send_markdown("报警: 开仓失败", f"交易所拒单回执:\n\n`{open_result}`")
                return

            self.status = "OPEN"
            logger.info(f"✅ {side} 纯市价开仓成功! 正在等待交易所生成持仓 ID...")
            time.sleep(2.0) # 留出时间让交易所生成真实的持仓，保证下一步挂止盈必定成功

            # 4. 提取真实开仓价并挂出原生的限价止盈单 (13刀)
            tp_price, open_price = self._execute_native_limit_tp(side)

            # 5. 推送战报
            report = (
                f"### 🚀 [CoinW] 短线刺客·新局开启\n\n"
                f"| 项目 | 详情 |\n"
                f"| :--- | :--- |\n"
                f"| **方向** | <font color='#FF0000'>{side}</font> |\n"
                f"| **本金** | `{usdt_amount} USDT` (50%) |\n"
                f"| **杠杆** | 20x |\n"
                f"| **开仓均价** | `{open_price}` |\n\n"
                f"🎯 **限价止盈已挂出**: `{tp_price}` *(13刀差价·一刀切)*"
            )
            self.notifier.send_markdown(f"短线开仓 {side}", report)

        except Exception as e:
            logger.error(f"战场异常: {e}", exc_info=True)

    def _execute_native_limit_tp(self, side: str):
        pos_info = self.client.get_position_info(self.symbol)
        open_price = 0.0
        
        data = pos_info.get("data", [])
        if data and len(data) > 0:
            open_price = float(data[0].get("openPrice", 0))

        if open_price <= 0:
            logger.warning("未获取到持仓均价，改用现价计算止盈！")
            open_price = self.client.get_current_price(self.symbol)

        if side == "LONG":
            tp_price = round(open_price + self.tp_eth_price_diff, 2)
        else:
            tp_price = round(open_price - self.tp_eth_price_diff, 2)

        res = self.client.place_limit_close_order(self.symbol, tp_price, rate="1.0")
        logger.info(f"🛡️ 盘口原生限价挂单状态: [{res.get('code')}] | 回执: {res}")
        
        if self.monitor_thread is None or not self.monitor_thread.is_alive():
            self.monitor_thread = threading.Thread(
                target=self._victory_monitor_daemon, 
                args=(tp_price,)
            )
            self.monitor_thread.daemon = True
            self.monitor_thread.start()
            
        return tp_price, open_price

    def _victory_monitor_daemon(self, tp_price):
        logger.info("🐶 钉钉捷报巡逻犬已放出，静默监控限价单成交状态...")
        while self.status == "OPEN":
            time.sleep(4.0) 
            
            if self.status != "OPEN":
                break
                
            try:
                pos_info = self.client.get_position_info(self.symbol)
                data = pos_info.get("data", [])
                
                if not data or len(data) == 0:
                    logger.info("🎉 仓位已空！判定为原生限价止盈已触发！")
                    msg = (
                        f"### 🎉 [CoinW] 刺客捷报\n\n"
                        f"**战况**: 13刀差价限价单 (`{tp_price}`) 已被顺利吃掉！\n\n"
                        f"**结果**: 利润已落袋，仓位彻底清空，静待下次号角。"
                    )
                    self.notifier.send_markdown("止盈捷报", msg)
                    self.status = "CLOSED"
                    break
            except Exception:
                pass

    def _close_all(self, reason):
        logger.info(f"🧹 {reason}")
        was_open = (self.status == "OPEN")
        self.status = "CLOSING" 
        
        # 1. 彻底撤销未成交的限价单
        cancel_res = self.client.cancel_all_open_orders(self.symbol)
        logger.info(f"清理挂单: {cancel_res}")
        time.sleep(0.5) 
        
        # 2. 逐一绞杀所有持仓（哪怕乌龙多空双开了，也会一个个杀干净）
        close_res = self.client.close_all_positions(self.symbol)
        logger.info(f"清理持仓: {close_res}")
        
        if was_open: 
            msg = f"### 💥 [CoinW] 阵地重置\n\n**动作**: {reason}\n\n**状态**: 历史限价单已全撤，旧仓位已强制市价清空。"
            self.notifier.send_markdown("系统清场", msg)
            
        self.status = "CLOSED"

coinw_processor = SignalProcessor()
