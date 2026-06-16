import os
import threading
from flask import Flask, request, jsonify
import logging
# 【核心修复】：引入正确的新名字 position_supervisor
from position_supervisor_coinw import position_supervisor

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] app: %(message)s')
app = Flask(__name__)

# 币赢的专属接收通道
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "无效的 JSON 数据"}), 400

    secret = data.get("secret", "")
    expected_secret = os.getenv("WEBHOOK_SECRET", "528586")
    
    if secret != expected_secret:
        logging.warning("[Webhook] Secret 校验失败！")
        return jsonify({"status": "error", "message": "Invalid secret"}), 403

    logging.info(f"[Webhook] 密码正确，收到有效信号: {data}")
    
    # 【核心修复】：调用新大脑的 handle_signal 方法
    try:
        threading.Thread(target=position_supervisor.handle_signal, args=(data,), daemon=True).start()
    except Exception as e:
        logging.error(f"[Webhook] 触发执行线程失败: {e}")
        return jsonify({"status": "error", "message": "内部执行错误"}), 500
        
    return jsonify({"message": "CoinW signal processing started", "status": "success"}), 200

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5002)
