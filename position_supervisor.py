def monitor_profit_take(self):
        """
        优雅的辅助止盈监控 (V16 动态5%目标版)
        """
        while True:
            try:
                # 获取当前持仓盈亏
                res = self.client._request("GET", "/v1/perpum/position/info", {"symbol": self.symbol})
                if res and "data" in res:
                    profit = float(res["data"].get("profit", 0))
                    
                    # 【核心计算】：目标 = 手续费成本 + (当前可用余额 * 5%)
                    # 这样做的好处是随着盈利积累，止盈门槛也会同步自动提升
                    assets = self.client.get_account_balance()
                    balance = float(assets.get("data", {}).get("availableUsdt", 10.0))
                    
                    total_value = self.get_dynamic_amount() * self.leverage
                    fee = total_value * 0.0015
                    target_profit = fee + (balance * 0.05) 
                    
                    if profit >= target_profit:
                        logger.info(f"✨ 达成 5% 优雅止盈: 盈亏{profit:.2f}U (目标{target_profit:.2f}U)")
                        self.safe_close(reason="辅助止盈监控")
                        self.status = "CLOSED" # 对齐 TV 状态
            except Exception as e:
                logger.error(f"监控波动: {e}")
            time.sleep(2)
