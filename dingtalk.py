#!/usr/bin/env python3
# dingtalk.py（CoinW V5.0 专属通用推送模块 - 狂暴美学版）
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

# 自动从 .env 文件或环境变量读取密钥
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
    if not DINGTALK_WEBHOOK: 
        return ""
    if DINGTALK_SECRET:
        timestamp, sign = _generate_sign(DINGTALK_SECRET)
        return f"{DINGTALK_WEBHOOK}&timestamp={timestamp}&sign={sign}"
    return DINGTALK_WEBHOOK

def send_markdown_message(title: str, text: str, is_at_all: bool = False):
    """
    发送极度美观的 Markdown 富文本战报
    带有异常重试机制，绝不丢失任何一封战报！
    """
    if not DINGTALK_WEBHOOK:
        logger.warning("[DingTalk] 未配置 Webhook，跳过发送")
        return False

    url = _get_signed_url()
    if not url: 
        return False

    # V5.0 专属底部狂暴水印
    full_text = f"### {title}\n> **⏱ 战报生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n---\n{text}\n---\n*🤖 币赢(CoinW) 双向狂暴死咬引擎 · 极速雷达监控中*"

    data = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": full_text
        },
        "at": {"isAtAll": is_at_all}
    }

    # 加入战报发送防丢机制（最多重试 3 次）
    for attempt in range(3):
        try:
            resp = requests.post(url, json=data, timeout=5)
            if resp.status_code == 200 and resp.json().get("errcode") == 0:
                logger.info(f"[DingTalk] Markdown 战报分发成功: {title}")
                return True
            else:
                logger.warning(f"[DingTalk] 战报分发受阻 (尝试 {attempt+1}/3): {resp.text}")
        except Exception as e:
            logger.warning(f"[DingTalk] 网络波动，战报延误 (尝试 {attempt+1}/3): {e}")
        
        time.sleep(1) # 重试缓冲

    logger.error(f"[DingTalk] 致命错误：战报发送彻底失败: {title}")
    return False
