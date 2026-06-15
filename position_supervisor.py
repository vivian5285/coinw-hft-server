class SignalProcessor:
    def __init__(self):
        self.client = CoinWClient()
        self.status = "EMPTY"  # 状态锁：EMPTY, HOLDING, CLOSED
        # ... 其他初始化 ...

    def safe_close(self, reason=""):
        """带状态锁的平仓"""
        if self.status == "EMPTY": # 如果已经是空仓，直接静默
            return True
            
        res = self.client.close_all_positions(self.symbol)
        if res and res.get("code") == 0:
            self.status = "EMPTY" # 平仓后解锁
            logger.info(f"✅ 执行平仓成功 (原因: {reason})")
            return True
        return False

    def on_ws_message(self, ws, message):
        """自动止盈监控"""
        # ... 解析利润 ...
        if profit >= target_profit: # 这里 target_profit 设为你想要的 3U-5U
            logger.info(f"💰 目标{target_profit}U 达成，执行止盈")
            if self.safe_close(reason="系统止盈"):
                self.status = "CLOSED" # 标记为已止盈

    def process_signal(self, payload):
        action = payload.get("action", "").upper()
        
        # 【状态对齐逻辑】
        if action == "CLOSE":
            if self.status == "CLOSED": # 如果系统已经止盈，这里保持静默
                logger.info("ℹ️ 收到 CLOSE 指令，但系统已提前止盈，保持静默")
                self.status = "EMPTY" # 重置锁
                return
            self.safe_close(reason="TV 指令")
            self.status = "EMPTY"
        
        elif action in ["LONG", "SHORT"]:
            self.safe_close(reason="TV 换向")
            # ... 执行开仓 ...
            self.status = "HOLDING"
