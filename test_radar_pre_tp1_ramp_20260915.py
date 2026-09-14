#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-09-15：CoinW侧两处修复的回归测试——跟币安同一批改：
1. `breathing_coefficient`死于1.0的bug修复(BreathStop.update())：
   深盈利区(tp3_plus)此前实际按死板的1.0×ATR收紧，比pre_tp1区的
   breath_tp12(2.3~2.5×ATR)还紧，完全反直觉("赚得越多雷达反而卡得越
   死")。修复后用cold_start_multiplier(profile)算出真实系数。
2. pre_tp1"起步呼吸地板"从"只在step_count==0生效的硬门槛"改成"随
   价格从entry走到TP1的进度连续收窄的坡道"——见breath_stop.py同日期
   注释，跟币安test_radar_pre_tp1_ramp_20260915.py同一套用例结构。

不碰任何真实账户/持仓，纯函数级+BreathStop状态机测试。
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("COINW_SKIP_BOOTSTRAP", "1")

import breath_stop as bs  # noqa: E402
from breath_profiles import BREATH_ETH, cold_start_multiplier, trail_distance_multiplier  # noqa: E402


class TestBreathingCoefficientNoLongerHardcoded(unittest.TestCase):
    def test_tp3_plus_zone_no_longer_tighter_than_pre_tp1(self):
        """核心回归：修复前tp3_plus区(coeff死于1.0)的追踪距离(1.0×ATR)
        比pre_tp1区的breath_tp12(2.31×ATR，BREATH_ETH)更紧，完全反直觉。
        修复后用cold_start_multiplier算出真实系数，tp3_plus区距离应该
        明显超过pre_tp1区。"""
        radar = bs.BreathStop("ETH")
        radar.set_atr(10.0)
        entry = 1000.0
        radar.arm(tp1_price=entry + 13.5, tp2_price=entry + 25.0, direction="LONG")
        radar.activate(entry_price=entry, tp2_price=entry + 25.0, tier="1",
                        direction="LONG", profile=BREATH_ETH)

        # 推进到远超TP3的深盈利区(entry+2.5+1.0+1.0=+45)，触发tp3_plus+confirm
        radar.update(current_price=entry + 46.0, profile=BREATH_ETH,
                     tp1_px=entry + 13.5, tp2_px=entry + 25.0, tp3_px=entry + 35.0)
        state = radar.get_state()
        tp3_plus_room = state.best_price - state.current_sl

        pre_tp1_trail_dist = float(BREATH_ETH["breath_tp12"]) * 10.0  # =23.1

        self.assertGreater(
            tp3_plus_room, pre_tp1_trail_dist,
            f"修复后深盈利区(tp3_plus)的追踪空间({tp3_plus_room:.2f})应该"
            f"明显超过pre_tp1区标称宽度({pre_tp1_trail_dist:.2f})，不能再"
            f"比刚武装时还紧",
        )
        # 系数本身应该落在min_mult~max_mult插值区间内(BREATH_ETH: 4.0~5.6)，
        # 不再是死板的1.0
        expected_coeff = cold_start_multiplier(BREATH_ETH)
        self.assertGreaterEqual(expected_coeff, float(BREATH_ETH["min_mult"]) - 0.01)


class TestPreTp1RampReplacesCliff(unittest.TestCase):
    def test_armed_at_gate_gets_hard_stop_level_room_not_breakeven(self):
        """复现BNB实盘诱因(跟币安同一套数字)：武装那一刻(progress很小)，
        坡道应该给到接近硬止损距离的空间，而不是立刻收紧到阶梯第一档。"""
        entry = 722.20
        atr = 2.6766
        initial_stop = 722.79
        gate = entry + 1.0 * atr
        tp1 = entry + 1.5 * atr
        tv_stop_dist = 2.5 * atr

        new_stop, new_highest, _, step_count = bs.calculate_stop_long(
            price=gate, entry_price=entry, initial_atr=atr,
            initial_stop=initial_stop, current_stop=initial_stop,
            highest_price=gate, breakeven_phase=False,
            breathing_coefficient=2.0, profile=BREATH_ETH,
            tp1_px=tp1, tp2_px=entry + 2.5 * atr, tp3_px=entry + 3.6 * atr,
            prev_step_count=0, tv_stop_dist=tv_stop_dist,
        )

        room_from_gate = gate - new_stop
        self.assertGreater(
            room_from_gate, 1.0 * atr,
            f"坡道修复后，武装瞬间离激活线的空间({room_from_gate:.4f})应该"
            f"明显超过1×ATR",
        )
        self.assertGreaterEqual(new_stop, entry - tv_stop_dist - 0.01)

    def test_hard_stop_tighter_than_trail_dist_collapses_to_hard_stop_constant(self):
        """trail_dist>tv_stop_dist时坡道退化成tv_stop_dist常数，不会比
        硬止损本身还松(镜像币安同名用例)。"""
        entry = 1034.14
        atr = 6.5211937475
        initial_stop = 1034.98
        best = 1038.5
        tp1 = 1039.1211937475
        tv_stop_dist = 6.52
        profile = dict(BREATH_ETH)
        profile["breath_tp12"] = 7.90 / atr  # 复刻GSUSDT当晚trail_dist=7.90

        new_stop, _, _, step_count = bs.calculate_stop_long(
            price=best, entry_price=entry, initial_atr=atr,
            initial_stop=initial_stop, current_stop=initial_stop,
            highest_price=best, breakeven_phase=False,
            breathing_coefficient=2.2130, profile=profile,
            tp1_px=tp1, tp2_px=1044.3381487456, tp3_px=1049.5551037436,
            prev_step_count=0, tv_stop_dist=tv_stop_dist,
        )
        self.assertAlmostEqual(new_stop, entry - tv_stop_dist, places=2)

    def test_short_side_mirrors_long(self):
        entry = 1000.0
        atr = 10.0
        initial_stop = 999.19
        gate = entry - 1.0 * atr
        tp1 = entry - 1.5 * atr
        tv_stop_dist = 2.5 * atr

        new_stop, _, _, _ = bs.calculate_stop_short(
            price=gate, entry_price=entry, initial_atr=atr,
            initial_stop=initial_stop, current_stop=initial_stop,
            lowest_price=gate, breakeven_phase=False,
            breathing_coefficient=2.0, profile=BREATH_ETH,
            tp1_px=tp1, tp2_px=entry - 2.5 * atr, tp3_px=entry - 3.6 * atr,
            prev_step_count=0, tv_stop_dist=tv_stop_dist,
        )
        room_from_gate = new_stop - gate
        self.assertGreater(room_from_gate, 1.0 * atr)
        self.assertLessEqual(new_stop, entry + tv_stop_dist + 0.01)


class TestSetReentryCountNoLongerDead(unittest.TestCase):
    def test_reentry_open_arms_with_tp2_gate_not_midpoint(self):
        """A3回归：重入开仓应该激活线=TP2(更远、更保守)，不再是首次开仓
        的(TP1+TP2)/2中点。"""
        radar = bs.BreathStop("ETH")
        radar.arm(tp1_price=1010.0, tp2_price=1020.0, direction="LONG")
        radar.set_reentry_count(1)
        gate = radar._activation_gate_price()
        self.assertAlmostEqual(gate, 1020.0, places=2, msg="重入应该用TP2当激活线，不是中点1015.0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
