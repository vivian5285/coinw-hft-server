#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-09-20新增：雷达首次开仓激活线公式的回归测试(本周问题总结item8
"Coinw的雷达激活比币安晚，已经到了tp2止盈位还没激活雷达锁住利润")。

背景：CoinW的_activation_gate_price()此前首次开仓用(TP1+TP2)/2中点当
激活线——比币安B系统自己的公式(entry沿盈利方向推进min(0.8×TP1距离,
ATR_MULT×ATR)的更近者，见radar_reentry_mixin.py::radar_gate_price_
from_tps)晚得多，直接对应宝贝的实盘反馈。这里对齐核心两条腿(TP1进度
腿+ATR腿，取min)，不移植mega_strong和per-symbol收益率腿这两个更细的
refinement(CoinW没有对应基础设施，且现在5个焦点品种在币安那边也都没
配置收益率腿)。重入开仓(reentry_count>=1)=TP2不变。

不碰任何真实账户/持仓，纯测试BreathStop这个类本身的纯逻辑。
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("COINW_SKIP_BOOTSTRAP", "1")

from breath_stop import BreathStop, RADAR_GATE_TP1_PROGRESS, RADAR_GATE_ATR_MULT_BY_TIER  # noqa: E402


class TestActivationGateTP1AtrDualTrigger(unittest.TestCase):
    def test_long_tp1_leg_wins_when_closer(self):
        """entry=100, TP1=110(距10), ATR=2, tier=1(1.8x)：TP1腿=0.8×10=8，
        ATR腿=1.8×2=3.6，ATR腿更近，应该取ATR腿→gate=101.6。"""
        r = BreathStop("BNB")
        r.set_atr(2.0)
        r.arm(tp1_price=110.0, tp2_price=120.0, direction="LONG",
              entry_price=100.0, tier="1")
        gate = r._activation_gate_price()
        self.assertAlmostEqual(gate, 100.0 + 1.8 * 2.0, places=4)

    def test_long_atr_leg_wins_when_tp1_far(self):
        """entry=100, TP1=200(距100，TP1腿=80)，ATR=2(ATR腿=3.6)：ATR腿
        更近，取ATR腿。"""
        r = BreathStop("XAU")
        r.set_atr(2.0)
        r.arm(tp1_price=200.0, tp2_price=210.0, direction="LONG",
              entry_price=100.0, tier="1")
        gate = r._activation_gate_price()
        self.assertAlmostEqual(gate, 100.0 + 1.8 * 2.0, places=4)

    def test_short_mirrors_long(self):
        r = BreathStop("XPD")
        r.set_atr(2.0)
        r.arm(tp1_price=90.0, tp2_price=80.0, direction="SHORT",
              entry_price=100.0, tier="1")
        gate = r._activation_gate_price()
        # TP1腿=0.8×10=8, ATR腿=1.8×2=3.6 → ATR腿更近
        self.assertAlmostEqual(gate, 100.0 - 1.8 * 2.0, places=4)

    def test_earlier_than_old_midpoint_formula(self):
        """核心回归：新公式算出的激活线必须比旧的(TP1+TP2)/2中点更早
        (更接近entry)——这是item8要解决的问题本身。"""
        entry, tp1, tp2, atr = 100.0, 108.0, 115.0, 2.0
        r = BreathStop("OPENAI")
        r.set_atr(atr)
        r.arm(tp1_price=tp1, tp2_price=tp2, direction="LONG",
              entry_price=entry, tier="1")
        new_gate = r._activation_gate_price()
        old_midpoint = (tp1 + tp2) / 2.0
        self.assertLess(new_gate, old_midpoint, "新激活线必须比旧中点更早(更接近entry)")
        self.assertGreater(new_gate, entry, "激活线仍然要在entry盈利方向那一侧")

    def test_tier_affects_atr_leg(self):
        """强趋势档(tier=2,2.5x)ATR腿应该比弱档(tier=0,1.5x)更宽——TP1
        设得足够远，让ATR腿在两种tier下都是min()的胜出者，才能纯粹隔离
        观察tier的影响。"""
        entry, tp1, atr = 100.0, 300.0, 2.0  # TP1腿=0.8×200=160，远大于任何ATR腿
        gates = {}
        for tier in ("0", "1", "2"):
            r = BreathStop("SNDK")
            r.set_atr(atr)
            r.arm(tp1_price=tp1, tp2_price=tp1 + 10, direction="LONG",
                  entry_price=entry, tier=tier)
            gates[tier] = r._activation_gate_price()
        self.assertLess(gates["0"], gates["1"])
        self.assertLess(gates["1"], gates["2"])
        self.assertAlmostEqual(gates["2"] - entry, RADAR_GATE_ATR_MULT_BY_TIER["2"] * atr, places=4)

    def test_reentry_gate_unchanged_still_tp2(self):
        """重入开仓(reentry_count>=1)激活线=TP2，这条两边本来就一致，
        新公式不该动它。"""
        r = BreathStop("XAU")
        r.set_atr(2.0)
        r.arm(tp1_price=110.0, tp2_price=120.0, direction="LONG",
              entry_price=100.0, tier="1")
        r.set_reentry_count(1)
        gate = r._activation_gate_price()
        self.assertAlmostEqual(gate, 120.0, places=4)

    def test_missing_entry_degrades_to_old_midpoint(self):
        """旧调用方没传entry_price(比如某个我没找全的调用点)——优雅退化
        回旧的(TP1+TP2)/2中点，不能返回0让雷达永远激活不了。"""
        r = BreathStop("BNB")
        r.set_atr(2.0)
        r.arm(tp1_price=110.0, tp2_price=120.0, direction="LONG")  # 不传entry_price
        gate = r._activation_gate_price()
        self.assertAlmostEqual(gate, 115.0, places=4)  # (110+120)/2

    def test_missing_atr_still_uses_tp1_leg(self):
        """ATR未通过set_atr()配置(=0)——ATR腿视为inf，只用TP1腿，不应该
        退化成中点(entry/TP1都有效时不该放弃新公式)。"""
        r = BreathStop("XPD")
        r.arm(tp1_price=110.0, tp2_price=120.0, direction="LONG",
              entry_price=100.0, tier="1")
        gate = r._activation_gate_price()
        self.assertAlmostEqual(gate, 100.0 + RADAR_GATE_TP1_PROGRESS * 10.0, places=4)

    def test_tp1_wrong_direction_falls_back_to_atr_leg_only(self):
        """TP1本身方向不对(比如滑点/陈旧价位导致LONG的TP1反而低于entry)
        ——TP1腿失效，只信ATR腿，不能用一个指向错误方向的TP1硬凑距离。"""
        r = BreathStop("BNB")
        r.set_atr(2.0)
        r.arm(tp1_price=95.0, tp2_price=120.0, direction="LONG",  # TP1<entry，方向不对
              entry_price=100.0, tier="1")
        gate = r._activation_gate_price()
        self.assertAlmostEqual(gate, 100.0 + 1.8 * 2.0, places=4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
