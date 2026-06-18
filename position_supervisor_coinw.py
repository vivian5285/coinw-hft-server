#!/usr/bin/env python3
# position_supervisor_coinw.py（CoinW V8.0 限价防对冲 + 实盘哨兵巡更版）
import logging
import time
import threading
from coinw_client import coinw_client
import dingtalk

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] CoinWSupervisor: %(message)s')
logger = logging.getLogger(__name__)

class CoinWProcessor:
    def __init__(self):
        self.leverage = 20
        self.symbol = "ETH"
        
        # 哨兵状态管理
        self.sentinel_thread = None
        self.monitoring = False
        self.watched_side = None
        self.watched_qty = 0.0
        self._lock = threading.Lock()
        
        logger.info("🟢 [CoinW] V8.0 刺客引擎就绪：开仓即挂 7U/15U 限价单，杜绝对冲！")

    def process_signal(self, payload: dict):
        action = payload.get("action", "").upper()
        if not action: return

        if action == "CLOSE":
            self._close_all("接收到 TV 主动平仓信号，执行绝对清场")
            self._stop_sentinel()
            return

        if action in ["LONG", "SHORT"]:
            signal_price = payload.get("price", coinw_client.get_current_price(self.symbol))
            logger.info(f"📡 接收到 TV {action} 信号！当前理论预期价: {signal_price}")

            # 1. 强制重置阵地：不管多空，先撤挂单再全平！(保持纯净一手)
            self._stop_sentinel()
            self._close_all(f"强制重置阵地: 准备执行新方向 {action}")
            
            # 2. 调用三段狙击引擎开仓
            success, entry_price, margin, final_qty = self._execute_escalating_open(action)
            
            if success and final_qty > 0:
                # 3. 计算 7U / 15U 止盈防线
                tp1_qty = round(final_qty * 0.5, 4)
                tp2_qty = round(final_qty - tp1_qty, 4) # 剩余全部给 TP2
                
                tp1_price = round(entry_price + 7.0 if action == "LONG" else entry_price - 7.0, 2)
                tp2_price = round(entry_price + 15.0 if action == "LONG" else entry_price - 15.0, 2)
                
                logger.info(f"🛡️ 正在挂载币赢极速限价防线... TP1: {tp1_price}({tp1_qty}), TP2: {tp2_price}({tp2_qty})")
                
                # 投递止盈减仓单 (is_close=True 确保防对冲机制激活)
                if tp1_qty > 0:
                    coinw_client.place_limit_order(self.symbol, action, tp1_price, tp1_qty, self.leverage, is_close=True)
                if tp2_qty > 0:
                    coinw_client.place_limit_order(self.symbol, action, tp2_price, tp2_qty, self.leverage, is_close=True)
                
                # 4. 汇报战果并启动防悬空哨兵
                tp_dict = {"tp1": tp1_price, "tp2": tp2_price}
                dingtalk.report_coinw_open(action, entry_price, final_qty, tp_dict, margin)
                
                self._start_sentinel(action, final_qty)
            else:
                self._report_timeout()

    def _close_all(self, reason: str):
        logger.info(f"🧹 执行清场: {reason}")
        for attempt in range(3):
            coinw_client.cancel_all_open_orders(self.symbol)
            time.sleep(0.5)
            coinw_client.close_all_positions(self.symbol)
            time.sleep(1.0)
            
            if not self._get_active_position():
                if reason: dingtalk.report_coinw_clear(reason)
                return
            logger.warning(f"⚠️ 第 {attempt+1} 次清场仍有残余，继续清剿！")

    def _execute_escalating_open(self, action: str):
        balance = coinw_client.get_available_balance()
        if balance < 10:
            logger.warning("[CoinW] 账户余额不足，放弃建仓。")
            return False, 0.0, 0.0, 0
            
        margin = balance * 0.50  # 动用50%本金
        total_amount = margin * self.leverage
        
        escalation_steps = [0.0, 1.5, 3.0]
        final_pos = None
        
        for strike_idx, slippage in enumerate(escalation_steps, 1):
            curr_px = coinw_client.get_current_price(self.symbol)
            if curr_px <= 0: continue
                
            target_price = curr_px + slippage if action == "LONG" else curr_px - slippage
            coinw_client.place_limit_order(self.symbol, action, target_price, total_amount, self.leverage, is_close=False)
            
            filled = False
            for _ in range(20): 
                time.sleep(1.0)
                pos = self._get_active_position()
                if pos and pos['side'] == action and pos['size'] >= total_amount * 0.85: 
                    filled = True
                    final_pos = pos
                    break
                    
            if filled: break
            coinw_client.cancel_all_open_orders(self.symbol)
            time.sleep(1.0)

        if final_pos and final_pos['size'] > 0:
            return True, final_pos['entry_price'], margin, final_pos['size']
            
        return False, 0.0, 0.0, 0

    def _get_active_position(self) -> dict:
        try:
            res = coinw_client.get_position_info(self.symbol)
            data = res.get("data", [])
            for pos in data:
                size = float(pos.get("position", pos.get("volume", pos.get("size", 0))))
                if size > 0:
                    entry = float(pos.get("openPrice", pos.get("avgPrice", 0)))
                    pos_mode = pos.get("positionType", "") 
                    side = "LONG" if "long" in str(pos_mode).lower() or pos.get("direction", "") == "long" else "SHORT"
                    return {"size": size, "entry_price": entry, "side": side}
            return None
        except Exception: return None

    # ==================== V8.0 哨兵防悬空对账引擎 ====================
    def _start_sentinel(self, side: str, qty: float):
        with self._lock:
            self.watched_side = side
            self.watched_qty = qty
            self.monitoring = True
        self.sentinel_thread = threading.Thread(target=self._sentinel_loop, daemon=True)
        self.sentinel_thread.start()

    def _stop_sentinel(self):
        with self._lock:
            self.monitoring = False
            self.watched_side = None
            self.watched_qty = 0.0

    def _sentinel_loop(self):
        logger.info("👀 [CoinW] 哨兵巡更启动，防幽灵悬空单机制运行中...")
        while self.monitoring:
            try:
                pos = self._get_active_position()
                current_qty = pos['size'] if pos else 0.0
                current_side = pos['side'] if pos else None

                # 强行对齐方向
                if current_qty > 0 and current_side and current_side != self.watched_side:
                    logger.warning("🚨 [哨兵] 发现币赢反向对冲仓位！执行惩罚性强制清理！")
                    self._close_all("哨兵防线：强制平掉所有反向与错位持仓")
                    self._stop_sentinel()
                    break

                if abs(current_qty - self.watched_qty) > 0.001: # 数量发生实质性变化
                    if current_qty == 0:
                        logger.info("💥 [哨兵] 仓位归零！立即启动防悬空清剿，抹除盘口一切残单！")
                        coinw_client.cancel_all_open_orders(self.symbol)
                        dingtalk.report_coinw_tp("全平 / 手动清空", current_qty)
                        self._stop_sentinel()
                        break
                    
                    elif current_qty < self.watched_qty:
                        logger.info(f"✨ [哨兵] 限价止盈吃单成功! 剩余: {current_qty}")
                        dingtalk.report_coinw_tp("限价减仓成功落袋", current_qty)
                        with self._lock: self.watched_qty = current_qty

                    elif current_qty > self.watched_qty:
                        logger.warning(f"👀 [哨兵] 警告: 检测到未知加仓动作 {current_qty}")
                        dingtalk.report_coinw_tp("发现异常外部加仓", current_qty)
                        with self._lock: self.watched_qty = current_qty

            except Exception: pass
            time.sleep(3) # 币赢哨兵每3秒雷达扫射一次

    def _report_timeout(self):
        dingtalk.report_coinw_clear("狙击建仓落空，撤单防站岗")

coinw_processor = CoinWProcessor()
