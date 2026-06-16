#!/usr/bin/env python3
# position_supervisor_coinw.py（完全体 - 数学反推限价 + 后台监控护城河）
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
        
        # 核心资金配置
        self.risk_ratio = 0.80           # 动用 80% 余额
        self.tp1_fixed_usdt = 5.0        # TP1 固定赚取 5 USDT
        self.tp2_balance_percent = 0.03  # TP2 赚取总本金的 3%
        
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
            # 1. 护城河第一步：无脑清理现存仓位和过往未成交挂单
            self._close_all(f"新号角 {side} 吹响，正在清理过往战局")
            time.sleep(1.5)

            # 2. 盘点子弹
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

            logger.info(f"✅ {side} 开仓成功! 准备计算阵地参数...")
            self.status = "OPEN"
            time.sleep(2.0) # 等待交易所记账

            # 4. 进入双轨止盈与监控机制
            self._setup_defense_system(side, usdt_amount, total_balance)

        except Exception as e:
            logger.error(f"战场异常: {e}", exc_info=True)

    def _setup_defense_system(self, side: str, usdt_amount: float, total_balance: float):
        """数学反推引擎与盘口挂单"""
        # 获取真实开仓均价
        pos_info = self.client.get_position_info(self.symbol)
        open_price = 0.0
        data = pos_info.get("data", [])
        if data and len(data) > 0:
            open_price = float(data[0].get("openPrice", 0))

        if open_price <= 0:
            open_price = self.client.get_current_price(self.symbol)

        # ---------------- 数学反推阶段 ----------------
        # 总名义价值 = 投入资金 * 杠杆
        total_notional = usdt_amount * self.leverage
        
        # TP1 价格计算: 目标涨跌幅 = 5U / 总名义价值
        tp1_pct = self.tp1_fixed_usdt / total_notional
        
        # TP2 价格计算: 目标涨跌幅 = (本金的3%) / 总名义价值
        tp2_target_usdt = total_balance * self.tp2_balance_percent
        tp2_pct = tp2_target_usdt / total_notional

        # 确定平仓方向与价格
        if side == "LONG":
            close_side = "SHORT"
            tp1_price = round(open_price * (1 + tp1_pct), 2)
            tp2_price = round(open_price * (1 + tp2_pct), 2)
        else:
            close_side = "LONG"
            tp1_price = round(open_price * (1 - tp1_pct), 2)
            tp2_price = round(open_price * (1 - tp2_pct), 2)

        half_amount = round(usdt_amount * 0.5, 2)

        logger.info(f"🎯 止盈阵地已确认 (开仓价: {open_price}):")
        logger.info(f"   -> [一防] {tp1_price} 派兵 {half_amount}U (锁定 {self.tp1_fixed_usdt}U 战果)")
        logger.info(f"   -> [二防] {tp2_price} 派兵 {half_amount}U (锁定本金 3% 战果)")

        # ---------------- 挂出物理限价单 ----------------
        res1 = self.client.place_limit_order(self.symbol, close_side, tp1_price, half_amount, self.leverage)
        time.sleep(0.5)
        res2 = self.client.place_limit_order(self.symbol, close_side, tp2_price, half_amount, self.leverage)
        
        logger.info(f"🛡️ 盘口护盾建立状态: TP1[{res1.get('code')}] | TP2[{res2.get('code')}]")

        # ---------------- 唤醒后台价格监控 (容错防线) ----------------
        if self.monitor_thread is None or not self.monitor_thread.is_alive():
            self.monitor_thread = threading.Thread(
                target=self._price_monitor_daemon, 
                args=(side, tp1_price, tp2_price, half_amount)
            )
            self.monitor_thread.daemon = True
            self.monitor_thread.start()

    def _price_monitor_daemon(self, side, tp1_price, tp2_price, half_amount):
        """VPS 级价格监控，防止交易所插针漏单"""
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
                        logger.info(f"✨ 价格到达 TP1({tp1_price})，检查挂单成交状态...")
                        tp1_done = True
                    elif current_price >= tp2_price:
                        logger.info(f"🚀 价格突破 TP2({tp2_price})，执行终局收尾！")
                        self._close_all("触发二段终极目标")
                        break
                else: # SHORT
                    if current_price <= tp1_price and not tp1_done:
                        logger.info(f"✨ 价格到达 TP1({tp1_price})，检查挂单成交状态...")
                        tp1_done = True
                    elif current_price <= tp2_price:
                        logger.info(f"🚀 价格突破 TP2({tp2_price})，执行终局收尾！")
                        self._close_all("触发二段终极目标")
                        break

            except Exception as e:
                pass
            
            time.sleep(1.5)

    def _close_all(self, reason):
        logger.info(f"🧹 {reason}")
        self.client.cancel_all_open_orders(self.symbol)
        time.sleep(0.5)
        self.client.close_all_positions(self.symbol)
        self.status = "CLOSED"

coinw_processor = SignalProcessor()
