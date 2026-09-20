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

# 2026-09-13新增：宝贝实盘发现同一笔OPENAI空单，币安B系统(tier=2强·真
# 放量确认→wide组合)硬止损距entry约1.68×k×ATR，比CoinW(tier=0弱→tight，
# 两边TV各自独立分析各自venue价格走势算出不同tier，不是bug)明显宽很多
# ——根因是wide模式原来对"结构止损离多远"完全没有上限，找到的摆动点
# 可能是60根K线窗口内很久以前的一个高点/低点，一旦离得太远，赶上开错
# 方向会让亏损被显著放大。修复：wide模式最终距离不能超过tight基准距离
# (k×ATR)的WIDE_MODE_CEILING_MULT倍——继续保留wide模式本意，但给"多喘
# 的空间"设一个绝对上限。跟币安B系统(smart_hard_stop.py)完全同一份
# 数值/同一套逻辑，两边保持一致。
WIDE_MODE_CEILING_MULT = 1.5

# 2026-09-20新增：宝贝实盘发现MU(币安B+CoinW两边都)、以及CoinW当天XPD/XAU
# 两笔真实止损出局，止损距entry仅0.1~0.2%——根因是tight模式(弱/中tier，
# 也是最常见的信号强度)完全没有最小距离下限，而这里算ATR/结构摆动点用的
# 固定30分钟K线，本身就比策略呼吸空间校准用的品种原生TV周期(49~91分钟，
# 见DUAL_MA_EXIT_INTERVAL_MIN)短得多，30分钟ATR天然偏小，k×ATR/结构位
# 两个候选只要恰好都薄，止损就能薄到一个正常波动就打穿——比wide模式那次
# OPENAI事故(止损太宽)反过来的镜像问题(止损太紧)。跟币安B系统
# (smart_hard_stop.py)完全同一份数值/同一套逻辑，两边保持一致。
# 修复：调用方现在可以传入breath_atr(品种真实呼吸周期上现算的ATR，跟
# breath_profiles.py呼吸系数校准用的同一个周期)，tight模式下止损距离不能
# 小于TIGHT_MODE_FLOOR_MULT×breath_atr；不传时退回用本函数自己算出来的
# atr自身做下限参考(仍能防住"结构摆动点比30分钟ATR带还近"这一种情形，
# 只是防不住"30分钟ATR本身就偏小"这一种，覆盖面比传了breath_atr时小)。
# 0.7是折中：比tier=0的k=1.5明显更紧(留给弱信号该有的克制)，但不会薄到
# 今天这种一个正常波动就打穿的程度。
TIGHT_MODE_FLOOR_MULT = 0.7

# 2026-09-12 v2（宝贝反复强调的点）：弱趋势该止损就止损（紧），强趋势+
# 真放量的话要给呼吸空间（宽），不能让一个恰好离得近的摆动点把"该给宽
# 止损"的意图吞掉。v1 里 struct/ATR 永远取"更紧的那个"(多头max/空头min)，
# 这其实等价于"永远优先保护本金、从不优先给呼吸空间"——强 tier 时哪怕
# ATR保护带算出来很宽，只要现价附近恰好有个摆动点，还是会被拉回紧的
# 那侧，跟"强趋势该宽"的诉求正好反着。v2 改成按"趋势是否真强"切换
# 取舍方向：
#   弱/中 tier，或强 tier但没查到真实放量confirmation → 沿用v1，取更紧者
#     （结构位/ATR保护带谁离现价近听谁的，宁可紧不可松）
#   强 tier 且查到真实放量confirmation → 反过来取更宽者（结构位/ATR保护带
#     谁离现价远听谁的，允许趋势呼吸，不因为凑巧路过一个摆动点就把它当
#     硬止损杀掉）
# "真实放量"不只信TV自己给的tier（那是开仓那一刻pine脚本算的静态值，
# 不会随行情实时更新）——VPS自己拿同一批klines算最近几根量能是否明显
# 放大，双重确认，防止tier=2但其实量没跟上的假强势。
VOLUME_CONFIRM_LOOKBACK = 20   # 基准量能取这个窗口内、最近N根之前的均量
VOLUME_CONFIRM_RECENT_N = 3    # 最近几根的均量拿来跟基准比
VOLUME_CONFIRM_MULT = 1.3      # 最近量能 ≥ 基准 × 此倍数 才算"真放量"


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


def _volume_confirmed(
    bars: List[list],
    lookback: int = VOLUME_CONFIRM_LOOKBACK,
    recent_n: int = VOLUME_CONFIRM_RECENT_N,
    mult: float = VOLUME_CONFIRM_MULT,
) -> bool:
    """最近 recent_n 根均量是否 ≥ 之前 lookback 根均量的 mult 倍——真放量
    确认，不信 TV 开仓那一刻给的静态 tier，VPS 自己用同一批 klines 复核。
    数据不够时保守返回 False（不确认 = 不放宽，跟止损"数据不全按紧算"
    一致）。"""
    if len(bars) < lookback + recent_n:
        return False
    base = bars[-(lookback + recent_n):-recent_n]
    recent = bars[-recent_n:]
    if not base or not recent:
        return False
    base_avg = sum(float(b[5]) for b in base) / len(base)
    recent_avg = sum(float(b[5]) for b in recent) / len(recent)
    if base_avg <= 0:
        return False
    return recent_avg >= mult * base_avg


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
    strong_tier: int = 2,
    breath_atr: Optional[float] = None,
    tight_floor_mult: float = TIGHT_MODE_FLOOR_MULT,
) -> Tuple[float, Dict[str, Any], bool, str]:
    """
    综合硬止损：结构摆动点(fractal pivot) + 分档ATR保护带，取更保守者。
    不读TV的stop_loss/atr字段——ATR和摆动点都从klines（VPS自己拉的，
    caller负责按自己选的周期/粒度提供）独立算。

    klines: [[open_ms, open, high, low, close, volume], ...]，时间升序，
            最后一根可以是未收盘的成型K线（结构/ATR计算对此不敏感）。

    返回 (hard_stop_price, meta, ok, error)。meta 含 atr/struct_stop/
    atr_stop/tier/k_tier/pivot_found/volume_confirmed/combo_mode，用于
    日志与人工核查。

    combo_mode：
      "tight"（弱/中tier，或强tier但没查到真放量）——struct/ATR两个候选
        取更靠近成交价的那个（多头取更高、空头取更低），宁紧不松。但
        距离不能小于tight_floor_mult×breath_atr(品种真实呼吸周期ATR，
        breath_atr不传时退回用本函数自己算出的atr)——防止30分钟K线上
        恰好都薄(结构位近+ATR带窄)时止损薄到一个正常波动就打穿。
      "wide"（强tier且查到真放量确认）——反过来取更远离成交价的那个，
        允许趋势呼吸，不被恰好路过的摆动点/过紧ATR带提前打出去。
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

    vol_ok = _volume_confirmed(bars)
    wide_mode = (t >= strong_tier) and vol_ok

    pivot = _last_confirmed_pivot(bars, side, confirm)

    wide_ceiling_dist = WIDE_MODE_CEILING_MULT * k * atr
    ceiling_applied = False
    floor_ref_atr = float(breath_atr) if breath_atr and float(breath_atr) > 0 else atr
    floor_dist = tight_floor_mult * floor_ref_atr
    floor_applied = False
    if side == "LONG":
        atr_stop = entry_price - k * atr
        if pivot is not None:
            struct_stop = pivot - struct_buffer_atr * atr
        else:
            struct_stop = min(float(b[3]) for b in bars)  # 找不到摆动点：简单窗口最低点兜底
        hard_sl = min(struct_stop, atr_stop) if wide_mode else max(struct_stop, atr_stop)
        if wide_mode and (entry_price - hard_sl) > wide_ceiling_dist:
            hard_sl = entry_price - wide_ceiling_dist
            ceiling_applied = True
        if not wide_mode and (entry_price - hard_sl) < floor_dist:
            hard_sl = entry_price - floor_dist
            floor_applied = True
        if hard_sl >= entry_price:
            return 0.0, {}, False, f"stop_above_entry_long:{hard_sl}>={entry_price}"
    else:
        atr_stop = entry_price + k * atr
        if pivot is not None:
            struct_stop = pivot + struct_buffer_atr * atr
        else:
            struct_stop = max(float(b[2]) for b in bars)
        hard_sl = max(struct_stop, atr_stop) if wide_mode else min(struct_stop, atr_stop)
        if wide_mode and (hard_sl - entry_price) > wide_ceiling_dist:
            hard_sl = entry_price + wide_ceiling_dist
            ceiling_applied = True
        if not wide_mode and (hard_sl - entry_price) < floor_dist:
            hard_sl = entry_price + floor_dist
            floor_applied = True
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
        "volume_confirmed": vol_ok,
        "combo_mode": "wide" if wide_mode else "tight",
        "wide_ceiling_applied": ceiling_applied,
        "wide_ceiling_dist": round(wide_ceiling_dist, 4) if wide_mode else 0.0,
        "breath_atr": round(floor_ref_atr, 4),
        "tight_floor_dist": round(floor_dist, 4) if not wide_mode else 0.0,
        "tight_floor_applied": floor_applied,
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
