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

# 趋势强弱仓位倾斜——2026-09-06 曾第二次上调过，**2026-09-12 宝贝拍板改为
# 固定公式，不再按 tier 缩放仓位**："账户的权重设置为本金余额的20%然后
# 3倍杠杆下单"。TIER_RISK_PCT/get_tier_risk_pct 这套按档位缩放的旧公式
# 保留在这里（shadow_contest.py 等仍可能引用常量本身），但 calc_position_
# size() 已经不再调用它——见下方 FIXED_POSITION_PCT/FIXED_LEVERAGE_MULT。
#   弱 tier0 : 本金×20%×5 = 本金×1.0 名义（现货一倍）
#   中 tier1 : 本金×30%×5 = 本金×1.5 名义
#   强 tier2 : 本金×40%×5 = 本金×2.0 名义（全仓两倍，上限）
# 未知/缺失 tier → 按最强档（0.40）。
TIER_RISK_PCT = {0: 0.20, 1: 0.30, 2: 0.40}
DEFAULT_RISK_PCT = 0.40

# 2026-09-12 新公式（宝贝拍板，替代上面的tier缩放）：
#   下单名义 = 本金余额 × FIXED_POSITION_PCT × FIXED_LEVERAGE_MULT
#            = 本金余额 × 20% × 3 = 本金余额 × 0.6 名义（约0.6倍杠杆敞口）
# 不再按 signal.tier 缩放仓位——tier 只用于硬止损的 K_tier 保护带宽度
# （见 atr_scenario.py::calc_smart_hard_stop_price），职责拆开：
#   仓位大小 = 固定公式；止损远近 = 按tier智能判断。
FIXED_POSITION_PCT = 0.20
FIXED_LEVERAGE_MULT = 3.0


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
        2026-09-12起：下单名义 = 本金余额 × 20% × 3倍杠杆，不再按 tier 缩放
        （宝贝拍板固定公式）。tier 参数仍保留在签名里（调用方/shadow_contest
        等历史调用点不用改），只用于日志展示，不参与仓位计算——tier 的实际
        作用转移到硬止损的 K_tier 保护带宽度（见 atr_scenario.py）。
        """
        if entry_price <= 0:
            return 0.0
        notional = balance * FIXED_POSITION_PCT * FIXED_LEVERAGE_MULT
        qty = notional / entry_price
        tier_s = str(tier).strip() if tier is not None else ""
        logger.info(
            f"[{self.symbol}] 固定仓位公式 本金×{FIXED_POSITION_PCT:.0%}×"
            f"{FIXED_LEVERAGE_MULT:.0f} 名义 {notional:.1f}U "
            f"(tier={tier_s or '—'}，不影响仓位大小)  qty={qty:.6f}"
        )
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
