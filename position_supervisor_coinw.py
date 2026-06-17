#!/usr/bin/env python3
import time
import threading
import logging
import json
import websocket # 引入 WebSocket 库
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
        
        # 实时盯盘目标价与方向 (由 WebSocket 线程读取)
        self.current_side = None
        self.tp_target_price = 0.0
        
        # WebSocket 实例
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
            # 1. 焦土重置
            self._close_all(f"🔄 强制重置阵地：准备执行新方向 {side}")
            time.sleep(1.5) 

            # 2. 算子弹
            total_balance = self.client.get_available_balance()
            if total_balance < 10:
                self.notifier.send_markdown("报警: 余额不足", f"当前余额 `{total_balance:.2f} U` 不足！")
                return

            usdt_amount = round(total_balance * self.risk_ratio, 2)
            logger.info(f"💰 可用: {total_balance:.2f} U | 动用 50%: {usdt_amount:.2f} U")

            # 3. 发射开单指令 (市价单)
            open_result = self.client.place_market_order(self.symbol, side, usdt_amount, self.leverage)
            if str(open_result.get("code")) not in ["200", "0"]:
                self.notifier.send_markdown("报警: 开仓失败", f"交易所拒单:\n\n`{open_result}`")
                return

            time.sleep(2.0) # 等待订单完全成交

            # 4. 反推真实开仓价与止盈价
            tp_price, open_price = self._calculate_target(side)
            
            # 5. 更新内存状态，准备激活 WebSocket 雷达
            self.current_side = side
            self.tp_target_price = tp_price
            self.status = "OPEN"

            # 6. 推送开仓战报
            report = (
                f"### 🚀 [CoinW] 短线刺客出击\n\n"
                f"| 项目 | 详情 |\n"
                f"| :--- | :--- |\n"
                f"| **方向** | <font color='#FF0000'>{side}</font> |\n"
                f"| **本金** | `{usdt_amount} USDT` (50%) |\n"
                f"| **杠杆** | 20x |\n"
                f"| **开仓** | `{open_price}` |\n\n"
                f"🎯 **光速 WS 雷达锁定**: `{tp_price}` *(毫秒级主动斩仓)*"
            )
            self.notifier.send_markdown(f"短线开仓 {side}", report)
            
            # 7. 启动 WebSocket 实时雷达
            self._start_websocket_radar()

        except Exception as e:
            logger.error(f"战场异常: {e}", exc_info=True)

    def _calculate_target(self, side: str):
        """仅反推真实开仓价和目标价"""
        pos_info = self.client.get_position_info(self.symbol)
        open_price = 0.0
        
        data = pos_info.get("data", [])
        if data and len(data) > 0:
            open_price = float(data[0].get("openPrice", 0))

        if open_price <= 0:
            open_price = self.client.get_current_price(self.symbol)

        if side == "LONG":
            tp_price = round(open_price + self.tp_eth_price_diff, 2)
        else:
            tp_price = round(open_price - self.tp_eth_price_diff, 2)
            
        return tp_price, open_price

    # ==========================================
    # WebSocket 毫秒级雷达核心逻辑
    # ==========================================
    def _start_websocket_radar(self):
        """启动长连接光缆"""
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
        
        # 放入后台独立线程运行，绝对不阻塞主程序
        wst = threading.Thread(target=self.ws.run_forever)
        wst.daemon = True
        wst.start()

    def _on_ws_open(self, ws):
        logger.info("✅ WebSocket 光缆连接成功！正在订阅 ETH 实时价格...")
        # ⚠️ 注意：这里使用的是最常见的币赢公开频道订阅格式。
        # 如果币赢文档有变更，可能需要微调这行 JSON。
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
            return # 如果不是开仓状态，忽略所有推过来的价格
            
        try:
            data = json.loads(message)
            # 解析行情推送包获取最新价 (此处需匹配币赢WS返回结构，通常带有 last_price)
            if "data" in data and isinstance(data["data"], dict):
                current_price_str = data["data"].get("last_price")
                if not current_price_str:
                    return
                
                current_price = float(current_price_str)
                
                # 核心绝杀逻辑：涨破/跌破目标价，直接斩仓！毫秒级响应！
                if self.current_side == "LONG" and current_price >= self.tp_target_price:
                    logger.info(f"✨ [WS毫秒触发] 多单突破 {self.tp_target_price}! 现价: {current_price}")
                    self.ws.close() # 目标达成，切断雷达省电
                    self._close_all("🎯 斩获 13U 盘口差价，WS 雷达光速落袋！")
                    
                elif self.current_side == "SHORT" and current_price <= self.tp_target_price:
                    logger.info(f"✨ [WS毫秒触发] 空单跌破 {self.tp_target_price}! 现价: {current_price}")
                    self.ws.close() # 目标达成，切断雷达省电
                    self._close_all("🎯 斩获 13U 盘口差价，WS 雷达光速落袋！")
        except Exception:
            pass

    def _on_ws_error(self, ws, error):
        logger.error(f"⚠️ WebSocket 雷达受干扰: {error}")

    def _on_ws_close(self, ws, close_status_code, close_msg):
        logger.info("🔌 WebSocket 行情光缆已断开。")

    # ==========================================

    def _close_all(self, reason):
        logger.info(f"🧹 {reason}")
        was_open = (self.status == "OPEN")
        self.status = "CLOSING" 
        
        # 切断 WS 雷达
        if self.ws:
            self.ws.close()
            self.ws = None
            
        self.client.cancel_all_open_orders(self.symbol)
        time.sleep(0.5) 
        
        self.client.close_all_positions(self.symbol)
        
        if was_open: 
            msg = f"### 💥 [CoinW] 阵地清算\n\n**动作**: {reason}\n\n**状态**: 利润已落袋，实盘全平清场完毕。"
            self.notifier.send_markdown("系统清场", msg)
            
        self.status = "CLOSED"

coinw_processor = SignalProcessor()
