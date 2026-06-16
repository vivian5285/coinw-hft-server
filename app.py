#!/usr/bin/env python3
# app.py（最终版）
from flask import Flask, request, jsonify
from position_supervisor_coinw import coinw_processor
import os

app = Flask(__name__)

SECRET_KEY = os.getenv("WEBHOOK_SECRET", "528586")

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    if not data or data.get("secret") != SECRET_KEY:
        return "Unauthorized", 401

    try:
        coinw_processor.process_signal(data)
        return jsonify({"status": "success"}), 200
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    return "healthy", 200


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5002)
