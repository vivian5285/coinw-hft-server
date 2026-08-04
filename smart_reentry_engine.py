#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能再入决策引擎 - CoinW单系统 v16.22.1

再入条件：
1. 雷达扫描出微赚区间
2. ADX >= 强趋势档(>30)
3. 未超过重入次数限制
4. 价格优于上次开仓
5. TP1未成交
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple


def calc_reentry_zone(atr: float, direction: str, tier_params: dict) -> Tuple[float, float]:
    """
    计算再入微赚区间

    Returns:
        (lower, upper) 价格区间
    """
    zone_pct = tier_params.get("reentry_zone_pct", 0.5)  # 0.5% ATR
    zone = atr * zone_pct

    if direction == "LONG":
        return None, zone  # 多头：价格下跌区间
    else:
        return zone, None  # 空头：价格上涨区间


def should_reenter(
    current_price: float,
    entry_price: float,
    atr: float,
    direction: str,
    tier: str,
    tp1_filled: bool,
    reentry_count: int,
    max_reentry: int,
    tier_params: dict,
) -> Tuple[bool, str]:
    """
    决策是否再入

    Returns:
        (should_reenter, reason)
    """
    direction = str(direction).upper()

    # 1) 检查重入次数
    if reentry_count >= max_reentry:
        return False, f"max_reentry:{reentry_count}>={max_reentry}"

    # 2) TP1已成交，禁止再入
    if tp1_filled:
        return False, "tp1_filled"

    # 3) 只允许强趋势再入
    if tier not in ("2",):
        return False, f"not_strong_tier:{tier}"

    # 4) 微赚区间检查
    zone_pct = tier_params.get("reentry_zone_pct", 0.5)
    zone = atr * zone_pct

    if direction == "LONG":
        # 多头：价格必须低于上次开仓（回踩）
        if current_price >= entry_price:
            return False, f"price_not_better:{current_price}>={entry_price}"
        # 在微亏区间
        if entry_price - current_price > zone * 2:
            return False, f"not_micro_profit:{entry_price - current_price}>{zone * 2}"
    else:
        # 空头：价格必须高于上次开仓（回踩）
        if current_price <= entry_price:
            return False, f"price_not_better:{current_price}<={entry_price}"
        if current_price - entry_price > zone * 2:
            return False, f"not_micro_profit:{current_price - entry_price}>{zone * 2}"

    # 5) 检查窗口
    # (实际窗口检查在上层根据K线时间判断)

    return True, "micro_profit_zone"


def calc_reentry_price(
    current_price: float,
    entry_price: float,
    atr: float,
    direction: str,
    tier_params: dict,
) -> float:
    """
    计算再入价格（双保险）
    min(5m低+tick, TV×0.997) 多头
    max(5m高-tick, TV×1.003) 空头
    """
    direction = str(direction).upper()
    tick = 0.01

    # 基础：优于上次开仓
    if direction == "LONG":
        # 多头：略低于现价
        target = min(current_price * 0.998, entry_price * 0.997)
        target = target - tick
    else:
        target = max(current_price * 1.002, entry_price * 1.003)
        target = target + tick

    return round(target, 2)


def calc_reentry_quantity(
    original_qty: float,
    reentry_count: int,
    tier: str,
) -> float:
    """
    计算再入数量（递减）
    """
    # 再入数量不超过原始仓位的50%
    factor = max(0.3, 1.0 - reentry_count * 0.2)
    return round(original_qty * factor, 4)
