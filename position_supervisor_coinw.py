#!/usr/bin/env python3
# position_supervisor_coinw.py（V6.0 洁癖清场 + 1h波段超长耐心 + 狂暴双向死咬机制）
import logging
import time
import threading
from coinw_client import CoinWClient
import dingtalk

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] Supervisor: %(message)s')
logger = logging.getLogger(__name__)

# 实例化币赢专属通信网关
coinw_client = CoinWClient()

class CoinWProcessor:
    def __init__(self):
        self.monitoring = False
        self.leverage = 20
        self.monitor_thread = None
        self._lock = threading.Lock()
        
        # 核心战略：分批止盈目标 (距离开仓价的 U 数)
        self.tp1_diff = 7.0   # 到达 7U，切除 50%
        self.tp2_diff = 15.0  # 到达 15U，全平收网
        
        logger.info("🟢 [CoinW] 1h波段极核引擎初始化完成，洁癖清场与狂暴雷达已就绪。")

    def process_signal(self, payload: dict):
        action = payload.get("action", "").upper()
        if not action: return

        # 切断现有的极速雷达，防止后台还在试图斩仓
        with self._lock:
            self.monitoring = False 

        # ==========================================
        # 场景一：TV 主动全平信号
        # ==========================================
        if action == "CLOSE":
            self._close_all("接收到 TV 主动平仓信号，执行绝对清场")
            return

        # ==========================================
        # 场景二：开仓指令 (启用开仓死咬机制)
        # ==========================================
        if action in ["LONG", "SHORT"]:
            # 【记录 TV 发出信号瞬间的盘口价格】作为参照物
            signal_price = payload.get("price")
            if not signal_price:
                signal_price = coinw_client.get_current_price("ETH")
            
            logger.info(f"📡 接收到 TV {action} 信号！当前理论预期价: {signal_price}")

            # 1. 绝对先决条件：不论同向还是反向，先强制重置阵地！确保永远只有单向一手！
            self._close_all(f"强制重置阵地: 准备执行新方向 {action}")
            
            # 2. 调用狂暴开仓引擎
            success, entry_price, margin, attempts = self._execute_pitbull_open(action)
            
            if success:
                # 真实建仓成功，启动分批止盈雷达
                self._report_open(action, margin, signal_price, entry_price, attempts)
                self._start_radar(action, entry_price)
            else:
                self._report_timeout()

    # ==========================================
    # 绝对焦土清场协议 (Absolute Zero Protocol)
    # ==========================================
    def _close_all(self, reason: str):
        """
        洁癖清场：绝不留一针一线。
        撤销一切限价单 -> 平掉一切实盘仓 -> 核对账本。如果没清干净，再来一遍！
        """
        logger.info(f"🧹 开始执行绝对清场: {reason}")
        for attempt in range(3):
            # 1. 杀掉所有的限价单/计划单
            coinw_client.cancel_all_open_orders(symbol="ETH")
            time.sleep(0.5)
            
            # 2. 发起全域平仓指令
            coinw_client.close_all_positions(symbol="ETH")
            time.sleep(1.0)
            
            # 3. 核对实盘，确保干净纯粹
            if not self._get_active_position():
                if reason:
                    self._report_clear(reason)
                return
                
            logger.warning(f"⚠️ 第 {attempt+1} 次清场后仍发现残余仓位，继续清剿！")

        logger.error("🚨 警告：经过 3 轮极致扫荡，阵地仍未彻底清空，请警惕极端深度！")

    # ==========================================
    # 狂暴开仓死咬机制 (1h 级别超长耐心专属版)
    # ==========================================
    def _execute_pitbull_open(self, action: str):
        """
        开仓死咬：挂单后等待 30 秒，没成交就撤单刷新现价重挂。
        最多循环 10 次，总耐心长达 5 分钟 (300秒)！
        返回: (是否成功, 最终均价, 动用本金, 尝试次数)
        """
        for attempt in range(1, 11):
            # 【铁律】：每次重新尝试入场前，必须清理可能存在的限价废单
            coinw_client.cancel_all_open_orders(symbol="ETH")
            time.sleep(0.2)

            balance = coinw_client.get_available_balance()
            if balance < 10:
                logger.warning(f"[CoinW] 账户余额不足 ({balance} USDT)，放弃建仓。")
                return False, 0.0, 0.0, attempt
                
            margin = balance * 0.50
            amount = margin * self.leverage
            
            logger.info(f"🐶 [狂暴开仓] 第 {attempt}/10 次尝试咬住盘口... (方向: {action})")
            coinw_client.place_market_order(symbol="ETH", side=action, amount=amount, leverage=self.leverage)
            
            # 等待 30 秒，每一秒核对一次实盘账本
            for _ in range(30):
                time.sleep(1)
                pos = self._get_active_position()
                if pos:
                    logger.info(f"✅ 实盘已确认持仓！建仓均价: {pos['entry_price']}")
                    return True, pos['entry_price'], margin, attempt
                    
            # 30秒没吃上，准备进入下一轮循环重新获取最新价
            logger.warning(f"⚠️ 现价逃逸，第 {attempt} 次挂单未在 30 秒内成交，准备重新测距...")
            
        return False, 0.0, 0.0, 10

    # ==========================================
    # 狂暴止盈死咬机制 (防卡单 + 防堆积终极版)
    # ==========================================
    def _execute_pitbull_close(self, action: str, target_ratio: float, level_name: str):
        """
        止盈死咬：强制调用 API 底层切除仓位，不见兔子不撒鹰！
        最多狂暴轰炸 10 次，且每次轰炸失败后，立刻清空限价废单。
        """
        for attempt in range(1, 11):
            pos = self._get_active_position()
            if not pos:
                return True, attempt  # 实盘空了，完美闭环
                
            current_size = pos['size']
            
            # 发起砸盘轰炸
            if target_ratio >= 1.0:
                coinw_client.close_all_positions(symbol="ETH") # 终极全平
            else:
                coinw_client.close_position_partial(symbol="ETH", close_rate=str(target_ratio)) # 底层切除一半
                
            time.sleep(2.0)  # 给撮合引擎 2 秒时间切肉
            
            # 核实切肉结果
            new_pos = self._get_active_position()
            if not new_pos:
                return True, attempt
                
            # 容错判断：只要规模缩小了（说明切肉成功），跳出循环
            if new_pos['size'] < current_size * 0.9:
                return True, attempt
                
            logger.warning(f"⚠️ [CoinW] {level_name} 止盈被交易所深度卡住！清理废单并启动第 {attempt+1} 次狂暴砸盘！")
            
            # 【终极防堆积补丁】：在发起下一次轰炸前，立刻把刚才可能因为深度差而转成限价单挂在盘口的废单彻底撤掉！
            coinw_client.cancel_all_open_orders(symbol="ETH")
            time.sleep(0.5)  # 缓冲时间，确保阵地干净后再进入下一轮循环
            
        return False, 10

    # ==========================================
    # 通用辅助模块
    # ==========================================
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

    # ==========================================
    # 分批极速雷达监控
    # ==========================================
    def _start_radar(self, action: str, entry_price: float):
        with self._lock:
            self.monitoring = True
            
        self.monitor_thread = threading.Thread(
            target=self._radar_loop, 
            args=(action, entry_price), 
            daemon=True
        )
        self.monitor_thread.start()

    def _radar_loop(self, action: str, entry_price: float):
        tp1_price = entry_price + self.tp1_diff if action == "LONG" else entry_price - self.tp1_diff
        tp2_price = entry_price + self.tp2_diff if action == "LONG" else entry_price - self.tp2_diff
        
        tp1_done = False
        logger.info(f"🎯 [极速雷达] 目标死锁: TP1={tp1_price:.2f}, TP2={tp2_price:.2f}")
        
        while self.monitoring:
            try:
                current_price = coinw_client.get_current_price("ETH")
                if current_price <= 0:
                    time.sleep(0.2); continue
                    
                # 阶段一：检测 TP1 (7U 差价)
                if not tp1_done:
                    if (action == "LONG" and current_price >= tp1_price) or \
                       (action == "SHORT" and current_price <= tp1_price):
                        logger.info(f"✨ [雷达] 价格击穿 TP1！启动 50% 斩仓死咬！")
                        success, attempts = self._execute_pitbull_close(action, 0.5, "TP1")
                        tp1_done = True
                        self._report_tp(action, "TP1 半仓落袋", entry_price, current_price, attempts)
                        continue  # 斩仓完毕，继续循环盯着 TP2
                        
                # 阶段二：检测 TP2 (15U 差价)
                if tp1_done:
                    if (action == "LONG" and current_price >= tp2_price) or \
                       (action == "SHORT" and current_price <= tp2_price):
                        logger.info(f"✨ [雷达] 价格击穿 TP2！启动终极全平死咬！")
                        success, attempts = self._execute_pitbull_close(action, 1.0, "TP2")
                        self.monitoring = False
                        self._report_tp(action, "TP2 终极全平", entry_price, current_price, attempts)
                        break

            except Exception:
                pass
            time.sleep(0.2)

    # ==========================================
    # 钉钉极简美学战报 (绝对唯物主义：只报实盘)
    # ==========================================
    def _report_clear(self, reason: str):
        text = f"**动作**：🔄 {reason}\n**状态**：幽灵挂单与双向持仓均已被无死角抹除，当前为**纯净空仓状态**。"
        dingtalk.send_markdown_message("💥 [CoinW] 阵地焦土清算", text)

    def _report_timeout(self):
        text = f"**战况异常**：已连续执行 10 轮扑咬（历时 5 分钟）。\n**原因**：盘口深度不足导致挂单全部落空，系统已彻底强撤并退回空仓待命。"
        dingtalk.send_markdown_message("⏳ [CoinW] 1h波段死咬建仓失败", text)

    def _report_open(self, action: str, margin: float, signal_price: float, entry_price: float, attempts: int):
        emoji = "🟩" if action == "LONG" else "🟥"
        tp1 = entry_price + self.tp1_diff if action == "LONG" else entry_price - self.tp1_diff
        tp2 = entry_price + self.tp2_diff if action == "LONG" else entry_price - self.tp2_diff
        
        text = f"""
| 项目 | 详情 |
| :--- | :--- |
| **方向** | {emoji} <font color="{'#32CD32' if action=='LONG' else '#FF0000'}">**{action}**</font> |
| **TV预期价** | `{signal_price:.2f}` |
| **实盘均价** | **{entry_price:.2f}** |
| **开仓耗时** | 历经 **{attempts}** 轮死咬扑捉 |

🎯 **两段式止盈死锁**: 
- **TP1 (平50%)**: `{tp1:.2f}` (+7U)
- **TP2 (全平)**: `{tp2:.2f}` (+15U)
"""
        dingtalk.send_markdown_message("🚀 [CoinW] 1h波段·实盘建仓成功", text)

    def _report_tp(self, action: str, level: str, entry: float, trigger: float, attempts: int):
        text = f"""
**💰 利润死咬成功！已核实实盘完成切割！**
- **战术阶段**：**{level}**
- **方向**：{action}
- **开仓均价**：{entry}
- **触发斩仓价**：{trigger}
- **轰炸次数**：撤销废单并循环砸盘 **{attempts}** 次后成交

*(雷达继续监控剩余阵地...)*
"""
        dingtalk.send_markdown_message(f"🎉 [CoinW] {level} 捷报", text)

# 全局单例
coinw_processor = CoinWProcessor()
