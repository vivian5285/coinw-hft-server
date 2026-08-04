#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通知模块 - CoinW单系统 v16.22.1

支持Telegram和钉钉通知
"""

import os
import time
import logging
import requests
from datetime import datetime

logger = logging.getLogger(__name__)

# ==================== 配置 ====================
DINGTALK_WEBHOOK = os.getenv("DINGTALK_WEBHOOK", "")
DINGTALK_SECRET = os.getenv("DINGTALK_SECRET", "")
DINGTALK_DISABLE = os.getenv("DINGTALK_DISABLE", "True").lower() == "true"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_DISABLE = os.getenv("TELEGRAM_DISABLE", "False").lower() == "true"

BRAND_PREFIX = "【CoinW单系统】"


# ==================== Telegram ====================

def _telegram_send(text: str):
    """发送Telegram消息"""
    if TELEGRAM_DISABLE or not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "Markdown",
        }
        resp = requests.post(url, json=data, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        logger.error(f"[Telegram] 发送失败: {e}")
        return False


# ==================== 钉钉 ====================

def _dingtalk_sign(secret: str) -> tuple:
    """钉钉签名"""
    import hmac, hashlib, base64, urllib.parse
    timestamp = str(round(time.time() * 1000))
    string_to_sign = f'{timestamp}\n{secret}'
    sign = base64.b64encode(
        hmac.new(secret.encode(), string_to_sign.encode(), digestmod=hashlib.sha256).digest()
    ).decode()
    return timestamp, urllib.parse.quote_plus(sign)


def _dingtalk_send(title: str, text: str):
    """发送钉钉消息"""
    if DINGTALK_DISABLE or not DINGTALK_WEBHOOK:
        return False

    try:
        url = DINGTALK_WEBHOOK
        if DINGTALK_SECRET:
            ts, sign = _dingtalk_sign(DINGTALK_SECRET)
            url = f"{url}&timestamp={ts}&sign={sign}"

        full_text = f"### {title}\n> **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n---\n{text}\n---\n{BRAND_PREFIX}"
        data = {
            "msgtype": "markdown",
            "markdown": {"title": title, "text": full_text}
        }
        resp = requests.post(url, json=data, timeout=8)
        return resp.status_code == 200
    except Exception as e:
        logger.error(f"[DingTalk] 发送失败: {e}")
        return False


# ==================== 统一发送 ====================

def _send(title: str, text: str):
    """发送通知"""
    # Telegram优先
    if not TELEGRAM_DISABLE and TELEGRAM_BOT_TOKEN:
        _telegram_send(f"{BRAND_PREFIX}\n{text}")

    # 钉钉备选
    if not DINGTALK_DISABLE and DINGTALK_WEBHOOK:
        _dingtalk_send(title, text)


# ==================== 通知函数 ====================

def report_coinw_open(action: str, entry_price: float, qty: float,
                     tp_dict: dict, margin: float = 0,
                     tier: str = "", tier_label: str = ""):
    """开仓通知"""
    emoji = "🟢" if action == "LONG" else "🔴"
    tier_info = f"\n📊 趋势档位: **{tier_label}**" if tier_label else ""

    text = f"""{emoji} **{action} 开仓**
━━━━━━━━━━━━━━━━━━
📍 品种: ETHUSDT
📈 方向: {action}
💰 开仓价: `{entry_price}`
📦 数量: `{qty}`
🎯 TP1: `{tp_dict.get('tp1', 0)}`
🎯 TP2: `{tp_dict.get('tp2', 0)}`
🛡️ 硬止损: `{tp_dict.get('hard_sl', 'N/A')}`{tier_info}
━━━━━━━━━━━━━━━━━━"""

    _send("CoinW开仓", text)


def report_coinw_tp(event: str, remaining: float = 0, price: float = 0):
    """TP成交/仓位变更通知"""
    emoji = "💰" if remaining == 0 else "✨"

    text = f"""{emoji} **{event}**
━━━━━━━━━━━━━━━━━━
📍 当前剩余: `{remaining}`
"""

    if price > 0:
        text += f"💵 参考价: `{price}`\n"

    text += "━━━━━━━━━━━━━━━━━━"

    _send(f"CoinW: {event}", text)


def report_coinw_clear(reason: str):
    """清仓通知"""
    text = f"""🧹 **清仓完成**
━━━━━━━━━━━━━━━━━━
📍 原因: {reason}
📊 状态: 空仓待命
━━━━━━━━━━━━━━━━━━"""

    _send("CoinW清仓", text)


def report_coinw_radar_activated(entry_price: float, tp2_price: float,
                                activation_price: float, initial_sl: float,
                                tier_label: str = ""):
    """雷达激活通知"""
    tier_info = f"\n📊 趋势档位: **{tier_label}**" if tier_label else ""

    text = f"""📡 **雷达激活**
━━━━━━━━━━━━━━━━━━
🎯 激活价锚定: `(TP1+TP2)/2`
💰 激活价格: `{activation_price}`
🛡️ 初始止损: `{initial_sl}`
📈 开仓价: `{entry_price}`
🎯 TP2目标: `{tp2_price}`{tier_info}
━━━━━━━━━━━━━━━━━━
*雷达启动被动追踪模式*"""

    _send("CoinW雷达激活", text)


def send_alert(message: str):
    """发送告警"""
    text = f"""🚨 **系统告警**
━━━━━━━━━━━━━━━━━━
📍 告警内容: {message}
⏰ 时间: {datetime.now().strftime('%H:%M:%S')}
━━━━━━━━━━━━━━━━━━"""

    _send("CoinW告警", text)


def send_error(message: str):
    """发送错误"""
    text = f"""❌ **错误**
━━━━━━━━━━━━━━━━━━
📍 错误: {message}
⏰ 时间: {datetime.now().strftime('%H:%M:%S')}
━━━━━━━━━━━━━━━━━━"""

    _send("CoinW错误", text)
