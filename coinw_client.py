#!/usr/bin/env python3
# coinw_client.py（最终修复版 - 域名已修正）
import time
import hmac
import hashlib
import requests
import os
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class CoinWClient:
    def __init__(self):
        self.api_key = os.getenv("COINW_API_KEY")
        self.secret_key = os.getenv("COINW_SECRET_KEY")
        self.base_url = "https://api.coinw.com"   # ← 已修正为官方域名

        if not self.api_key or not self.secret_key:
            raise ValueError("请在 .env 文件中配置 COINW_API_KEY 和 COINW_SECRET_KEY")

    def _sign(self, params: dict) -> str:
        query = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
        return hmac.new(self.secret_key.encode(), query.encode(), hashlib.sha256).hexdigest()

    def _request(self, method: str, endpoint: str, params: dict = None):
        if params is None:
            params = {}

        params["timestamp"] = int(time.time() * 1000)
        params["api_key"] = self.api_key
        params["sign"] = self._sign(params)

        url = f"{self.base_url}{endpoint}"

        try:
            if method.upper() == "GET":
                response = requests.get(url, params=params, timeout=15)
            else:
                response = requests.post(url, data=params, timeout=15)

            return response.json()
        except Exception as e:
            logger.error(f"[CoinW] 请求异常: {e}")
            return {"code": -1, "msg": str(e)}

    # ==================== 账户与行情 ====================
    def get_account_balance(self):
        return self._request("GET", "/v1/perpum/account/balance")

    def get_available_balance(self):
        res = self.get_account_balance()
        return float(res.get("data", {}).get("availableUsdt", 0))

    def get_current_price(self, symbol: str = "ETHUSDT"):
        res = self._request("GET", "/v1/perpum/market/ticker", {"symbol": symbol})
        return float(res.get("data", {}).get("lastPrice", 0))

    def get_position_info(self, symbol: str = "ETHUSDT"):
        return self._request("GET", "/v1/perpum/position/info", {"symbol": symbol})

    # ==================== 交易接口 ====================
    def place_market_order(self, symbol: str, side: str, amount: float, leverage: int = 5):
        return self._request("POST", "/v1/perpum/order/market", {
            "symbol": symbol,
            "side": side,
            "amount": amount,
            "leverage": leverage
        })

    def place_limit_order(self, symbol: str, side: str, price: float, amount: float):
        return self._request("POST", "/v1/perpum/order/limit", {
            "symbol": symbol,
            "side": side,
            "price": price,
            "amount": amount,
            "type": "limit",
            "post_only": True
        })

    def close_all_positions(self, symbol: str = "ETHUSDT"):
        self.cancel_all_open_orders(symbol)
        time.sleep(0.5)
        return self._request("POST", "/v1/perpum/position/close_all", {"symbol": symbol})

    def cancel_all_open_orders(self, symbol: str = "ETHUSDT"):
        return self._request("POST", "/v1/perpum/order/cancel_all", {"symbol": symbol})
