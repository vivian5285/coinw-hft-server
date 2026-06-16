#!/usr/bin/env python3
# coinw_client.py（最终版）
import os
import time
import hmac
import hashlib
import base64
import json
import requests
from dotenv import load_dotenv

load_dotenv()


class CoinWClient:
    def __init__(self):
        self.api_key = os.getenv("COINW_API_KEY")
        self.secret_key = os.getenv("COINW_API_SECRET")
        self.base_url = "https://api.coinw.com"

        if not self.api_key or not self.secret_key:
            raise ValueError("请在 .env 中配置 COINW_API_KEY 和 COINW_API_SECRET")

    def _request(self, method: str, endpoint: str, params: dict = None):
        if params is None:
            params = {}

        timestamp = str(int(time.time() * 1000))
        request_url = f"{self.base_url}{endpoint}"

        if method.upper() == "GET":
            query_params = "&".join(f"{k}={v}" for k, v in sorted(params.items()) if v is not None)
            encoded_params = f"{timestamp}{method}{endpoint}?{query_params}" if query_params else f"{timestamp}{method}{endpoint}"
        else:
            encoded_params = f"{timestamp}{method}{endpoint}{json.dumps(params)}"

        signature = base64.b64encode(
            hmac.new(self.secret_key.encode(), encoded_params.encode(), hashlib.sha256).digest()
        ).decode("US-ASCII")

        headers = {
            "sign": signature,
            "api_key": self.api_key,
            "timestamp": timestamp,
        }

        try:
            if method.upper() == "GET":
                resp = requests.get(request_url, params=params, headers=headers, timeout=10)
            else:
                headers["Content-type"] = "application/json"
                resp = requests.post(request_url, data=json.dumps(params), headers=headers, timeout=10)
            return resp.json()
        except Exception as e:
            return {"code": -1, "msg": str(e)}

    def get_account_balance(self):
        return self._request("GET", "/v1/perpum/account/available")

    def get_available_balance(self):
        res = self.get_account_balance()
        try:
            data = res.get("data", {})
            return float(data.get("value", 0))
        except:
            return 0.0

    def get_current_price(self, symbol="ETH"):
        res = self._request("GET", "/v1/perpumPublic/ticker", {"instrument": symbol})
        try:
            data = res.get("data", [])
            if isinstance(data, list) and len(data) > 0:
                return float(data[0].get("last_price", 0))
            return 0.0
        except:
            return 0.0

    def get_position_info(self, symbol="ETH"):
        return self._request("GET", "/v1/perpum/positions", {"instrument": symbol})

    def place_market_order(self, symbol, side, amount, leverage=5):
        return self._request("POST", "/v1/perpum/order", {
            "instrument": symbol,
            "direction": side.lower(),
            "quantityUnit": "0",           # USDT 模式
            "quantity": str(amount),
            "leverage": str(leverage),
            "positionModel": "1",
            "positionType": "plan"
        })

    def close_all_positions(self, symbol="ETH"):
        self.cancel_all_open_orders(symbol)
        time.sleep(0.5)
        return self._request("DELETE", "/v1/perpum/allpositions", {"instrument": symbol})

    def cancel_all_open_orders(self, symbol="ETH"):
        return self._request("DELETE", "/v1/perpum/order", {"instrument": symbol})
