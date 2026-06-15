from flask import Flask, request, jsonify
# 直接导入对应币赢的大脑，确保逻辑完全隔离
from position_supervisor_coinw import SignalProcessor as CoinWProcessor

app = Flask(__name__)

# 初始化币赢的大脑实例
coinw_bot = CoinWProcessor()

# TV 警报的统一安全密钥
SECRET_KEY = "528586"

@app.route('/webhook', methods=['POST'])
def webhook():
    # 1. 安全校验
    data = request.json
    if not data or data.get("secret") != SECRET_KEY:
        return "Unauthorized", 401

    # 2. 信号处理
    # 因为这个 app.py 专门部署在 5002 端口，处理币赢流量
    # 所以不需要额外的 platform 判断，进来的一律交给 coinw_bot
    try:
        coinw_bot.process_signal(data)
        return jsonify({"status": "success", "msg": "CoinW Order Processed"}), 200
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    # 给 deploy_check.sh 用的健康检测接口
    return "healthy", 200

if __name__ == '__main__':
    # 注意：生产环境使用 Gunicorn 启动
    app.run(host='127.0.0.1', port=5002)
