#!/usr/bin/env python3
# dingtalk.py（CoinW 专属通用推送模块）
import os
import time
import hmac
import hashlib
import base64
import urllib.parse
import logging
import requests
from datetime import datetime

logger = logging.getLogger(__name__)

# 会自动从你的 .env 文件或环境变量里读取这两个密钥
DINGTALK_WEBHOOK = os.getenv("DINGTALK_WEBHOOK", "")
DINGTALK_SECRET = os.getenv("DINGTALK_SECRET", "")

def _generate_sign(secret: str) -> tuple:
    """生成加签 timestamp + sign"""
    timestamp = str(round(time.time() * 1000))
    secret_enc = secret.encode('utf-8')
    string_to_sign = f'{timestamp}\n{secret}'
    string_to_sign_enc = string_to_sign.encode('utf-8')
    hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    return timestamp, sign

def _get_signed_url() -> str:
    """获取带签名的最终 URL"""
    if not DINGTALK_WEBHOOK: return ""
    if DINGTALK_SECRET:
        timestamp, sign = _generate_sign(DINGTALK_SECRET)
        return f"{DINGTALK_WEBHOOK}&timestamp={timestamp}&sign={sign}"
    return DINGTALK_WEBHOOK

def send_markdown_message(title: str, text: str, is_at_all: bool = False):
    """发送极度美观的 Markdown 富文本消息"""
    if not DINGTALK_WEBHOOK:
        logger.warning("[DingTalk] 未配置 Webhook，跳过发送")
        return False

    try:
        url = _get_signed_url()
        if not url: return False

        # 币赢专属底部水印
        full_text = f"### {title}\n> **⏱ 汇报时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n---\n{text}\n---\n*🤖 币赢(CoinW)高频刺客引擎 · 极速雷达监控中*"

        data = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": full_text
            },
            "at": {"isAtAll": is_at_all}
        }

        resp = requests.post(url, json=data, timeout=8)
        if resp.status_code == 200 and resp.json().get("errcode") == 0:
            logger.info(f"[DingTalk] Markdown 报告发送成功: {title}")
            return True
        else:
            logger.error(f"[DingTalk] 发送失败: {resp.text}")
            return False
    except Exception as e:
        logger.error(f"[DingTalk] 发送异常: {e}", exc_info=True)
        return False
