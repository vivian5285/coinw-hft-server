#!/usr/bin/env python3
# app.py（币赢最终版 - 端口 5002）
from flask import Flask, request, jsonify
from position_supervisor_coinw import coinw_processor

app = Flask(__name__)

# 安全密钥（与 TradingView 保持一致）
SECRET_KEY = "528586"


@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json

    # 安全校验
    if not data or data.get("secret") != SECRET_KEY:
        return "Unauthorized", 401

    try:
        # 调用核心处理器
        coinw_processor.process_signal(data)
        return jsonify({"status": "success", "msg": "CoinW signal processed"}), 200
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500


@app.route('/health', methods=['GET'])
def health():
    return "healthy", 200


if __name__ == '__main__':
    # 生产环境请使用 Gunicorn 启动
    app.run(host='127.0.0.1', port=5002)
