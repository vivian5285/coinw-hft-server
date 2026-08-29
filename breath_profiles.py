#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
呼吸参数表 - CoinW单系统

2026-08-29 换代：从"ADX 三档 + BreathProfile 类"整体切到币安单系统 v2.1 的
"每品种校准 + 价格分区呼吸"模型。当前仅 ETH 接入。结构对齐币安，系数按
CoinW 自己的 150 分钟周期独立校准（币安 ETH 走 90 分钟，CoinW ETH 走
150 分钟——见 BREATH_ETH 上方校准注释）。

雷达推进逻辑见 breath_stop.py（已同步换成币安的 calculate_breath_stop：
价格分区 pre_tp1 / tp1_tp2 / tp2_tp3 / tp3_confirm / tp3_plus）。

旧的 BreathProfile / 三档 tiers / get_tier_params 已废除。get_breath_profile
现在返回一份扁平参数 dict（_BreathDict，带 get_tier_params 兼容垫片，tier
参数被忽略），签名与币安 eth-webhook-server 的 get_breath_profile 对齐。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# 共用边界（ATR 比插值；TP3+ 实际 min/max 由品种档覆盖）
RATIO_FLOOR = 0.6
RATIO_CEILING = 2.2

# ETH 基线 —— 结构对齐币安 v2.1，但系数按 CoinW 自己的 150 分钟周期校准
# （币安 ETH 是 90 分钟；CoinW 用户确认 CoinW ETH 走 150 分钟）。
# 2026-08-29 校准：方法同币安 scratch_calibrate（30m×5 合成 150m，ATR(14)，
# fractal pivot ±3 确认，回调距离/本地ATR 分位）。1020 根合成 150m K线
# （~106 天）、148 个回调样本，ATR%=1.12%，回调/ATR：P50=2.56 / P75=3.45 /
# P90=5.16。step_trigger≈0.375×breath_tp12（沿用币安 ETH/BNB/ZEC/XPD 家族
# 惯例，与同为 150m 的 BNB/ZEC/XPD 对齐），step_advance≈0.65×step_trigger。
BREATH_ETH: Dict[str, Any] = {
    "name": "ETH",
    "initial_sl_atr": 0.0,        # 规格 v2.1：激活用保本位，不用 ATR 臂
    "fee_cover_pct": 0.0008,
    "stop_exec_buffer": 0.3,
    "early_be_atr": 0.0,
    "step_trigger_atr": 0.96,    # 150m 校准：0.375×breath_tp12
    "step_advance_atr": 0.62,    # 150m 校准：0.65×step_trigger
    "phase_switch_atr": 3.0,
    "tp1_atr": 1.35,
    "tp1_floor_atr": 0.0,
    "tp2_atr": 2.5,
    "tp2_floor_atr": 0.0,
    "breath_tp12": 2.56,        # 150m 校准：覆盖实测中位数回调 (P50=2.56)
    "breath_tp23": 3.45,        # 150m 校准：覆盖实测 75 分位回调 (P75=3.45)
    "phase2_trail_mult": 1.0,
    "min_mult": 4.0,           # 150m 校准：0.72×max_mult
    "max_mult": 5.5,           # 150m 校准：覆盖实测 90 分位回调 (P90=5.16) + 0.3
    "ratio_floor": RATIO_FLOOR,
    "ratio_ceiling": RATIO_CEILING,
    "tick_size": 0.01,
    "entry_score": 3,
    "exit_score": 2,
}


class _BreathDict(dict):
    """扁平参数 dict + 兼容垫片：旧代码 `.get_tier_params(tier)` 仍可调，tier 被忽略。"""

    __slots__ = ()

    def get_tier_params(self, tier: Optional[str] = None) -> "dict":
        return self


_BY_SYMBOL: Dict[str, Dict[str, Any]] = {
    "ETH": BREATH_ETH,
}


def get_breath_profile(symbol: str = "ETH", exchange: str = "coinw") -> Dict[str, Any]:
    """按品种返回一份扁平呼吸参数（dict 拷贝，调用方可安全改写）。未知品种回退 ETH。"""
    sym = str(symbol or "ETH").strip().upper()
    base = _BY_SYMBOL.get(sym) or BREATH_ETH
    return _BreathDict(base)


def default_breath_profile() -> Dict[str, Any]:
    return _BreathDict(BREATH_ETH)


def trail_distance_multiplier(ratio: float, profile: Optional[Dict[str, Any]] = None) -> float:
    """
    连续线性插值（TP3+ 动态追踪带宽）：
      ratio<=ratio_floor  → min_mult
      ratio>=ratio_ceiling → max_mult
      否则线性。
    从币安 breath_profiles.py 原样移植。
    """
    p = profile if isinstance(profile, dict) and profile else BREATH_ETH
    lo = float(p.get("ratio_floor") if p.get("ratio_floor") is not None else RATIO_FLOOR)
    hi = float(p.get("ratio_ceiling") if p.get("ratio_ceiling") is not None else RATIO_CEILING)
    mn = float(p.get("min_mult") if p.get("min_mult") is not None else 2.0)
    mx = float(p.get("max_mult") if p.get("max_mult") is not None else 2.5)
    r = float(ratio or 0.0)
    if r <= lo:
        return mn
    if r >= hi:
        return mx
    if hi <= lo:
        return mx
    t = (r - lo) / (hi - lo)
    return mn + (mx - mn) * t


def cold_start_multiplier(profile: Optional[Dict[str, Any]] = None) -> float:
    """0 次采样：ratio=1.0 代入公式。"""
    return trail_distance_multiplier(1.0, profile)


def map_coeff_from_tiers(smooth_ratio: float, tiers: Optional[List] = None) -> float:
    """兼容旧名：现改为连续插值。"""
    profile = tiers if isinstance(tiers, dict) else None
    return trail_distance_multiplier(float(smooth_ratio or 0), profile)


def get_all_breath_profiles() -> Dict[str, Dict[str, Any]]:
    return {k: _BreathDict(v) for k, v in _BY_SYMBOL.items()}
