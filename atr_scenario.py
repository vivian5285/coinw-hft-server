#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
硬止损公式 - CoinW单系统 v16.22.1

唯一公式：|TV价 − stop_loss| × 1.15
锚定交易所成交价
"""

from __future__ import annotations

import os
from typing import Optional


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
