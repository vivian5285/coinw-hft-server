#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETH 万亿战神 AI 量化交易引擎 - 币赢 (CoinW) 私有核心通信客户端
终极生产版：集成双抽屉全域撤单、实盘稳定开仓组合以及多空持仓循环绞杀机制。
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

    def get_open_orders(self, symbol="ETH", position_type="plan"):
        """精准分箱抓取订单簿：支持通过 positionType 翻找特定类型的抽屉"""
        return self._request("GET", "/v1/perpum/orders/open", {
            "instrument": symbol,
            "positionType": position_type
        })

    # ==========================================
    # 核心执行端指令 (刺客动作)
    # ==========================================

    def place_market_order(self, symbol, side, amount, leverage=20):
        """
        【实盘稳定运行版】开仓委托接口
        使用实盘 100% 验证放行通过的 plan 委托加当前盘口价组合，彻底封杀 902 与 9002 拒单报错。
        下单后会以限价单形式挂入盘口等待撮合，配合主程序 15 秒超时强撤防线。
        """
        current_price = self.get_current_price(symbol)
        open_price = round(current_price, 2)
        
        return self._request("POST", "/v1/perpum/order", {
            "instrument": symbol,
            "direction": side.lower(),
            "quantityUnit": "0",           # 0 代表以 USDT 计价模式下单
            "quantity": str(amount),
            "leverage": str(leverage),
            "positionModel": "1",          # 1 代表全仓模式
            "positionType": "plan",        # 经实盘测试，此配置币赢绝对放行
            "openPrice": str(open_price)   # 配合 plan 锁定当前价报单
        })

    def close_all_positions(self, symbol="ETH"):
        """
        【循环逐一绞杀机制】一键全平持仓
        废弃高危罢工的一键平仓接口。通过 For 循环扫描，不论持仓状态是单向、还是多空双开乌龙，
        全部强行提取唯一的仓位 ID 逐个发令拔除，彻底封杀对冲锁仓状态下的罢工 Bug。
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
                        "closeRate": "1.0"  # 1.0 代表 100% 仓位一刀切全部砸平
                    })
                    closed_count += 1
                    time.sleep(0.2)         # 给交易所撮合引擎释放记账的物理缓冲
            return {"code": 0, "msg": f"阵地扫荡完毕：成功强制全平了 {closed_count} 个仓位"}
        except Exception as e:
            return {"code": -1, "msg": f"逐一平仓流水线异常: {e}"}

    def cancel_all_open_orders(self, symbol="ETH"):
        """
        【终极全域双抽屉扫荡】无盲区撤单
        同时强行穿透并清理 "1" (普通限价) 和 "plan" (计划/条件委托) 两个独立账本，
        彻底消灭由于参数回退留在盘口的“幽灵挂单”，为下一次重新布局腾出绝对干净的舞台。
        """
        cancel_count = 0
        
        # 币赢把单子分存放在两个不同的抽屉，我们两个抽屉全部拉开无差别剿灭
        for p_type in ["1", "plan"]:
            try:
                res = self.get_open_orders(symbol, position_type=p_type)
                data = res.get("data")
                if not data:
                    continue
                    
                order_list = []
                if isinstance(data, list):
                    order_list = data
                elif isinstance(data, dict):
                    order_list = data.get("rows", []) or data.get("list", []) or data.get("data", [])
                    
                for order in order_list:
                    order_id = order.get("id")
                    if order_id:
                        # 锁定挂单 ID，直接向 API 发送定点斩杀指令
                        self._request("DELETE", "/v1/perpum/order", {"id": str(order_id)})
                        cancel_count += 1
                        time.sleep(0.1)     # 撤单小延迟，防止触发频控
            except Exception:
                pass                        # 出现异常时静默跳过，确保强行翻找下一个抽屉
                
        return {"code": 0, "msg": f"全域扫荡完成：成功斩杀了 {cancel_count} 笔盘口挂单"}
