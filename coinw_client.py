#!/usr/bin/env python3
# coinw_client.py (高频系统底层引擎 - V3 降维打击 CCXT 版)
import os
import ccxt
import logging
from dotenv import load_dotenv

# 自动加载隐藏的 .env 文件
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class CoinWClient:
    def __init__(self):
        api_key = os.getenv("COINW_API_KEY")
        secret_key = os.getenv("COINW_SECRET_KEY")
        
        if not api_key or not secret_key:
            logger.error("❌ 未读取到 COINW_API_KEY 或 COINW_SECRET_KEY，请检查 .env 文件！")
            return

        # 使用 CCXT 实例化 CoinW 引擎
        self.exchange = ccxt.coinw({
            'apiKey': api_key,
            'secret': secret_key,
            'enableRateLimit': True, # 开启自动防封禁限频保护
            'options': {
                'defaultType': 'swap', # 核心：直接把枪口锁定为合约(Swap)账户！
            }
        })
        logger.info("✅ 成功加载 CCXT 跨平台量化引擎 (CoinW 模块)！")

    def get_account_balance(self):
        """测试获取合约账户资产信息"""
        try:
            logger.info("正在通过 CCXT 请求 CoinW 合约真实余额...")
            # fetch_balance() 会自动处理一切复杂的签名和正确的路由解析
            balance = self.exchange.fetch_balance()
            
            # 提取 USDT 可用余额与总余额
            usdt_free = balance.get('USDT', {}).get('free', 0.0)
            usdt_total = balance.get('USDT', {}).get('total', 0.0)
            
            logger.info(f"🎉 成功打通！当前合约账户 USDT 可用余额: {usdt_free}")
            logger.info(f"💰 当前合约账户 USDT 总权益: {usdt_total}")
            
            return usdt_free
                
        except ccxt.AuthenticationError as e:
            logger.error(f"❌ 鉴权失败 (API Key 错误或未开放合约权限): {e}")
        except Exception as e:
            logger.error(f"❌ 探测发生严重异常: {e}")

if __name__ == "__main__":
    logger.info("=== 启动 V3 引擎降维探测 ===")
    client = CoinWClient()
    client.get_account_balance()
