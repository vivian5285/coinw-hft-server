#!/usr/bin/env python3
# coinw_client.py (高频系统底层引擎 - V6.1 完美市价破解版)
import os
import time
import hmac
import hashlib
import base64
import json
import requests
import logging
from dotenv import load_dotenv

# 自动加载 .env 文件中的秘钥
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class CoinWClient:
    def __init__(self):
        self.api_key = os.getenv("COINW_API_KEY")
        self.sec_key = os.getenv("COINW_SECRET_KEY")
        self.base_url = "https://api.coinw.com"

        if not self.api_key or not self.sec_key:
            logger.error("❌ 未读取到 COINW_API_KEY 或 COINW_SECRET_KEY！")

    def _request(self, method: str, api_url: str, params: dict = None):
        """核心加密与请求发射器"""
        if params is None:
            params = {}

        timestamp = str(int(time.time() * 1000))
        request_url = f"{self.base_url}{api_url}"

        # 严格的拼接规则
        if method.upper() == "GET":
            query_params = "&".join(f"{key}={value}" for key, value in params.items() if value is not None)
            encoded_params = f"{timestamp}{method.upper()}{api_url}?{query_params}" if query_params else f"{timestamp}{method.upper()}{api_url}"
        else:
            encoded_params = f"{timestamp}{method.upper()}{api_url}{json.dumps(params)}"

        # 终极 Base64 + HMAC-SHA256 加密
        signature = base64.b64encode(
            hmac.new(
                bytes(self.sec_key, 'utf-8'), 
                msg=bytes(encoded_params, 'utf-8'), 
                digestmod=hashlib.sha256
            ).digest()
        ).decode("US-ASCII")

        headers = {
            "sign": signature,
            "api_key": self.api_key,
            "timestamp": timestamp,
        }
        
        if method.upper() in ["POST", "DELETE", "PUT"]:
            headers["Content-type"] = "application/json"

        try:
            # 发送请求
            if method.upper() == "GET":
                response = requests.get(request_url, params=params, headers=headers, timeout=5)
            elif method.upper() == "POST":
                response = requests.post(request_url, data=json.dumps(params), headers=headers, timeout=5)
            elif method.upper() == "DELETE":
                response = requests.delete(request_url, data=json.dumps(params), headers=headers, timeout=5)
            
            logger.info(f"HTTP 状态码: {response.status_code}")
            logger.info(f"交易所底层原始答复: {response.text}")
            
            if response.status_code == 200:
                return response.json()
            else:
                return None
                
        except Exception as e:
            logger.error(f"❌ 请求发生异常: {e}")
            return None

    def get_account_balance(self):
        """获取合约账户资产"""
        logger.info("=== 准备请求合约账户资产 ===")
        api_url = "/v1/perpum/account/getUserAssets"
        return self._request("GET", api_url)

    def place_market_order(self, symbol: str, direction: str, usdt_amount: float, leverage: int = 5):
        """极速市价开仓扳机"""
        logger.info(f"=== 准备发射开仓指令: {symbol} {direction} 本金:{usdt_amount}U 杠杆:{leverage}X ===")
        api_url = "/v1/perpum/order"
        params = {
            "instrument": symbol.lower(),
            "direction": direction.lower(), 
            "leverage": str(leverage),
            "quantityUnit": "0",  # 0代表按 USDT 金额开仓
            "quantity": str(usdt_amount),
            "positionModel": "1", # 1: 全仓模式
            "positionType": "plan",
            # 【V6.1 破解补丁】：明确声明为市价单
            "type": "market",
            "openPrice": "0"      # 价格传0代表市价全吃
        }
        return self._request("POST", api_url, params)

    def close_all_positions(self, symbol: str = "eth"):
        """一键极速全平扳机"""
        logger.info(f"=== 触发紧急撤退！正在市价全平 {symbol} ===")
        api_url = "/v1/perpum/allpositions"
        params = {
            "instrument": symbol.lower()
        }
        return self._request("DELETE", api_url, params)

if __name__ == "__main__":
    client = CoinWClient()
    
    # 【测试动作 1】：获取余额 (安全，不花钱)
    client.get_account_balance()
    
    # --- ⚠️ 以下为实盘资金操作测试区 ---
    
    # 【测试动作 2】：极小额开仓测试 (目前已开启！)
    client.place_market_order("ETH", "long", 10.0, leverage=5)
    
    # 【测试动作 3】：一键全平测试 (目前被注释保护中)
    # client.close_all_positions("ETH")
