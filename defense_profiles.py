#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
防御参数配置 - CoinW单系统 v16.22.1

三层防线参数：
1. 硬止损：|TV价 - stop_loss| × 1.15
2. TP1/TP2：10%/20%
3. 雷达：TP2成交后激活，呼吸跟随
"""

from __future__ import annotations

import os
from typing import Dict, Tuple


class DefenseProfile:
    """防御参数配置"""

    def __init__(self, symbol: str):
        self.symbol = str(symbol or "ETH").upper()

        # 硬止损呼吸垫
        self.hard_stop_buffer: float = 1.15

        # TP分批比例
        self.tp1_ratio: float = 0.10  # 10%
        self.tp2_ratio: float = 0.20  # 20%
        self.tp3_ratio: float = 0.70  # 70%

        # TP档位限制
        self.place_tp_levels: int = 2  # 只挂TP1+TP2

        # 仓位公式
        self.risk_pct: float = 0.20       # 本金20%
        self.leverage_multiplier: float = 5.0  # 5倍

        # 雷达激活参数
        self.radar_breath_min: float = 1.0   # 最小呼吸
        self.radar_breath_max: float = 3.0   # 最大呼吸

        # 再入参数
        self.reentry_enabled: bool = True
        self.max_reentry: int = 1

        # 防叠单
        self.max_open_orders: int = 5

    def calc_position_size(self, balance: float, entry_price: float) -> float:
        """计算仓位"""
        risk_capital = balance * self.risk_pct
        notional_cap = risk_capital * self.leverage_multiplier
        qty = notional_cap / entry_price
        return qty

    def calc_hard_stop(self, entry_price: float, stop_loss: float) -> float:
        """计算硬止损价格"""
        if stop_loss <= 0:
            return 0.0
        dist = abs(entry_price - stop_loss) * self.hard_stop_buffer
        # 多头：止损在下方；空头：止损在上方
        if entry_price > stop_loss:  # LONG
            return entry_price - dist
        else:  # SHORT
            return entry_price + dist

    def calc_tp_prices(self, entry_price: float, direction: str) -> Tuple[float, float, float]:
        """计算TP价格（从signal获取，这里只是边界检查）"""
        return 0.0, 0.0, 0.0  # TP由TV webhook提供


# 品种配置表
_SYMBOL_PROFILES: Dict[str, DefenseProfile] = {}


def get_defense_profile(symbol: str = "ETH") -> DefenseProfile:
    """获取防御配置"""
    sym = str(symbol or "ETH").upper()

    if sym not in _SYMBOL_PROFILES:
        _SYMBOL_PROFILES[sym] = DefenseProfile(sym)

    return _SYMBOL_PROFILES[sym]


def get_all_profiles() -> Dict[str, DefenseProfile]:
    """获取全部配置"""
    return dict(_SYMBOL_PROFILES)


# 默认配置
DEFAULT_PROFILE = DefenseProfile("ETH")
