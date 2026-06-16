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
        self.leverage = 5
        
        self.risk_ratio = 0.80           
        self.tp1_fixed_usdt = 2.0        
        self.tp2_balance_percent = 0.01  
        
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
            self._close_all(f"🔄 接收到反转信号 {side}，执行清场护城河")
            time.sleep(1.5)

            total_balance = self.client.get_available_balance()
            if total_balance < 10:
                msg = f"❌ **资金枯竭**\n\n当前余额 `{total_balance:.2f} U` 不足，系统放弃开仓！"
                self.notifier.send_markdown("报警: 余额不足", msg)
                return

            usdt_amount = round(total_balance * self.risk_ratio, 2)
            open_result = self.client.place_market_order(self.symbol, side, usdt_amount, self.leverage)
            
            if str(open_result.get("code")) not in ["200", "0"]:
                self.notifier.send_markdown("报警: 开仓失败", f"交易所回执拒单:\n\n`{open_result}`")
                return

            self.status = "OPEN"
            time.sleep(2.0)

            # 激活后台盯盘并计算目标，获取标尺参数
            tp1_price, tp2_price, open_price = self._activate_sniper_mode(side, usdt_amount, total_balance)

            # 发送开仓战报
            report = (
                f"### 🚀 [CoinW] 战机起飞\n\n"
                f"**作战方向**: <font color='#FF0000'>{side}</font>\n\n"
                f"**动用本金**: `{usdt_amount} USDT` (80%)\n\n"
                f"**开仓均价**: `{open_price}`\n\n"
                f"---\n\n"
                f"🎯 **[防线一]**: `{tp1_price}` *(落袋 {self.tp1_fixed_usdt}U + 覆盖手续费)*\n\n"
                f"🎯 **[防线二]**: `{tp2_price}` *(全平，赚取总本金 1%)*"
            )
            self.notifier.send_markdown(f"开仓战报 {side}", report)

        except Exception as e:
            logger.error(f"战场异常: {e}", exc_info=True)

    def _activate_sniper_mode(self, side: str, usdt_amount: float, total_balance: float):
        pos_info = self.client.get_position_info(self.symbol)
        open_price = 0.0
        data = pos_info.get("data", [])
        if data and len(data) > 0:
            open_price = float(data[0].get("openPrice", 0))

        if open_price <= 0:
            open_price = self.client.get_current_price(self.symbol)

        total_notional = usdt_amount * self.leverage
        half_notional = total_notional * 0.5 
        estimated_fee = total_notional * 0.0015 
        
        tp1_pct = (self.tp1_fixed_usdt + estimated_fee) / half_notional
        tp2_target_usdt = total_balance * self.tp2_balance_percent
        tp2_pct = tp2_target_usdt / half_notional

        if side == "LONG":
            tp1_price = round(open_price * (1 + tp1_pct), 2)
            tp2_price = round(open_price * (1 + tp2_pct), 2)
        else:
            tp1_price = round(open_price * (1 - tp1_pct), 2)
            tp2_price = round(open_price * (1 - tp2_pct), 2)

        if self.monitor_thread is None or not self.monitor_thread.is_alive():
            self.monitor_thread = threading.Thread(
                target=self._price_monitor_daemon, 
                args=(side, tp1_price, tp2_price)
            )
            self.monitor_thread.daemon = True
            self.monitor_thread.start()
            
        return tp1_price, tp2_price, open_price

    def _price_monitor_daemon(self, side, tp1_price, tp2_price):
        tp1_done = False
        while self.status == "OPEN":
            try:
                current_price = self.client.get_current_price(self.symbol)
                if current_price <= 0:
                    time.sleep(1)
                    continue

                if side == "LONG":
                    if current_price >= tp1_price and not tp1_done:
                        self.client.close_partial_position_market(self.symbol, rate="0.5")
                        msg = f"### ✨ [CoinW] 防线一击破\n\n**突破价格**: `{current_price}`\n\n**战术动作**: 斩仓 50%，利润 `{self.tp1_fixed_usdt}U` 已落袋，底仓继续奔跑！"
                        self.notifier.send_markdown("止盈捷报 TP1", msg)
                        tp1_done = True
                    elif current_price >= tp2_price and tp1_done:
                        self._close_all("🎯 达成 1% 终极收益目标，落袋为安")
                        break
                else: 
                    if current_price <= tp1_price and not tp1_done:
                        self.client.close_partial_position_market(self.symbol, rate="0.5")
                        msg = f"### ✨ [CoinW] 防线一击破\n\n**跌破价格**: `{current_price}`\n\n**战术动作**: 斩仓 50%，利润 `{self.tp1_fixed_usdt}U` 已落袋，底仓继续奔跑！"
                        self.notifier.send_markdown("止盈捷报 TP1", msg)
                        tp1_done = True
                    elif current_price <= tp2_price and tp1_done:
                        self._close_all("🎯 达成 1% 终极收益目标，落袋为安")
                        break
            except Exception:
                pass
            time.sleep(1.5)

    def _close_all(self, reason):
        logger.info(f"🧹 {reason}")
        
        cancel_res = self.client.cancel_all_open_orders(self.symbol)
        time.sleep(0.5) 
        close_res = self.client.close_all_positions(self.symbol)
        
        if self.status == "OPEN":  # 只在有仓位被平掉时发送清场报告，防止日志刷屏
            msg = f"### 💥 [CoinW] 焦土清场\n\n**触发原因**: {reason}\n\n**执行动作**: 已撤销所有遗留挂单并市价全平。"
            self.notifier.send_markdown("系统清场", msg)
            
        self.status = "CLOSED"

coinw_processor = SignalProcessor()
