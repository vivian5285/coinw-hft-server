#!/usr/bin/env python3
# coinw_client.py (高频系统底层引擎 - V4 官方原生探路版)
import requests
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class CoinWClient:
    def __init__(self):
        # 基础 URL 完全对齐你找出的官方文档
        self.base_url = "https://api.coinw.com" 

    def test_public_endpoint(self):
        """测试官方文档中的公共合约接口"""
        endpoint = f"{self.base_url}/api/v1/perpum/instruments" 
        
        try:
            logger.info(f"正在探测官方合约公共接口: {endpoint}")
            response = requests.get(endpoint, timeout=5)
            logger.info(f"HTTP 状态码: {response.status_code}")
            
            # 如果成功，打印前 500 个字符看看长什么样
            if response.status_code == 200:
                logger.info(f"✅ 成功获取合约市场数据: {response.text[:500]}...")
            else:
                logger.error(f"❌ 请求失败: {response.text}")
                
        except Exception as e:
            logger.error(f"❌ 探测发生严重异常: {e}")

if __name__ == "__main__":
    logger.info("=== 启动 V4 官方原生探路 ===")
    client = CoinWClient()
    client.test_public_endpoint()
