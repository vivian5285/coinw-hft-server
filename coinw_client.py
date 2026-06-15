#!/usr/bin/env python3
# coinw_client.py (高频系统底层引擎 - V2.2 JSON 格式攻坚版)
import os
import time
import hmac
import hashlib
import requests
import logging
import json
from urllib.parse import urlencode
from dotenv import load_dotenv

# 1. 自动加载隐藏的 .env 文件
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class CoinWClient:
    def __init__(self):
        self.api_key = os.getenv("COINW_API_KEY")
        self.secret_key = os.getenv("COINW_SECRET_KEY")
        
        # CoinW API 基础域名
        self.base_url = "https://api.coinw.com" 
        
        if not self.api_key or not self.secret_key:
            logger.error("❌ 未读取到 COINW_API_KEY 或 COINW_SECRET_KEY，请检查 .env 文件！")
        else:
            logger.info("✅ 成功从 .env 加载 API 密钥！")

    def _sign_request(self, params: dict) -> dict:
        """核心加密签名算法 (HMAC-SHA256)"""
        params['api_key'] = self.api_key
        params['timestamp'] = str(int(time.time() * 1000))
        
        # 将参数按字母名字典序排序
        sorted_params = sorted(params.items())
        query_string = urlencode(sorted_params)
        
        # 使用 Secret Key 进行 HMAC SHA256 加密
        signature = hmac.new(
            self.secret_key.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest().upper() 
        
        # 把签名塞进参数里
        params['sign'] = signature
        return params

    def get_account_balance(self):
        """测试获取账户资产信息 (JSON 终极破解版)"""
        # 探测 CoinW 合约(Swap)账户接口
        endpoint = f"{self.base_url}/api/v1/private/swap/account" 
        
        params = {}
        signed_params = self._sign_request(params)
        
        try:
            logger.info(f"正在探测接口: {endpoint}")
            
            # 【V2.2 核心改动】：明确告诉服务器，我们要发送的是 JSON 数据！
            headers = {"Content-Type": "application/json"}
            
            # 打印出我们到底发了什么，做到心里有数
            logger.info(f"发送的 JSON 负载: {json.dumps(signed_params)}")
            
            # 使用 json=signed_params，requests 会自动将我们的字典完美转换成 JSON 字符串
            response = requests.post(endpoint, json=signed_params, headers=headers, timeout=5)
            
            logger.info(f"HTTP 状态码: {response.status_code}")
            logger.info(f"[CoinWClient] 交易所底层原始答复: {response.text}")
                
        except Exception as e:
            logger.error(f"❌ 探测发生严重异常: {e}")

if __name__ == "__main__":
    logger.info("=== 启动 V2.2 合约接口 JSON 格式探测 ===")
    client = CoinWClient()
    client.get_account_balance()
