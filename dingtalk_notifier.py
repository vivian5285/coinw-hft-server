#!/usr/bin/env python3
# dingtalk_notifier.py (适配短线美学版)
import json
import requests
import os
from dotenv import load_dotenv

load_dotenv()

class DingTalkNotifier:
    def __init__(self):
        self.webhook = os.getenv("DINGTALK_WEBHOOK")

    def send_markdown(self, title, text):
        """发送美化后的 Markdown 战报"""
        if not self.webhook:
            return

        # 封装 Markdown 格式，添加一些色彩标签以适配手机阅读
        data = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": f"{text}\n\n> --- \n> ⏱️ *系统更新: {time.strftime('%H:%M:%S')}* | 🚀 *短线刺客模式*"
            },
            "at": {
                "isAtAll": False
            }
        }
        
        try:
            requests.post(self.webhook, json=data, timeout=5)
        except Exception as e:
            print(f"钉钉发送失败: {e}")
