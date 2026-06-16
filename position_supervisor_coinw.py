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
        
        self.risk_ratio = 0.80           # 动用 80% 余额
        self.tp1_fixed_usdt = 5.0        # TP1 纯利 5 USDT
        self.tp2_balance_percent = 0.03  # TP2 纯利总本金的 3%
        
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
            self._close_all(f"新号角 {side} 吹响，正在清理过往战局")
            time.sleep(1.5)

            total_balance = self.client.get_available_balance()
            if total_balance < 10:
                logger.warning(f"❌ 资金枯竭 (当前 {total_balance:.2f} U)，放弃开仓")
                return

            usdt_amount = round(total_balance * self.risk_ratio, 2)
            logger.info(f"💰 账户可用: {total_balance:.2f} USDT | 准星锁定 80%: {usdt_amount:.2f} USDT")

            open_result = self.client.place_market_order(self.symbol, side, usdt_amount, self.leverage)
            if str(open_result.get("code")) not in ["200", "0"]:
                logger.error(f"❌ 开仓受挫: {open_result}")
                return

            logger.info(f"✅ {side} 开仓成功! 准备建立盘口护盾...")
            self.status = "OPEN"
            time.sleep(2.0)

            self._setup_defense_system(side, usdt_amount, total_balance)

        except Exception as e:
            logger.error(f"战场异常: {e}", exc_info=True)

    def _setup_defense_system(self, side: str, usdt_amount: float, total_balance: float):
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

        logger.info(f"🎯 止盈阵地已确认 (开仓价: {open_price}):")
        logger.info(f"   -> [一防] {tp1_price} (锁定 5.0U 战果)")
        logger.info(f"   -> [二防] {tp2_price} (锁定本金 3% 战果)")

        res1 = self.client.place_limit_close_order(self.symbol, tp1_price, rate="0.5")
        time.sleep(0.5)
        res2 = self.client.place_limit_close_order(self.symbol, tp2_price, rate="1.0")
        
        logger.info(f"🛡️ 盘口护盾建立状态: TP1[{res1.get('code')}] | TP2[{res2.get('code')}]")

        if self.monitor_thread is None or not self.monitor_thread.is_alive():
            self.monitor_thread = threading.Thread(
                target=self._price_monitor_daemon, 
                args=(side, tp1_price, tp2_price)
            )
            self.monitor_thread.daemon = True
            self.monitor_thread.start()

    def _price_monitor_daemon(self, side, tp1_price, tp2_price):
        logger.info("👁️‍🗨️ 交易大脑上帝视角已开启，实时盯盘中...")
        tp1_done = False
        
        while self.status == "OPEN":
            try:
                current_price = self.client.get_current_price(self.symbol)
                if current_price <= 0:
                    time.sleep(2)
                    continue

                if side == "LONG":
                    if current_price >= tp1_price and not tp1_done:
                        logger.info(f"✨ 价格突破 TP1({tp1_price})，确认第一防线战果！")
                        tp1_done = True
                    elif current_price >= tp2_price:
                        logger.info(f"🚀 价格突破 TP2({tp2_price})，执行终局清场！")
                        self._close_all("触发二段终极目标")
                        break
                else: 
                    if current_price <= tp1_price and not tp1_done:
                        logger.info(f"✨ 价格跌破 TP1({tp1_price})，确认第一防线战果！")
                        tp1_done = True
                    elif current_price <= tp2_price:
                        logger.info(f"🚀 价格跌破 TP2({tp2_price})，执行终局清场！")
                        self._close_all("触发二段终极目标")
                        break
            except Exception:
                pass
            time.sleep(1.5)

    def _close_all(self, reason):
        """【终极护城河】先索敌撤单，再焦土全平，顺序不能错"""
        logger.info(f"🧹 {reason}")
        
        # 1. 索敌与摧毁：精准逐一撤销当前挂单
        cancel_res = self.client.cancel_all_open_orders(self.symbol)
        logger.info(f"🗑️ 遗留挂单清理报告: {cancel_res.get('msg')}")
        time.sleep(1.0) # 留给交易所撮合引擎一秒的时间释放冻结额度
        
        # 2. 焦土政策：强制市价全平现存仓位
        close_res = self.client.close_all_positions(self.symbol)
        logger.info(f"💥 强制市价全平回执: {close_res}")
        time.sleep(1.0)
        
        self.status = "CLOSED"

coinw_processor = SignalProcessor()
