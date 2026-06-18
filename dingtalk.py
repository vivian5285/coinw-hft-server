#!/usr/bin/env python3
# dingtalk.py（CoinW V8.0 7U/15U限价单专属战报版）
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

DINGTALK_WEBHOOK = os.getenv("DINGTALK_WEBHOOK", "")
DINGTALK_SECRET = os.getenv("DINGTALK_SECRET", "")

def _generate_sign(secret: str) -> tuple:
    timestamp = str(round(time.time() * 1000))
    secret_enc = secret.encode('utf-8')
    string_to_sign = f'{timestamp}\n{secret}'
    string_to_sign_enc = string_to_sign.encode('utf-8')
    hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    return timestamp, sign

def _get_signed_url() -> str:
    if not DINGTALK_WEBHOOK: return ""
    if DINGTALK_SECRET:
        timestamp, sign = _generate_sign(DINGTALK_SECRET)
        return f"{DINGTALK_WEBHOOK}&timestamp={timestamp}&sign={sign}"
    return DINGTALK_WEBHOOK

def send_markdown_message(title: str, text: str):
    if not DINGTALK_WEBHOOK: return False
    try:
        url = _get_signed_url()
        full_text = f"### {title}\n> **⏱ 战报生成**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n---\n{text}\n---\n*🤖 币赢 (CoinW) V8.0 · 极限防对冲哨兵*"
        data = {
            "msgtype": "markdown",
            "markdown": {"title": title, "text": full_text}
        }
        requests.post(url, json=data, timeout=8)
    except Exception as e:
        logger.error(f"[DingTalk] 发送异常: {e}")

# ==================== 场景化战报模板 ====================

def report_coinw_open(side: str, entry_price: float, qty: float, tp_dict: dict, margin: float):
    emoji = "🟩" if side == "LONG" else "🟥"
    text = f"""### 🚀 币赢实盘建仓报告
> **单向纯净模式，限价止盈网已撒下！**

📍 **实盘核心数据**
- **交易方向**: {emoji} {side}
- **投入本金**: `{margin:.2f}` USDT (本金50% / 20x)
- **实盘均价**: `{entry_price}`
- **成功建仓**: `{qty}` 筹码总量

🎯 **交易所极速限价单 (7/15 目标)**
- **TP1 (7U - 平50%)**: `{tp_dict.get('tp1')}`
- **TP2 (15U - 全平)**: `{tp_dict.get('tp2')}`

*(注: 防悬空哨兵已启动，绝不允许幽灵挂单出现！)*
"""
    send_markdown_message("币赢新开仓实盘核实", text)

def report_coinw_tp(event_type: str, remaining_qty: float):
    status_emoji = "💰" if "落袋" in event_type else "🛡️"
    text = f"""### {status_emoji} 哨兵对账报告
- **触发事件**: **{event_type}**
- **当前余量**: 剩余 `{remaining_qty}` 筹码
- **系统状态**: 
"""
    if remaining_qty == 0:
        text += "仓位已彻底归零，系统已强制 **切除盘口一切残余挂单**，防止对冲爆雷，阵地重置完毕！"
    else:
        text += "已确认利润落袋或发现外部干预，哨兵继续紧盯剩余筹码。"
        
    send_markdown_message(f"哨兵事件: {event_type}", text)

def report_coinw_clear(reason: str):
    text = f"""### 🧹 阵地焦土清算报告
- **触发原因**: {reason}
- **执行动作**: 盘口挂单、幽灵残余与实盘旧仓已被彻底清剿。
- **当前状态**: **绝对纯净空仓**
"""
    send_markdown_message("币赢焦土清场", text)
