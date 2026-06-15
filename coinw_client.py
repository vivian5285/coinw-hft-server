#!/usr/bin/env python3
# coinw_client.py (高频系统底层引擎 - V5 官方底层逻辑直连版)
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
        """完全按照官方 Python 示例重构的核心加密与请求发射器"""
        if params is None:
            params = {}

        # 1. 生成时间戳
        timestamp = str(int(time.time() * 1000))
        request_url = f"{self.base_url}{api_url}"

        # 2. 拼接加密前置字符串 (要求极度严苛，包含时间戳、方法和路径)
        if method.upper() == "GET":
            # GET 方法的参数必须用 & 拼接
            query_params = "&".join(f"{key}={value}" for key, value in params.items() if value is not None)
            encoded_params = f"{timestamp}{method.upper()}{api_url}?{query_params}" if query_params else f"{timestamp}{method.upper()}{api_url}"
        else:
            # POST/DELETE/PUT 方法必须把参数转为 JSON 字符串拼接
            encoded_params = f"{timestamp}{method.upper()}{api_url}{json.dumps(params)}"

        # 3. 生成 HMAC SHA256 并进行 Base64 编码 (破案核心)
        signature = base64.b64encode(
            hmac.new(
                bytes(self.sec_key, 'utf-8'), 
                msg=bytes(encoded_params, 'utf-8'), 
                digestmod=hashlib.sha256
            ).digest()
        ).decode("US-ASCII")

        # 4. 组装请求头
        headers = {
            "sign": signature,
            "api_key": self.api_key,
            "timestamp": timestamp,
        }
        
        if method.upper() in ["POST", "DELETE", "PUT"]:
            headers["Content-type"] = "application/json"

        # 5. 发送最终请求
        try:
            if method.upper() == "GET":
                response = requests.get(request_url, params=params, headers=headers, timeout=5)
            elif method.upper() == "POST":
                response = requests.post(request_url, data=json.dumps(params), headers=headers, timeout=5)
            
            # 成功或失败，都将交易所的回答打印出来
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
        """获取合约账户资产 (使用最新的绝密门牌号)"""
        logger.info("=== 准备携带终极签名请求合约账户资产 ===")
        # 绝密路由：获取合约账户资产
        api_url = "/v1/perpum/account/getUserAssets"
        return self._request("GET", api_url)

if __name__ == "__main__":
    client = CoinWClient()
    client.get_account_balance()
