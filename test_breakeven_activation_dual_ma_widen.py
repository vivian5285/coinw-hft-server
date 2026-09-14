#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-09-14："保本激活加宽"(_dual_ma_activation_anchor +
_activate_radar里的组合逻辑)回归测试——第三版修正公式，跟币安B系统
同一批改的移植版本(同一天补的回归测试，此前这份文件一直停留在更早的
"现价±0.5×ATR"版本，跟代码实际已经改成的gate_dist版本早已脱节——这次
一并补齐)。

背景见position_supervisor_coinw.py::DUAL_MA_ACTIVATION_GATE_*常量顶部
注释：实盘复现(XPTUSDT首次发现，BNBUSDT验证第一版/第二版公式都不够
用)：同一笔TV信号币安B/CoinW同时开空，雷达激活公式(entry∓tick∓fee)
完全按entry锚定，价格才刚朝有利方向走一点点就摸到激活线，止损立刻
锁死在纯手续费保本位，随后一次很正常的回踩就把这条贴着保本的止损
打穿。

第二版("entry±0.5×gate_dist"跟纯保本取更松，独立算锚点再比较)写完后
用BNB真实数字复算才发现方向性漏洞：谁更松取决于两个不相关公式的巧
合——手续费保本缓冲通常远小于1个ATR，当gate_dist(激活线到entry的距离)
明显大于2倍手续费缓冲时，"entry±0.5×gate_dist"反而比纯保本更贴近激
活线、更紧，取更松的min/max结果又回退成纯保本，形同虚设，BNB正是
这种情形。

第三版最终修正：不再独立算锚点去比较，直接在纯保本(initial_sl)的基
础上做加减法——保本位再往回让出ACTIVATION_RETAIN_FRAC(50%)比例的
gate_dist当额外缓冲。由构造保证100%比纯保本更松，不再依赖任何巧合的
数值关系，同时依然随激活线(CoinW用(TP1+TP2)/2)的远近自适应。

不碰任何真实账户/持仓，self.client/self.pipeline全部用测试替身，
self.radar用真实BreathStop实例(验证真实的activated/current_sl状态
转换)。
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("COINW_SKIP_BOOTSTRAP", "1")

import position_supervisor_coinw as psc  # noqa: E402
from breath_stop import BreathStop  # noqa: E402

ENTRY = 1790.88
ATR = 3.0007
# 用TP1=1786.93/TP2=1790.03 → 激活线(TP1+TP2)/2=1788.48，复现XPT实盘
# "gate≈1788.4800"的真实数字。
TP1_SHORT = 1786.93
TP2_SHORT = 1790.03
ACTIVATION_PX = (TP1_SHORT + TP2_SHORT) / 2.0  # 1788.48
RETAIN_FRAC = 0.5


class _FakePipeline:
    def __init__(self, side="SHORT", entry=ENTRY, tp2_px=TP2_SHORT, hard_sl_px=1794.44):
        self.data = {
            "entry": entry,
            "side": side,
            "tier": "1",
            "position_id": "pos1",
            "tp2": {"px": tp2_px},
            "hard_sl_px": hard_sl_px,
        }


def _mk_supervisor(symbol="XPT", side="SHORT", entry=ENTRY, tp1_px=TP1_SHORT,
                    tp2_px=TP2_SHORT, hard_sl_px=1794.44):
    s = object.__new__(psc.PositionSupervisorCoinW)
    s.symbol = symbol
    s.pipeline = _FakePipeline(side=side, entry=entry, tp2_px=tp2_px, hard_sl_px=hard_sl_px)
    s.radar = BreathStop(symbol)
    s.radar.set_atr(ATR)
    # arm()先记下TP1(activate()自己的tp2_price参数后面会覆盖TP2，保持一致
    # 即可)，这样_activation_gate_price()才能算出(TP1+TP2)/2，而不是退化
    # 成纯TP2。
    s.radar.arm(tp1_price=tp1_px, tp2_price=tp2_px, direction=side)
    s.client = MagicMock()
    return s


def _breakeven(side, entry, symbol="XPT"):
    from breath_stop import initial_stop_price
    import breath_profiles
    profile = breath_profiles.get_breath_profile(symbol=symbol)
    return round(float(initial_stop_price(side, entry, profile=profile)), 2)


PURE_BREAKEVEN_SHORT = _breakeven("SHORT", ENTRY)  # 1789.44
GATE_DIST_SHORT = abs(ACTIVATION_PX - ENTRY)  # 2.4
WIDENED_SHORT = round(PURE_BREAKEVEN_SHORT + RETAIN_FRAC * GATE_DIST_SHORT, 2)  # 1790.64


class TestActivationWidenModeGate(unittest.TestCase):
    def setUp(self):
        os.environ.pop("DUAL_MA_ACTIVATION_GATE", None)
        psc.DUAL_MA_ACTIVATION_GATE_ENABLED = True

    def test_gate_off_falls_back_to_pure_breakeven(self):
        s = _mk_supervisor()
        psc.DUAL_MA_ACTIVATION_GATE_ENABLED = False
        try:
            s._activate_radar(ACTIVATION_PX)
        finally:
            psc.DUAL_MA_ACTIVATION_GATE_ENABLED = True
        self.assertAlmostEqual(s.radar.get_state().current_sl, PURE_BREAKEVEN_SHORT, places=2)


class TestActivationWidenBMode(unittest.TestCase):
    def test_first_open_widens_beyond_pure_breakeven(self):
        """复现XPT实盘场景：止损从纯保本1789.44在此基础上再让出
        0.5×gate_dist(2.4)=1.2，加宽到1790.64，而不是贴着保本被正常
        回踩打穿。"""
        s = _mk_supervisor()
        s._activate_radar(ACTIVATION_PX)
        self.assertTrue(s.radar.get_state().activated)
        self.assertAlmostEqual(s.radar.get_state().current_sl, WIDENED_SHORT, places=2)
        self.assertGreater(s.radar.get_state().current_sl, PURE_BREAKEVEN_SHORT)  # SHORT：更松=更高

    def test_bnb_style_large_atr_gate_still_widens_beyond_breakeven(self):
        """复现BNB实盘的根本诱因：激活线离entry的距离远大于纯手续费
        保本距entry的距离——第二版公式("entry±0.5×gate_dist"独立算锚
        点再跟纯保本比较)在这种情形下会因为两个公式互不相关而巧合地
        退化成纯保本(形同虚设，10小时内两账户各复现5次)。第三版必须
        在纯保本基础上做加减法，因此不管gate_dist多大，永远比纯保本
        更松(LONG更低=更松)。"""
        entry = 722.20
        atr = 2.6766
        gate_px = entry + atr  # TP1=TP2=entry+atr，令(TP1+TP2)/2恰好等于entry+atr
        s = _mk_supervisor(symbol="BNB", side="LONG", entry=entry,
                            tp1_px=gate_px, tp2_px=gate_px, hard_sl_px=entry - 5.0)
        s.radar.set_atr(atr)

        s._activate_radar(gate_px)

        self.assertTrue(s.radar.get_state().activated)
        pure_breakeven = _breakeven("LONG", entry, symbol="BNB")
        gate_dist = abs(gate_px - entry)
        expected = round(pure_breakeven - RETAIN_FRAC * gate_dist, 2)
        self.assertAlmostEqual(s.radar.get_state().current_sl, expected, places=2)
        self.assertLess(
            s.radar.get_state().current_sl, pure_breakeven,
            "第二版公式在这种大ATR/小手续费场景下会退化成纯保本，第三版必须真的比纯保本更松(LONG更低)",
        )
        self.assertGreater(gate_px - s.radar.get_state().current_sl, atr)

    def test_reentry_not_widened_stays_pure_breakeven(self):
        s = _mk_supervisor()
        s.radar.set_reentry_count(1)
        s._activate_radar(ACTIVATION_PX)
        self.assertAlmostEqual(s.radar.get_state().current_sl, PURE_BREAKEVEN_SHORT, places=2)

    def test_invalid_gate_price_falls_back_to_pure_breakeven(self):
        """TP1/TP2都缺失(激活线取不到值) → 退回纯保本，不报错。"""
        s = _mk_supervisor(tp1_px=0.0, tp2_px=0.0)
        s._activate_radar(ACTIVATION_PX)
        self.assertAlmostEqual(s.radar.get_state().current_sl, PURE_BREAKEVEN_SHORT, places=2)

    def test_widen_never_exceeds_hard_stop_ceiling(self):
        """人为把综合硬止损设得很近，验证加宽结果不会松过硬止损。"""
        s = _mk_supervisor(hard_sl_px=1789.60)  # 比正常加宽结果(1790.64)更紧
        s._activate_radar(ACTIVATION_PX)
        self.assertAlmostEqual(s.radar.get_state().current_sl, 1789.60, places=2)

    def test_long_side_mirrors_short_logic(self):
        tp1 = ENTRY + 2.0
        tp2 = ENTRY + 2.8
        gate_px = (tp1 + tp2) / 2.0  # ENTRY+2.4，跟SHORT夹具的gate_dist对称
        s = _mk_supervisor(side="LONG", entry=ENTRY, tp1_px=tp1, tp2_px=tp2,
                            hard_sl_px=ENTRY - 5.0)

        s._activate_radar(gate_px)

        breakeven = _breakeven("LONG", ENTRY)
        gate_dist = abs(gate_px - ENTRY)
        expected = round(breakeven - RETAIN_FRAC * gate_dist, 2)
        self.assertAlmostEqual(s.radar.get_state().current_sl, expected, places=2)
        self.assertLess(s.radar.get_state().current_sl, breakeven)  # 多头加宽=更低=更松


if __name__ == "__main__":
    unittest.main(verbosity=2)
