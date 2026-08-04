#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Console API - CoinW单系统 v16.22.1

Web管理界面API：
- 多API档案热切换
- 风险参数调整
- Webhook密钥管理
- 状态查询
"""

import os
import json
import logging
from flask import Blueprint, request, jsonify

logger = logging.getLogger(__name__)

console_bp = Blueprint('console', __name__, url_prefix='/console')

# 档案存储路径
PROFILES_FILE = os.path.join(os.path.dirname(__file__), 'data', 'account_profiles.json')


def load_profiles():
    """加载档案"""
    if os.path.exists(PROFILES_FILE):
        try:
            with open(PROFILES_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {"current": "default", "profiles": {}}


def save_profiles(data):
    """保存档案"""
    os.makedirs(os.path.dirname(PROFILES_FILE), exist_ok=True)
    with open(PROFILES_FILE, 'w') as f:
        json.dump(data, f, indent=2)


@console_bp.route('/profiles', methods=['GET'])
def get_profiles():
    """获取档案列表"""
    data = load_profiles()
    return jsonify({
        "current": data.get("current", "default"),
        "profiles": data.get("profiles", {}),
    })


@console_bp.route('/profiles', methods=['POST'])
def save_profile():
    """保存档案"""
    payload = request.get_json()
    if not payload:
        return jsonify({"error": "invalid payload"}), 400

    data = load_profiles()
    name = payload.get("name", "default")
    profile = payload.get("profile", {})

    data["profiles"][name] = profile

    if payload.get("activate"):
        data["current"] = name

    save_profiles(data)

    # 如果激活，应用配置
    if payload.get("activate"):
        _apply_profile(name, profile)

    return jsonify({"ok": True, "current": data["current"]})


@console_bp.route('/switch', methods=['POST'])
def switch_profile():
    """切换档案"""
    payload = request.get_json()
    name = payload.get("name")

    data = load_profiles()
    if name not in data.get("profiles", {}):
        return jsonify({"error": "profile not found"}), 404

    data["current"] = name
    save_profiles(data)

    _apply_profile(name, data["profiles"][name])

    return jsonify({"ok": True, "current": name})


def _apply_profile(name: str, profile: dict):
    """应用档案配置"""
    from position_supervisor_coinw import PositionSupervisorCoinW
    from coinw_client import coinw_client

    # 切换API密钥
    api_key = profile.get("api_key")
    api_secret = profile.get("api_secret")

    if api_key and api_secret:
        coinw_client.rebind_credentials(api_key, api_secret)
        logger.info(f"API已切换: {name}")

    # 应用风险参数
    risk_pct = profile.get("risk_pct")
    if risk_pct:
        from defense_profiles import get_defense_profile
        prof = get_defense_profile()
        prof.risk_pct = float(risk_pct)
        logger.info(f"风险比例已更新: {risk_pct}")


@console_bp.route('/status', methods=['GET'])
def get_status():
    """获取系统状态"""
    from position_supervisor_coinw import COINW_SUPERVISOR_VERSION, trading_paused
    from pipeline_ledger import get_pipeline
    from api_throttle import get_throttle_status
    from risk_manager import get_risk_manager

    # 获取所有品种状态
    symbols = ["ETH", "BTC", "XAU", "BNB"]
    pipelines = {}

    for sym in symbols:
        p = get_pipeline(sym, "coinw")
        pipelines[sym] = {
            "phase": p.phase.value,
            "side": p.data.get("side", ""),
            "qty": p.data.get("qty", 0),
            "entry": p.data.get("entry", 0),
        }

    # 限流状态
    throttle = get_throttle("coinw")
    throttle_status = throttle.get_status() if throttle else {}

    # 风险状态
    risk = get_risk_manager()
    risk_status = risk.get_status() if risk else {}

    return jsonify({
        "version": COINW_SUPERVISOR_VERSION,
        "trading_paused": trading_paused,
        "pipelines": pipelines,
        "throttle": throttle_status,
        "risk": risk_status,
    })


@console_bp.route('/pause', methods=['POST'])
def pause_trading():
    """暂停交易"""
    from position_supervisor_coinw import pause_all_trading

    payload = request.get_json() or {}
    reason = payload.get("reason", "手动暂停")

    pause_all_trading(reason)
    return jsonify({"ok": True})


@console_bp.route('/resume', methods=['POST'])
def resume_trading():
    """恢复交易"""
    from position_supervisor_coinw import resume_all_trading

    resume_all_trading()
    return jsonify({"ok": True})


@console_bp.route('/webhook-secret', methods=['GET', 'POST'])
def webhook_secret():
    """获取/设置Webhook密钥"""
    if request.method == 'GET':
        return jsonify({
            "secret": os.getenv("WEBHOOK_SECRET", ""),
        })

    payload = request.get_json()
    secret = payload.get("secret")

    if not secret:
        return jsonify({"error": "missing secret"}), 400

    # 更新环境变量（仅当前进程）
    os.environ["WEBHOOK_SECRET"] = secret
    os.environ["TV_WEBHOOK_SECRET"] = secret

    # 保存到.env
    env_file = os.path.join(os.path.dirname(__file__), '.env')
    try:
        with open(env_file, 'a') as f:
            f.write(f"\nWEBHOOK_SECRET={secret}\n")
    except Exception:
        pass

    return jsonify({"ok": True})
