import os
import time
import hmac
import hashlib
import requests
import json
import base64
from dotenv import load_dotenv

# 自动寻找并加载项目根目录下的 .env 文件
load_dotenv()

class CoinWClient:
    def __init__(self):
        # 动态从 .env 中读取 API 凭证
        self.api_key = os.getenv("COINW_API_KEY")
        self.secret_key = os.getenv("COINW_API_SECRET")
        
        if not self.api_key or not self.secret_key:
            print("❌ 致命错误: 未能读取到 API 密钥，请检查 .env 文件。")
            
        self.base_url = "https://api.futurescw.com" 

    def _request(self, method, endpoint, params=None, is_public=False):
        """
        底层请求封装，兼容公有行情接口与私有交易接口
        """
        # --- 公有接口处理（如获取现价，不需要签名） ---
        if is_public:
            url = f"{self.base_url}{endpoint}"
            try:
                res = requests.request(method, url, params=params)
                return res.json()
            except Exception as e:
                return {"code": -1, "msg": str(e)}

        # --- 私有接口处理（严格遵循官方 V1 签名规范） ---
        if params is None: 
            params = {}
            
        method = method.upper()
        timestamp = str(int(time.time() * 1000))
        request_url = f"{self.base_url}{endpoint}"

        if method == "GET":
            query_params = "&".join(f"{key}={value}" for key, value in params.items() if value is not None)
            encoded_params = f'{timestamp}{method}{endpoint}?{query_params}' if query_params else f'{timestamp}{method}{endpoint}'
        else:
            encoded_params = f'{timestamp}{method}{endpoint}{json.dumps(params)}'

        signature = base64.b64encode(
            hmac.new(
                bytes(self.secret_key, 'utf-8'), 
                msg=bytes(encoded_params, 'utf-8'), 
                digestmod=hashlib.sha256
            ).digest()
        ).decode("US-ASCII")

        headers = {
            "sign": signature,
            "api_key": self.api_key,
            "timestamp": timestamp,
        }

        try:
            if method == "GET":
                response = requests.get(request_url, params=params, headers=headers)
            else:
                headers["Content-type"] = "application/json"
                response = requests.request(method, request_url, data=json.dumps(params), headers=headers)
            return response.json()
        except Exception as e:
            return {"code": -1, "msg": str(e)}

    # ================= 辅助功能：现价与精度 =================

    def format_price(self, price, decimals=2):
        """强制格式化价格精度（ETH通常为2位小数，BTC为1位）"""
        format_str = "{:." + str(decimals) + "f}"
        return format_str.format(float(price))

    def get_latest_price(self, symbol):
        """获取盘口最新成交价 (现价)"""
        res = self._request("GET", "/v1/perpumPublic/ticker", {"instrument": symbol}, is_public=True)
        try:
            # 官方公共行情接口解析
            data = res.get("data", {})
            return float(data.get("lastPrice", 0))
        except Exception:
            return 0.0

    # ================= 核心交易接口 =================

    def place_current_price_order(self, symbol, side, amount, decimals=2):
        """
        【现价发送指令】
        先获取最新现价，再以该价格下达限价单（滑动价差点位极低，且精度绝对安全）
        """
        current_price = self.get_latest_price(symbol)
        if current_price <= 0:
            return {"code": -1, "msg": "获取现价失败，触发熔断停止开仓"}
        
        formatted_price = self.format_price(current_price, decimals)
        print(f"📡 捕获 {symbol} 现价: {formatted_price}，正在执行 {side.upper()} 指令...")
        
        return self._request("POST", "/v1/perpum/order", {
            "instrument": symbol,
            "direction": side.lower(),
            "quantityUnit": "1",           # 1代表合约张数
            "quantity": str(amount),
            "openPrice": formatted_price,  # 已经过精度截断的安全现价
            "positionModel": "1"
        })

    def place_limit_order(self, symbol, side, price, amount, decimals=2):
        """标准指定价格限价单"""
        formatted_price = self.format_price(price, decimals)
        return self._request("POST", "/v1/perpum/order", {
            "instrument": symbol,
            "direction": side.lower(),
            "quantityUnit": "1",
            "quantity": str(amount),
            "openPrice": formatted_price,
            "positionModel": "1"
        })

    def place_market_order(self, symbol, side, amount, leverage):
        """纯市价单开仓（不吃价格精度，但容易产生滑点）"""
        return self._request("POST", "/v1/perpum/order", {
            "instrument": symbol,
            "direction": side.lower(),
            "quantityUnit": "1",
            "quantity": str(amount),
            "leverage": str(leverage),
            "positionModel": "1"
        })

    def close_all_positions(self, symbol):
        """系统安全基石：一键全平"""
        return self._request("DELETE", "/v1/perpum/allpositions", {
            "instrument": symbol
        })

    def get_account_balance(self):
        """获取可用余额"""
        return self._request("GET", "/v1/perpum/account/available")

    def get_avg_price(self, symbol):
        """获取持仓均价"""
        res = self._request("GET", "/v1/perpum/positions", {"instrument": symbol})
        try:
            data = res.get("data", [])
            if isinstance(data, list) and len(data) > 0:
                return float(data[0].get("openPrice", 0))
            return 0.0
        except Exception:
            return 0.0
