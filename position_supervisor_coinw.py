import time
import threading
import logging
from coinw_client import CoinWClient

# ================= 日志配置 =================
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] [CoinW-Brain] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

class SignalProcessor:
    def __init__(self):
        """
        币赢全自动交易执行大脑初始化
        """
        self.client = CoinWClient()
        self.symbol = "ETH"      # 默认交易对
        self.leverage = 5        # 默认杠杆倍数
        self.status = "IDLE"     # 状态机: IDLE / OPEN / CLOSED
        self.monitor_thread = None

    def process_signal(self, data):
        """
        统一网关信号处理入口 (供 app.py 调用)
        """
        action = data.get("action", "").upper()
        quantity = float(data.get("quantity", 0.01)) # 默认内测最小数量
        
        logger.info(f"📥 接收到核心交战信号: {action} {quantity} {self.symbol}")
        
        if action not in ["LONG", "SHORT", "CLOSE"]:
            logger.warning(f"⚠️ 未知信号动作: {action}，已拦截")
            return

        # 1. 平仓信号处理
        if action == "CLOSE":
            self.safe_close(reason="TV 主动发出平仓信号")
            return

        # 2. 开仓前置风控：获取可用余额 (防 402 熔断)
        assets_res = self.client.get_account_balance()
        balance = 0.0
        
        # 解析币赢资产结构
        try:
            if isinstance(assets_res, dict) and "data" in assets_res:
                # 根据官方返回结构，通常资金数据嵌套在 data 内
                data_obj = assets_res["data"]
                # 处理可能返回的是列表或字典的情况
                if isinstance(data_obj, list) and len(data_obj) > 0:
                    balance = float(data_obj[0].get("available", 0.0))
                elif isinstance(data_obj, dict):
                    balance = float(data_obj.get("available", data_obj.get("availableUsdt", 0.0)))
        except Exception as e:
            logger.error(f"解析余额异常: {e}, 原始返回: {assets_res}")

        if balance <= 0:
            logger.error(f"❌ 余额异常 (获取失败或不足: {balance})，触发安全熔断，放弃开仓！")
            return

        logger.info(f"💰 当前可用余额: {balance} USDT，风控准入通过，准备开仓...")

        # 3. 执行开仓：调用高精度的现价单
        logger.info(f"🚀 正在向币赢发送 {action} 指令...")
        res = self.client.place_current_price_order(
            symbol=self.symbol,
            side=action,
            amount=quantity,
            decimals=2  # ETH 强制要求 2 位小数精度
        )
        
        # 4. 回执处理与状态机切换
        # 币赢成功状态码通常为 "200" 或 0
        code = str(res.get("code", ""))
        if code in ["200", "0"]:
            logger.info(f"✅ 开仓指令已确认！交易所回执: {res}")
            self.status = "OPEN"
            self.start_profit_monitor()
        else:
            logger.error(f"❌ 开仓被拒，交易所回执: {res}")

    def start_profit_monitor(self):
        """启动后台止盈监控线程"""
        if self.monitor_thread is None or not self.monitor_thread.is_alive():
            logger.info("🛡️ 正在唤醒 V16 动态辅助止盈守护进程...")
            self.monitor_thread = threading.Thread(target=self.monitor_profit_take)
            self.monitor_thread.daemon = True # 主进程退出时子线程一并退出
            self.monitor_thread.start()

    def monitor_profit_take(self):
        """
        优雅的辅助止盈监控 (动态 5% 目标版)
        """
        while self.status == "OPEN":
            try:
                # 获取当前持仓盈亏
                res = self.client._request("GET", "/v1/perpum/positions", {"instrument": self.symbol})
                if res and "data" in res:
                    data = res["data"]
                    if isinstance(data, list) and len(data) > 0:
                        position = data[0]
                        # 获取未实现盈亏 (视具体 API 字段而定，通常为 profit 或 unrealizedProfit)
                        profit = float(position.get("profit", position.get("unrealizedProfit", 0)))
                        
                        # 获取当前余额以计算动态目标
                        assets = self.client.get_account_balance()
                        balance = 10.0 # 默认保底值
                        if isinstance(assets, dict) and "data" in assets:
                            a_data = assets["data"]
                            if isinstance(a_data, list) and len(a_data) > 0:
                                balance = float(a_data[0].get("available", 10.0))
                            elif isinstance(a_data, dict):
                                balance = float(a_data.get("available", a_data.get("availableUsdt", 10.0)))
                        
                        # 【核心风控】：目标 = 预估手续费 + (当前可用余额 * 5%)
                        # 注意：此处简化了仓位价值计算，专注于净资产动态挂钩
                        target_profit = 0.5 + (balance * 0.05) 
                        
                        if profit >= target_profit:
                            logger.info(f"✨ 达成动态止盈阈值: 当前盈亏 {profit:.2f}U (目标 {target_profit:.2f}U)")
                            self.safe_close(reason="辅助系统触发动态止盈")
                            break
            except Exception as e:
                logger.error(f"监控链路波动: {e}")
            
            # 控制查询频率，避免 API 速率限制 (Rate Limit)
            time.sleep(3)

    def safe_close(self, reason="未知"):
        """
        调用底层的一键全平，确保任何情况下都能净身出场
        """
        logger.info(f"🚨 启动紧急全平指令，触发原因: {reason}")
        res = self.client.close_all_positions(self.symbol)
        logger.info(f"🛡️ 全平回执: {res}")
        self.status = "CLOSED"
