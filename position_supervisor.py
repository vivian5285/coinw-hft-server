def place_order_with_take_profit(self, direction, amount):
        """
        开启“下单+挂单”模式：
        1. 发送市价开仓
        2. 获取开仓均价
        3. 计算目标利润 2% (balance * 0.02) 的点位，直接挂限价止盈单
        """
        # 1. 开仓
        res = self.client.place_market_order(self.symbol, direction, amount, self.leverage)
        
        if res and res.get("code") == 0:
            self.status = "HOLDING"
            # 2. 获取刚才的成交均价 (假设开仓后立刻查询持仓)
            avg_price = self.get_avg_price() 
            
            # 3. 计算止盈目标 (吃 2% 波动)
            # 多单止盈 = 开仓价 * 1.02，空单止盈 = 开仓价 * 0.98
            offset = 0.02 if direction == "LONG" else -0.02
            tp_price = avg_price * (1 + offset)
            
            # 4. 发送限价止盈指令 (挂在交易所侧)
            self.client.place_limit_order(self.symbol, "CLOSE_DIRECTION", tp_price, amount)
            logger.info(f"🎯 挂单成功: 止盈价位 {tp_price:.2f}")
