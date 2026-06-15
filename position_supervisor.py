def monitor_profit_take(self):
        """
        优雅的监控者：每 2 秒悄悄检查一次盈亏
        目的：在 TV 信号到来前，帮账户实现低风险“入袋为安”
        """
        while True:
            try:
                # 获取当前持仓数据 (调用你的 client 接口)
                pos_info = self.client._request("GET", "/v1/perpum/positions/all")
                if pos_info and "data" in pos_info:
                    # 假设这里能解析到当前持仓的总盈亏 profit
                    profit = float(pos_info["data"].get("profit", 0))
                    
                    # 【优雅逻辑】：
                    # 1. 基础门槛：利润必须覆盖手续费 (约 0.15%)
                    # 2. 止盈目标：例如 1.0U 纯利
                    total_value = self.get_dynamic_amount() * self.leverage
                    fee = total_value * 0.0015
                    
                    if profit >= (fee + 1.0):
                        logger.info(f"✨ 达成优雅止盈点: 盈亏{profit:.2f}U (成本{fee:.2f}U)")
                        self.safe_close()
            except Exception as e:
                logger.error(f"监控异常: {e}")
            
            time.sleep(2) # 每2秒查一次，兼顾效率与负载
