#!/usr/bin/env python3
# coinw_client.py（基于你昨晚能用的版本 + 最小修改）
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
            return resp.json()
        except Exception as e:
            return {"code": -1, "msg": str(e)}

    # ==================== 补全的方法 ====================

    def get_account_balance(self):
        return self._request("GET", "/v1/perpum/account/balance")

    def get_available_balance(self):
        """获取可用 USDT 余额"""
        res = self.get_account_balance()
        try:
            data = res.get("data", {})
            return float(data.get("availableUsdt", 0))
        except:
            return 0.0

    def get_current_price(self, symbol="ETHUSDT"):
        """获取最新成交价"""
        res = self._request("GET", "/v1/perpum/market/ticker", {"symbol": symbol})
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
        """一键全平（先撤单再平仓）"""
        self.cancel_all_open_orders(symbol)
        time.sleep(0.5)
        return self._request("POST", "/v1/perpum/position/close_all", {"symbol": symbol})

    def cancel_all_open_orders(self, symbol="ETHUSDT"):
        return self._request("POST", "/v1/perpum/order/cancel_all", {"symbol": symbol})
