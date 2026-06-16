#!/usr/bin/env python3
# coinw_client.py（完整版 - 基于你测试过的版本）
import time
import hmac
import hashlib
import requests
import os
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class CoinWClient:
    def __init__(self):
        self.api_key = os.getenv("COINW_API_KEY")
        self.secret_key = os.getenv("COINW_SECRET_KEY")
        self.base_url = "https://api.futurescw.com"   # 你测试通过的域名

        if not self.api_key or not self.secret_key:
            raise ValueError("请在 .env 文件中配置 COINW_API_KEY 和 COINW_SECRET_KEY")

    def _sign(self, params: dict) -> str:
        """生成签名"""
        query = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
        return hmac.new(self.secret_key.encode(), query.encode(), hashlib.sha256).hexdigest()

    def _request(self, method: str, endpoint: str, params: dict = None):
        """统一请求封装"""
        if params is None:
            params = {}

        params["timestamp"] = int(time.time() * 1000)
        params["api_key"] = self.api_key
        params["sign"] = self._sign(params)

        url = f"{self.base_url}{endpoint}"

        try:
            if method.upper() == "GET":
                response = requests.get(url, params=params, timeout=15)
            else:
                response = requests.post(url, data=params, timeout=15)

            return response.json()
        except Exception as e:
            logger.error(f"[CoinW] 请求异常: {e}")
            return {"code": -1, "msg": str(e)}

    # ==================== 账户与行情 ====================
    def get_account_balance(self):
        """获取账户余额"""
        return self._request("GET", "/v1/perpum/account/balance")

    def get_available_balance(self):
        """获取可用 USDT 余额"""
        res = self.get_account_balance()
        return float(res.get("data", {}).get("availableUsdt", 0))

    def get_current_price(self, symbol: str = "ETHUSDT"):
        """获取当前最新价格"""
        res = self._request("GET", "/v1/perpum/market/ticker", {"symbol": symbol})
        return float(res.get("data", {}).get("lastPrice", 0))

    def get_position_info(self, symbol: str = "ETHUSDT"):
        """获取当前持仓信息"""
        return self._request("GET", "/v1/perpum/position/info", {"symbol": symbol})

    def get_avg_price(self, symbol: str = "ETHUSDT"):
        """获取当前持仓均价"""
        res = self.get_position_info(symbol)
        return float(res.get("data", {}).get("avgPrice", 0))

    # ==================== 交易接口 ====================
    def place_market_order(self, symbol: str, side: str, amount: float, leverage: int = 5):
        """市价开仓"""
        return self._request("POST", "/v1/perpum/order/market", {
            "symbol": symbol,
            "side": side,
            "amount": amount,
            "leverage": leverage
        })

    def place_limit_order(self, symbol: str, side: str, price: float, amount: float):
        """挂限价止盈单（Post Only）"""
        return self._request("POST", "/v1/perpum/order/limit", {
            "symbol": symbol,
            "side": side,
            "price": price,
            "amount": amount,
            "type": "limit",
            "post_only": True
        })

    def close_all_positions(self, symbol: str = "ETHUSDT"):
        """全平仓位（并撤销挂单）"""
        self.cancel_all_open_orders(symbol)
        time.sleep(0.5)
        return self._request("POST", "/v1/perpum/position/close_all", {"symbol": symbol})

    def cancel_all_open_orders(self, symbol: str = "ETHUSDT"):
        """撤销所有挂单"""
        return self._request("POST", "/v1/perpum/order/cancel_all", {"symbol": symbol})
