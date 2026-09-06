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

import logging
import os
from typing import Dict, Tuple

logger = logging.getLogger(__name__)

# 趋势强弱仓位倾斜（2026-09-06 用户重定）。
# 本金余额 × 趋势强度百分比 × 5倍杠杆 = 下单名义。
#   弱 tier0 : 本金×10%×5 = 本金×0.50 名义
#   中 tier1 : 本金×15%×5 = 本金×0.75 名义
#   强 tier2 : 本金×20%×5 = 本金×1.00 名义（满仓一倍 = 现货一倍，上限）
# 未知/缺失 tier → 按最强档（0.20），与既有默认行为一致。
TIER_RISK_PCT = {0: 0.10, 1: 0.15, 2: 0.20}
DEFAULT_RISK_PCT = 0.20


def get_tier_risk_pct(tier) -> float:
    """tier ∈ {0,1,2} / "0"/"1"/"2" → 对应本金百分比；其余 → DEFAULT_RISK_PCT。"""
    try:
        t = int(str(tier).strip())
    except (TypeError, ValueError):
        return DEFAULT_RISK_PCT
    return float(TIER_RISK_PCT.get(t, DEFAULT_RISK_PCT))


# 兼容旧引用：换算成"相对强档(本金×1.0名义)的系数"
TIER_NOTIONAL_MULT = {t: (p * 5.0) for t, p in TIER_RISK_PCT.items()}  # {0:0.50,1:0.75,2:1.00}


def get_tier_notional_mult(tier) -> float:
    return get_tier_risk_pct(tier) * 5.0


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

        # 仓位公式：本金 × 趋势百分比(见 TIER_RISK_PCT) × 5倍杠杆
        self.risk_pct: float = 0.20       # 仅作 tier 缺失时的兜底
        self.leverage_multiplier: float = 5.0  # 5倍

        # 雷达激活参数
        self.radar_breath_min: float = 1.0   # 最小呼吸
        self.radar_breath_max: float = 3.0   # 最大呼吸

        # 再入参数
        self.reentry_enabled: bool = True
        self.max_reentry: int = 1

        # 防叠单
        self.max_open_orders: int = 5

    def calc_position_size(self, balance: float, entry_price: float, tier=None) -> float:
        """
        下单名义 = 本金余额 × 趋势强度百分比(tier) × 5倍杠杆。
          弱 tier0 10% / 中 tier1 15% / 强 tier2 20%（强档 = 本金×1.0 名义）。
          tier 缺省/非法 → DEFAULT_RISK_PCT(0.20，按强档兜底)。
        """
        if entry_price <= 0:
            return 0.0
        rp = get_tier_risk_pct(tier)
        notional = balance * rp * self.leverage_multiplier
        qty = notional / entry_price
        tier_s = str(tier).strip() if tier is not None else ""
        if tier_s in ("0", "1", "2"):
            logger.info(
                f"[{self.symbol}] 趋势档位仓位 tier={tier_s} 本金×{rp:.0%}×5 "
                f"名义 {notional:.1f}U (占本金 {rp*5:.2f}x)  qty={qty:.6f}"
            )
        elif tier_s:
            logger.warning(f"[{self.symbol}] tier={tier!r} 无法识别，按强档 20%×5")
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
