#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETH 万亿战神 AI 量化交易引擎 - 币赢 (CoinW) 私有核心通信客户端
V4.0 终极生产版：集成双抽屉全域撤单、多空双向持仓专属按比例切割刀。
"""

import os
import time
import hmac
import hashlib
import base64
import json
import requests
from dotenv import load_dotenv

# 加载环境变数
load_dotenv()

class CoinWClient:
    def __init__(self):
        self.api_key = os.getenv("COINW_API_KEY")
        self.secret_key = os.getenv("COINW_API_SECRET")
        self.base_url = "https://api.coinw.com"

        if not self.api_key or not self.secret_key:
            raise ValueError("错误：未在 .env 中检测到有效 COINW_API_KEY 或 COINW_API_SECRET")

    def _request(self, method: str, endpoint: str, params: dict = None):
        """
        底层 HMAC-SHA256 签名与底层安全加密通信网关
        """
        if params is None:
            params = {}

        timestamp = str(int(time.time() * 1000))
        request_url = f"{self.base_url}{endpoint}"

        # 构造签名字符串
        if method.upper() == "GET":
            query_params = "&".join(f"{k}={v}" for k, v in sorted(params.items()) if v is not None)
            encoded_params = f"{timestamp}{method}{endpoint}?{query_params}" if query_params else f"{timestamp}{method}{endpoint}"
        else:
            encoded_params = f"{timestamp}{method}{endpoint}{json.dumps(params)}"

        # 生成安全签名
        signature = base64.b64encode(
            hmac.new(self.secret_key.encode("utf-8"), encoded_params.encode("utf-8"), hashlib.sha256).digest()
        ).decode("US-ASCII")

        # 装配标准的机构级请求头
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
            return {"code": -1, "msg": f"网络通信层异常: {str(e)}"}

    # ==========================================
    # 核心资金与盘口信息接口 (资产雷达)
    # ==========================================

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

    def get_open_orders(self, symbol="ETH", position_type="plan"):
        return self._request("GET", "/v1/perpum/orders/open", {
            "instrument": symbol,
            "positionType": position_type
        })

    # ==========================================
    # 核心执行端指令 (刺客动作)
    # ==========================================

    def place_market_order(self, symbol, side, amount, leverage=20):
        current_price = self.get_current_price(symbol)
        open_price = round(current_price, 2)
        
        return self._request("POST", "/v1/perpum/order", {
            "instrument": symbol,
            "direction": side.lower(),
            "quantityUnit": "0",           
            "quantity": str(amount),
            "leverage": str(leverage),
            "positionModel": "1",          
            "positionType": "plan",        
            "openPrice": str(open_price)   
        })

    def close_all_positions(self, symbol="ETH"):
        pos_info = self.get_position_info(symbol)
        closed_count = 0
        try:
            data = pos_info.get("data", [])
            if not data or len(data) == 0:
                return {"code": 0, "msg": "当前没有需要清理的实盘持仓"}

            for pos in data:
                pos_id = pos.get("id")
                if pos_id:
                    self._request("DELETE", "/v1/perpum/positions", {
                        "id": str(pos_id),
                        "closeRate": "1.0"  
                    })
                    closed_count += 1
                    time.sleep(0.2)         
            return {"code": 0, "msg": f"阵地扫荡完毕：成功强制全平了 {closed_count} 个仓位"}
        except Exception as e:
            return {"code": -1, "msg": f"逐一平仓流水线异常: {e}"}

    def close_position_partial(self, symbol="ETH", close_rate="0.5"):
        """
        【双向持仓专属安全切割刀】绕过反向下单，直接从底层扣减指定比例仓位。
        """
        pos_info = self.get_position_info(symbol)
        closed_count = 0
        try:
            data = pos_info.get("data", [])
            if not data or len(data) == 0:
                return {"code": 0, "msg": "当前没有需要平的实盘持仓"}

            for pos in data:
                pos_id = pos.get("id")
                if pos_id:
                    self._request("DELETE", "/v1/perpum/positions", {
                        "id": str(pos_id),
                        "closeRate": str(close_rate)
                    })
                    closed_count += 1
                    time.sleep(0.2)
            return {"code": 0, "msg": f"成功按 {close_rate} 比例切除了 {closed_count} 个仓位"}
        except Exception as e:
            return {"code": -1, "msg": f"部分平仓异常: {e}"}

    def cancel_all_open_orders(self, symbol="ETH"):
        cancel_count = 0
        for p_type in ["1", "plan"]:
            try:
                res = self.get_open_orders(symbol, position_type=p_type)
                data = res.get("data")
                if not data: continue
                    
                order_list = []
                if isinstance(data, list): order_list = data
                elif isinstance(data, dict): order_list = data.get("rows", []) or data.get("list", []) or data.get("data", [])
                    
                for order in order_list:
                    order_id = order.get("id")
                    if order_id:
                        self._request("DELETE", "/v1/perpum/order", {"id": str(order_id)})
                        cancel_count += 1
                        time.sleep(0.1)     
            except Exception:
                pass                        
        return {"code": 0, "msg": f"成功斩杀了 {cancel_count} 笔盘口挂单"}
