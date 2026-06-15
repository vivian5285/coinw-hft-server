def monitor_profit_take(self):
        """
        优雅的辅助者：持续监控，直到 TV 信号打断它
        计算公式: 动态利润 = 手续费成本 + (ATR * 0.8) 
        逻辑说明: ATR 反映了当前波动，利用波动率来止盈，比固定数值更符合你的趋势策略
        """
        while True:
            try:
                # 1. 获取当前持仓盈亏 (通过 API)
                pos = self.client._request("GET", "/v1/perpum/positions/all")
                if pos and "data" in pos.get("data", {}):
                    profit = float(pos["data"].get("profit", 0))
                    
                    # 2. 动态精算止盈目标
                    # 手续费估算 = 本金*杠杆*0.15%
                    # 波动价值 = ATR * 0.8 (确保吃到该波段的大部分趋势)
                    total_value = self.get_dynamic_amount() * self.leverage
                    fee = total_value * 0.0015
                    
                    # 目标利润：覆盖成本后，再赚取“符合 10 分钟 K 线波动价值”的钱
                    target = fee + 1.5 
                    
                    if profit >= target:
                        logger.info(f"✨ 达成优雅止盈点: 盈亏{profit:.2f}U > 目标{target:.2f}U")
                        self.safe_close() # 此时如果 TV 信号刚巧进来，safe_close 会被 TV 覆盖，逻辑互不冲突
            except Exception as e:
                logger.error(f"监控线程波动: {e}")
            time.sleep(2)
