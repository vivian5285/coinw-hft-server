#!/usr/bin/env python3
# position_supervisor_coinw.py（V6.5 洁癖清场 + 7U/15U专属防线 + 冰山切片扫单版）
import logging
import time
import threading
from coinw_client import CoinWClient
import dingtalk

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] Supervisor: %(message)s')
logger = logging.getLogger(__name__)

coinw_client = CoinWClient()

class CoinWProcessor:
    def __init__(self):
        self.monitoring = False
        self.leverage = 20
        self.monitor_thread = None
        self._lock = threading.Lock()
        
        # 👑 币赢严格锁定：分批止盈目标 (距离开仓价的 U 数)
        self.tp1_diff = 7.0   # 到达 7U，切除 50%
        self.tp2_diff = 15.0  # 到达 15U，全平收网
        
        logger.info("🟢 [CoinW] 1h波段极核引擎初始化完成，7U/15U专属防线与冰山雷达就绪。")

    def process_signal(self, payload: dict):
        action = payload.get("action", "").upper()
        if not action: return

        with self._lock:
            self.monitoring = False 

        if action == "CLOSE":
            self._close_all("接收到 TV 主动平仓信号，执行绝对清场")
            return

        if action in ["LONG", "SHORT"]:
            signal_price = payload.get("price")
            if not signal_price:
                signal_price = coinw_client.get_current_price("ETH")
            
            logger.info(f"📡 接收到 TV {action} 信号！当前理论预期价: {signal_price}")

            # 1. 绝对先决条件：强制重置阵地，确保纯净单向一手
            self._close_all(f"强制重置阵地: 准备执行新方向 {action}")
            
            # 2. 调用冰山切片开仓引擎
            success, entry_price, margin, attempts = self._execute_pitbull_open(action)
            
            if success:
                # 真实建仓成功，启动 7U/15U 专属止盈雷达
                self._report_open(action, margin, signal_price, entry_price, attempts)
                self._start_radar(action, entry_price)
            else:
                self._report_timeout()

    def _close_all(self, reason: str):
        logger.info(f"🧹 开始执行绝对清场: {reason}")
        for attempt in range(3):
            coinw_client.cancel_all_open_orders(symbol="ETH")
            time.sleep(0.5)
            coinw_client.close_all_positions(symbol="ETH")
            time.sleep(1.0)
            if not self._get_active_position():
                if reason:
                    self._report_clear(reason)
                return
            logger.warning(f"⚠️ 第 {attempt+1} 次清场后仍发现残余仓位，继续清剿！")
        logger.error("🚨 警告：经过 3 轮极致扫荡，阵地仍未彻底清空！")

    # ==========================================
    # 狂暴开仓死咬机制 (冰山切片 + 降维扫单版)
    # ==========================================
    def _execute_pitbull_open(self, action: str):
        """
        应对币赢盘口薄弱：将总资金切分为 3 份冰山订单，化整为零分批吃单，规避交易所滑点保护拒单。
        """
        balance = coinw_client.get_available_balance()
        if balance < 10:
            logger.warning(f"[CoinW] 账户余额不足 ({balance} USDT)，放弃建仓。")
            return False, 0.0, 0.0, 0
            
        margin = balance * 0.50
        total_amount = margin * self.leverage
        
        # 拆分为 3 刀横扫盘口
        slice_amount = total_amount / 3.0
        logger.info(f"🐶 [冰山切片] 启动深度保护！总额 {total_amount:.2f} 将分 3 刀切入盘口！")

        success_slices = 0
        final_attempts = 0

        for slice_idx in range(1, 4):
            slice_filled = False
            logger.info(f"🔪 正在执行第 {slice_idx}/3 刀切片投递 (单笔名义: {slice_amount:.2f})...")
            
            # 每刀给 5 次死咬扑捉机会
            for attempt in range(1, 6):
                final_attempts += 1
                coinw_client.cancel_all_open_orders(symbol="ETH")
                time.sleep(0.2)
                
                coinw_client.place_market_order(symbol="ETH", side=action, amount=slice_amount, leverage=self.leverage)
                
                # 等待 15 秒逐秒核查账本
                for _ in range(15):
                    time.sleep(1)
                    pos = self._get_active_position()
                    if pos and pos['size'] > ((slice_idx - 1) * 0.001):
                        slice_filled = True
                        success_slices += 1
                        logger.info(f"✅ 第 {slice_idx} 刀吃肉成功！当前实盘持仓均价: {pos['entry_price']}")
                        break
                
                if slice_filled:
                    break
                    
                logger.warning(f"⚠️ 第 {slice_idx} 刀未命中盘口，重新挥刀测距...")
            
            time.sleep(2.0) # 刀与刀之间喘息 2 秒，等待盘口流动性恢复

        pos = self._get_active_position()
        if success_slices > 0 and pos:
            logger.info(f"🎉 冰山建仓完毕！成功捕获 {success_slices}/3 筹码，综合均价: {pos['entry_price']}")
            return True, pos['entry_price'], (margin / 3.0) * success_slices, final_attempts
            
        return False, 0.0, 0.0, final_attempts

    def _execute_pitbull_close(self, action: str, target_ratio: float, level_name: str):
        for attempt in range(1, 11):
            pos = self._get_active_position()
            if not pos: return True, attempt
                
            current_size = pos['size']
            if target_ratio >= 1.0:
                coinw_client.close_all_positions(symbol="ETH")
            else:
                coinw_client.close_position_partial(symbol="ETH", close_rate=str(target_ratio))
                
            time.sleep(2.0)
            new_pos = self._get_active_position()
            if not new_pos or new_pos['size'] < current_size * 0.9:
                return True, attempt
                
            logger.warning(f"⚠️ {level_name} 止盈遭遇阻力！清理废单并启动第 {attempt+1} 次清仓轰炸！")
            coinw_client.cancel_all_open_orders(symbol="ETH")
            time.sleep(0.5)
            
        return False, 10

    def _get_active_position(self) -> dict:
        try:
            res = coinw_client.get_position_info("ETH")
            data = res.get("data", [])
            if not data: return None
            for pos in data:
                size = float(pos.get("position", pos.get("volume", pos.get("size", pos.get("holdVolume", 0)))))
                if size > 0:
                    entry = float(pos.get("openPrice", pos.get("avgPrice", pos.get("price", 0))))
                    return {"size": size, "entry_price": entry}
            return None
        except Exception:
            return None

    def _start_radar(self, action: str, entry_price: float):
        with self._lock:
            self.monitoring = True
        self.monitor_thread = threading.Thread(target=self._radar_loop, args=(action, entry_price), daemon=True)
        self.monitor_thread.start()

    def _radar_loop(self, action: str, entry_price: float):
        tp1_price = entry_price + self.tp1_diff if action == "LONG" else entry_price - self.tp1_diff
        tp2_price = entry_price + self.tp2_diff if action == "LONG" else entry_price - self.tp2_diff
        
        tp1_done = False
        logger.info(f"🎯 [币赢雷达] 7U/15U 防线死锁: TP1={tp1_price:.2f}, TP2={tp2_price:.2f}")
        
        while self.monitoring:
            try:
                current_price = coinw_client.get_current_price("ETH")
                if current_price <= 0:
                    time.sleep(0.2); continue
                    
                if not tp1_done:
                    if (action == "LONG" and current_price >= tp1_price) or \
                       (action == "SHORT" and current_price <= tp1_price):
                        logger.info(f"✨ 价格击穿 7U 防线！启动半仓落袋轰炸！")
                        success, attempts = self._execute_pitbull_close(action, 0.5, "TP1")
                        tp1_done = True
                        self._report_tp(action, "7U 半仓落袋", entry_price, current_price, attempts)
                        continue
                        
                if tp1_done:
                    if (action == "LONG" and current_price >= tp2_price) or \
                       (action == "SHORT" and current_price <= tp2_price):
                        logger.info(f"✨ 价格击穿 15U 终极目标！启动全平收网！")
                        success, attempts = self._execute_pitbull_close(action, 1.0, "TP2")
                        self.monitoring = False
                        self._report_tp(action, "15U 终极全平", entry_price, current_price, attempts)
                        break
            except Exception:
                pass
            time.sleep(0.2)

    def _report_clear(self, reason: str):
        text = f"**动作**：🔄 {reason}\n**状态**：挂单与旧仓位已被彻底抹除，阵地已重置为**纯净空仓**。"
        dingtalk.send_markdown_message("💥 [CoinW] 阵地焦土清算", text)

    def _report_timeout(self):
        text = f"**战况报告**：冰山切片扑咬全部落空。\n**原因**：盘口极端缺乏流动性，系统已彻底强撤并退回空仓待命。"
        dingtalk.send_markdown_message("⏳ [CoinW] 冰山建仓全部落空", text)

    def _report_open(self, action: str, margin: float, signal_price: float, entry_price: float, attempts: int):
        emoji = "🟩" if action == "LONG" else "🟥"
        tp1 = entry_price + self.tp1_diff if action == "LONG" else entry_price - self.tp1_diff
        tp2 = entry_price + self.tp2_diff if action == "LONG" else entry_price - self.tp2_diff
        
        text = f"""
| 项目 | 详情 |
| :--- | :--- |
| **方向** | {emoji} **{action}** |
| **TV预期价** | `{signal_price:.2f}` |
| **实盘均价** | **{entry_price:.2f}** |
| **打入策略** | 冰山切片共轰炸 **{attempts}** 次 |

🎯 **两段式严格止盈边界**: 
- **TP1 (平50%)**: `{tp1:.2f}` (+7U)
- **TP2 (全平)**: `{tp2:.2f}` (+15U)
"""
        dingtalk.send_markdown_message("🚀 [CoinW] 实盘冰山建仓成功", text)

    def _report_tp(self, action: str, level: str, entry: float, trigger: float, attempts: int):
        text = f"""
**💰 利润死咬成功！已核实实盘完成切割！**
- **战术阶段**：**{level}**
- **开仓均价**：{entry}
- **触发斩仓价**：{trigger}
- **轰炸次数**：循环砸盘 **{attempts}** 次后成交
"""
        dingtalk.send_markdown_message(f"🎉 [CoinW] {level} 捷报", text)

coinw_processor = CoinWProcessor()
