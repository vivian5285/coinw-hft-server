#!/usr/bin/env python3
# position_supervisor_coinw.py（V3.0 终极黄金耐心 + 极速内存雷达版）
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
        self.target_profit_diff = 13.0  # 核心战略：死磕 13U 差价
        self.leverage = 20
        self.monitor_thread = None
        self._lock = threading.Lock()
        logger.info("🟢 [CoinW] 高频刺客引擎初始化完成，极速雷达待命。")

    def process_signal(self, payload: dict):
        """处理来自 TV 的纯净 JSON 信号"""
        action = payload.get("action", "").upper()
        if not action:
            return

        # 只要有新信号，立刻切断现有的极速雷达，防止多线程打架
        with self._lock:
            self.monitoring = False 

        # ==========================================
        # 场景一：TV 下发全平指令 (CLOSE)
        # ==========================================
        if action == "CLOSE":
            self._close_all("接收到 TV 主动平仓信号")
            return

        # ==========================================
        # 场景二：TV 下发开仓指令 (LONG / SHORT)
        # ==========================================
        if action in ["LONG", "SHORT"]:
            # 1. 前置焦土清场（绝对护城河）
            self._close_all(f"强制重置阵地: 准备执行新方向 {action}")

            # 2. 核心资金核算 (动用 50% 可用余额，20倍杠杆)
            balance = coinw_client.get_available_balance()
            if balance < 10:
                logger.warning(f"[CoinW] 账户余额不足 ({balance} USDT)，放弃建仓。")
                return
                
            margin = balance * 0.50
            amount = margin * self.leverage  # 转化为 API 能够识别的名义价值
            
            # 3. 稳定下达开仓指令
            logger.info(f"[CoinW] 发射开仓指令: {action} (本金: {margin:.2f}U, 杠杆: {self.leverage}x)")
            coinw_client.place_market_order(symbol="ETH", side=action, amount=amount, leverage=self.leverage)
            
            # 4. 【黄金 60 秒】实盘死等核实机制
            filled = False
            entry_price = 0.0
            
            for attempt in range(60):
                time.sleep(1) # 每秒查一次账本
                pos = self._get_active_position()
                if pos:
                    filled = True
                    entry_price = pos['entry_price']
                    break
                    
            # 5. 防呆强撤兜底
            if not filled:
                coinw_client.cancel_all_open_orders(symbol="ETH")
                logger.warning(f"[CoinW] 60秒未成交，执行防呆强撤。")
                self._report_timeout()
                return
                
            # 6. 真实建仓成功，钉钉播报
            target_price = entry_price + self.target_profit_diff if action == "LONG" else entry_price - self.target_profit_diff
            self._report_open(action, margin, entry_price, target_price)
            
            # 7. 唤醒极速内存雷达
            self._start_radar(action, entry_price, target_price)

    # ==========================================
    # 核心动作与雷达追踪模块
    # ==========================================

    def _close_all(self, reason: str):
        """绝对焦土清场：撤单 + 全平"""
        coinw_client.cancel_all_open_orders(symbol="ETH")
        time.sleep(0.5) # 给交易所撮合引擎 0.5 秒缓冲
        coinw_client.close_all_positions(symbol="ETH")
        self._report_clear(reason)

    def _get_active_position(self) -> dict:
        """精准提取实盘持仓均价"""
        try:
            res = coinw_client.get_position_info("ETH")
            data = res.get("data", [])
            if not data: return None
            
            for pos in data:
                # 兼容币赢可能返回的各种仓位字段名
                size = float(pos.get("position", pos.get("volume", pos.get("size", pos.get("holdVolume", 0)))))
                if size > 0:
                    entry = float(pos.get("openPrice", pos.get("avgPrice", pos.get("price", 0))))
                    return {"size": size, "entry_price": entry}
            return None
        except Exception as e:
            logger.error(f"[CoinW] 解析实盘持仓异常: {e}")
            return None

    def _start_radar(self, action: str, entry_price: float, target_price: float):
        """拉起后台微线程，200ms 极速轮询盯盘"""
        with self._lock:
            self.monitoring = True
            
        self.monitor_thread = threading.Thread(
            target=self._radar_loop, 
            args=(action, entry_price, target_price), 
            daemon=True
        )
        self.monitor_thread.start()

    def _radar_loop(self, action: str, entry_price: float, target_price: float):
        """极速内存雷达：每秒 5 次扫描接口，无视 WS 假死"""
        logger.info(f"🎯 [极速雷达] 已锁定目标: {target_price:.2f} (200ms 高频模式)")
        
        while self.monitoring:
            try:
                current_price = coinw_client.get_current_price("ETH")
                if current_price <= 0:
                    time.sleep(0.2)
                    continue
                    
                # 扣动扳机条件
                if action == "LONG" and current_price >= target_price:
                    self._execute_tp(action, entry_price, current_price)
                    break
                elif action == "SHORT" and current_price <= target_price:
                    self._execute_tp(action, entry_price, current_price)
                    break
                    
            except Exception as e:
                pass # 忽略网络波动，继续疯狂轮询
                
            time.sleep(0.2) # 关键核心：200 毫秒极限探测间隔

    def _execute_tp(self, action: str, entry_price: float, current_price: float):
        """触发 13U 斩仓指令"""
        with self._lock:
            self.monitoring = False # 销毁雷达
            
        logger.info(f"✨ [极速雷达] 破局！现价: {current_price}，立即市价全平！")
        coinw_client.close_all_positions("ETH")
        self._report_tp(action, entry_price, current_price)

    # ==========================================
    # 钉钉美学战报模块
    # ==========================================

    def _report_clear(self, reason: str):
        text = f"**动作**：🔄 {reason}\n**状态**：幽灵挂单与现有持仓已被彻底清理归零。"
        dingtalk.send_markdown_message("💥 [CoinW] 阵地清算", text)

    def _report_timeout(self):
        text = f"**动作**：强制撤销指令\n**原因**：受限于盘口深度，挂单满 60 秒仍未排到成交，系统已安全强撤并退回空仓待命。"
        dingtalk.send_markdown_message("⏳ [CoinW] 60秒防呆强撤", text)

    def _report_open(self, action: str, margin: float, entry_price: float, target_price: float):
        emoji = "🟩" if action == "LONG" else "🟥"
        text = f"""
| 项目 | 详情 |
| :--- | :--- |
| **方向** | {emoji} <font color="{'#32CD32' if action=='LONG' else '#FF0000'}">**{action}**</font> |
| **本金** | **{margin:.2f} USDT** (50%) |
| **杠杆** | **20x** |
| **真实开仓价** | **{entry_price:.2f}** |

🎯 **极速内存雷达锁定**: `{target_price:.2f}` *(全自动斩仓)*
"""
        dingtalk.send_markdown_message("🚀 [CoinW] 短线刺客·真实建仓", text)

    def _report_tp(self, action: str, entry: float, trigger: float):
        text = f"""
**💰 利润落袋**：13U 差价已被雷达瞬间吃掉！
- **方向**：{action}
- **开仓均价**：{entry}
- **触发斩仓价**：{trigger}

*(等待 TV 下达下一个入场信号...)*
"""
        dingtalk.send_markdown_message("🎉 [CoinW] 刺客捷报", text)

# 全局单例
coinw_processor = CoinWProcessor()
