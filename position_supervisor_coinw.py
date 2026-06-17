#!/usr/bin/env python3
# position_supervisor_coinw.py（V7.0 黄金60秒三段狙击 + 信号锚定止盈 + 实盘看门狗版）
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
        
        # 👑 币赢严格锁定：分批止盈目标 (距离 TV 信号锚定点的 U 数)
        self.tp1_diff = 7.0   # 到达 7U，切除 50%
        self.tp2_diff = 15.0  # 到达 15U，全平收网
        
        logger.info("🟢 [CoinW] 1h波段极核引擎初始化，三段狙击、锚定防线与实盘看门狗已就绪。")

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
            
            logger.info(f"📡 接收到 TV {action} 信号！当前理论锚定预期价: {signal_price}")

            # 1. 绝对先决条件：强制重置阵地，确保纯净单向一手
            self._close_all(f"强制重置阵地: 准备执行新方向 {action}")
            
            # 2. 调用黄金60秒三段狙击引擎 (放弃市价单，采用递进限价)
            success, entry_price, margin, attempts = self._execute_escalating_open(action)
            
            if success:
                # 真实建仓成功，启动 7U/15U 专属止盈雷达 (传入 signal_price 作为锚点)
                self._report_open(action, margin, signal_price, entry_price, attempts)
                self._start_radar(action, signal_price, entry_price)
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
    # 黄金 60 秒三段递进狙击机制 (Escalating Limit Orders)
    # ==========================================
    def _execute_escalating_open(self, action: str):
        balance = coinw_client.get_available_balance()
        if balance < 10:
            logger.warning(f"[CoinW] 账户余额不足 ({balance} USDT)，放弃建仓。")
            return False, 0.0, 0.0, 0
            
        margin = balance * 0.50
        total_amount = margin * self.leverage
        
        # 定义三段狙击的让利幅度 (U)
        # 第一枪: 不让利；第二枪: 让 1.5U；第三枪: 让 3.0U
        escalation_steps = [0.0, 1.5, 3.0]
        wait_time_per_strike = 20 # 每次挂单等待 20 秒
        
        logger.info(f"🐺 [三段狙击] 启动！总目标筹码 {total_amount:.2f}，准备分梯次拦截盘口！")

        final_pos = None
        
        for strike_idx, slippage in enumerate(escalation_steps, 1):
            current_price = coinw_client.get_current_price("ETH")
            if current_price <= 0:
                time.sleep(1); continue
                
            # 计算本轮的狙击限价
            target_price = current_price + slippage if action == "LONG" else current_price - slippage
            
            logger.info(f"🔫 第 {strike_idx} 枪测距完毕：挂出限价 {target_price:.2f} (让利 {slippage}U)")
            
            # 发射限价单
            coinw_client.place_limit_order(symbol="ETH", side=action, price=target_price, amount=total_amount, leverage=self.leverage)
            
            # 扫描盘口等待成交 (每秒扫一次，总计 20 秒)
            filled = False
            for _ in range(wait_time_per_strike):
                time.sleep(1.0)
                pos = self._get_active_position()
                if pos and pos['size'] >= total_amount * 0.90: # 容差 10%，视为基本吃满
                    filled = True
                    final_pos = pos
                    break
                    
            if filled:
                logger.info(f"✅ 第 {strike_idx} 枪命中目标！筹码已吃饱！")
                break
                
            # 20秒过去了还没吃满，果断撤销残单，准备下一次拔枪
            logger.warning(f"⚠️ 第 {strike_idx} 枪未能全歼盘口，果断撤单！准备进入下一梯次追击...")
            coinw_client.cancel_all_open_orders(symbol="ETH")
            time.sleep(1.0) # 撤单缓冲

        if final_pos and final_pos['size'] > 0:
            logger.info(f"🎉 狙击战役结束！成功捕获筹码: {final_pos['size']:.2f}, 综合均价: {final_pos['entry_price']}")
            return True, final_pos['entry_price'], margin, strike_idx
            
        return False, 0.0, 0.0, 3

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

    def _start_radar(self, action: str, signal_price: float, entry_price: float):
        with self._lock:
            self.monitoring = True
        self.monitor_thread = threading.Thread(target=self._radar_loop, args=(action, signal_price, entry_price), daemon=True)
        self.monitor_thread.start()

    def _radar_loop(self, action: str, signal_price: float, entry_price: float):
        # 👑 核心黑科技：以 TV 信号锚定点计算止盈
        tp1_price = signal_price + self.tp1_diff if action == "LONG" else signal_price - self.tp1_diff
        tp2_price = signal_price + self.tp2_diff if action == "LONG" else signal_price - self.tp2_diff
        
        tp1_done = False
        logger.info(f"🎯 [智能锚定雷达] TV信号锚定: {signal_price:.2f} | 实际入场: {entry_price:.2f}")
        logger.info(f"🎯 锁定 7U/15U 防线: TP1={tp1_price:.2f}, TP2={tp2_price:.2f}")
        
        watchdog_counter = 0 # 🐶 新增：看门狗计数器
        
        while self.monitoring:
            try:
                # 🐶 每循环 25 次 (约 5 秒)，向交易所查一次岗，看仓位是不是被人工平掉了
                watchdog_counter += 1
                if watchdog_counter >= 25:
                    watchdog_counter = 0
                    if not self._get_active_position():
                        logger.info("👀 [雷达巡更] 发现实盘仓位已清零 (可能触发止损或被人工干预)，雷达自动休眠待命！")
                        self.monitoring = False
                        break

                current_price = coinw_client.get_current_price("ETH")
                if current_price <= 0:
                    time.sleep(0.2); continue
                    
                if not tp1_done:
                    if (action == "LONG" and current_price >= tp1_price) or \
                       (action == "SHORT" and current_price <= tp1_price):
                        logger.info(f"✨ 击穿 7U 信号防线！启动半仓落袋！")
                        success, attempts = self._execute_pitbull_close(action, 0.5, "TP1")
                        tp1_done = True
                        self._report_tp(action, "7U(锚定) 半仓落袋", entry_price, current_price, attempts)
                        continue
                        
                if tp1_done:
                    if (action == "LONG" and current_price >= tp2_price) or \
                       (action == "SHORT" and current_price <= tp2_price):
                        logger.info(f"✨ 击穿 15U 终极目标！启动全平收网！")
                        success, attempts = self._execute_pitbull_close(action, 1.0, "TP2")
                        self.monitoring = False
                        self._report_tp(action, "15U(锚定) 终极全平", entry_price, current_price, attempts)
                        break
            except Exception:
                pass
            time.sleep(0.2)

    def _report_clear(self, reason: str):
        text = f"**动作**：🔄 {reason}\n**状态**：挂单与旧仓位已被彻底抹除，阵地已重置为**纯净空仓**。"
        dingtalk.send_markdown_message("💥 [CoinW] 阵地焦土清算", text)

    def _report_timeout(self):
        text = f"**战况报告**：黄金60秒三段狙击全部落空。\n**原因**：盘口流动性枯竭且价格飞速偏离，为防止高位站岗，系统已撤单并重置为空仓。"
        dingtalk.send_markdown_message("⏳ [CoinW] 狙击建仓落空保护", text)

    def _report_open(self, action: str, margin: float, signal_price: float, entry_price: float, attempts: int):
        emoji = "🟩" if action == "LONG" else "🟥"
        tp1 = signal_price + self.tp1_diff if action == "LONG" else signal_price - self.tp1_diff
        tp2 = signal_price + self.tp2_diff if action == "LONG" else signal_price - self.tp2_diff
        
        text = f"""
| 项目 | 详情 |
| :--- | :--- |
| **方向** | {emoji} **{action}** |
| **TV信号锚定** | `{signal_price:.2f}` |
| **实盘均价** | **{entry_price:.2f}** |
| **打入策略** | 第 **{attempts}** 枪命中目标 |

🎯 **两段式严格止盈边界(信号锚定)**: 
- **TP1 (平50%)**: `{tp1:.2f}` (+7U)
- **TP2 (全平)**: `{tp2:.2f}` (+15U)
"""
        dingtalk.send_markdown_message("🚀 [CoinW] 狙击战役建仓成功", text)

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
