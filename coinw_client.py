#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETH 万亿战神 AI 量化交易引擎 - 币赢 (CoinW) V8.0 限价刺客版
专属适配：防双向对冲、双重撤单清场
"""

import os
import time
import hmac
import hashlib
import base64
import json
import requests
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

class CoinWClient:
    def __init__(self):
        self.api_key = os.getenv("COINW_API_KEY")
        self.secret_key = os.getenv("COINW_API_SECRET")
        self.base_url = "https://api.coinw.com"

        if not self.api_key or not self.secret_key:
            logger.error("🚨 缺少币赢 API 密钥！")

    def _request(self, method: str, endpoint: str, params: dict = None):
        if params is None: params = {}
        timestamp = str(int(time.time() * 1000))
        request_url = f"{self.base_url}{endpoint}"

        if method.upper() == "GET":
            query_params = "&".join(f"{k}={v}" for k, v in sorted(params.items()) if v is not None)
            encoded_params = f"{timestamp}{method}{endpoint}?{query_params}" if query_params else f"{timestamp}{method}{endpoint}"
        else:
            encoded_params = f"{timestamp}{method}{endpoint}{json.dumps(params)}"

        signature = base64.b64encode(
            hmac.new(self.secret_key.encode("utf-8"), encoded_params.encode("utf-8"), hashlib.sha256).digest()
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
            return {"code": -1, "msg": f"网络通信异常: {str(e)}"}

    def get_available_balance(self):
        res = self._request("GET", "/v1/perpum/account/available")
        try:
            return float(res.get("data", {}).get("value", 0))
        except: return 0.0

    def get_current_price(self, symbol="ETH"):
        res = self._request("GET", "/v1/perpumPublic/ticker", {"instrument": symbol})
        try:
            data = res.get("data", [])
            if isinstance(data, list) and len(data) > 0: return float(data[0].get("last_price", 0))
            return 0.0
        except: return 0.0

    def get_position_info(self, symbol="ETH"):
        return self._request("GET", "/v1/perpum/positions", {"instrument": symbol})

    def get_open_orders(self, symbol="ETH", position_type="plan"):
        return self._request("GET", "/v1/perpum/orders/open", {"instrument": symbol, "positionType": position_type})

    # ==================== V8.0 核心新增：币赢专属防对冲限价引擎 ====================
    def place_limit_order(self, symbol, side, price, amount, leverage=20, is_close=False):
        """
        is_close=False -> 正常开仓建仓
        is_close=True  -> 挂限价止盈单 (强制反向指令吃掉原仓位，防对冲)
        """
        direction = side.lower()
        if is_close:
            # 币赢特殊逻辑：如果持有多单，止盈必须挂空单指令 (在单向模式下自动抵消)
            direction = "short" if side.upper() == "LONG" else "long"

        params = {
            "instrument": symbol,
            "direction": direction,
            "quantityUnit": "0",           
            "quantity": str(round(amount, 4)), # 保证精度安全
            "leverage": str(leverage),
            "positionModel": "1",          # 强锁定：1=单向持仓模式
            "orderType": "limit",          # 纯净限价单
            "price": str(round(price, 2))
        }

        # 如果平台支持底层 reduceOnly 标识，直接挂载
        if is_close:
            params["reduceOnly"] = True 

        action_msg = "止盈减仓" if is_close else "开仓建仓"
        logger.info(f"⚔️ 币赢限价指令 [{action_msg}]: {direction} {amount} 筹码 @ {price}")
        return self._request("POST", "/v1/perpum/order", params)

    def close_all_positions(self, symbol="ETH"):
        pos_info = self.get_position_info(symbol)
        closed_count = 0
        try:
            data = pos_info.get("data", [])
            for pos in data:
                pos_id = pos.get("id")
                if pos_id:
                    self._request("DELETE", "/v1/perpum/positions", {"id": str(pos_id), "closeRate": "1.0"})
                    closed_count += 1
                    time.sleep(0.2)         
            return {"code": 0, "msg": f"清剿完毕：平仓 {closed_count} 个"}
        except Exception as e: return {"code": -1, "msg": str(e)}

    def cancel_all_open_orders(self, symbol="ETH"):
        cancel_count = 0
        for p_type in ["1", "plan"]:
            try:
                res = self.get_open_orders(symbol, position_type=p_type)
                data = res.get("data")
                if not data: continue
                order_list = data if isinstance(data, list) else (data.get("rows", []) or data.get("list", []) or data.get("data", []))
                for order in order_list:
                    order_id = order.get("id")
                    if order_id:
                        self._request("DELETE", "/v1/perpum/order", {"id": str(order_id)})
                        cancel_count += 1
                        time.sleep(0.1)     
            except Exception: pass                        
        return {"code": 0, "msg": f"撤单完毕：斩杀 {cancel_count} 笔挂单"}

coinw_client = CoinWClient()
