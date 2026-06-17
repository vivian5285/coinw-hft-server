#!/usr/bin/env python3
import time
import threading
import logging
import json
import websocket 
from coinw_client import CoinWClient
from dingtalk_notifier import DingTalkNotifier

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

class SignalProcessor:
    def __init__(self):
        self.client = CoinWClient()
        self.notifier = DingTalkNotifier()
        self.symbol = "ETH"
        
        # 50%本金 / 20倍 / 13刀主动盯盘
        self.leverage = 20               
        self.risk_ratio = 0.50           
        self.tp_eth_price_diff = 13.0    
        
        self.status = "IDLE"
        
        self.current_side = None
        self.tp_target_price = 0.0
        self.ws = None

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
            # 1. 铁律：任何新信号到达，绝对前置清场！清剿所有幽灵挂单，斩平所有历史仓位！
            self._close_all(f"🔄 强制重置阵地：准备执行新方向 {side}")
            time.sleep(1.5) 

            # 2. 算子弹
            total_balance = self.client.get_available_balance()
            if total_balance < 10:
                self.notifier.send_markdown("报警: 余额不足", f"当前余额 `{total_balance:.2f} U` 不足！")
                return

            usdt_amount = round(total_balance * self.risk_ratio, 2)
            logger.info(f"💰 可用: {total_balance:.2f} U | 动用 50%: {usdt_amount:.2f} U")

            # 3. 发射开单指令 (带价格的限价伪市价单)
            open_result = self.client.place_market_order(self.symbol, side, usdt_amount, self.leverage)
            if str(open_result.get("code")) not in ["200", "0"]:
                self.notifier.send_markdown("报警: 开仓失败", f"交易所拒单:\n\n`{open_result}`")
                return

            # 4. 【核心升级】死盯实盘核实是否成交 (最大等待 15 秒)
            logger.info(f"⏳ 订单已挂入盘口，正在核实实盘是否真正吃单成交...")
            filled_price = self._wait_for_position_fill(timeout=15)

            # 如果 15 秒了还没成交，启动防呆机制
            if filled_price is None:
                logger.warning(f"⚠️ 开仓挂单未能在 15 秒内成交，执行超时强撤！防呆机制触发！")
                self.client.cancel_all_open_orders(self.symbol) # 杀掉这个幽灵订单
                self.notifier.send_markdown(
                    "⚠️ 开仓超时强撤", 
                    f"**方向**: {side}\n\n指令发出后 **15秒** 仍未被交易所撮合，为防挂单被意外吃掉，系统已主动撤销此单并退回空仓待命。"
                )
                self.status = "CLOSED"
                return

            # 走到这里，说明 100% 真正实盘有持仓了！
            self.status = "OPEN"
            self.current_side = side

            # 5. 反推目标价
            if side == "LONG":
                self.tp_target_price = round(filled_price + self.tp_eth_price_diff, 2)
            else:
                self.tp_target_price = round(filled_price - self.tp_eth_price_diff, 2)

            # 6. 【只发真捷报】推送到钉钉
            report = (
                f"### 🚀 [CoinW] 短线刺客·真实建仓\n\n"
                f"| 项目 | 详情 |\n"
                f"| :--- | :--- |\n"
                f"| **方向** | <font color='#FF0000'>{side}</font> |\n"
                f"| **本金** | `{usdt_amount} USDT` (50%) |\n"
                f"| **杠杆** | 20x |\n"
                f"| **真实开仓价** | `{filled_price}` |\n\n"
                f"🎯 **WS 极速雷达锁定**: `{self.tp_target_price}` *(主动斩仓)*"
            )
            self.notifier.send_markdown(f"短线开仓 {side}", report)
            
            # 7. 开启 WS 雷达
            self._start_websocket_radar()

        except Exception as e:
            logger.error(f"战场异常: {e}", exc_info=True)

    def _wait_for_position_fill(self, timeout=15):
        """死循环轮询实盘，确认仓位是否真实建立。建立则返回开仓价，未建立返回 None"""
        for _ in range(timeout):
            try:
                pos_info = self.client.get_position_info(self.symbol)
                data = pos_info.get("data", [])
                for pos in data:
                    open_price = float(pos.get("openPrice", 0))
                    if open_price > 0:
                        return open_price  # 只要查到了有均价大于 0 的持仓，证明成交了！
            except Exception:
                pass
            time.sleep(1) # 每秒查一次实盘
        return None

    # ==========================================
    # WebSocket 毫秒级雷达核心逻辑
    # ==========================================
    def _start_websocket_radar(self):
        if self.ws is not None:
            self.ws.close()
            
        logger.info("🔌 正在连接币赢 WebSocket 实时行情光缆...")
        websocket.enableTrace(False)
        self.ws = websocket.WebSocketApp(
            "wss://ws.futurescw.com/perpum",
            on_open=self._on_ws_open,
            on_message=self._on_ws_message,
            on_error=self._on_ws_error,
            on_close=self._on_ws_close
        )
        
        wst = threading.Thread(target=self.ws.run_forever)
        wst.daemon = True
        wst.start()

    def _on_ws_open(self, ws):
        logger.info("✅ WebSocket 光缆连接成功！正在订阅 ETH 实时价格...")
        sub_msg = {
            "event": "subscribe",
            "params": {
                "channel": "ticker",
                "instrument": "ETH"
            }
        }
        ws.send(json.dumps(sub_msg))

    def _on_ws_message(self, ws, message):
        if self.status != "OPEN":
            return 
            
        try:
            data = json.loads(message)
            if "data" in data and isinstance(data["data"], dict):
                current_price_str = data["data"].get("last_price")
                if not current_price_str:
                    return
                
                current_price = float(current_price_str)
                
                if self.current_side == "LONG" and current_price >= self.tp_target_price:
                    logger.info(f"✨ [WS触发] 多单突破 {self.tp_target_price}! 现价: {current_price}")
                    self.ws.close()
                    self._close_all("🎯 斩获 13U 盘口差价，WS 雷达光速落袋！")
                    
                elif self.current_side == "SHORT" and current_price <= self.tp_target_price:
                    logger.info(f"✨ [WS触发] 空单跌破 {self.tp_target_price}! 现价: {current_price}")
                    self.ws.close()
                    self._close_all("🎯 斩获 13U 盘口差价，WS 雷达光速落袋！")
        except Exception:
            pass

    def _on_ws_error(self, ws, error):
        pass

    def _on_ws_close(self, ws, close_status_code, close_msg):
        logger.info("🔌 WebSocket 行情光缆已断开。")

    # ==========================================

    def _close_all(self, reason):
        logger.info(f"🧹 {reason}")
        was_open = (self.status == "OPEN")
        self.status = "CLOSING" 
        
        if self.ws:
            self.ws.close()
            self.ws = None
            
        # 1. 绝对优先：撤掉所有盘口幽灵挂单
        self.client.cancel_all_open_orders(self.symbol)
        time.sleep(0.5) 
        
        # 2. 强平所有仓位
        self.client.close_all_positions(self.symbol)
        
        if was_open: 
            msg = f"### 💥 [CoinW] 阵地清算\n\n**动作**: {reason}\n\n**状态**: 幽灵挂单与现有持仓已被彻底清理归零。"
            self.notifier.send_markdown("系统清场", msg)
            
        self.status = "CLOSED"

coinw_processor = SignalProcessor()
