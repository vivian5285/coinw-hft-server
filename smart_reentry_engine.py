#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能再入决策 - CoinW单系统

止损出局后（非 TV 平仓 / 非手动），若原趋势仍然成立，在有限时间窗内按
缩小仓位再进一次。参照币安「smart reentry」概念，适配 150m + 币赢 K 线。

再入闸门（全部满足才放行）：
  · reentry_count < max（默认 1）
  · 150m ADX(14) 仍 ≥ 门槛（趋势没散）
  · 原方向的唐奇安通道仍未被反向击穿，且收盘仍在通道中位数正确一侧
  · 现价已收复原进场价（多单回到 entry 之上 / 空单回到 entry 之下）
    —— 说明那根止损是甩针不是趋势反转
  · 现价没把差价追太远（|price-entry|/entry ≤ max_chase）
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

DEFAULTS = {
    "max_reentry": 1,
    "adx_period": 14,
    "adx_gate": 20.0,
    "donchian_n": 20,
    "max_chase_pct": 0.006,   # 现价相对原 entry 追价上限
    "size_factor": 0.6,       # 再入仓位 = 原档位 × 此系数
}


def _atr_unused():  # 占位，避免误引
    pass


def _adx(bars: List[list], period: int) -> float:
    if len(bars) < period * 2 + 1:
        return 0.0
    pdm, mdm, tr = [], [], []
    for i in range(1, len(bars)):
        up = bars[i][2] - bars[i - 1][2]
        dn = bars[i - 1][3] - bars[i][3]
        pdm.append(up if (up > dn and up > 0) else 0.0)
        mdm.append(dn if (dn > up and dn > 0) else 0.0)
        h, l, pc = bars[i][2], bars[i][3], bars[i - 1][4]
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))

    def w(seq):
        s = sum(seq[:period]); out = [s]
        for v in seq[period:]:
            s = s - s / period + v; out.append(s)
        return out

    a, p, m = w(tr), w(pdm), w(mdm)
    dx = []
    for x, y, z in zip(a, p, m):
        if x <= 0:
            continue
        pdi, mdi = 100 * y / x, 100 * z / x
        d = pdi + mdi
        dx.append(100 * abs(pdi - mdi) / d if d > 0 else 0.0)
    if len(dx) < period:
        return 0.0
    adx = sum(dx[:period]) / period
    for v in dx[period:]:
        adx = (adx * (period - 1) + v) / period
    return adx


def _donchian(bars: List[list], n: int) -> Tuple[float, float, float]:
    seg = bars[-1 - n:-1] if len(bars) > n else bars[:-1]
    if not seg:
        return 0.0, 0.0, 0.0
    hh = max(c[2] for c in seg)
    ll = min(c[3] for c in seg)
    return hh, ll, (hh + ll) / 2.0


def reentry_gate(bars_150m: List[list], side: str, orig_entry: float,
                 last_price: float, reentry_count: int,
                 cfg: Optional[Dict] = None) -> Tuple[bool, str]:
    """返回 (可再入, 原因)。bars_150m 需含最后一根已收盘。"""
    c = dict(DEFAULTS)
    if cfg:
        c.update(cfg)
    side = str(side or "").upper()
    if reentry_count >= c["max_reentry"]:
        return False, "reentry_count_max"
    if not bars_150m or len(bars_150m) < max(c["donchian_n"], c["adx_period"] * 2) + 3:
        return False, "not_enough_bars"
    if orig_entry <= 0 or last_price <= 0:
        return False, "bad_price"

    adx = _adx(bars_150m, c["adx_period"])
    if adx < c["adx_gate"]:
        return False, f"adx_gone({adx:.1f})"

    hh, ll, mid = _donchian(bars_150m, c["donchian_n"])
    close = bars_150m[-1][4]
    if side == "LONG":
        if close < ll:
            return False, "channel_broke_down"
        if close < mid:
            return False, "close_below_mid"
        if last_price < orig_entry:
            return False, "not_recovered"
    elif side == "SHORT":
        if close > hh:
            return False, "channel_broke_up"
        if close > mid:
            return False, "close_above_mid"
        if last_price > orig_entry:
            return False, "not_recovered"
    else:
        return False, "bad_side"

    if abs(last_price - orig_entry) / orig_entry > c["max_chase_pct"]:
        return False, "chased_too_far"

    return True, f"ok(adx={adx:.1f})"
