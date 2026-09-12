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
回调距离/本地ATR 分位。

**周期（2026-09-12当天二次修正）**：第一版按"沿用币安同品种150分钟"假设
校准过一次，当天晚些时候宝贝直接给了 CoinW 这边 TV 警报面板截图确认
真实周期——**BNB=45分钟，XPD=45分钟，SNDK=75分钟，OPENAI=2小时(120分钟)
——四个品种周期各不相同，也都不是币安那边的150分钟**，第一版数值作废，
本次按真实周期重新拉K线全部重新校准。CoinW granularity 原生支持
{1,3,5,15,30,60,120,240,360,480,1440,10080}分钟——OPENAI的120分钟正好
是原生粒度，直接拉，不用合成；BNB/XPD的45分钟、SNDK的75分钟都不是原生
粒度，用能整除的最细原生粒度15分钟K线合成（45=15×3，75=15×5）。

**数据量**：CoinW 公开 klines 接口单次最多回1500根、不支持分页翻更早
历史（实测 endTime/before 参数均无效）——OPENAI用120m原生粒度，1500根
覆盖约109天（197个回调样本，比第一版31天/50样本厚实很多）；BNB/XPD/SNDK
用15m合成，1500根15m只能覆盖约15.6天（51~73个回调样本，比币安同品种
60~83天的样本更薄——这是CoinW数据接口的硬限制，用更细粒度合成换不来更长
历史，等实盘跑出更长真实历史后应该重新校准一遍加厚样本）。

tp1_atr/tp2_atr/phase_switch_atr/fee_cover_pct/stop_exec_buffer/
tick_size/entry_score/exit_score 沿用全系统统一默认值（这几项从来都不是
按品种校准的，币安那边所有品种也是同一套值）。step_trigger_atr≈0.375×
breath_tp12、step_advance_atr≈0.65×step_trigger_atr 是币安那边SNDK等
品种验证过的跨品种经验比例；min_mult/max_mult 比例沿用币安同品种自己的
既有比例（BNB0.72／OPENAI0.8／SNDK0.72／XPD0.79——这是币安该品种自己的
尾部特征，比统一比例更贴合，即便周期不同也是该品种自己的"行情性格"，
比套统一比例更合理）。未接 has_staged_exit_gate：不确认CoinW这边TV
pine脚本是否也有这个机制，跟CoinW-ETH现有档案一样先不设。
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

# BNB 基线 —— 2026-09-12二次校准：真实TV周期45分钟（宝贝截图确认，第一版
# 150分钟假设作废）。CoinW真实15m K线合成45m，499根覆盖约15.6天，87个
# 摆动点、56个回调样本。ATR%=0.44%。回调分布：P50=2.43×ATR，P75=3.20×ATR，
# P90=4.41×ATR。
BREATH_BNB: Dict[str, Any] = {
    "name": "BNB",
    "initial_sl_atr": 0.0,
    "fee_cover_pct": 0.0008,
    "stop_exec_buffer": 0.3,
    "early_be_atr": 0.0,
    "step_trigger_atr": 0.91,   # 0.375×breath_tp12
    "step_advance_atr": 0.59,   # 0.65×step_trigger
    "phase_switch_atr": 3.0,
    "tp1_atr": 1.35,
    "tp1_floor_atr": 0.0,
    "tp2_atr": 2.5,
    "tp2_floor_atr": 0.0,
    "breath_tp12": 2.43,  # 覆盖实测中位数回调(2.43)
    "breath_tp23": 3.20,  # 覆盖实测75分位回调(3.20)
    "phase2_trail_mult": 1.0,
    "min_mult": 3.4,      # 0.72×max_mult（沿用币安BNB自己的min/max比例）
    "max_mult": 4.7,      # 覆盖实测90分位回调(4.41)以上
    "ratio_floor": RATIO_FLOOR,
    "ratio_ceiling": RATIO_CEILING,
    "tick_size": 0.01,
    "entry_score": 3,
    "exit_score": 2,
}

# OPENAI 基线 —— 2026-09-12二次校准：真实TV周期2小时/120分钟（宝贝截图
# 确认，第一版150分钟假设作废）。120分钟正好是CoinW原生K线粒度，不用
# 合成，1500根覆盖约109天（比第一版31天厚实很多），262个摆动点、197个
# 回调样本。ATR%=1.43%。回调分布：P50=2.25×ATR，P75=3.59×ATR，
# P90=5.12×ATR。
BREATH_OPENAI: Dict[str, Any] = {
    "name": "OPENAI",
    "initial_sl_atr": 0.0,
    "fee_cover_pct": 0.0008,
    "stop_exec_buffer": 0.3,
    "early_be_atr": 0.0,
    "step_trigger_atr": 0.84,   # 0.375×breath_tp12
    "step_advance_atr": 0.55,   # 0.65×step_trigger
    "phase_switch_atr": 3.0,
    "tp1_atr": 1.35,
    "tp1_floor_atr": 0.0,
    "tp2_atr": 2.5,
    "tp2_floor_atr": 0.0,
    "breath_tp12": 2.25,  # 覆盖实测中位数回调(2.25)
    "breath_tp23": 3.59,  # 覆盖实测75分位回调(3.59)
    "phase2_trail_mult": 1.0,
    "min_mult": 4.3,      # 0.8×max_mult（沿用币安OPENAI自己的min/max比例）
    "max_mult": 5.4,      # 覆盖实测90分位回调(5.12)以上
    "ratio_floor": RATIO_FLOOR,
    "ratio_ceiling": RATIO_CEILING,
    "tick_size": 0.01,
    "entry_score": 3,
    "exit_score": 2,
}

# SNDK 基线 —— 2026-09-12二次校准：真实TV周期75分钟（宝贝截图确认，第
# 一版150分钟假设作废）。CoinW真实15m K线合成75m，299根覆盖约15.5天，
# 62个摆动点、51个回调样本。ATR%=0.63%。回调分布：P50=2.42×ATR，
# P75=4.09×ATR，P90=6.44×ATR。
BREATH_SNDK: Dict[str, Any] = {
    "name": "SNDK",
    "initial_sl_atr": 0.0,
    "fee_cover_pct": 0.0008,
    "stop_exec_buffer": 0.3,
    "early_be_atr": 0.0,
    "step_trigger_atr": 0.91,   # 0.375×breath_tp12
    "step_advance_atr": 0.59,   # 0.65×step_trigger
    "phase_switch_atr": 3.0,
    "tp1_atr": 1.35,
    "tp1_floor_atr": 0.0,
    "tp2_atr": 2.5,
    "tp2_floor_atr": 0.0,
    "breath_tp12": 2.42,  # 覆盖实测中位数回调(2.42)
    "breath_tp23": 4.09,  # 覆盖实测75分位回调(4.09)
    "phase2_trail_mult": 1.0,
    "min_mult": 4.8,      # 0.72×max_mult（沿用币安SNDK自己的min/max比例）
    "max_mult": 6.7,      # 覆盖实测90分位回调(6.44)以上
    "ratio_floor": RATIO_FLOOR,
    "ratio_ceiling": RATIO_CEILING,
    "tick_size": 0.01,
    "entry_score": 3,
    "exit_score": 2,
}

# XPD 基线（钯金）—— 2026-09-12二次校准：真实TV周期45分钟（宝贝截图确认，
# 第一版150分钟假设作废）。CoinW真实15m K线合成45m，499根覆盖约15.6天，
# 93个摆动点、73个回调样本。ATR%=0.28%。回调分布：P50=2.19×ATR，
# P75=3.58×ATR，P90=5.87×ATR。
BREATH_XPD: Dict[str, Any] = {
    "name": "XPD",
    "initial_sl_atr": 0.0,
    "fee_cover_pct": 0.0008,
    "stop_exec_buffer": 0.3,
    "early_be_atr": 0.0,
    "step_trigger_atr": 0.82,   # 0.375×breath_tp12
    "step_advance_atr": 0.53,   # 0.65×step_trigger
    "phase_switch_atr": 3.0,
    "tp1_atr": 1.35,
    "tp1_floor_atr": 0.0,
    "tp2_atr": 2.5,
    "tp2_floor_atr": 0.0,
    "breath_tp12": 2.19,  # 覆盖实测中位数回调(2.19)
    "breath_tp23": 3.58,  # 覆盖实测75分位回调(3.58)
    "phase2_trail_mult": 1.0,
    "min_mult": 4.9,      # 0.79×max_mult（沿用币安XPD自己的min/max比例）
    "max_mult": 6.2,      # 覆盖实测90分位回调(5.87)以上
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
