#!/usr/bin/env python3
import time
import threading
import logging
from coinw_client import CoinWClient

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

class SignalProcessor:
    def __init__(self):
        self.client = CoinWClient()
        self.symbol = "ETH"
        self.leverage = 5
        
        # 保守稳健风控配置
        self.risk_ratio = 0.80           # 动用 80% 余额开仓
        self.tp1_fixed_usdt = 2.0        # TP1 目标：纯赚 2 USDT
        self.tp2_balance_percent = 0.01  # TP2 目标：赚取总本金的 1%
        
        self.monitor_thread = None
        self.status = "IDLE"

    def process_signal(self, data: dict):
        action = data.get("action", "").upper()
        logger.info(f"========== 收到新TV信号: {action} ==========")

        if action == "CLOSE":
            self._close_all("TV 主动平仓信号")
            return

        if action in ["LONG", "SHORT"]:
            self._refresh_position(action)

    def _refresh_position(self, side: str):
        try:
            # 1. 护城河：先索敌撤单，再全平现存仓位
            self._close_all(f"新号角 {side} 吹响，正在清理过往战局")
            time.sleep(1.5)

            # 2. 盘点资金
            total_balance = self.client.get_available_balance()
            if total_balance < 10:
                logger.warning(f"❌ 资金枯竭 (当前 {total_balance:.2f} U)，放弃开仓")
                return

            usdt_amount = round(total_balance * self.risk_ratio, 2)
            logger.info(f"💰 账户可用: {total_balance:.2f} USDT | 准星锁定 80%: {usdt_amount:.2f} USDT")

            # 3. 市价重仓出击
            open_result = self.client.place_market_order(self.symbol, side, usdt_amount, self.leverage)
            if str(open_result.get("code")) not in ["200", "0"]:
                logger.error(f"❌ 开仓受挫: {open_result}")
                return

            logger.info(f"✅ {side} 开仓成功! 进入上帝视角盯盘模式...")
            self.status = "OPEN"
            time.sleep(2.0)

            # 4. 激活后台价格狙击系统
            self._activate_sniper_mode(side, usdt_amount, total_balance)

        except Exception as e:
            logger.error(f"战场异常: {e}", exc_info=True)

    def _activate_sniper_mode(self, side: str, usdt_amount: float, total_balance: float):
        # 获取开仓均价
        pos_info = self.client.get_position_info(self.symbol)
        open_price = 0.0
        data = pos_info.get("data", [])
        if data and len(data) > 0:
            open_price = float(data[0].get("openPrice", 0))

        if open_price <= 0:
            open_price = self.client.get_current_price(self.symbol)

        # ---------------- 数学目标反推 ----------------
        total_notional = usdt_amount * self.leverage
        half_notional = total_notional * 0.5 
        estimated_fee = total_notional * 0.0015 # 预估全局开平双边手续费
        
        # TP1 涨跌幅 = (涵盖全部手续费 + 2U净利) / 50%仓位价值
        tp1_pct = (self.tp1_fixed_usdt + estimated_fee) / half_notional
        
        # TP2 涨跌幅 = (本金1%目标) / 剩余50%仓位价值
        tp2_target_usdt = total_balance * self.tp2_balance_percent
        tp2_pct = tp2_target_usdt / half_notional

        if side == "LONG":
            tp1_price = round(open_price * (1 + tp1_pct), 2)
            tp2_price = round(open_price * (1 + tp2_pct), 2)
        else:
            tp1_price = round(open_price * (1 - tp1_pct), 2)
            tp2_price = round(open_price * (1 - tp2_pct), 2)

        logger.info(f"🎯 狙击标尺已锁定 (开仓价: {open_price}):")
        logger.info(f"   -> [一防] {tp1_price} (市价斩仓 50%，保底 {self.tp1_fixed_usdt}U + 覆盖手续费)")
        logger.info(f"   -> [二防] {tp2_price} (市价全平，赚取本金 1%)")

        if self.monitor_thread is None or not self.monitor_thread.is_alive():
            self.monitor_thread = threading.Thread(
                target=self._price_monitor_daemon, 
                args=(side, tp1_price, tp2_price)
            )
            self.monitor_thread.daemon = True
            self.monitor_thread.start()

    def _price_monitor_daemon(self, side, tp1_price, tp2_price):
        logger.info("👁️‍🗨️ VPS 价格监控雷达启动，最高频轮询中...")
        tp1_done = False
        
        while self.status == "OPEN":
            try:
                current_price = self.client.get_current_price(self.symbol)
                if current_price <= 0:
                    time.sleep(1)
                    continue

                if side == "LONG":
                    if current_price >= tp1_price and not tp1_done:
                        logger.info(f"✨ 突破 TP1({tp1_price})! 正在执行 50% 市价平仓落袋...")
                        res = self.client.close_partial_position_market(self.symbol, rate="0.5")
                        logger.info(f"🔪 TP1 执行回执: {res}")
                        tp1_done = True
                    elif current_price >= tp2_price and tp1_done:
                        logger.info(f"🚀 突破 TP2({tp2_price})! 执行终局清场！")
                        self._close_all("达成 1% 终极收益目标")
                        break
                else: 
                    if current_price <= tp1_price and not tp1_done:
                        logger.info(f"✨ 跌破 TP1({tp1_price})! 正在执行 50% 市价平仓落袋...")
                        res = self.client.close_partial_position_market(self.symbol, rate="0.5")
                        logger.info(f"🔪 TP1 执行回执: {res}")
                        tp1_done = True
                    elif current_price <= tp2_price and tp1_done:
                        logger.info(f"🚀 跌破 TP2({tp2_price})! 执行终局清场！")
                        self._close_all("达成 1% 终极收益目标")
                        break
            except Exception:
                pass
            
            # 提高盯盘频率至 1.5 秒
            time.sleep(1.5)

    def _close_all(self, reason):
        """【终极护城河】先索敌撤单，再市价全平"""
        logger.info(f"🧹 {reason}")
        
        cancel_res = self.client.cancel_all_open_orders(self.symbol)
        if "成功" in cancel_res.get('msg', ''):
            logger.info(f"🗑️ 遗留挂单清理: {cancel_res.get('msg')}")
            time.sleep(0.5) 
        
        close_res = self.client.close_all_positions(self.symbol)
        logger.info(f"💥 强制市价全平回执: {close_res}")
        
        self.status = "CLOSED"

coinw_processor = SignalProcessor()
