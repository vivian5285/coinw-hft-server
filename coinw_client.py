#!/usr/bin/env python3
# coinw_client.py (高频系统底层引擎 - V1 连通测试版)
import os
import time
import hmac
import hashlib
import requests
import logging
from urllib.parse import urlencode

# 配置简单的日志输出
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class CoinWClient:
    def __init__(self):
        # 强制从环境变量读取，绝不把秘钥写在代码里（最高安全级别）
        self.api_key = os.getenv("COINW_API_KEY")
        self.secret_key = os.getenv("COINW_SECRET_KEY")
        
        # CoinW 合约 API 的基础域名 (如果官方有变更需调整)
        self.base_url = "https://api.coinw.com" 
        
        if not self.api_key or not self.secret_key:
            logger.warning("未检测到 COINW_API_KEY 或 COINW_SECRET_KEY，请确保环境变量已配置！")

    def _get_headers(self):
        """生成鉴权请求头 (具体按 CoinW 官方文档微调)"""
        return {
            "Content-Type": "application/json",
            "AccessKey": self.api_key if self.api_key else ""
        }

    def _sign_request(self, params: dict) -> dict:
        """核心加密签名算法 (HMAC-SHA256)"""
        if not self.secret_key:
            return params
            
        params['timestamp'] = str(int(time.time() * 1000))
        # 将参数按字母顺序排序并拼接
        query_string = urlencode(sorted(params.items()))
        # 生成签名
        signature = hmac.new(
            self.secret_key.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        params['sign'] = signature
        return params

    def get_current_price(self, symbol: str = "ETH/USDT") -> float:
        """获取合约当前价格 (免签名公共接口测试)"""
        # 注意：此处使用 CoinW 常见的公共行情接口路径，用于初步打通网络
        endpoint = f"{self.base_url}/api/v1/public?command=returnTicker"
        try:
            response = requests.get(endpoint, timeout=5)
            response.raise_for_status()
            data = response.json()
            
            # 解析逻辑（根据实际返回 JSON 结构适配）
            if data and "data" in data:
                # 假设返回的数据里包含我们需要的币种信息
                tickers = data["data"]
                if symbol in tickers:
                    price = float(tickers[symbol].get("last", 0.0))
                    logger.info(f"[CoinWClient] 成功获取 {symbol} 最新价格: {price}")
                    return price
            
            logger.warning(f"[CoinWClient] 价格获取格式不匹配，原始返回: {data}")
            return 0.0
            
        except requests.exceptions.RequestException as e:
            logger.error(f"[CoinWClient] 网络请求失败: {e}")
            return 0.0
        except Exception as e:
            logger.error(f"[CoinWClient] 解析数据异常: {e}")
            return 0.0

if __name__ == "__main__":
    # 本地直接运行该文件时的测试代码
    logger.info("=== 开始测试 CoinW API 连通性 ===")
    client = CoinWClient()
    price = client.get_current_price("ETH/USDT")
    if price > 0:
        logger.info("✅ 恭喜！服务器与 CoinW 交易所的网络通信已完美打通！")
    else:
        logger.error("❌ 通信失败或解析异常，需要核对基础路由。")
