#!/usr/bin/env python3
import os
import threading
from flask import Flask, request, jsonify
import logging
import json
from position_supervisor_coinw import coinw_processor

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] app: %(message)s')
app = Flask(__name__)

@app.route('/coinw/webhook', methods=['POST'])
def webhook():
    # 1. 提取 JSON 包裹 (终极兼容模式：无视 TV 的 Header 标签，强制暴力解析)
    data = request.get_json(force=True, silent=True)
    if not data:
        try:
            raw_data = request.get_data(as_text=True)
            data = json.loads(raw_data)
        except Exception:
            return jsonify({"status": "error", "message": "无效的 JSON 数据"}), 400

    secret = data.get("secret", "")
    expected_secret = os.getenv("WEBHOOK_SECRET", "528586")
    
    if secret != expected_secret:
        logging.warning("[Webhook] Secret 校验失败！")
        return jsonify({"status": "error", "message": "Invalid secret"}), 403

    logging.info(f"[Webhook] 密码正确，收到币赢有效信号: {data}")
    
    try:
        threading.Thread(target=coinw_processor.process_signal, args=(data,), daemon=True).start()
    except Exception as e:
        logging.error(f"[Webhook] 触发执行线程失败: {e}")
        return jsonify({"status": "error", "message": "内部执行错误"}), 500
        
    return jsonify({"message": "Signal processing started", "status": "success"}), 200

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5002)
