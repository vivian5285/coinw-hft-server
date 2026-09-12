#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
呼吸参数表 - CoinW单系统

2026-08-29 换代：从"ADX 三档 + BreathProfile 类"整体切到币安单系统 v2.1 的
"每品种校准 + 价格分区呼吸"模型。结构对齐币安，系数按 CoinW 自己的 TV 周期
独立校准（不能直接抄币安系数——CoinW ETH 就是活生生的反例：币安 ETH 走
90 分钟，CoinW ETH 实际是 150 分钟，2026-09-06 又重校准成 59 分钟）。

雷达推进逻辑见 breath_stop.py（已同步换成币安的 calculate_breath_stop：
价格分区 pre_tp1 / tp1_tp2 / tp2_tp3 / tp3_confirm / tp3_plus）。

旧的 BreathProfile / 三档 tiers / get_tier_params 已废除。get_breath_profile
现在返回一份扁平参数 dict（_BreathDict，带 get_tier_params 兼容垫片，tier
参数被忽略），签名与币安 eth-webhook-server 的 get_breath_profile 对齐。

2026-09-12 新增 BNB/OPENAI/SNDK/XPD（宝贝要求币赢对齐币安、这4个品种接入
交易）。方法同 ETH：真实摆动点识别（fractal pivot，±3根确认）+ ATR(14)，
回调距离/本地ATR 分位。**数据来源与已知局限**：CoinW 公开 klines 接口
(/v1/perpumPublic/klines) 单次最多回 1500 根、不支持分页翻更早历史（实测
endTime/before 参数均无效），30m 是能整除150分钟的最细粒度，1500根30m≈
31天，是目前能拿到的历史上限——比币安那边同品种校准用的60~83天样本明显
薄（37~50个回调样本 vs 币安的53~173个），统计显著性弱一些，等实盘跑出更长
历史后应该重新校准一遍加厚样本。**周期假设**：这4个品种在 CoinW 这边的
TV 报警周期沿用币安同品种的150分钟（BNB/OPENAI/SNDK/XPD 在币安都是150分
钟，OPENAI/XPD 这点有宝贝给的TV警报截图佐证），宝贝没有明确逐个确认过
CoinW 侧是否也是150分钟——如果实际不是，需要按正确周期重新拉数重新校准
（ETH 就因为周期搞错重新校准过，不是不可能发生）。
tp1_atr/tp2_atr/phase_switch_atr/fee_cover_pct/stop_exec_buffer/
tick_size/entry_score/exit_score 沿用全系统统一默认值（这几项从来都不是
按品种校准的，币安那边所有品种也是同一套值）。step_trigger_atr≈0.375×
breath_tp12、step_advance_atr≈0.65×step_trigger_atr 是币安那边SNDK等
品种验证过的跨品种经验比例；min_mult/max_mult 比例沿用币安同品种自己的
既有比例（BNB0.72／OPENAI0.8／SNDK0.72／XPD0.79——这是币安该品种自己的
尾部特征，比统一比例更贴合）。未接 has_staged_exit_gate：不确认CoinW这边
TV pine脚本是否也有这个机制，跟CoinW-ETH现有档案一样先不设。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# 共用边界（ATR 比插值；TP3+ 实际 min/max 由品种档覆盖）
RATIO_FLOOR = 0.6
RATIO_CEILING = 2.2

# ETH 基线 —— 结构对齐币安 v2.1，系数按 CoinW ETH 的 TV 周期校准。
# 2026-09-06 重校准：用户确认 CoinW ETH 的 TV 周期改为 59 分钟（此前 150 分钟）。
# 59 是质数，用 Binance 1m ×59 合成（同价），方法同币安 scratch_calibrate
# （ATR(14)，fractal pivot ±3 确认，回调距离/本地ATR 分位）。1003 根合成
# 59m K线（~41 天）、171 个回调样本，ATR%=0.39%，回调/ATR：P50=2.31 /
# P75=3.36 / P90=5.32。step_trigger≈0.375×breath_tp12，step_advance≈0.65×。
# 运行时 CoinW 侧重算（恢复/再入/climax/3TF/影子）用 60m 原生 K 线作 59m 近似
# （CoinW granularity 无 59，且 1m limit 只到 25h 拼不出足够 59m 历史）。
BREATH_ETH: Dict[str, Any] = {
    "name": "ETH",
    "initial_sl_atr": 0.0,        # 规格 v2.1：激活用保本位，不用 ATR 臂
    "fee_cover_pct": 0.0008,
    "stop_exec_buffer": 0.3,
    "early_be_atr": 0.0,
    "step_trigger_atr": 0.87,    # 59m 校准：0.375×breath_tp12
    "step_advance_atr": 0.57,    # 59m 校准：0.65×step_trigger
    "phase_switch_atr": 3.0,
    "tp1_atr": 1.35,
    "tp1_floor_atr": 0.0,
    "tp2_atr": 2.5,
    "tp2_floor_atr": 0.0,
    "breath_tp12": 2.31,        # 59m 校准：覆盖实测中位数回调 (P50=2.31)
    "breath_tp23": 3.36,        # 59m 校准：覆盖实测 75 分位回调 (P75=3.36)
    "phase2_trail_mult": 1.0,
    "min_mult": 4.0,           # 59m 校准：0.72×max_mult
    "max_mult": 5.6,           # 59m 校准：覆盖实测 90 分位回调 (P90=5.32) + 0.3
    "ratio_floor": RATIO_FLOOR,
    "ratio_ceiling": RATIO_CEILING,
    "tick_size": 0.01,
    "entry_score": 3,
    "exit_score": 2,
}

# BNB 基线 —— 2026-09-12新增，150分钟周期假设（见上方模块docstring局限说明）。
# CoinW真实30m K线合成150m，299根覆盖约31天，49个摆动点、37个回调样本。
# ATR%=1.09%。回调分布：P50=2.68×ATR，P75=3.26×ATR，P90=5.19×ATR。
BREATH_BNB: Dict[str, Any] = {
    "name": "BNB",
    "initial_sl_atr": 0.0,
    "fee_cover_pct": 0.0008,
    "stop_exec_buffer": 0.3,
    "early_be_atr": 0.0,
    "step_trigger_atr": 1.01,   # 0.375×breath_tp12
    "step_advance_atr": 0.66,   # 0.65×step_trigger
    "phase_switch_atr": 3.0,
    "tp1_atr": 1.35,
    "tp1_floor_atr": 0.0,
    "tp2_atr": 2.5,
    "tp2_floor_atr": 0.0,
    "breath_tp12": 2.68,  # 覆盖实测中位数回调(2.68)
    "breath_tp23": 3.26,  # 覆盖实测75分位回调(3.26)
    "phase2_trail_mult": 1.0,
    "min_mult": 4.0,      # 0.72×max_mult（沿用币安BNB自己的min/max比例）
    "max_mult": 5.5,      # 覆盖实测90分位回调(5.19)以上
    "ratio_floor": RATIO_FLOOR,
    "ratio_ceiling": RATIO_CEILING,
    "tick_size": 0.01,
    "entry_score": 3,
    "exit_score": 2,
}

# OPENAI 基线 —— 2026-09-12新增，150分钟周期假设（见上方模块docstring局限
# 说明；这个周期有宝贝给的TV警报截图佐证）。CoinW真实30m K线合成150m，
# 299根覆盖约31天，58个摆动点、50个回调样本。ATR%=1.90%——盘前品种波动率
# 偏高，跟币安OPENAI的观察一致。回调分布：P50=2.39×ATR，P75=3.52×ATR，
# P90=4.51×ATR。
BREATH_OPENAI: Dict[str, Any] = {
    "name": "OPENAI",
    "initial_sl_atr": 0.0,
    "fee_cover_pct": 0.0008,
    "stop_exec_buffer": 0.3,
    "early_be_atr": 0.0,
    "step_trigger_atr": 0.90,   # 0.375×breath_tp12
    "step_advance_atr": 0.59,   # 0.65×step_trigger
    "phase_switch_atr": 3.0,
    "tp1_atr": 1.35,
    "tp1_floor_atr": 0.0,
    "tp2_atr": 2.5,
    "tp2_floor_atr": 0.0,
    "breath_tp12": 2.39,  # 覆盖实测中位数回调(2.39)
    "breath_tp23": 3.52,  # 覆盖实测75分位回调(3.52)
    "phase2_trail_mult": 1.0,
    "min_mult": 3.8,      # 0.8×max_mult（沿用币安OPENAI自己的min/max比例）
    "max_mult": 4.8,      # 覆盖实测90分位回调(4.51)以上
    "ratio_floor": RATIO_FLOOR,
    "ratio_ceiling": RATIO_CEILING,
    "tick_size": 0.01,
    "entry_score": 3,
    "exit_score": 2,
}

# SNDK 基线 —— 2026-09-12新增，150分钟周期假设（见上方模块docstring局限
# 说明）。CoinW真实30m K线合成150m，299根覆盖约31天，55个摆动点、42个
# 回调样本。ATR%=1.42%。回调分布：P50=2.75×ATR，P75=3.75×ATR，
# P90=6.42×ATR。
BREATH_SNDK: Dict[str, Any] = {
    "name": "SNDK",
    "initial_sl_atr": 0.0,
    "fee_cover_pct": 0.0008,
    "stop_exec_buffer": 0.3,
    "early_be_atr": 0.0,
    "step_trigger_atr": 1.03,   # 0.375×breath_tp12
    "step_advance_atr": 0.67,   # 0.65×step_trigger
    "phase_switch_atr": 3.0,
    "tp1_atr": 1.35,
    "tp1_floor_atr": 0.0,
    "tp2_atr": 2.5,
    "tp2_floor_atr": 0.0,
    "breath_tp12": 2.75,  # 覆盖实测中位数回调(2.75)
    "breath_tp23": 3.75,  # 覆盖实测75分位回调(3.75)
    "phase2_trail_mult": 1.0,
    "min_mult": 4.8,      # 0.72×max_mult（沿用币安SNDK自己的min/max比例）
    "max_mult": 6.7,      # 覆盖实测90分位回调(6.42)以上
    "ratio_floor": RATIO_FLOOR,
    "ratio_ceiling": RATIO_CEILING,
    "tick_size": 0.01,
    "entry_score": 3,
    "exit_score": 2,
}

# XPD 基线（钯金）—— 2026-09-12新增，150分钟周期假设（见上方模块docstring
# 局限说明；这个周期有宝贝给的TV警报截图佐证）。CoinW真实30m K线合成
# 150m，299根覆盖约31天，51个摆动点、35个回调样本。ATR%=0.85%。回调分布：
# P50=2.87×ATR，P75=4.51×ATR，P90=6.53×ATR。
BREATH_XPD: Dict[str, Any] = {
    "name": "XPD",
    "initial_sl_atr": 0.0,
    "fee_cover_pct": 0.0008,
    "stop_exec_buffer": 0.3,
    "early_be_atr": 0.0,
    "step_trigger_atr": 1.08,   # 0.375×breath_tp12
    "step_advance_atr": 0.70,   # 0.65×step_trigger
    "phase_switch_atr": 3.0,
    "tp1_atr": 1.35,
    "tp1_floor_atr": 0.0,
    "tp2_atr": 2.5,
    "tp2_floor_atr": 0.0,
    "breath_tp12": 2.87,  # 覆盖实测中位数回调(2.87)
    "breath_tp23": 4.51,  # 覆盖实测75分位回调(4.51)
    "phase2_trail_mult": 1.0,
    "min_mult": 5.4,      # 0.79×max_mult（沿用币安XPD自己的min/max比例）
    "max_mult": 6.8,      # 覆盖实测90分位回调(6.53)以上
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
    "BNB": BREATH_BNB,
    "OPENAI": BREATH_OPENAI,
    "SNDK": BREATH_SNDK,
    "XPD": BREATH_XPD,
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
