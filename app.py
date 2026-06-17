#!/usr/bin/env python3
# app.py（CoinW 异步防阻塞最终版）
from flask import Flask, request, jsonify
from position_supervisor_coinw import coinw_processor
import os
import threading
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] app: %(message)s')
app = Flask(__name__)

SECRET_KEY = os.getenv("WEBHOOK_SECRET", "528586")

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    if not data or data.get("secret") != SECRET_KEY:
        logging.warning("[Webhook] 收到无权限的请求或 Secret 错误")
        return "Unauthorized", 401

    logging.info(f"[Webhook] 密码正确，收到 TV 信号: {data.get('action')}")
    
    try:
        # 【核心修复】：剥离主线程，瞬间回复 TV，防止 Webhook 超时报错
        threading.Thread(target=coinw_processor.process_signal, args=(data,), daemon=True).start()
        return jsonify({"status": "success"}), 200
    except Exception as e:
        logging.error(f"[Webhook] 触发执行线程失败: {e}")
        return jsonify({"status": "error", "msg": str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    return "healthy", 200

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5002)
