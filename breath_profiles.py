#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
呼吸参数表 - CoinW单系统 v16.22.1

ADX三档雷达步进/呼吸参数
"""

from __future__ import annotations

import os
from typing import Dict, Optional


class BreathProfile:
    """呼吸参数"""

    def __init__(self, symbol: str):
        self.symbol = str(symbol).upper()

        # ADX档位参数
        self.tiers: Dict[str, dict] = {
            "0": {  # 弱趋势
                "step_trigger": 0.40,    # 步进触发（ATR倍数）
                "step_advance": 0.25,    # 步进幅度
                "breath_12": 0.8,       # TP1-TP2呼吸
                "breath_23": 1.0,       # TP2-TP3呼吸
                "trail_min": 1.2,       # 追踪止损最小
                "trail_max": 1.5,       # 追踪止损最大
            },
            "1": {  # 中趋势
                "step_trigger": 0.50,
                "step_advance": 0.35,
                "breath_12": 1.2,
                "breath_23": 1.6,
                "trail_min": 1.8,
                "trail_max": 2.5,
            },
            "2": {  # 强趋势
                "step_trigger": 0.60,
                "step_advance": 0.40,
                "breath_12": 1.5,
                "breath_23": 2.0,
                "trail_min": 2.5,
                "trail_max": 3.5,
            },
        }

    def get_tier_params(self, tier: str) -> dict:
        """获取档位参数"""
        tier = str(tier or "1")
        return self.tiers.get(tier, self.tiers["1"])

    def calc_step_trigger(self, atr: float, tier: str = "1") -> float:
        """计算步进触发价"""
        params = self.get_tier_params(tier)
        return atr * params["step_trigger"]

    def calc_step_advance(self, atr: float, tier: str = "1") -> float:
        """计算步进幅度"""
        params = self.get_tier_params(tier)
        return atr * params["step_advance"]


# 品种配置
_SYMBOL_BREATH_PROFILES: Dict[str, BreathProfile] = {
    "ETH": BreathProfile("ETH"),
    "BTC": BreathProfile("BTC"),
    "XAU": BreathProfile("XAU"),
    "BNB": BreathProfile("BNB"),
}


def get_breath_profile(symbol: str = "ETH") -> BreathProfile:
    """获取呼吸参数"""
    sym = str(symbol or "ETH").upper()
    if sym not in _SYMBOL_BREATH_PROFILES:
        _SYMBOL_BREATH_PROFILES[sym] = BreathProfile(sym)
    return _SYMBOL_BREATH_PROFILES[sym]


def get_all_breath_profiles() -> Dict[str, BreathProfile]:
    return dict(_SYMBOL_BREATH_PROFILES)
