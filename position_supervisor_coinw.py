#!/usr/bin/env python3
# position_supervisor_coinw.py（50%仓位 + 20倍杠杆 + 13刀一刀切止盈）
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
        self.leverage = 20               # 20倍重装杠杆
        self.risk_ratio = 0.50           # 【更新】动用可用余额的 50%
        self.tp_eth_price_diff = 13.0    # 【更新】严格死锁 13 美金盘口差价
        
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
            # 1. 斩断过往（同向/反向无差别处理）：
            # 只要有新信号，绝对优先撤销没成交的13刀限价单，并强制市价全平现存持仓，保证永远只有一手
            self._close_all(f"🔄 强制重置阵地：准备执行新方向 {side}")
            time.sleep(1.5) # 给予交易所系统释放冻结资金的缓冲时间

            # 2. 盘点子弹
            total_balance = self.client.get_available_balance()
            if total_balance < 10:
                msg = f"❌ **资金枯竭**\n\n当前余额 `{total_balance:.2f} U` 不足，系统拒绝开仓！"
                self.notifier.send_markdown("报警: 余额不足", msg)
                return

            # 【核心逻辑】使用 50% 可用余额
            usdt_amount = round(total_balance * self.risk_ratio, 2)
            logger.info(f"💰 账户可用: {total_balance:.2f} USDT | 准星锁定 50%: {usdt_amount:.2f} USDT")

            # 3. 闪电市价开仓 (20倍)
            open_result = self.client.place_market_order(self.symbol, side, usdt_amount, self.leverage)
            if str(open_result.get("code")) not in ["200", "0"]:
                self.notifier.send_markdown("报警: 开仓失败", f"交易所拒单回执:\n\n`{open_result}`")
                return

            self.status = "OPEN"
            logger.info(f"✅ {side} 开仓成功! 正在等待交易所仓位 ID 记账...")
            time.sleep(2.0)

            # 4. 提取真实开仓价并挂出原生的限价止盈单 (13刀)
            tp_price, open_price = self._execute_native_limit_tp(side)

            # 5. 推送战报 (适配美学排版)
            report = (
                f"### 🚀 [CoinW] 短线刺客·新局开启\n\n"
                f"| 项目 | 详情 |\n"
                f"| :--- | :--- |\n"
                f"| **方向** | <font color='#FF0000'>{side}</font> |\n"
                f"| **本金** | `{usdt_amount} USDT` (50%) |\n"
                f"| **杠杆** | 20x |\n"
                f"| **开仓** | `{open_price}` |\n\n"
                f"🎯 **限价止盈**: `{tp_price}` *(13刀差价·一刀切)*"
            )
            self.notifier.send_markdown(f"短线开仓 {side}", report)

        except Exception as e:
            logger.error(f"战场异常: {e}", exc_info=True)

    def _execute_native_limit_tp(self, side: str):
        """精准反推并直接向交易所报单簿投递 13刀 极速限价平仓单"""
        pos_info = self.client.get_position_info(self.symbol)
        open_price = 0.0
        
        data = pos_info.get("data", [])
        if data and len(data) > 0:
            open_price = float(data[0].get("openPrice", 0))

        if open_price <= 0:
            open_price = self.client.get_current_price(self.symbol)

        # 【核心逻辑】绝对价格反推：13刀差价
        if side == "LONG":
            tp_price = round(open_price + self.tp_eth_price_diff, 2)
        else:
            tp_price = round(open_price - self.tp_eth_price_diff, 2)

        # 发射纯正的原生限价平仓单 (rate="1.0" 代表 100% 仓位一刀切)
        res = self.client.place_limit_close_order(self.symbol, tp_price, rate="1.0")
        logger.info(f"🛡️ 盘口原生限价护盾建立状态: [{res.get('code')}] | 回执: {res}")
        
        # 激活轻量级止盈巡逻犬，为钉钉捷报做准备
        if self.monitor_thread is None or not self.monitor_thread.is_alive():
            self.monitor_thread = threading.Thread(
                target=self._victory_monitor_daemon, 
                args=(tp_price,)
            )
            self.monitor_thread.daemon = True
            self.monitor_thread.start()
            
        return tp_price, open_price

    def _victory_monitor_daemon(self, tp_price):
        """轻量级巡逻犬：静默检查仓位是否被交易所撮合吃掉"""
        logger.info("🐶 钉钉捷报巡逻犬已放出，静默监控限价单成交状态...")
        while self.status == "OPEN":
            time.sleep(4.0) 
            
            if self.status != "OPEN":
                break
                
            try:
                pos_info = self.client.get_position_info(self.symbol)
                data = pos_info.get("data", [])
                
                # 如果查不到任何持仓，说明 13 刀限价单被交易所成功吃掉了
                if not data or len(data) == 0:
                    logger.info("🎉 仓位已空！判定为原生限价止盈已触发！")
                    msg = (
                        f"### 🎉 [CoinW] 刺客捷报\n\n"
                        f"**战况**: 13刀差价限价单 (`{tp_price}`) 已被顺利吃掉！\n\n"
                        f"**结果**: 利润已落袋，仓位清空，静待下次号角。"
                    )
                    self.notifier.send_markdown("止盈捷报", msg)
                    self.status = "CLOSED"
                    break
            except Exception:
                pass

    def _close_all(self, reason):
        """焦土护城河：先撤销所有挂单，再强制清空持仓"""
        logger.info(f"🧹 {reason}")
        
        # 先切断状态，防止止盈巡逻犬误报
        was_open = (self.status == "OPEN")
        self.status = "CLOSING" 
        
        # 1. 索敌并逐一强制干掉盘口上没成交的 13刀 限价单
        self.client.cancel_all_open_orders(self.symbol)
        time.sleep(0.5) 
        
        # 2. 市价强平现存仓位
        self.client.close_all_positions(self.symbol)
        
        # 发送清场战报
        if was_open: 
            msg = f"### 💥 [CoinW] 阵地重置\n\n**动作**: {reason}\n\n**状态**: 历史限价单已全撤，旧仓位已强制市价清空。"
            self.notifier.send_markdown("系统清场", msg)
            
        self.status = "CLOSED"

coinw_processor = SignalProcessor()
