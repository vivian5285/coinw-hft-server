#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-09-12："综合硬止损"回归测试（atr_scenario.calc_smart_hard_stop_price）。

背景——宝贝拍板："不用理会tv的仓位公式...然后就是硬止损...tv的不行，太
木讷了，还是综合的硬止损比较合理，同时vps应该自己也要分辨趋势更加智慧
点，tv给方向，vps开单"。新公式：结构摆动点(fractal pivot,±3根确认) +
分档ATR保护带(K_tier按tier 0/1/2=1.5/2.5/3.5)，取更保守者，完全不读TV
的stop_loss/atr字段，ATR和摆动点都从VPS自己拉的K线独立算。

同时覆盖 defense_profiles.calc_position_size 的新固定仓位公式（本金×20%
×3倍杠杆，不再按tier缩放，tier只影响硬止损宽窄）。

只测纯函数，不碰任何真实持仓/下单/网络。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from atr_scenario import calc_smart_hard_stop_price  # noqa: E402
from defense_profiles import DefenseProfile  # noqa: E402


def _make_bars(n=80, start=100.0, step=0.5, half_range=0.5, dip_at=None, dip_depth=5.0):
    """构造一段平稳上涨的合成K线，可选在dip_at插入一个明确的摆动低点。"""
    bars = []
    t0 = 1_700_000_000_000
    period_ms = 30 * 60 * 1000
    for i in range(n):
        close = start + i * step
        o = close - step
        h = close + half_range
        l = close - half_range
        if dip_at is not None and i == dip_at:
            l = close - dip_depth
            h = close + half_range  # 高点不动，只做出一个下影插针式摆动低点
        bars.append([t0 + i * period_ms, o, h, l, close, 100.0])
    return bars


class TestSmartHardStopBasics(unittest.TestCase):
    def test_insufficient_klines_rejected(self):
        bars = _make_bars(n=10)  # 远不够 atr_period+confirm+1
        price, meta, ok, err = calc_smart_hard_stop_price("LONG", 105.0, bars, tier=1)
        self.assertFalse(ok)
        self.assertTrue(err.startswith("insufficient_klines"))

    def test_invalid_side_rejected(self):
        bars = _make_bars(n=80)
        price, meta, ok, err = calc_smart_hard_stop_price("SIDEWAYS", 139.5, bars, tier=1)
        self.assertFalse(ok)
        self.assertEqual(err, "invalid_entry_or_side")

    def test_zero_entry_price_rejected(self):
        bars = _make_bars(n=80)
        price, meta, ok, err = calc_smart_hard_stop_price("LONG", 0, bars, tier=1)
        self.assertFalse(ok)

    def test_long_stop_is_below_entry_and_uses_dip_as_structure(self):
        bars = _make_bars(n=80, dip_at=50, dip_depth=8.0)
        entry = bars[-1][4]
        price, meta, ok, err = calc_smart_hard_stop_price("LONG", entry, bars, tier=0)
        self.assertTrue(ok, err)
        self.assertLess(price, entry, "多头止损必须在成交价下方")
        self.assertTrue(meta["pivot_found"], "刻意插入的摆动低点应该被识别到")
        self.assertGreater(meta["atr"], 0)

    def test_short_stop_is_above_entry(self):
        bars = _make_bars(n=80, step=-0.5, start=200.0)  # 下降序列模拟空头场景
        entry = bars[-1][4]
        price, meta, ok, err = calc_smart_hard_stop_price("SHORT", entry, bars, tier=0)
        self.assertTrue(ok, err)
        self.assertGreater(price, entry, "空头止损必须在成交价上方")

    def test_no_pivot_falls_back_to_window_low_not_failure(self):
        """纯直线无摆动点场景：不应该整体失败，走简单窗口兜底。"""
        bars = _make_bars(n=80)  # 无dip，全程平稳上涨，摆动低点识别不到真正的局部极值
        entry = bars[-1][4]
        price, meta, ok, err = calc_smart_hard_stop_price("LONG", entry, bars, tier=1)
        self.assertTrue(ok, err)
        self.assertIsInstance(price, float)


class TestSmartHardStopTierWidens(unittest.TestCase):
    """tier越强(K_tier越大)，ATR保护带应该越宽——但取更保守者后，只要
    结构位没被ATR保护带盖过，最终止损可能不随tier变化；这里专门构造一个
    "结构位很近、ATR保护带才是决定因素"的场景来验证tier确实影响止损宽窄。
    """

    def test_higher_tier_gives_wider_atr_floor_when_structure_is_tight(self):
        # 摆动低点紧贴成交价（dip很浅），这样多头止损会被ATR保护带(K_tier)
        # 而不是结构位主导——max(struct_stop, atr_stop)，struct_stop很高
        # (离price很近)，tier越大atr_stop越低，max取更高者结构位还是会赢，
        # 除非结构位比atr_stop还低。用SHORT+浅摆动高点更容易构造让ATR主导
        # 的场景：atr_stop = entry + k*atr，k越大atr_stop越高，min()取更低
        # 者——如果struct_stop(摆动高点)比atr_stop还高，min会一直选
        # struct_stop不随tier变化；反过来如果struct_stop很低(浅摆动)，
        # min会在tier小的时候选atr_stop(离price近)，tier变大atr_stop也跟
        # 着变大，可能超过struct_stop，min转而选struct_stop——不是单调的。
        # 直接验证 atr_stop 分量本身随tier单调收紧/放宽，比验证最终hard_sl
        # 更稳（最终值还叠加了structure的max/min，不是纯ATR函数）。
        bars = _make_bars(n=80)  # 无dip：pivot大概率找不到，退化用窗口low兜底(更稳定可预测)
        entry = bars[-1][4]
        _, meta0, ok0, _ = calc_smart_hard_stop_price("LONG", entry, bars, tier=0)
        _, meta2, ok2, _ = calc_smart_hard_stop_price("LONG", entry, bars, tier=2)
        self.assertTrue(ok0 and ok2)
        self.assertGreater(
            meta0["atr_stop"], meta2["atr_stop"],
            "tier=0(K=1.5)的atr_stop应该比tier=2(K=3.5)更贴近成交价"
            "(数值更大，因为LONG的atr_stop=entry-k*atr，k越大离price越远、数值越小)",
        )
        self.assertEqual(meta0["k_tier"], 1.5)
        self.assertEqual(meta2["k_tier"], 3.5)

    def test_missing_tier_defaults_to_tightest(self):
        bars = _make_bars(n=80)
        entry = bars[-1][4]
        _, meta, ok, err = calc_smart_hard_stop_price("LONG", entry, bars, tier=None)
        self.assertTrue(ok, err)
        self.assertEqual(meta["k_tier"], 1.5, "tier缺失应该按最紧档(1.5)保守兜底")

    def test_invalid_tier_string_defaults_to_tightest(self):
        bars = _make_bars(n=80)
        entry = bars[-1][4]
        _, meta, ok, err = calc_smart_hard_stop_price("LONG", entry, bars, tier="not-a-tier")
        self.assertTrue(ok, err)
        self.assertEqual(meta["k_tier"], 1.5)


class TestFixedPositionSizing(unittest.TestCase):
    """defense_profiles.calc_position_size：2026-09-13起恢复按tier分档——
    弱40%/中50%/强60%(本金notional占比)，风险比例固定20%不变，只有杠杆
    按档位变化(2.0/2.5/3.0x)。"""

    def setUp(self):
        self.profile = DefenseProfile("OPENAI")

    def test_tier_scaled_notional_40_50_60_pct(self):
        balance = 1000.0
        entry = 1500.0
        expected = {0: 0.40, 1: 0.50, 2: 0.60}
        for tier, frac in expected.items():
            qty = self.profile.calc_position_size(balance, entry, tier)
            expected_qty = (balance * frac) / entry
            self.assertAlmostEqual(
                qty, expected_qty, places=8,
                msg=f"tier={tier} 应该对应本金×{frac:.0%}名义",
            )

    def test_missing_or_invalid_tier_defaults_to_strongest(self):
        """tier缺失/非法 → 按最强档(60%)兜底。"""
        balance = 1000.0
        entry = 1500.0
        expected_qty = (balance * 0.60) / entry
        for tier in (None, "garbage"):
            qty = self.profile.calc_position_size(balance, entry, tier)
            self.assertAlmostEqual(qty, expected_qty, places=8, msg=f"tier={tier!r}")

    def test_zero_entry_price_returns_zero(self):
        self.assertEqual(self.profile.calc_position_size(1000.0, 0), 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
