#!/usr/bin/env python3
# position_supervisor_coinw.py（短线刺客 - 原生限价一刀切完全体）
import time
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
        
        # 10分钟短线超频核心风控配置
        self.leverage = 20               # 20倍重装杠杆
        self.risk_ratio = 0.80           # 动用可用余额的 80%
        self.tp_eth_price_diff = 10.0    # 严格死锁 10 美金盘口差价

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
            # 1. 斩断过往：先扫射所有未成交限价单，再强制市价全平当前持仓
            self._close_all(f"🔄 接收到反转新指令 {side}，前置焦土清理")
            time.sleep(1.5) # 给予交易所系统释放保证金的硬缓冲时间

            # 2. 盘点子弹
            total_balance = self.client.get_available_balance()
            if total_balance < 10:
                msg = f"❌ **资金枯竭**\n\n当前余额 `{total_balance:.2f} U` 不足，系统拒绝开仓！"
                self.notifier.send_markdown("报警: 余额不足", msg)
                return

            usdt_amount = round(total_balance * self.risk_ratio, 2)
            logger.info(f"💰 账户可用: {total_balance:.2f} USDT | 准星锁定 80%: {usdt_amount:.2f} USDT")

            # 3. 闪电市价开仓
            open_result = self.client.place_market_order(self.symbol, side, usdt_amount, self.leverage)
            if str(open_result.get("code")) not in ["200", "0"]:
                self.notifier.send_markdown("报警: 开仓失败", f"交易所拒单回执:\n\n`{open_result}`")
                return

            logger.info(f"✅ {side} 开仓成功! 正在等待交易所仓位 ID 记账...")
            time.sleep(2.0) # 核心延迟：必须等待撮合引擎生成精确的持仓条目

            # 4. 提取真实开仓价并挂出原生的限价止盈单
            tp_price, open_price = self._execute_native_limit_tp(side)

            # 5. 推送战报
            report = (
                f"### 🚀 [CoinW] 短线刺客·全自动挂单\n\n"
                f"**作战方向**: <font color='#FF0000'>{side}</font> *(20x 杠杆)*\n\n"
                f"**开仓动用**: `{usdt_amount} USDT` (80%)\n\n"
                f"**开仓均价**: `{open_price}`\n\n"
                f"---\n\n"
                f"🎯 **交易所原生限价止盈**: `{tp_price}` *(10刀差价·一刀切全平)*\n\n"
                f"💡 *状态: 限价单已死死钉入币赢订单簿，VPS 已释放盯盘线程，纯静默等待成交。*"
            )
            self.notifier.send_markdown(f"短线开仓 {side}", report)

        except Exception as e:
            logger.error(f"战场异常: {e}", exc_info=True)

    def _execute_native_limit_tp(self, side: str):
        """精准反推并直接向交易所报单簿投递限价平仓单"""
        pos_info = self.client.get_position_info(self.symbol)
        open_price = 0.0
        
        data = pos_info.get("data", [])
        if data and len(data) > 0:
            open_price = float(data[0].get("openPrice", 0))

        if open_price <= 0:
            open_price = self.client.get_current_price(self.symbol)

        # 绝对价格反推
        if side == "LONG":
            tp_price = round(open_price + self.tp_eth_price_diff, 2)
        else:
            tp_price = round(open_price - self.tp_eth_price_diff, 2)

        # 发射纯正的原生限价平仓单 (rate="1.0" 代表 100% 仓位一刀切)
        res = self.client.place_limit_close_order(self.symbol, tp_price, rate="1.0")
        logger.info(f"🛡️ 盘口原生限价护盾建立状态: [{res.get('code')}] | 回执: {res}")
        
        return tp_price, open_price

    def _close_all(self, reason):
        """焦土护城河：先撤销所有挂单，再强制清空持仓"""
        logger.info(f"🧹 {reason}")
        
        # 1. 索敌并逐一强制干掉盘口上没成交的限价单
        cancel_res = self.client.cancel_all_open_orders(self.symbol)
        logger.info(f"🗑️ 盘口未成交挂单清理报告: {cancel_res.get('msg')}")
        time.sleep(0.5) 
        
        # 2. 市价强平现存仓位
        close_res = self.client.close_all_positions(self.symbol)
        
        # 发送清场战报
        msg = f"### 💥 [CoinW] 短线全平清场\n\n**触发原因**: {reason}\n\n**执行状态**: 原生限价单已全撤，持仓已强制市价清空。"
        self.notifier.send_markdown("系统清场", msg)
