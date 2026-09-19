#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-09-19：breath_profiles.py焦点品种周期重新校准的回归测试。

背景：宝贝核对TV警报截图反馈BNB/XPD/SNDK/OPENAI/XAU的真实TV周期已经
从2026-09-12/13那批校准值(45/45/75/45分钟)变成了65/49/91/65/50分钟，
配合position_supervisor_coinw.py::DUAL_MA_EXIT_INTERVAL_MIN同一天的
周期校正，breath_profiles.py里对应的呼吸系数(ATR回调分布校准出来的
trail倍数)也必须用真实新周期重新测，不能只改K线拉取周期不改雷达系数。

排查中还发现一个既存缺口(不是本次改动引入的)：XAU此前压根没有自己的
BREATH_XAU、_BY_SYMBOL里没登记，一直静默回退用BREATH_ETH——这次一并
补上专属档。

不碰任何真实账户/持仓，纯读breath_profiles.py模块常量。
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("COINW_SKIP_BOOTSTRAP", "1")

import breath_profiles as bp  # noqa: E402


class TestXauHasDedicatedProfile(unittest.TestCase):
    def test_xau_no_longer_falls_back_to_eth(self):
        """核心回归：XAU此前静默回退ETH，现在必须返回自己的专属档。"""
        xau = bp.get_breath_profile("XAU")
        eth = bp.get_breath_profile("ETH")
        self.assertNotEqual(xau["breath_tp12"], eth["breath_tp12"])
        self.assertEqual(xau["name"], "XAU")

    def test_xau_matches_binance_b_system_calibration(self):
        """跟币安B系统同一批真实数据校准，数值应该完全一致(同一批数据
        算的)。"""
        xau = bp.get_breath_profile("XAU")
        self.assertAlmostEqual(xau["breath_tp12"], 2.69, places=2)
        self.assertAlmostEqual(xau["breath_tp23"], 3.97, places=2)
        self.assertAlmostEqual(xau["max_mult"], 6.3, places=1)
        self.assertAlmostEqual(xau["min_mult"], 4.7, places=1)


class TestFiveSymbolsRecalibratedForNewPeriods(unittest.TestCase):
    """验证BNB/XPD/SNDK/OPENAI的breath_tp12(实测中位数回调)已经更新
    成2026-09-19新周期下的实测值，不再是2026-09-12/13那批旧周期的值。"""

    def test_bnb_updated_for_65min(self):
        p = bp.get_breath_profile("BNB")
        self.assertAlmostEqual(p["breath_tp12"], 2.61, places=2)
        self.assertNotAlmostEqual(p["breath_tp12"], 2.45, places=2)

    def test_openai_updated_for_65min(self):
        p = bp.get_breath_profile("OPENAI")
        self.assertAlmostEqual(p["breath_tp12"], 2.39, places=2)
        self.assertNotAlmostEqual(p["breath_tp12"], 2.51, places=2)

    def test_xpd_updated_for_49min(self):
        p = bp.get_breath_profile("XPD")
        self.assertAlmostEqual(p["breath_tp12"], 2.40, places=2)
        self.assertNotAlmostEqual(p["breath_tp12"], 2.46, places=2)

    def test_sndk_updated_for_91min(self):
        p = bp.get_breath_profile("SNDK")
        self.assertAlmostEqual(p["breath_tp12"], 2.23, places=2)
        self.assertNotAlmostEqual(p["breath_tp12"], 2.36, places=2)

    def test_step_trigger_derivation_formula_consistent(self):
        """step_trigger_atr必须是0.375×breath_tp12(既定推算方法，不是
        脚本粗算建议里直接拿p50当step_trigger那版)——5个焦点品种逐一
        验证公式没有跑偏。"""
        for sym in ("BNB", "XPD", "SNDK", "OPENAI", "XAU"):
            p = bp.get_breath_profile(sym)
            expected_trigger = round(0.375 * p["breath_tp12"], 2)
            self.assertAlmostEqual(
                p["step_trigger_atr"], expected_trigger, places=1,
                msg=f"{sym}: step_trigger_atr应该≈0.375×breath_tp12",
            )
            expected_advance = round(0.65 * p["step_trigger_atr"], 2)
            self.assertAlmostEqual(
                p["step_advance_atr"], expected_advance, places=1,
                msg=f"{sym}: step_advance_atr应该≈0.65×step_trigger_atr",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
