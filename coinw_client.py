#!/usr/bin/env python3
# coinw_client.py (高频系统底层引擎 - V2.1 合约接口硬核探测版)
import os
import time
import hmac
import hashlib
import requests
import logging
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
            logger.error("❌ 未读取到 COINW_API_KEY 或 COINW_SECRET_KEY，请检查 .env 文件是否配置正确！")
        else:
            logger.info("✅ 成功从 .env 加载 API 密钥！")

    def _sign_request(self, params: dict) -> dict:
        """核心加密签名算法 (HMAC-SHA256)"""
        # CoinW 鉴权必须的参数
        params['api_key'] = self.api_key
        params['timestamp'] = str(int(time.time() * 1000))
        
        # 将参数按字母名字典序排序
        sorted_params = sorted(params.items())
        # 拼接成 a=1&b=2 的形式
        query_string = urlencode(sorted_params)
        
        # 使用 Secret Key 进行 HMAC SHA256 加密
        signature = hmac.new(
            self.secret_key.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest().upper() # 转换为大写十六进制
        
        # 把签名也塞进参数里
        params['sign'] = signature
        return params

    def get_account_balance(self):
        """测试获取账户资产信息 (硬核探测版)"""
        # 探测 CoinW 合约(Swap)账户接口
        endpoint = f"{self.base_url}/api/v1/private/swap/account" 
        
        params = {}
        signed_params = self._sign_request(params)
        
        try:
            logger.info(f"正在探测接口: {endpoint}")
            # 明确请求头，告诉服务器我们发送的是表单数据
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            
            response = requests.post(endpoint, data=signed_params, headers=headers, timeout=5)
            
            # 去掉强硬的报错拦截，直接打印原始状态码和交易所的真实答复
            logger.info(f"HTTP 状态码: {response.status_code}")
            logger.info(f"[CoinWClient] 交易所底层原始答复: {response.text}")
                
        except Exception as e:
            logger.error(f"❌ 探测发生严重异常: {e}")

if __name__ == "__main__":
    logger.info("=== 启动 V2.1 合约接口硬核探测 ===")
    client = CoinWClient()
    client.get_account_balance()
