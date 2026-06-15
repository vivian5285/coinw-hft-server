#!/usr/bin/env python3
# coinw_client.py (高频系统底层引擎 - V2 账户鉴权与余额测试版)
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
        
        # CoinW 合约/现货 API 基础域名
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
        """测试获取账户资产信息 (鉴权测试)"""
        # 注意：这里我们先用一个通用的私有接口进行网络与签名打样探测
        # 不同交易所的合约和现货私有路径不同，这一步主要是为了验证签名算法是否被 CoinW 认可
        endpoint = f"{self.base_url}/api/v1/private/account/asset" 
        
        params = {}
        signed_params = self._sign_request(params)
        
        try:
            logger.info("正在携带数字签名请求私有账户数据...")
            # 私有接口通常需要 POST 请求
            response = requests.post(endpoint, data=signed_params, timeout=5)
            
            # 如果 HTTP 状态码不是 200，这行会抛出异常
            response.raise_for_status() 
            data = response.json()
            
            logger.info(f"[CoinWClient] 交易所返回原始数据: {data}")
            
            # 判断鉴权是否成功
            code = str(data.get("code", ""))
            if code == "200" or code == "0":
                logger.info("✅ 鉴权完美通过！我们成功读取到了你的私有账户！")
            else:
                logger.warning(f"⚠️ 服务器连通了，但鉴权未通过，请留意返回的错误提示。")
                
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ 网络或接口路由请求失败 (可能是路由路径需按合约文档微调): {e}")

if __name__ == "__main__":
    logger.info("=== 启动 V2 账户鉴权与余额探测 ===")
    client = CoinWClient()
    client.get_account_balance()
