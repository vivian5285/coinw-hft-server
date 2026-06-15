from flask import Flask, request, jsonify
# 导入我们两个独立的大脑
from position_supervisor_coinw import SignalProcessor as CoinWProcessor
from position_supervisor_binance import SignalProcessor as BinanceProcessor

app = Flask(__name__)

# 初始化大脑实例 (保持它们在内存中常驻，实现高频响应)
coinw_bot = CoinWProcessor()
binance_bot = BinanceProcessor()

# ⚠️ 务必在这里配置你的统一密钥，用于验证 TV 的合法性
SECRET_KEY = "528586" 

@app.route('/webhook', methods=['POST'])
def webhook():
    # 1. 解析 JSON 数据
    data = request.json
    if not data:
        return "Empty Payload", 400

    # 2. 身份校验 (安全第一)
    if data.get("secret") != SECRET_KEY:
        return "Unauthorized: Wrong Secret", 401

    # 3. 路由分发 (分流逻辑)
    platform = data.get("platform", "").upper() # TV 警报里需包含 "platform":"COINW"
    
    try:
        if platform == "COINW":
            coinw_bot.process_signal(data)
            return jsonify({"status": "success", "platform": "CoinW"}), 200
        
        elif platform == "BINANCE":
            binance_bot.process_signal(data)
            return jsonify({"status": "success", "platform": "Binance"}), 200
        
        else:
            return f"Unknown Platform: {platform}", 400
            
    except Exception as e:
        return f"Internal Server Error: {str(e)}", 500

if __name__ == '__main__':
    # 生产环境我们用 Gunicorn，这里仅用于本地调试
    app.run(host='0.0.0.0', port=5002)
