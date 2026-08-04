#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
雷达再入配置 - CoinW单系统 v16.22.1

ADX档位 / 再入窗口 / 双保险参数
"""

from __future__ import annotations

import os
import json
from typing import Dict, Optional


class ReentryProfile:
    """再入配置"""

    def __init__(self, symbol: str):
        self.symbol = str(symbol).upper()

        # 再入窗口（K线根数）
        self.reentry_windows: Dict[str, int] = {
            "ETH": 2,   # 2×90m = 3h
            "BTC": 2,
            "XAU": 3,   # 3×45m = 2.25h
            "BNB": 2,
        }

        # 最大重入次数
        self.max_reentry: int = 1

        # 再入微赚区间（ATR倍数）
        self.reentry_zone_pct: float = 0.5

        # 成功放宽一档
        self.loosen_after_success: bool = True

    def get_reentry_window(self, symbol: str = None) -> int:
        """获取再入窗口（K线根数）"""
        sym = str(symbol or self.symbol).upper()
        return self.reentry_windows.get(sym, 2)


def load_reentry_tiers_from_file() -> Dict:
    """从配置文件加载"""
    config_path = os.path.join(os.path.dirname(__file__), "config", "reentry_tiers.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


# 全局配置
_DEFAULT_REENTRY = ReentryProfile("ETH")
_SYMBOL_REENTRY: Dict[str, ReentryProfile] = {}


def get_reentry_profile(symbol: str = "ETH") -> ReentryProfile:
    """获取再入配置"""
    sym = str(symbol or "ETH").upper()
    if sym not in _SYMBOL_REENTRY:
        _SYMBOL_REENTRY[sym] = ReentryProfile(sym)
    return _SYMBOL_REENTRY[sym]


def get_all_reentry_profiles() -> Dict[str, ReentryProfile]:
    return dict(_SYMBOL_REENTRY)
