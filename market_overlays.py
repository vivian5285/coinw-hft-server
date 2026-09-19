#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
市场结构叠加层 - CoinW单系统

- climax_check      : 进场前的高潮插针否决 + 过度延伸告警（参照币安：climax 拒单、
                      overextension 仅告警）
- reversal_candle   : 持仓中的高周期(4h)逆向放量反转K线 -> 触发反转锁利(收保本)

全纯 Python，无 numpy。K 线格式 [ts, o, h, l, c, v]，最后一根允许未收盘。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple


def _atr(bars: List[list], n: int = 14) -> float:
    if len(bars) < n + 1:
        return 0.0
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i][2], bars[i][3], bars[i - 1][4]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = sum(trs[:n]) / n
    for tr in trs[n:]:
        atr = (atr * (n - 1) + tr) / n
    return atr


def _ema(vals: List[float], n: int) -> float:
    if not vals:
        return 0.0
    k = 2.0 / (n + 1)
    e = vals[0]
    for v in vals[1:]:
        e = v * k + e * (1 - k)
    return e


def climax_check(bars: List[list], side: str, price: float,
                 cfg: Optional[Dict] = None) -> Tuple[bool, bool, str]:
    """
    返回 (veto, warn, detail)。
      veto=True  -> 建议拒绝这次进场（高潮插针：最近一根振幅过大且方向与进场相反）
      warn=True  -> 仅告警（过度延伸：现价离 EMA 太远）
    """
    c = {"climax_atr_mult": 3.0, "overext_atr_mult": 4.0, "ema_n": 20, "atr_n": 14}
    if cfg:
        c.update(cfg)
    if len(bars) < c["atr_n"] + 3 or price <= 0:
        return False, False, "insufficient"
    atr = _atr(bars, c["atr_n"])
    if atr <= 0:
        return False, False, "atr0"
    last = bars[-1]
    rng = last[2] - last[3]
    up_bar = last[4] >= last[1]
    side = str(side or "").upper()

    veto = False
    detail = []
    # 高潮插针：最近一根振幅 > climax_atr_mult×ATR，且这根的方向和我们要进的方向一致
    # （多单进场时出现一根暴力大阳 -> 大概率买在顶）
    if rng > c["climax_atr_mult"] * atr and (
        (side == "LONG" and up_bar) or (side == "SHORT" and not up_bar)
    ):
        veto = True
        detail.append(f"climax_range={rng/atr:.1f}xATR")

    # 过度延伸：现价离 EMA(ema_n) 超过 overext_atr_mult×ATR（仅告警）
    closes = [b[4] for b in bars[-(c["ema_n"] * 3):]]
    ema = _ema(closes, c["ema_n"])
    warn = False
    if ema > 0 and abs(price - ema) > c["overext_atr_mult"] * atr:
        warn = True
        detail.append(f"overext={abs(price-ema)/atr:.1f}xATR")

    return veto, warn, " ".join(detail) or "ok"


def reversal_candle(bars_4h: List[list], side: str,
                    cfg: Optional[Dict] = None) -> Tuple[bool, str]:
    """
    最后一根【已收盘】4h 是否为逆向放量反转K线：
      多单 -> 大阴线（实体/振幅比 body_ratio ≥ 门槛）且成交量 > vol_mult×近20根均量
      空单 -> 对称大阳线
    返回 (hit, detail)。调用方自己保证只在新 4h 收盘后调用一次。

    2026-09-15对齐币安：决定性K线判据从"实体/ATR"改成"实体/振幅"
    (body_ratio=abs(c-o)/max(h-l,1e-9))——这正是本仓库自己的IMPULSE_EXIT
    (_maybe_fast_lock_on_impulse_candle)已经在用的同一种判据形状，只是
    这里应用在4H周期而不是TV周期K线上。此前CoinW单独用"实体/ATR"、
    币安用"实体/振幅"，两套独立公式、非巧合数值偏差；两边这次统一到
    同一种形状+币安当天事故复盘校准过的常量(0.55/1.15)。
    """
    c = {"body_ratio": 0.55, "vol_mult": 1.15, "atr_n": 14, "vol_n": 20}
    if cfg:
        c.update(cfg)
    if len(bars_4h) < max(c["atr_n"], c["vol_n"]) + 3:
        return False, "insufficient"
    b = bars_4h[-2] if len(bars_4h) >= 2 else bars_4h[-1]  # 最后一根已收盘
    body = abs(b[4] - b[1])
    rng = max(b[2] - b[3], 1e-9)
    vols = [x[5] for x in bars_4h[-1 - c["vol_n"]:-1]]
    avg_v = sum(vols) / len(vols) if vols else 0.0
    bearish = b[4] < b[1]
    side = str(side or "").upper()

    body_ratio = body / rng
    big = body_ratio >= c["body_ratio"]
    heavy = avg_v > 0 and b[5] > c["vol_mult"] * avg_v
    if side == "LONG" and bearish and big and heavy:
        return True, f"bear_body_ratio={body_ratio:.2f} vol={b[5]/avg_v:.1f}x"
    if side == "SHORT" and (not bearish) and big and heavy:
        return True, f"bull_body_ratio={body_ratio:.2f} vol={b[5]/avg_v:.1f}x"
    return False, "no"
