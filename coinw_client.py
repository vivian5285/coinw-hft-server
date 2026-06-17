#!/usr/bin/env python3
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
                resp = requests.request(method.upper(), request_url, data=json.dumps(params), headers=headers, timeout=10)
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

    def get_open_orders(self, symbol="ETH"):
        """【修复】移除 positionType 参数，无差别抓取盘口所有隐藏挂单"""
        return self._request("GET", "/v1/perpum/orders/open", {
            "instrument": symbol
        })

    def place_market_order(self, symbol, side, amount, leverage=20):
        """【重大修复】纯正市价单，绝不传 openPrice，强制瞬间吃单！"""
        return self._request("POST", "/v1/perpum/order", {
            "instrument": symbol,
            "direction": side.lower(),
            "quantityUnit": "0",           
            "quantity": str(amount),
            "leverage": str(leverage),
            "positionModel": "1"
        })

    def place_limit_close_order(self, symbol, price, rate="1.0"):
        """原生持仓限价平仓单"""
        pos_info = self.get_position_info(symbol)
        try:
            data = pos_info.get("data", [])
            if data and len(data) > 0:
                pos_id = data[0].get("id")
                if pos_id:
                    return self._request("DELETE", "/v1/perpum/positions", {
                        "id": str(pos_id),
                        "positionType": "plan",
                        "orderPrice": str(round(price, 2)),
                        "closeRate": str(rate)
                    })
        except Exception as e:
            return {"code": -1, "msg": f"绑定持仓ID异常: {e}"}
        return {"code": -1, "msg": "未找到有效持仓"}

    def close_all_positions(self, symbol="ETH"):
        """【重大修复】循环逐一绞杀：查出所有多空持仓，一个个强制平仓，解决对冲状态罢工 Bug"""
        pos_info = self.get_position_info(symbol)
        closed_count = 0
        try:
            data = pos_info.get("data", [])
            for pos in data:
                pos_id = pos.get("id")
                if pos_id:
                    self._request("DELETE", "/v1/perpum/positions", {
                        "id": str(pos_id),
                        "closeRate": "1.0"
                    })
                    closed_count += 1
                    time.sleep(0.2)
            return {"code": 0, "msg": f"成功逐一平掉 {closed_count} 个仓位"}
        except Exception as e:
            return {"code": -1, "msg": f"逐一平仓异常: {e}"}

    def cancel_all_open_orders(self, symbol="ETH"):
        """全域撤单"""
        res = self.get_open_orders(symbol)
        cancel_count = 0
        try:
            data = res.get("data")
            if not data:
                return {"code": 0, "msg": "当前无挂单"}
                
            order_list = []
            if isinstance(data, list):
                order_list = data
            elif isinstance(data, dict):
                order_list = data.get("rows", []) or data.get("list", [])
                
            for order in order_list:
                order_id = order.get("id")
                if order_id:
                    self._request("DELETE", "/v1/perpum/order", {"id": str(order_id)})
                    cancel_count += 1
                    time.sleep(0.1) 
        except Exception as e:
            return {"code": -1, "msg": f"撤单异常: {e}"}
        return {"code": 0, "msg": f"清空了 {cancel_count} 笔挂单"}
