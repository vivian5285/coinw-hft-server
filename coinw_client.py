#!/usr/bin/env python3
# coinw_client.py（临时调试版 - 带详细打印）
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

    def _sign(self, method: str, endpoint: str, params: dict, timestamp: str) -> str:
        if method.upper() == "GET":
            query = "&".join([f"{k}={v}" for k, v in sorted(params.items()) if v is not None])
            sign_str = f"{timestamp}{method}{endpoint}?{query}" if query else f"{timestamp}{method}{endpoint}"
        else:
            sign_str = f"{timestamp}{method}{endpoint}{json.dumps(params)}"

        signature = base64.b64encode(
            hmac.new(self.secret_key.encode(), sign_str.encode(), hashlib.sha256).digest()
        ).decode("US-ASCII")
        return signature

    def _request(self, method: str, endpoint: str, params: dict = None, is_public: bool = False):
        if params is None:
            params = {}

        timestamp = str(int(time.time() * 1000))
        url = f"{self.base_url}{endpoint}"

        print(f"[DEBUG] 请求: {method} {url}")
        print(f"[DEBUG] 参数: {params}")

        if is_public:
            try:
                resp = requests.request(method, url, params=params, timeout=10)
                result = resp.json()
                print(f"[DEBUG] 公共接口返回: {result}")
                return result
            except Exception as e:
                print(f"[DEBUG] 公共接口异常: {e}")
                return {"code": -1, "msg": str(e)}

        # 私有接口
        sign = self._sign(method, endpoint, params, timestamp)
        headers = {
            "sign": sign,
            "api_key": self.api_key,
            "timestamp": timestamp,
        }

        try:
            if method.upper() == "GET":
                resp = requests.get(url, params=params, headers=headers, timeout=10)
            else:
                headers["Content-type"] = "application/json"
                resp = requests.request(method, url, data=json.dumps(params), headers=headers, timeout=10)

            result = resp.json()
            print(f"[DEBUG] 接口返回: {result}")   # ← 重点看这里
            return result
        except Exception as e:
            print(f"[DEBUG] 请求异常: {e}")
            return {"code": -1, "msg": str(e)}

    # ==================== 常用方法（带调试） ====================

    def get_account_balance(self):
        return self._request("GET", "/v1/perpum/account/available")

    def get_available_balance(self):
        res = self.get_account_balance()
        print(f"[DEBUG] get_available_balance 解析前: {res}")
        try:
            data = res.get("data", [])
            if isinstance(data, list) and len(data) > 0:
                return float(data[0].get("available", 0))
            return 0.0
        except Exception as e:
            print(f"[DEBUG] 解析余额异常: {e}")
            return 0.0

    def get_current_price(self, symbol="ETH"):
        res = self._request("GET", "/v1/perpumPublic/ticker", {"instrument": symbol}, is_public=True)
        print(f"[DEBUG] get_current_price 解析前: {res}")
        try:
            return float(res.get("data", {}).get("lastPrice", 0))
        except:
            return 0.0

    def get_position_info(self, symbol="ETH"):
        return self._request("GET", "/v1/perpum/positions", {"instrument": symbol})

    def place_market_order(self, symbol, side, amount, leverage=5):
        return self._request("POST", "/v1/perpum/order", {
            "instrument": symbol,
            "direction": side.lower(),
            "quantityUnit": "1",
            "quantity": str(amount),
            "leverage": str(leverage),
            "positionModel": "1"
        })

    def close_all_positions(self, symbol="ETH"):
        return self._request("DELETE", "/v1/perpum/allpositions", {"instrument": symbol})

    def cancel_all_open_orders(self, symbol="ETH"):
        return self._request("DELETE", "/v1/perpum/order", {"instrument": symbol})
