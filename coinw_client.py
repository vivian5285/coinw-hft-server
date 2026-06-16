#!/usr/bin/env python3
# coinw_client.py（带调试打印完整版）
import os
import time
import hmac
import hashlib
import requests
from dotenv import load_dotenv

load_dotenv()


class CoinWClient:
    def __init__(self):
        self.api_key = os.getenv("COINW_API_KEY")
        self.secret_key = os.getenv("COINW_API_SECRET")
        self.base_url = "https://api.futurescw.com"   # 保持你昨晚能用的域名

        if not self.api_key or not self.secret_key:
            raise ValueError("请在 .env 中配置 COINW_API_KEY 和 COINW_API_SECRET")

    def _sign(self, params: dict) -> str:
        """保持你原来能用的签名方式"""
        query = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
        return hmac.new(self.secret_key.encode(), query.encode(), hashlib.sha256).hexdigest()

    def _request(self, method: str, endpoint: str, params: dict = None):
        if params is None:
            params = {}

        params["timestamp"] = int(time.time() * 1000)
        params["api_key"] = self.api_key
        params["sign"] = self._sign(params)

        try:
            url = f"{self.base_url}{endpoint}"
            if method.upper() == "GET":
                resp = requests.get(url, params=params, timeout=10)
            else:
                resp = requests.post(url, data=params, timeout=10)
            result = resp.json()
            print(f"[DEBUG] {method} {endpoint} 返回: {result}")   # 调试打印
            return result
        except Exception as e:
            print(f"[DEBUG] {method} {endpoint} 异常: {e}")
            return {"code": -1, "msg": str(e)}

    # ==================== 常用方法（带调试） ====================

    def get_account_balance(self):
        return self._request("GET", "/v1/perpum/account/balance")

    def get_available_balance(self):
        res = self.get_account_balance()
        print(f"[DEBUG] get_available_balance 解析前: {res}")
        try:
            data = res.get("data", {})
            return float(data.get("availableUsdt", 0))
        except:
            return 0.0

    def get_current_price(self, symbol="ETHUSDT"):
        res = self._request("GET", "/v1/perpum/market/ticker", {"symbol": symbol})
        print(f"[DEBUG] get_current_price 解析前: {res}")
        try:
            return float(res.get("data", {}).get("lastPrice", 0))
        except:
            return 0.0

    def get_position_info(self, symbol="ETHUSDT"):
        return self._request("GET", "/v1/perpum/position/info", {"symbol": symbol})

    def place_market_order(self, symbol, side, amount, leverage=5):
        return self._request("POST", "/v1/perpum/order/market", {
            "symbol": symbol,
            "side": side,
            "amount": amount,
            "leverage": leverage
        })

    def place_limit_order(self, symbol, side, price, amount):
        return self._request("POST", "/v1/perpum/order/limit", {
            "symbol": symbol,
            "side": side,
            "price": price,
            "amount": amount,
            "type": "limit",
            "post_only": True
        })

    def close_all_positions(self, symbol="ETHUSDT"):
        self.cancel_all_open_orders(symbol)
        time.sleep(0.5)
        return self._request("POST", "/v1/perpum/position/close_all", {"symbol": symbol})

    def cancel_all_open_orders(self, symbol="ETHUSDT"):
        return self._request("POST", "/v1/perpum/order/cancel_all", {"symbol": symbol})
