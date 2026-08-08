#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
雷达呼吸止损 - CoinW单系统 v16.22.1

两阶段雷达：
1. 保本起步 -> 阶梯跟随 -> 动态追踪
激活条件（对齐币安单系统v2.1规格，2026-08-08改）：现价达到激活线即可，
不依赖TP1/TP2是否真的成交——首次开仓激活线=(TP1+TP2)/2中点，重入开仓
激活线=TP2。TP是否成交仅作为账本记录/日志核对项，不作为激活的阻塞条件
(CoinW小仓位下TP1经常因不足1张最小单位被跳过，若继续拿"TP成交"当激活
前提，雷达会永远激活不了)。
"""

from __future__ import annotations

import time
import threading
from typing import Dict, Optional, Tuple
from dataclasses import dataclass


@dataclass
class RadarState:
    activated: bool = False
    current_sl: float = 0.0
    entry_price: float = 0.0
    tp1_price: float = 0.0
    tp2_price: float = 0.0
    direction: str = "LONG"
    tier: str = "1"
    phase: str = "idle"  # idle/breakeven/trail/dynamic
    last_update: float = 0.0
    reentry_count: int = 0


class BreathStop:
    """雷达呼吸止损引擎"""

    def __init__(self, symbol: str = "ETH"):
        self.symbol = str(symbol).upper()
        self._lock = threading.Lock()
        self._state = RadarState()
        self._atr: float = 0.0

    def reset(self):
        """重置雷达"""
        with self._lock:
            self._state = RadarState()

    def set_atr(self, atr: float):
        """设置ATR"""
        with self._lock:
            self._atr = float(atr or 0)

    def arm(self, tp1_price: float, tp2_price: float, direction: str = "LONG"):
        """
        武装雷达——开仓后立即调用，记下TP1/TP2价格和方向，供should_activate
        算激活线用。注意这里不置activated=True，只是让should_activate有
        数据可用（之前的坑：should_activate要判断的tp2_price只在activate()
        里才写入，但activate()恰恰是should_activate判断为True之后才调用的，
        自己依赖自己产生的结果，永远判不出True）。
        """
        with self._lock:
            self._state.tp1_price = float(tp1_price or 0)
            self._state.tp2_price = float(tp2_price or 0)
            self._state.direction = str(direction or "LONG").upper()

    def _activation_gate_price(self) -> float:
        """激活线：首次开仓=(TP1+TP2)/2中点，重入开仓(reentry_count>=1)=TP2"""
        tp1 = self._state.tp1_price
        tp2 = self._state.tp2_price
        if self._state.reentry_count >= 1:
            return tp2
        if tp1 > 0 and tp2 > 0:
            return (tp1 + tp2) / 2.0
        return tp2  # TP1缺失时退化为TP2，不至于完全打不开

    def activate(self, entry_price: float, tp2_price: float,
                tier: str = "1", direction: str = "LONG"):
        """
        激活雷达
        激活价锚定：(TP1+TP2)/2（首次）或TP2（重入）
        """
        with self._lock:
            if self._state.activated:
                return  # 已激活不重复

            self._state.activated = True
            self._state.entry_price = float(entry_price)
            self._state.tp2_price = float(tp2_price)
            self._state.tier = str(tier)
            self._state.direction = str(direction).upper()
            self._state.phase = "breakeven"
            self._state.last_update = time.time()

            # 保本起步：entry ± tick ± fee
            tick = 0.01  # 最小价格单位
            fee_cover = self._atr * 0.0008 if self._atr > 0 else entry_price * 0.0008

            if self._state.direction == "LONG":
                self._state.current_sl = entry_price - tick - fee_cover
            else:
                self._state.current_sl = entry_price + tick + fee_cover

            self._state.current_sl = round(self._state.current_sl, 2)

    def check_activation(self, current_price: float) -> bool:
        """检查是否满足激活条件"""
        with self._lock:
            if self._state.activated:
                return True

            if not self._state.tp2_price or self._state.tp2_price <= 0:
                return False

            tp2 = self._state.tp2_price
            entry = self._state.entry_price

            if self._state.direction == "LONG":
                # 多头：现价达到TP2水平
                return current_price >= tp2
            else:
                # 空头：现价达到TP2水平
                return current_price <= tp2

    def should_activate(self, current_price: float) -> Tuple[bool, str]:
        """
        判断是否应该激活——纯价格判断，不要求TP1/TP2实际成交(对齐币安v2.1：
        "TP1是否已成交仅作为日志核对项，不作为激活的阻塞条件")。CoinW小
        仓位下TP1经常因不足1张最小单位被跳过，若还拿"TP成交"当前提，雷达
        会永远激活不了。

        Returns:
            (should_activate, reason)
        """
        with self._lock:
            if self._state.activated:
                return False, "already_activated"

            gate = self._activation_gate_price()
            if not gate or gate <= 0:
                return False, "no_activation_gate_price"

            direction = self._state.direction

            if direction == "LONG":
                if current_price >= gate:
                    return True, f"price_reached_gate({gate:.2f})"
            else:
                if current_price <= gate:
                    return True, f"price_reached_gate({gate:.2f})"

            return False, "price_not_there"

    def update(self, current_price: float, tier_params: dict) -> Optional[float]:
        """
        更新雷达止损价

        Args:
            current_price: 当前价格
            tier_params: 档位参数

        Returns:
            新止损价（如果更新了）
        """
        with self._lock:
            if not self._state.activated:
                return None

            phase = self._state.phase

            if phase == "breakeven":
                # 保本阶段：等待浮盈积累
                new_sl = self._advance_breakeven(current_price, tier_params)
                if new_sl and new_sl != self._state.current_sl:
                    self._state.current_sl = new_sl
                    self._state.last_update = time.time()
                    return new_sl

            elif phase == "trail":
                # 阶梯跟随阶段
                new_sl = self._advance_trail(current_price, tier_params)
                if new_sl and new_sl != self._state.current_sl:
                    self._state.current_sl = new_sl
                    self._state.last_update = time.time()
                    return new_sl

            elif phase == "dynamic":
                # 动态追踪阶段
                new_sl = self._advance_dynamic(current_price, tier_params)
                if new_sl and new_sl != self._state.current_sl:
                    self._state.current_sl = new_sl
                    self._state.last_update = time.time()
                    return new_sl

            return None

    def _advance_breakeven(self, current_price: float, params: dict) -> Optional[float]:
        """保本阶段推进"""
        entry = self._state.entry_price
        trail_min = params.get("trail_min", 1.5) * self._atr

        direction = self._state.direction

        if direction == "LONG":
            profit = current_price - entry
            if profit >= trail_min:
                self._state.phase = "trail"
                return round(current_price - trail_min, 2)
        else:
            profit = entry - current_price
            if profit >= trail_min:
                self._state.phase = "trail"
                return round(current_price + trail_min, 2)

        return None

    def _advance_trail(self, current_price: float, params: dict) -> Optional[float]:
        """阶梯跟随阶段"""
        step_trigger = params.get("step_trigger", 0.5) * self._atr
        step_advance = params.get("step_advance", 0.35) * self._atr
        breath = params.get("breath_12", 1.2) * self._atr

        direction = self._state.direction
        current_sl = self._state.current_sl

        if direction == "LONG":
            # 只上移
            if current_price - current_sl >= step_trigger + breath:
                new_sl = current_price - breath
                self._state.phase = self._maybe_dynamic(params)
                return round(new_sl, 2)
        else:
            # 只下移
            if current_sl - current_price >= step_trigger + breath:
                new_sl = current_price + breath
                self._state.phase = self._maybe_dynamic(params)
                return round(new_sl, 2)

        return None

    def _advance_dynamic(self, current_price: float, params: dict) -> Optional[float]:
        """动态追踪阶段"""
        trail_min = params.get("trail_min", 1.5) * self._atr
        trail_max = params.get("trail_max", 3.0) * self._atr

        direction = self._state.direction
        current_sl = self._state.current_sl

        if direction == "LONG":
            if current_price > current_sl:
                # 连续追踪
                new_sl = current_price - trail_min
                return round(min(new_sl, current_sl + trail_max), 2)
        else:
            if current_price < current_sl:
                new_sl = current_price + trail_min
                return round(max(new_sl, current_sl - trail_max), 2)

        return None

    def _maybe_dynamic(self, params: dict) -> str:
        """检查是否进入动态追踪"""
        trail_min = params.get("trail_min", 1.5) * self._atr
        entry = self._state.entry_price
        current_sl = self._state.current_sl
        direction = self._state.direction

        if direction == "LONG":
            profit = current_sl - entry
        else:
            profit = entry - current_sl

        if profit >= 3 * self._atr:
            return "dynamic"

        return "trail"

    def get_state(self) -> RadarState:
        """获取雷达状态"""
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
            )

    def set_reentry_count(self, count: int):
        """设置重入次数"""
        with self._lock:
            self._state.reentry_count = max(0, count)


# 雷达状态管理
_RADARS: Dict[str, BreathStop] = {}
_RADAR_LOCK = threading.Lock()


def get_radar(symbol: str = "ETH") -> BreathStop:
    """获取雷达"""
    sym = str(symbol or "ETH").upper()
    with _RADAR_LOCK:
        if sym not in _RADARS:
            _RADARS[sym] = BreathStop(sym)
        return _RADARS[sym]
