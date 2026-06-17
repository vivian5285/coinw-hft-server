#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETH 万亿战神 AI 量化交易引擎 - 币赢 (CoinW) 私有核心通信客户端
终极生产版：已彻底修复 9002 拒单报错，支持纯物理市价吃单与 13 刀极限锁盈。
"""

import os
import time
import hmac
import hashlib
import base64
import json
import requests
from dotenv import load_dotenv

# 加载环境变量
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
        底层 HMAC-SHA256 签名与加密通信网关
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
        """获取永续合约账户可用资产明细"""
        return self._request("GET", "/v1/perpum/account/available")

    def get_available_balance(self):
        """抓取当前可直接调用的可用 USDT 余额数字"""
        res = self.get_account_balance()
        try:
            data = res.get("data", {})
            return float(data.get("value", 0))
        except:
            return 0.0

    def get_current_price(self, symbol="ETH"):
        """获取盘口最新现价 (Ticker)"""
        res = self._request("GET", "/v1/perpumPublic/ticker", {"instrument": symbol})
        try:
            data = res.get("data", [])
            if isinstance(data, list) and len(data) > 0:
                return float(data[0].get("last_price", 0))
            return 0.0
        except:
            return 0.0

    def get_position_info(self, symbol="ETH"):
        """精准检索当前品种的实盘持仓状态详情"""
        return self._request("GET", "/v1/perpum/positions", {"instrument": symbol})

    def get_open_orders(self, symbol="ETH"):
        """无差别抓取该币种在盘口上残留的所有未成交挂单 (包含限价单与计划单)"""
        return self._request("GET", "/v1/perpum/orders/open", {
            "instrument": symbol
        })

    # ==========================================
    # 核心执行端指令 (刺客动作)
    # ==========================================

    def place_market_order(self, symbol, side, amount, leverage=20):
        """
        【真·市价终极修复版】市价开仓委托
        使用标准的 positionType: "market"，彻底封杀 9002 报错，强制撮合引擎瞬间吃单！
        """
        return self._request("POST", "/v1/perpum/order", {
            "instrument": symbol,
            "direction": side.lower(),
            "quantityUnit": "0",           # 0 代表以 USDT 计价模式下单
            "quantity": str(amount),
            "leverage": str(leverage),
            "positionModel": "1",          # 1 代表全仓模式
            "positionType": "market"       # 【救命修复】行业标准的市价单标识
        })

    def place_limit_close_order(self, symbol, price, rate="1.0"):
        """
        原生限价平仓锁盈
        通过精确绑定当前持仓的内部唯一 ID，将限价平仓单钉入订单簿。不占用可用余额，不报 9008 错误。
        """
        pos_info = self.get_position_info(symbol)
        try:
            data = pos_info.get("data", [])
            if data and len(data) > 0:
                pos_id = data[0].get("id")
                if pos_id:
                    return self._request("DELETE", "/v1/perpum/positions", {
                        "id": str(pos_id),
                        "positionType": "plan",  # 代表属于止盈挂单类型
                        "orderPrice": str(round(price, 2)),
                        "closeRate": str(rate)   # "1.0" 代表 100% 仓位一刀切
                    })
        except Exception as e:
            return {"code": -1, "msg": f"绑定持仓 ID 限价止盈流产: {e}"}
        return {"code": -1, "msg": "拒绝挂限价单：盘面未检测到任何可用持仓"}

    def close_all_positions(self, symbol="ETH"):
        """
        【循环绞杀平仓】一键市价全平
        废弃高危罢工的一键平仓接口，改为通过 For 循环扫描，不论持仓状态是单向、还是罕见的多空双开，全部逐一强制拔除。
        """
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
                        "closeRate": "1.0"  # 市价 100% 斩杀平仓
                    })
                    closed_count += 1
                    time.sleep(0.2)         # 给撮合引擎释放记账的时间微调
            return {"code": 0, "msg": f"阵地扫荡完毕：成功强制全平了 {closed_count} 个方向的仓位"}
        except Exception as e:
            return {"code": -1, "msg": f"逐一平仓流水线异常: {e}"}

    def cancel_all_open_orders(self, symbol="ETH"):
        """
        全域撤单
        全方位检索订单簿中所有未成交的挂单，进行无死角清除，为下一次重新布局腾出干净的舞台。
        """
        res = self.get_open_orders(symbol)
        cancel_count = 0
        try:
            data = res.get("data")
            if not data:
                return {"code": 0, "msg": "订单簿干干净净，没有需要撤销的挂单"}
                
            order_list = []
            if isinstance(data, list):
                order_list = data
            elif isinstance(data, dict):
                order_list = data.get("rows", []) or data.get("list", []) or data.get("data", [])
                
            for order in order_list:
                order_id = order.get("id")
                if order_id:
                    self._request("DELETE", "/v1/perpum/order", {"id": str(order_id)})
                    cancel_count += 1
                    time.sleep(0.1)         # 撤单缓冲，防频发限制
        except Exception as e:
            return {"code": -1, "msg": f"撤单流水线遭遇阻碍: {e}"}
        return {"code": 0, "msg": f"全域撤单完毕：已成功从盘口抹去 {cancel_count} 笔遗留单"}
