#!/usr/bin/env python3
# position_supervisor_coinw.py（V4.0 1h波段 + 分批止盈 + 狂暴死咬机制）
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
        
        # 核心战略升级：分批止盈目标 (距离开仓价的差价)
        self.tp1_diff = 7.0   # 到达 7U 差价，平 50%
        self.tp2_diff = 15.0  # 再涨 8U (总计 15U)，平剩余 100%
        
        logger.info("🟢 [CoinW] 1h波段引擎初始化完成，狂暴追杀雷达待命。")

    def process_signal(self, payload: dict):
        action = payload.get("action", "").upper()
        if not action:
            return

        # 切断旧雷达
        with self._lock:
            self.monitoring = False 

        # ==========================================
        # 场景一：TV 主动全平信号
        # ==========================================
        if action == "CLOSE":
            self._close_all("接收到 TV 1h级别主动平仓信号")
            return

        # ==========================================
        # 场景二：开仓指令 (耐心升级：180秒)
        # ==========================================
        if action in ["LONG", "SHORT"]:
            self._close_all(f"强制重置阵地: 准备执行新方向 {action}")

            balance = coinw_client.get_available_balance()
            if balance < 10:
                logger.warning(f"[CoinW] 账户余额不足 ({balance} USDT)，放弃建仓。")
                return
                
            margin = balance * 0.50
            amount = margin * self.leverage
            
            logger.info(f"[CoinW] 发射开仓指令: {action} (本金: {margin:.2f}U, 杠杆: {self.leverage}x)")
            coinw_client.place_market_order(symbol="ETH", side=action, amount=amount, leverage=self.leverage)
            
            # 【白金 180 秒】极度耐心死等机制
            filled = False
            entry_price = 0.0
            
            for attempt in range(180):
                time.sleep(1) 
                pos = self._get_active_position()
                if pos:
                    filled = True
                    entry_price = pos['entry_price']
                    break
                    
            if not filled:
                coinw_client.cancel_all_open_orders(symbol="ETH")
                logger.warning(f"[CoinW] 180秒未成交，执行防呆强撤。")
                self._report_timeout()
                return
                
            # 真实建仓成功，启动雷达
            self._report_open(action, margin, entry_price)
            self._start_radar(action, entry_price)

    # ==========================================
    # 狂暴死咬平仓机制 (防卡单专属)
    # ==========================================
    def _execute_pitbull_close(self, action: str, target_ratio: float, level_name: str):
        """
        死咬机制：强制市价平仓，直到实盘真正减少
        target_ratio: 0.5 (平50%), 1.0 (全平)
        """
        for attempt in range(10):  # 最多狂暴追杀 10 次
            pos = self._get_active_position()
            if not pos:
                return True  # 已经空了，完美闭环
                
            current_size = pos['size']
            
            if target_ratio == 1.0:
                # 终极全平
                coinw_client.close_all_positions(symbol="ETH")
            else:
                # 算出一半的数量去反向平仓
                close_qty = current_size * target_ratio
                close_side = "SHORT" if action == "LONG" else "LONG"
                coinw_client.place_market_order(symbol="ETH", side=close_side, amount=close_qty, leverage=self.leverage)
                
            time.sleep(2.0)  # 给撮合引擎 2 秒时间消化
            
            # 核心核实步骤
            new_pos = self._get_active_position()
            if not new_pos:
                return True
                
            # 如果仓位确实变小了（容错 10%），说明砸盘成功
            if new_pos['size'] < current_size * 0.9:
                return True
                
            logger.warning(f"⚠️ [CoinW] {level_name} 止盈被深度卡住！第 {attempt+1} 次重新发起市价砸盘！")
            
        return False

    def _close_all(self, reason: str):
        coinw_client.cancel_all_open_orders(symbol="ETH")
        time.sleep(0.5)
        coinw_client.close_all_positions(symbol="ETH")
        if reason:
            self._report_clear(reason)

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
        except Exception as e:
            logger.error(f"[CoinW] 解析实盘持仓异常: {e}")
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
        logger.info(f"🎯 [极速雷达] 目标锁定: TP1={tp1_price:.2f}, TP2={tp2_price:.2f}")
        
        while self.monitoring:
            try:
                current_price = coinw_client.get_current_price("ETH")
                if current_price <= 0:
                    time.sleep(0.2); continue
                    
                # 阶段一：检测 TP1 (7U 差价)
                if not tp1_done:
                    if (action == "LONG" and current_price >= tp1_price) or \
                       (action == "SHORT" and current_price <= tp1_price):
                        logger.info(f"✨ [极速雷达] TP1 破局！现价: {current_price}，立即启动 50% 死咬斩仓！")
                        self._execute_pitbull_close(action, 0.5, "TP1")
                        tp1_done = True
                        self._report_tp(action, "TP1 落袋 50%", entry_price, current_price)
                        continue  # 斩仓完毕，继续循环盯着 TP2
                        
                # 阶段二：检测 TP2 (15U 差价)
                if tp1_done:
                    if (action == "LONG" and current_price >= tp2_price) or \
                       (action == "SHORT" and current_price <= tp2_price):
                        logger.info(f"✨ [极速雷达] TP2 破局！现价: {current_price}，启动全平死咬斩仓！")
                        self._execute_pitbull_close(action, 1.0, "TP2")
                        self.monitoring = False
                        self._report_tp(action, "TP2 终极闭环", entry_price, current_price)
                        break

            except Exception as e:
                pass
            time.sleep(0.2)

    # ==========================================
    # 钉钉美学战报
    # ==========================================
    def _report_clear(self, reason: str):
        text = f"**动作**：🔄 {reason}\n**状态**：幽灵挂单与现有持仓已被彻底清理归零。"
        dingtalk.send_markdown_message("💥 [CoinW] 阵地清算", text)

    def _report_timeout(self):
        text = f"**动作**：强制撤销指令\n**原因**：挂单满 3 分钟仍未排到成交，系统已安全强撤并退回空仓待命。"
        dingtalk.send_markdown_message("⏳ [CoinW] 180秒耐心防呆强撤", text)

    def _report_open(self, action: str, margin: float, entry_price: float):
        emoji = "🟩" if action == "LONG" else "🟥"
        tp1 = entry_price + self.tp1_diff if action == "LONG" else entry_price - self.tp1_diff
        tp2 = entry_price + self.tp2_diff if action == "LONG" else entry_price - self.tp2_diff
        
        text = f"""
| 项目 | 详情 |
| :--- | :--- |
| **方向** | {emoji} <font color="{'#32CD32' if action=='LONG' else '#FF0000'}">**{action}**</font> |
| **真实开仓价** | **{entry_price:.2f}** |

🎯 **分批雷达已锁定**: 
- **TP1 (平50%)**: `{tp1:.2f}` (差价7U)
- **TP2 (全平)**: `{tp2:.2f}` (总差价15U)
"""
        dingtalk.send_markdown_message("🚀 [CoinW] 1h波段·建仓成功", text)

    def _report_tp(self, action: str, level: str, entry: float, trigger: float):
        text = f"""
**💰 利润锁定**：目标价格已被击穿，死咬斩仓执行成功！
- **战术阶段**：**{level}**
- **方向**：{action}
- **开仓均价**：{entry}
- **触发价格**：{trigger}
"""
        dingtalk.send_markdown_message(f"🎉 [CoinW] {level} 捷报", text)

# 全局单例
coinw_processor = CoinWProcessor()
