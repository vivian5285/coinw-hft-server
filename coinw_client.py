#!/usr/bin/env python3
# coinw_client.py（调试增强版 - 带详细日志）
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

# ==================== 日志配置 ====================
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class CoinWClient:
    def __init__(self):
        self.api_key = os.getenv("COINW_API_KEY")
        self.secret_key = os.getenv("COINW_API_SECRET")
        self.base_url = "https://api.coinw.com"

        if not self.api_key or not self.secret_key:
            raise ValueError("请在 .env 中配置 COINW_API_KEY 和 COINW_API_SECRET")

        logger.info("CoinWClient 初始化成功")

    def _request(self, method: str, endpoint: str, params: dict = None):
        """
        统一请求封装（带详细日志）
        """
        if params is None:
            params = {}

        timestamp = str(int(time.time() * 1000))
        request_url = f"{self.base_url}{endpoint}"

        # ==================== 签名构造 ====================
        if method.upper() == "GET":
            query_params = "&".join(f"{k}={v}" for k, v in sorted(params.items()) if v is not None)
            encoded_params = f"{timestamp}{method}{endpoint}?{query_params}" if query_params else f"{timestamp}{method}{endpoint}"
        else:
            encoded_params = f"{timestamp}{method}{endpoint}{json.dumps(params)}"

        signature = base64.b64encode(
            hmac.new(self.secret_key.encode(), encoded_params.encode(), hashlib.sha256).digest()
        ).decode("US-ASCII")

        # ==================== 详细日志输出 ====================
        logger.debug(f"请求方法: {method} | 接口: {endpoint}")
        logger.debug(f"签名字符串: {encoded_params}")
        logger.debug(f"生成的签名: {signature}")

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

            result = resp.json()

            # 打印返回结果（生产环境可改为 logger.debug）
            logger.info(f"接口返回 [{endpoint}] → Code: {result.get('code')} | Msg: {result.get('msg', '')}")
            logger.debug(f"完整返回内容: {result}")

            return result

        except Exception as e:
            logger.error(f"请求异常 [{endpoint}] → {e}")
            return {"code": -1, "msg": str(e)}

    # ==================== 常用方法 ====================

    def get_account_balance(self):
        """获取账户余额原始返回"""
        return self._request("GET", "/v1/perpum/account/available")

    def get_available_balance(self):
        """获取可用 USDT 余额"""
        res = self.get_account_balance()
        try:
            data = res.get("data", {})
            balance = float(data.get("value", 0))
            logger.debug(f"可用余额: {balance} USDT")
            return balance
        except Exception as e:
            logger.error(f"解析余额失败: {e}")
            return 0.0

    def get_current_price(self, symbol="ETH"):
        """获取最新成交价"""
        res = self._request("GET", "/v1/perpumPublic/ticker", {"instrument": symbol})
        try:
            data = res.get("data", [])
            if isinstance(data, list) and len(data) > 0:
                price = float(data[0].get("last_price", 0))
                logger.debug(f"当前价格: {price}")
                return price
            return 0.0
        except Exception as e:
            logger.error(f"获取价格失败: {e}")
            return 0.0

    def get_position_info(self, symbol="ETH"):
        """获取当前持仓信息"""
        return self._request("GET", "/v1/perpum/positions", {"instrument": symbol})

    def place_market_order(self, symbol, side, amount, leverage=5):
        """
        市价开仓（USDT 金额模式）
        amount: USDT 金额
        """
        logger.info(f"市价开仓请求 → 方向: {side} | 金额: {amount} USDT | 杠杆: {leverage}x")
        return self._request("POST", "/v1/perpum/order", {
            "instrument": symbol,
            "direction": side.lower(),
            "quantityUnit": "0",
            "quantity": str(amount),
            "leverage": str(leverage),
            "positionModel": "1",
            "positionType": "plan"
        })

    def place_limit_order(self, symbol, side, price, amount):
        """
        挂限价单（主要用于止盈）
        amount: USDT 金额
        """
        logger.info(f"限价单请求 → 方向: {side} | 价格: {price} | 金额: {amount} USDT")
        return self._request("POST", "/v1/perpum/order", {
            "instrument": symbol,
            "direction": side.lower(),
            "quantityUnit": "0",
            "quantity": str(amount),
            "openPrice": str(price),
            "leverage": "1",
            "positionModel": "1",
            "positionType": "plan"
        })

    def close_all_positions(self, symbol="ETH"):
        """一键全平（内部自动先撤单）"""
        logger.info(f"执行全平操作: {symbol}")
        self.cancel_all_open_orders(symbol)
        time.sleep(0.5)
        return self._request("DELETE", "/v1/perpum/allpositions", {"instrument": symbol})

    def cancel_all_open_orders(self, symbol="ETH"):
        """撤销所有未成交挂单"""
        logger.info(f"撤销所有挂单: {symbol}")
        return self._request("DELETE", "/v1/perpum/order", {"instrument": symbol})
