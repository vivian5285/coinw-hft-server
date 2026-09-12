#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
硬止损公式 - CoinW单系统 v16.22.1

旧公式（calc_hard_stop_price）：|TV价 − stop_loss| × 1.15，锚定交易所成交价。
调用方 position_supervisor_coinw.py 已在 2026-09-12 切到不看 TV 自己算的
stop_loss（宝贝原话："不用理会tv的仓位公式...tv的（止损）不行，太木讷了"）
——旧函数原样保留（向后兼容/单测覆盖），但不再是实际生效路径。

新公式（calc_smart_hard_stop_price，2026-09-12新增）："综合硬止损"：VPS 自己
拉K线独立判断，TV 只给方向，不看 TV 的 stop_loss/atr 字段：
  结构止损 = 最近一个真实确认的摆动点(fractal pivot，±3根确认，跟这仓
             eth-webhook-server 项目里所有呼吸参数校准用的同一套方法，
             比简单"最近N根最低点"更抗噪声——单根插针不会误判成摆动点)
             ∓ 0.3×ATR 缓冲
  ATR保护带 = 成交价 ∓ K_tier×ATR（K_tier 按 TV 给的 tier 强弱分档：
             弱0=1.5 / 中1=2.5 / 强2=3.5，tier缺失按最紧的1.5兜底——
             止损这条防线，数据不全时宁可保守也不要给太宽的止损空间）
  硬止损 = 两者取更保守者（多头取更高、空头取更低）——结构位太近时
           ATR保护带兜住最小距离，结构位找不到摆动点或明显更远时用简单
           N根高低点兜底。
ATR/摆动点都由这个模块自己从VPS拉到的K线独立算，不用TV传来的atr/
stop_loss字段——真正做到"TV给方向，VPS自己判断怎么开、止损放哪"。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple


def calc_hard_stop_price(tv_price: float, tv_stop_loss: float,
                         entry_price: float = None,
                         direction: str = "LONG",
                         buffer: float = None) -> tuple:
    """
    计算硬止损价格

    公式：dist = |tv_price - tv_stop_loss| × buffer
    多头：hard_sl = entry_price - dist
    空头：hard_sl = entry_price + dist

    Args:
        tv_price: TV webhook价格
        tv_stop_loss: TV webhook的stop_loss
        entry_price: 交易所成交价（可选）
        direction: LONG/SHORT
        buffer: 呼吸垫（默认1.15）

    Returns:
        (hard_stop_price, dist, ok, error)
    """
    if buffer is None:
        buffer = float(os.getenv("HARD_STOP_BUFFER", "1.15"))

    # 检查stop_loss
    if tv_stop_loss <= 0:
        return 0.0, 0.0, False, "missing_stop_loss"

    if tv_price <= 0:
        return 0.0, 0.0, False, "missing_tv_price"

    # 计算距离
    dist = abs(tv_price - tv_stop_loss) * buffer

    if dist <= 0:
        return 0.0, 0.0, False, "zero_distance"

    # 使用成交价或TV价格
    ref_price = entry_price if entry_price and entry_price > 0 else tv_price

    # 计算止损价
    direction = str(direction).upper()
    if direction == "LONG":
        hard_stop = ref_price - dist
    else:  # SHORT
        hard_stop = ref_price + dist

    # 验证止损是否有效
    if direction == "LONG":
        if hard_stop >= ref_price:
            return 0.0, dist, False, "stop_above_entry_long"
    else:
        if hard_stop <= ref_price:
            return 0.0, dist, False, "stop_below_entry_short"

    return round(hard_stop, 2), round(dist, 4), True, ""


def verify_hard_stop(hard_stop_price: float, entry_price: float,
                     direction: str, tv_price: float = None,
                     tv_stop_loss: float = None,
                     max_drift_pct: float = 0.02) -> tuple:
    """
    验证硬止损是否符合预期

    Returns:
        (ok, detail)
    """
    direction = str(direction).upper()

    if hard_stop_price <= 0:
        return False, f"invalid_stop_price:{hard_stop_price}"

    if entry_price <= 0:
        return False, f"invalid_entry_price:{entry_price}"

    # 计算预期值（如果有TV数据）
    if tv_price and tv_stop_loss:
        buffer = float(os.getenv("HARD_STOP_BUFFER", "1.15"))
        dist = abs(tv_price - tv_stop_loss) * buffer
        ref = entry_price if entry_price > 0 else tv_price

        if direction == "LONG":
            expected = ref - dist
        else:
            expected = ref + dist

        drift = abs(hard_stop_price - expected) / max(expected, 1)
        if drift > max_drift_pct:
            return False, f"drift_too_large:{drift:.2%}>max{max_drift_pct:.2%}"

    # 验证方向正确
    if direction == "LONG":
        if hard_stop_price >= entry_price:
            return False, f"long_stop_above_entry:{hard_stop_price}>={entry_price}"
    else:
        if hard_stop_price <= entry_price:
            return False, f"short_stop_below_entry:{hard_stop_price}<={entry_price}"

    return True, "ok"


# ==================== 综合硬止损（2026-09-12新增） ====================

# K_tier：ATR保护带倍数，按TV给的tier强弱分档。tier缺失/非法时用最紧的
# 1.5（止损这条防线数据不全宁可保守，跟仓位公式"缺失按最强档"的取向刻意
# 相反——参见 defense_profiles.py 顶部注释）。
K_TIER_DEFAULT: Dict[int, float] = {0: 1.5, 1: 2.5, 2: 3.5}
STRUCT_LOOKBACK_BARS = 60      # 摆动点识别的K线窗口（VPS自己拉的K线根数）
STRUCT_CONFIRM = 3             # fractal pivot 左右各3根确认（跟本项目呼吸参数校准同一套方法）
STRUCT_BUFFER_ATR = 0.3        # 摆动点缓冲垫（×ATR）
ATR_PERIOD = 14


def _true_ranges(bars: List[list]) -> List[float]:
    trs = []
    for i in range(1, len(bars)):
        h = float(bars[i][2])
        l = float(bars[i][3])
        pc = float(bars[i - 1][4])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return trs


def _atr_last(bars: List[list], period: int = ATR_PERIOD) -> float:
    """Wilder ATR，取最后一个值。bars不足返回0（调用方需拒绝零ATR）。"""
    if not bars or len(bars) < period + 1:
        return 0.0
    trs = _true_ranges(bars)
    if len(trs) < period:
        return 0.0
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def _last_confirmed_pivot(bars: List[list], side: str, confirm: int = STRUCT_CONFIRM) -> Optional[float]:
    """
    从最新往回找第一个真实确认的摆动点（±confirm根都不更极端才算数）。
    LONG找摆动低点(支撑)，SHORT找摆动高点(阻力)。找不到返回None（调用方
    兜底用简单窗口最低/最高点，不整体失败）。
    """
    highs = [float(b[2]) for b in bars]
    lows = [float(b[3]) for b in bars]
    n = len(bars)
    for i in range(n - 1 - confirm, confirm - 1, -1):
        if side == "LONG":
            window = lows[i - confirm:i] + lows[i + 1:i + 1 + confirm]
            if window and lows[i] < min(window):
                return lows[i]
        else:
            window = highs[i - confirm:i] + highs[i + 1:i + 1 + confirm]
            if window and highs[i] > max(window):
                return highs[i]
    return None


def calc_smart_hard_stop_price(
    side: str,
    entry_price: float,
    klines: List[list],
    tier: Any = None,
    struct_lookback: int = STRUCT_LOOKBACK_BARS,
    confirm: int = STRUCT_CONFIRM,
    struct_buffer_atr: float = STRUCT_BUFFER_ATR,
    atr_period: int = ATR_PERIOD,
    k_tier: Optional[Dict[int, float]] = None,
) -> Tuple[float, Dict[str, Any], bool, str]:
    """
    综合硬止损：结构摆动点(fractal pivot) + 分档ATR保护带，取更保守者。
    不读TV的stop_loss/atr字段——ATR和摆动点都从klines（VPS自己拉的，
    caller负责按自己选的周期/粒度提供）独立算。

    klines: [[open_ms, open, high, low, close, volume], ...]，时间升序，
            最后一根可以是未收盘的成型K线（结构/ATR计算对此不敏感）。

    返回 (hard_stop_price, meta, ok, error)。meta 含 atr/struct_stop/
    atr_stop/tier/k_tier/pivot_found，用于日志与人工核查。
    """
    side = str(side or "").upper()
    entry_price = float(entry_price or 0)
    if entry_price <= 0 or side not in ("LONG", "SHORT"):
        return 0.0, {}, False, "invalid_entry_or_side"

    bars = list(klines or [])
    if struct_lookback and len(bars) > struct_lookback:
        bars = bars[-struct_lookback:]
    if len(bars) < atr_period + confirm + 1:
        return 0.0, {}, False, f"insufficient_klines:{len(bars)}"

    atr = _atr_last(bars, atr_period)
    if atr <= 0:
        return 0.0, {}, False, "zero_atr"

    k_map = dict(k_tier or K_TIER_DEFAULT)
    try:
        t = int(str(tier).strip())
    except (TypeError, ValueError):
        t = 0  # tier缺失/非法：止损防线宁可按最紧档保守，不同于仓位公式的取向
    k = float(k_map.get(t, k_map.get(0, 1.5)))

    pivot = _last_confirmed_pivot(bars, side, confirm)

    if side == "LONG":
        atr_stop = entry_price - k * atr
        if pivot is not None:
            struct_stop = pivot - struct_buffer_atr * atr
        else:
            struct_stop = min(float(b[3]) for b in bars)  # 找不到摆动点：简单窗口最低点兜底
        hard_sl = max(struct_stop, atr_stop)
        if hard_sl >= entry_price:
            return 0.0, {}, False, f"stop_above_entry_long:{hard_sl}>={entry_price}"
    else:
        atr_stop = entry_price + k * atr
        if pivot is not None:
            struct_stop = pivot + struct_buffer_atr * atr
        else:
            struct_stop = max(float(b[2]) for b in bars)
        hard_sl = min(struct_stop, atr_stop)
        if hard_sl <= entry_price:
            return 0.0, {}, False, f"stop_below_entry_short:{hard_sl}<={entry_price}"

    meta = {
        "atr": round(atr, 4),
        "tier": t,
        "k_tier": k,
        "struct_stop": round(struct_stop, 4),
        "atr_stop": round(atr_stop, 4),
        "pivot_found": pivot is not None,
        "bars_used": len(bars),
    }
    return round(hard_sl, 2), meta, True, ""


class AtrScenario:
    """
    ATR场景计算器（保留接口，与币安系统兼容）
    CoinW系统直接使用TV webhook的atr
    """

    def __init__(self):
        pass

    def calc_stop(self, tv_price: float, tv_stop_loss: float,
                  entry_price: float = None,
                  direction: str = "LONG") -> dict:
        """计算止损"""
        price, dist, ok, err = calc_hard_stop_price(
            tv_price, tv_stop_loss, entry_price, direction
        )
        return {
            "hard_stop_price": price,
            "distance": dist,
            "ok": ok,
            "error": err,
        }

    def get_atr(self, tv_atr: float = None) -> float:
        """直接返回TV的atr"""
        return float(tv_atr or 0)


# 单例
_atr_scenario: Optional[AtrScenario] = None


def get_atr_scenario() -> AtrScenario:
    global _atr_scenario
    if _atr_scenario is None:
        _atr_scenario = AtrScenario()
    return _atr_scenario
