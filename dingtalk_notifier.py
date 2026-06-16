#!/usr/bin/env python3
import os
import time
import hmac
import hashlib
import base64
import urllib.parse
import requests
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

class DingTalkNotifier:
    def __init__(self):
        self.webhook = os.getenv("DINGTALK_WEBHOOK")
        self.secret = os.getenv("DINGTALK_SECRET")

    def send_markdown(self, title: str, text: str):
        """发送钉钉 Markdown 格式消息"""
        if not self.webhook:
            logger.warning("未配置 DINGTALK_WEBHOOK，跳过钉钉推送。")
            return

        url = self.webhook
        # 如果配置了加签密钥，则生成签名追加到 URL
        if self.secret:
            timestamp = str(round(time.time() * 1000))
            secret_enc = self.secret.encode('utf-8')
            string_to_sign = '{}\n{}'.format(timestamp, self.secret)
            string_to_sign_enc = string_to_sign.encode('utf-8')
            hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
            sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
            url = f"{self.webhook}&timestamp={timestamp}&sign={sign}"

        headers = {'Content-Type': 'application/json'}
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": text
            }
        }

        try:
            res = requests.post(url, json=payload, headers=headers, timeout=5)
            if res.status_code != 200 or res.json().get("errcode") != 0:
                logger.error(f"钉钉推送失败: {res.text}")
        except Exception as e:
            logger.error(f"钉钉请求异常: {e}")
