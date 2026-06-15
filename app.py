#!/usr/bin/env python3
# app.py (CoinW 高频网关通讯塔 - 5002 端口)
from flask import Flask, request, jsonify
import os
import threading
import logging
from dotenv import load_dotenv

# 接入刚刚写好的交易大脑
from position_supervisor import SignalProcessor

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# 从 .env 读取你的专属防伪秘钥 (528586)
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
processor = SignalProcessor()

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    if not data:
        return jsonify({"status": "error", "message": "空负载"}), 400

    # 1. 验证 TradingView 身份
    if str(data.get("secret")) != str(WEBHOOK_SECRET):
        logger.warning("⚠️ 收到非法 Webhook 请求，秘钥不匹配，已拦截！")
        return jsonify({"status": "error", "message": "未授权"}), 401

    action = data.get("action", "").upper()
    logger.info(f"🚨 [网关] 成功接收 TV 信号: {action}")

    # 2. 开启异步线程让大脑去处理交易，网关立刻给 TV 回复 200 OK，确保极速响应
    threading.Thread(target=processor.process_signal, args=(data,)).start()

    return jsonify({"status": "success", "message": "信号已接收并下发执行"}), 200

@app.route('/health', methods=['GET'])
def health_check():
    return "CoinW HFT Gateway is running perfectly", 200

if __name__ == '__main__':
    logger.info("=== 🚀 CoinW 高频网关启动 (监听端口: 5002) ===")
    app.run(host='0.0.0.0', port=5002)
