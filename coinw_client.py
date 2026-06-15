import time
import hmac
import hashlib
import requests
import json
import base64

class CoinWClient:
    def __init__(self):
        # 请确保这些配置在你的环境中
        self.api_key = "你的API_KEY"
        self.secret_key = "你的SECRET_KEY"
        self.base_url = "https://api.futurescw.com" # 请根据实际 API 文档确认

    def _sign(self, params):
        """生成签名"""
        query = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
        return hmac.new(self.secret_key.encode(), query.encode(), hashlib.sha256).hexdigest()

    def _request(self, method, endpoint, params=None):
        """底层请求封装"""
        if params is None: params = {}
        params['timestamp'] = int(time.time() * 1000)
        params['api_key'] = self.api_key
        params['sign'] = self._sign(params)
        
        try:
            url = f"{self.base_url}{endpoint}"
            response = requests.request(method, url, data=params)
            return response.json()
        except Exception as e:
            return {"code": -1, "msg": str(e)}

    # ================= 核心交易接口 =================

    def place_market_order(self, symbol, side, amount, leverage):
        """市价开仓"""
        return self._request("POST", "/v1/perpum/order/market", {
            "symbol": symbol,
            "side": side, # LONG/SHORT
            "amount": amount,
            "leverage": leverage
        })

    def place_limit_order(self, symbol, side, price, amount):
        """挂限价止盈单 (Post-only)"""
        return self._request("POST", "/v1/perpum/order/limit", {
            "symbol": symbol,
            "side": side, # CLOSE_LONG / CLOSE_SHORT
            "price": price,
            "amount": amount,
            "type": "limit",
            "post_only": True 
        })

    def close_all_positions(self, symbol):
        """全平仓位并撤销所有挂单 (这是系统安全的基石)"""
        # 1. 撤销所有当前挂单，防止限价止盈单遗留
        self._request("POST", "/v1/perpum/order/cancel_all", {"symbol": symbol})
        # 2. 市价平仓
        return self._request("POST", "/v1/perpum/position/close_all", {"symbol": symbol})

    def get_account_balance(self):
        """获取余额 (用于动态仓位计算)"""
        return self._request("GET", "/v1/perpum/account/balance")

    def get_avg_price(self, symbol):
        """获取当前持仓均价"""
        res = self._request("GET", "/v1/perpum/position/info", {"symbol": symbol})
        return float(res.get("data", {}).get("avgPrice", 0))
