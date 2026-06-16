#!/usr/bin/env python3
# coinw_client.py（短线高频原生限价版）
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

    # ==================== 资产与盘口接口 ====================

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
        """获取所有当前挂在盘口的未成交限价止盈单"""
        return self._request("GET", "/v1/perpum/orders/open", {
            "instrument": symbol,
            "positionType": "plan" 
        })

    # ==================== 交易核心指令 ====================

    def place_market_order(self, symbol, side, amount, leverage=20):
        """市价开仓"""
        current_price = self.get_current_price(symbol)
        open_price = round(current_price, 2)

        return self._request("POST", "/v1/perpum/order", {
            "instrument": symbol,
            "direction": side.lower(),
            "quantityUnit": "0",           # USDT模式
            "quantity": str(amount),
            "leverage": str(leverage),
            "positionModel": "1",          # 全仓模式
            "positionType": "plan",
            "openPrice": str(open_price)
        })

    def place_limit_close_order(self, symbol, price, rate="1.0"):
        """原生持仓限价平仓单（不占用任何保证金，防9008错误）"""
        pos_info = self.get_position_info(symbol)
        try:
            data = pos_info.get("data", [])
            if data and len(data) > 0:
                pos_id = data[0].get("id")
                if pos_id:
                    return self._request("DELETE", "/v1/perpum/positions", {
                        "id": pos_id,
                        "positionType": "plan",
                        "orderPrice": str(round(price, 2)), # 止盈价格
                        "closeRate": str(rate)              # 1.0 代表 100% 一刀切全平
                    })
        except Exception as e:
            return {"code": -1, "msg": f"绑定持仓ID限价止盈异常: {e}"}
        return {"code": -1, "msg": "未找到有效持仓，无法挂出限价单"}

    def close_all_positions(self, symbol="ETH"):
        """强制市价全平"""
        return self._request("DELETE", "/v1/perpum/allpositions", {"instrument": symbol})

    def cancel_all_open_orders(self, symbol="ETH"):
        """全域撤单：扫描盘口所有属于该品种的限价单并彻底抹去"""
        res = self.get_open_orders(symbol)
        cancel_count = 0
        try:
            data = res.get("data")
            if not data:
                return {"code": 0, "msg": "当前无任何遗留限价单"}
                
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
            return {"code": -1, "msg": f"撤单流水线异常: {e}"}
        return {"code": 0, "msg": f"成功扫描并清空了 {cancel_count} 笔未成交限价单"}
