#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
雷达呼吸止损 - CoinW单系统

2026-08-29 换代：推进逻辑从"三阶段(breakeven/trail/dynamic) + ADX 三档"整体
换成币安单系统 v2.1 的 calculate_breath_stop —— 按价格相对 TP 进度分区
(pre_tp1 / tp1_tp2 / tp2_tp3 / tp3_confirm / tp3_plus)：
  · 激活臂 = 保本起步 entry ± tick ± entry×fee_cover_pct
  · 阶梯：价格每涨 step_trigger_atr×ATR，止损上移 step_advance_atr×ATR
  · 分区呼吸：TP1–TP2 用 breath_tp12、TP2–TP3 用 breath_tp23、
    TP3+ 用 min_mult~max_mult 按 ATR 比连续插值；阶梯止损受呼吸空间封顶
    (pre_tp1 区除外)，呼吸空间只进不退
  · 浮盈≥phase_switch_atr(默认3) 或已确认走出 TP3 → 动态追踪阶段
下面 4 个纯函数 (_tick_size / initial_stop_price / _zone_trail_atr /
calculate_stop_* / calculate_breath_stop) 从币安 eth-webhook-server 的
breath_stop.py 原样移植，逐字段吃 breath_profiles.BREATH_ETH。

激活逻辑不变（2026-08-08 已对齐 v2.1）：现价到激活线即可 —— 首次开仓
激活线=(TP1+TP2)/2 中点，重入开仓=TP2，不依赖 TP 是否真的成交
(CoinW 小仓位下 TP1 常因不足 1 张最小单位被跳过)。
"""

from __future__ import annotations

import time
import threading
from typing import Any, Dict, Optional, Tuple
from dataclasses import dataclass

from breath_profiles import (
    BREATH_ETH,
    cold_start_multiplier,
    default_breath_profile,
    trail_distance_multiplier,
)

FEE_COVER_PCT = 0.0008
TP3_CONFIRM_ATR = 1.0  # 刚过TP3但还没走出这么远之前，呼吸空间暂不放宽到 tp3_plus
TP1_ATR = float(BREATH_ETH["tp1_atr"])
TP2_ATR = float(BREATH_ETH["tp2_atr"])
PHASE_SWITCH_ATR = float(BREATH_ETH["phase_switch_atr"])


# ==================== 币安 breath_stop.py 原样移植的纯函数 ====================

def _tick_size(profile: Dict[str, Any]) -> float:
    try:
        t = float(profile.get("tick_size") or 0.01)
    except (TypeError, ValueError):
        t = 0.01
    return t if t > 0 else 0.01


def initial_stop_price(side: str, entry_price: float, initial_atr: float = 0.0,
                       profile: Optional[Dict[str, Any]] = None) -> float:
    """
    雷达激活臂（保本起步）：多 = entry + tick + fee_cover；空 = entry − tick − fee_cover。
    签名与币安 breath_stop.py 一致；initial_atr 仅在 profile 带正 initial_sl_atr 时用到
    （CoinW 的 BREATH_ETH 里是 0.0，走保本位分支）。
    """
    p = profile if isinstance(profile, dict) and profile else default_breath_profile()
    entry = float(entry_price or 0)
    if entry <= 0:
        return 0.0
    side = str(side or "").strip().upper()
    mult = float(p.get("initial_sl_atr") or 0)
    atr = float(initial_atr or 0)
    if mult > 0 and atr > 0:
        if side == "SHORT":
            return round(entry + mult * atr, 2)
        return round(entry - mult * atr, 2)
    tick = _tick_size(p)
    try:
        fee_pct = abs(float(p.get("fee_cover_pct") or FEE_COVER_PCT))
    except (TypeError, ValueError):
        fee_pct = FEE_COVER_PCT
    fee = entry * fee_pct
    if side == "SHORT":
        return round(entry - tick - fee, 2)
    if side == "LONG":
        return round(entry + tick + fee, 2)
    return 0.0


def _zone_trail_atr(*, side: str, price: float, entry: float, atr: float,
                    profile: Dict[str, Any], coeff: float,
                    tp1_px: float = 0.0, tp2_px: float = 0.0,
                    tp3_px: float = 0.0) -> Tuple[float, str]:
    """按价格相对 TP 进度返回呼吸空间（×ATR）与区名。tp3_px<=0 时用 ATR 倍数估 TP3 参考位。"""
    side_u = str(side or "").upper()
    b12 = float(profile.get("breath_tp12") or 1.2)
    b23 = float(profile.get("breath_tp23") or 1.6)
    tp1_a = float(profile.get("tp1_atr") or TP1_ATR)
    tp2_a = float(profile.get("tp2_atr") or TP2_ATR)
    confirm_atr = float(
        profile.get("tp3_confirm_atr")
        if profile.get("tp3_confirm_atr") is not None
        else TP3_CONFIRM_ATR
    )

    if side_u == "LONG":
        tp3_ref = tp3_px if tp3_px > 0 else entry + (tp2_a + 1.0) * atr
        past_tp3 = price >= tp3_ref
        past_tp3_confirmed = price >= tp3_ref + confirm_atr * atr
        past_tp2 = (tp2_px > 0 and price >= tp2_px) or (
            tp2_px <= 0 and price >= entry + tp2_a * atr
        )
        past_tp1 = (tp1_px > 0 and price >= tp1_px) or (
            tp1_px <= 0 and price >= entry + tp1_a * atr
        )
    else:
        tp3_ref = tp3_px if tp3_px > 0 else entry - (tp2_a + 1.0) * atr
        past_tp3 = price <= tp3_ref
        past_tp3_confirmed = price <= tp3_ref - confirm_atr * atr
        past_tp2 = (tp2_px > 0 and price <= tp2_px) or (
            tp2_px <= 0 and price <= entry - tp2_a * atr
        )
        past_tp1 = (tp1_px > 0 and price <= tp1_px) or (
            tp1_px <= 0 and price <= entry - tp1_a * atr
        )

    if past_tp3_confirmed:
        return float(coeff), "tp3_plus"
    if past_tp3:
        return b23, "tp3_confirm"
    if past_tp2:
        return b23, "tp2_tp3"
    if past_tp1:
        return b12, "tp1_tp2"
    return b12, "pre_tp1"


def calculate_stop_long(price, entry_price, initial_atr, initial_stop, current_stop,
                        highest_price, breakeven_phase, breathing_coefficient=1.0,
                        profile=None, tp1_px=0.0, tp2_px=0.0, tp3_px=0.0):
    """多单。返回 (新止损, 新最高, 新阶段bool, step_count)。"""
    p = profile if isinstance(profile, dict) and profile else default_breath_profile()
    price = float(price or 0)
    entry_price = float(entry_price or 0)
    initial_atr = float(initial_atr or 0)
    initial_stop = float(initial_stop or 0)
    current_stop = float(current_stop or 0)
    highest_price = float(highest_price or entry_price or 0)
    coeff = float(breathing_coefficient or 1.0)
    if coeff <= 0:
        coeff = cold_start_multiplier(p)

    step_trig = float(p.get("step_trigger_atr") or 1.05)
    step_adv = float(p.get("step_advance_atr") or 0.68)

    new_highest = max(highest_price, price) if price > 0 else highest_price
    new_stop = current_stop
    step_count = 0
    if entry_price <= 0 or initial_atr <= 0 or price <= 0:
        return new_stop, new_highest, bool(breakeven_phase), step_count

    trail_mult, zone = _zone_trail_atr(
        side="LONG", price=price, entry=entry_price, atr=initial_atr,
        profile=p, coeff=coeff, tp1_px=float(tp1_px or 0),
        tp2_px=float(tp2_px or 0), tp3_px=float(tp3_px or 0),
    )
    trail_dist = trail_mult * initial_atr
    trail_floor = new_highest - trail_dist
    phase_sw = float(p.get("phase_switch_atr") or PHASE_SWITCH_ATR or 3.0)
    mfe_atr = (new_highest - entry_price) / initial_atr if initial_atr > 0 else 0.0
    new_phase = zone == "tp3_plus" or (phase_sw > 0 and mfe_atr >= phase_sw)

    step_trigger = step_trig * initial_atr
    step_count = max(0, int((price - entry_price) / step_trigger)) if step_trigger > 0 else 0
    step_stop = initial_stop + step_count * step_adv * initial_atr
    # 阶梯止损不得比当前呼吸空间(trail_floor)更紧；pre_tp1 区除外
    # （见币安 breath_stop.py v2.10 / v2.11 注释）。
    if trail_floor > 0 and zone != "pre_tp1":
        step_stop = min(step_stop, trail_floor)
    candidate = max(float(new_stop or 0), float(current_stop or 0), float(step_stop or 0))
    candidate = max(candidate, trail_floor)

    f1 = float(p.get("tp1_floor_atr") or 0.0)
    f2 = float(p.get("tp2_floor_atr") or 0.0)
    if f2 > 0 and zone in ("tp2_tp3", "tp3_confirm", "tp3_plus"):
        candidate = max(candidate, entry_price + f2 * initial_atr)
    elif f1 > 0 and zone == "tp1_tp2":
        candidate = max(candidate, entry_price + f1 * initial_atr)

    return round(float(candidate), 2), round(float(new_highest), 2), bool(new_phase), int(step_count)


def calculate_stop_short(price, entry_price, initial_atr, initial_stop, current_stop,
                         lowest_price, breakeven_phase, breathing_coefficient=1.0,
                         profile=None, tp1_px=0.0, tp2_px=0.0, tp3_px=0.0):
    """空单对称。返回 (新止损, 新最低, 新阶段bool, step_count)。"""
    p = profile if isinstance(profile, dict) and profile else default_breath_profile()
    price = float(price or 0)
    entry_price = float(entry_price or 0)
    initial_atr = float(initial_atr or 0)
    initial_stop = float(initial_stop or 0)
    current_stop = float(current_stop or 0)
    lowest_price = float(lowest_price or entry_price or 0)
    coeff = float(breathing_coefficient or 1.0)
    if coeff <= 0:
        coeff = cold_start_multiplier(p)

    step_trig = float(p.get("step_trigger_atr") or 1.05)
    step_adv = float(p.get("step_advance_atr") or 0.68)

    new_lowest = min(lowest_price, price) if (lowest_price > 0 and price > 0) else (
        price if price > 0 else lowest_price
    )
    if lowest_price <= 0 and price > 0:
        new_lowest = price
    new_stop = current_stop
    step_count = 0
    if entry_price <= 0 or initial_atr <= 0 or price <= 0:
        return new_stop, new_lowest, bool(breakeven_phase), step_count

    trail_mult, zone = _zone_trail_atr(
        side="SHORT", price=price, entry=entry_price, atr=initial_atr,
        profile=p, coeff=coeff, tp1_px=float(tp1_px or 0),
        tp2_px=float(tp2_px or 0), tp3_px=float(tp3_px or 0),
    )
    trail_dist = trail_mult * initial_atr
    trail_ceil = new_lowest + trail_dist
    phase_sw = float(p.get("phase_switch_atr") or PHASE_SWITCH_ATR or 3.0)
    mfe_atr = (entry_price - new_lowest) / initial_atr if initial_atr > 0 else 0.0
    new_phase = zone == "tp3_plus" or (phase_sw > 0 and mfe_atr >= phase_sw)

    step_trigger = step_trig * initial_atr
    step_count = max(0, int((entry_price - price) / step_trigger)) if step_trigger > 0 else 0
    step_stop = initial_stop - step_count * step_adv * initial_atr
    if trail_ceil > 0 and zone != "pre_tp1":
        step_stop = max(step_stop, trail_ceil)
    refs = [x for x in (current_stop, new_stop, step_stop) if x > 0]
    candidate = min(refs) if refs else step_stop
    if candidate <= 0:
        candidate = trail_ceil
    else:
        candidate = min(candidate, trail_ceil)

    f1 = float(p.get("tp1_floor_atr") or 0.0)
    f2 = float(p.get("tp2_floor_atr") or 0.0)
    if f2 > 0 and zone in ("tp2_tp3", "tp3_confirm", "tp3_plus"):
        floor = entry_price - f2 * initial_atr
        candidate = min(candidate, floor) if candidate > 0 else floor
    elif f1 > 0 and zone == "tp1_tp2":
        floor = entry_price - f1 * initial_atr
        candidate = min(candidate, floor) if candidate > 0 else floor

    return round(float(candidate), 2), round(float(new_lowest), 2), bool(new_phase), int(step_count)


def calculate_breath_stop(side, price, entry_price, initial_atr, initial_stop,
                          current_stop, best_price, breakeven_phase,
                          breathing_coefficient=1.0, profile=None,
                          tp1_px=0.0, tp2_px=0.0, tp3_px=0.0, **_kw):
    """
    统一入口。best_price = 多单 highest / 空单 lowest。
    返回 dict: stop, best, breakeven_phase, meta。
    """
    p = profile if isinstance(profile, dict) and profile else default_breath_profile()
    side = str(side or "").strip().upper()
    atr = float(initial_atr or 0)
    entry = float(entry_price or 0)
    px = float(price or 0)
    coeff = float(breathing_coefficient or 1.0)
    if coeff <= 0:
        coeff = cold_start_multiplier(p)
    trail_mult, zone = _zone_trail_atr(
        side=side, price=px, entry=entry, atr=atr, profile=p, coeff=coeff,
        tp1_px=float(tp1_px or 0), tp2_px=float(tp2_px or 0), tp3_px=float(tp3_px or 0),
    )
    meta = {
        "trail_atr": trail_mult,
        "breathing_coefficient": coeff,
        "profile": p.get("name") or "ETH",
        "zone": zone,
        "phase": "trail" if zone == "tp3_plus" else "ladder",
        "step_count": 0,
    }
    if side == "SHORT":
        stop, best, phase, step_count = calculate_stop_short(
            px, entry, atr, initial_stop, current_stop, best_price,
            breakeven_phase, breathing_coefficient=coeff, profile=p,
            tp1_px=tp1_px, tp2_px=tp2_px, tp3_px=tp3_px,
        )
    else:
        stop, best, phase, step_count = calculate_stop_long(
            px, entry, atr, initial_stop, current_stop, best_price,
            breakeven_phase, breathing_coefficient=coeff, profile=p,
            tp1_px=tp1_px, tp2_px=tp2_px, tp3_px=tp3_px,
        )
    meta["step_count"] = int(step_count)
    meta["phase"] = "trail" if phase else "ladder"
    meta["trail_distance"] = round(atr * trail_mult, 4) if atr > 0 else 0.0
    return {"stop": stop, "best": best, "breakeven_phase": phase, "meta": meta}


# ==================== 有状态雷达外壳（激活逻辑不变） ====================

@dataclass
class RadarState:
    activated: bool = False
    current_sl: float = 0.0
    entry_price: float = 0.0
    tp1_price: float = 0.0
    tp2_price: float = 0.0
    direction: str = "LONG"
    tier: str = "1"
    phase: str = "idle"  # idle / trail / dynamic
    last_update: float = 0.0
    reentry_count: int = 0
    # 2026-08-29 换代新增
    best_price: float = 0.0     # 多单 highest / 空单 lowest
    initial_stop: float = 0.0   # 激活时的保本起步位
    initial_atr: float = 0.0    # 激活时锁定的 ATR（对齐币安 LockedInitialAtr）


class BreathStop:
    """雷达呼吸止损引擎"""

    def __init__(self, symbol: str = "ETH"):
        self.symbol = str(symbol).upper()
        self._lock = threading.Lock()
        self._state = RadarState()
        self._atr: float = 0.0

    def reset(self):
        with self._lock:
            self._state = RadarState()

    def set_atr(self, atr: float):
        with self._lock:
            self._atr = float(atr or 0)

    def arm(self, tp1_price: float, tp2_price: float, direction: str = "LONG"):
        """开仓后立即调用，记下 TP1/TP2 与方向，供 should_activate 算激活线。"""
        with self._lock:
            self._state.tp1_price = float(tp1_price or 0)
            self._state.tp2_price = float(tp2_price or 0)
            self._state.direction = str(direction or "LONG").upper()

    def _activation_gate_price(self) -> float:
        """激活线：首次开仓=(TP1+TP2)/2 中点，重入开仓(reentry_count>=1)=TP2。"""
        tp1 = self._state.tp1_price
        tp2 = self._state.tp2_price
        if self._state.reentry_count >= 1:
            return tp2
        if tp1 > 0 and tp2 > 0:
            return (tp1 + tp2) / 2.0
        return tp2  # TP1 缺失时退化为 TP2

    def activate(self, entry_price: float, tp2_price: float,
                 tier: str = "1", direction: str = "LONG",
                 profile: Optional[Dict[str, Any]] = None):
        """激活雷达。保本起步位 = entry ± tick ± entry×fee_cover_pct（走币安 initial_stop_price）。"""
        with self._lock:
            if self._state.activated:
                return
            p = profile if isinstance(profile, dict) and profile else BREATH_ETH
            self._state.activated = True
            self._state.entry_price = float(entry_price)
            self._state.tp2_price = float(tp2_price)
            self._state.tier = str(tier)
            self._state.direction = str(direction).upper()
            self._state.phase = "trail"  # 币安模型无独立 breakeven 阶段：激活即进入阶梯/分区
            self._state.initial_atr = float(self._atr or 0)
            self._state.best_price = float(entry_price)
            sl = initial_stop_price(self._state.direction, entry_price, profile=p)
            self._state.initial_stop = round(float(sl), 2)
            self._state.current_sl = round(float(sl), 2)
            self._state.last_update = time.time()

    def check_activation(self, current_price: float) -> bool:
        with self._lock:
            if self._state.activated:
                return True
            if not self._state.tp2_price or self._state.tp2_price <= 0:
                return False
            tp2 = self._state.tp2_price
            if self._state.direction == "LONG":
                return current_price >= tp2
            return current_price <= tp2

    def should_activate(self, current_price: float) -> Tuple[bool, str]:
        """纯价格判断，不要求 TP 实际成交（对齐币安 v2.1）。"""
        with self._lock:
            if self._state.activated:
                return False, "already_activated"
            gate = self._activation_gate_price()
            if not gate or gate <= 0:
                return False, "no_activation_gate_price"
            if self._state.direction == "LONG":
                if current_price >= gate:
                    return True, f"price_reached_gate({gate:.2f})"
            else:
                if current_price <= gate:
                    return True, f"price_reached_gate({gate:.2f})"
            return False, "price_not_there"

    def update(self, current_price: float,
               profile: Optional[Dict[str, Any]] = None,
               tp1_px: float = 0.0, tp2_px: float = 0.0,
               tp3_px: float = 0.0) -> Optional[float]:
        """
        推进雷达止损（币安 v2.1 价格分区模型）。只在止损实际向盈利方向移动时返回新值。

        Args:
            current_price: 当前价
            profile: 呼吸参数 dict（breath_profiles.get_breath_profile 的返回值）
            tp1_px / tp2_px / tp3_px: TV 下发的 TP 价；缺失(<=0)时按 ATR 倍数估算
        """
        with self._lock:
            st = self._state
            if not st.activated:
                return None
            price = float(current_price or 0)
            if price <= 0:
                return None
            p = profile if isinstance(profile, dict) and profile else default_breath_profile()
            atr = float(st.initial_atr or self._atr or 0)
            if atr <= 0 or st.entry_price <= 0:
                return None
            side = st.direction

            if side == "LONG":
                best = max(float(st.best_price or st.entry_price), price)
            else:
                b = float(st.best_price or st.entry_price)
                best = min(b, price) if b > 0 else price

            res = calculate_breath_stop(
                side=side, price=price, entry_price=st.entry_price,
                initial_atr=atr, initial_stop=st.initial_stop,
                current_stop=st.current_sl, best_price=best,
                breakeven_phase=(st.phase == "dynamic"), profile=p,
                tp1_px=float(tp1_px or 0), tp2_px=float(tp2_px or 0),
                tp3_px=float(tp3_px or 0),
            )
            new_sl = float(res.get("stop") or 0)
            st.best_price = float(res.get("best") or best)
            st.phase = "dynamic" if res.get("breakeven_phase") else "trail"

            if new_sl <= 0:
                return None
            cur = float(st.current_sl or 0)
            # 只进不退
            if side == "LONG" and new_sl <= cur:
                return None
            if side == "SHORT" and cur > 0 and new_sl >= cur:
                return None
            if abs(new_sl - cur) < 1e-9:
                return None
            st.current_sl = new_sl
            st.last_update = time.time()
            return new_sl

    def get_state(self) -> RadarState:
        with self._lock:
            return RadarState(
                activated=self._state.activated,
                current_sl=self._state.current_sl,
                entry_price=self._state.entry_price,
                tp1_price=self._state.tp1_price,
                tp2_price=self._state.tp2_price,
                direction=self._state.direction,
                tier=self._state.tier,
                phase=self._state.phase,
                last_update=self._state.last_update,
                reentry_count=self._state.reentry_count,
                best_price=self._state.best_price,
                initial_stop=self._state.initial_stop,
                initial_atr=self._state.initial_atr,
            )

    def set_reentry_count(self, count: int):
        with self._lock:
            self._state.reentry_count = max(0, count)

    def seed_stop(self, sl: float):
        """启动恢复用：把 current_sl / initial_stop 直接锚到交易所现有止损，
        之后 update() 的只进不退守卫保证不会把线放松。"""
        with self._lock:
            s = float(sl or 0)
            if s > 0:
                self._state.current_sl = s
                self._state.initial_stop = s

    def mark_activated(self, entry_price: float, tp2_price: float,
                       direction: str = "LONG"):
        """启动恢复用：现价已过激活线时，直接把雷达置为已激活（不重算 current_sl，
        随后请紧接着 seed_stop 锚定交易所现值）。"""
        with self._lock:
            self._state.activated = True
            self._state.entry_price = float(entry_price)
            self._state.tp2_price = float(tp2_price or entry_price)
            self._state.direction = str(direction).upper()
            self._state.phase = "trail"
            self._state.initial_atr = float(self._atr or 0)
            self._state.best_price = float(entry_price)
            self._state.last_update = time.time()


# 雷达状态管理
_RADARS: Dict[str, BreathStop] = {}
_RADAR_LOCK = threading.Lock()


def get_radar(symbol: str = "ETH") -> BreathStop:
    sym = str(symbol or "ETH").upper()
    with _RADAR_LOCK:
        if sym not in _RADARS:
            _RADARS[sym] = BreathStop(sym)
        return _RADARS[sym]
