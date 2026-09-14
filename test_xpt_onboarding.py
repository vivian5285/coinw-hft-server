#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-09-13：CoinW新增XPT(铂金)品种上线回归测试——跟币安B系统同批上线，
45分钟周期，跟XPD同族贵金属。

验证：
  1) symbol_config.ACTIVE_SYMBOLS/SYMBOL_MAP/等辅助表都登记了XPT。
  2) webhook_parser能正确把TV的"XPTUSDT.P"归一化成"XPT"并判定为合法品种。
  3) breath_profiles能查到XPT的呼吸档，且不是回退到ETH默认档。
  4) reentry_profiles显式登记了XPT的再入窗口。
  5) WEEKEND_PAUSE_SYMBOLS默认清单包含XPT(机制本身仍默认关闭，不影响
     实际开仓，只是名单一致性)。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import symbol_config  # noqa: E402
import breath_profiles  # noqa: E402


class TestXptSymbolConfig(unittest.TestCase):
    def test_active_symbols(self):
        # 2026-09-15暂停(注释形式，非删除)：宝贝拍板只精细化做BNB/XPD/
        # SNDK/OPENAI/XAU这5个，见symbol_config.py同日期注释。
        self.assertNotIn("XPT", symbol_config.ACTIVE_SYMBOLS)

    def test_symbol_map(self):
        self.assertEqual(symbol_config.SymbolConfig.get_symbol("XPTUSDT"), "XPT")

    def test_min_notional_present(self):
        self.assertIn("XPT", symbol_config.SymbolConfig.MIN_NOTIONAL)

    def test_is_valid_symbol(self):
        self.assertTrue(symbol_config.SymbolConfig.is_valid_symbol("XPTUSDT"))


class TestXptWebhookParsing(unittest.TestCase):
    def test_normalize_and_valid(self):
        from webhook_parser import WebhookParser, VALID_SYMBOLS
        # 2026-09-15暂停：VALID_SYMBOLS=set(ACTIVE_SYMBOLS)，见
        # symbol_config.py同日期注释；归一化本身不受影响。
        self.assertNotIn("XPT", VALID_SYMBOLS)
        p = WebhookParser()
        self.assertEqual(p._normalize_symbol("XPTUSDT.P"), "XPT")
        self.assertEqual(p._normalize_symbol("XPT"), "XPT")


class TestXptBreathProfile(unittest.TestCase):
    def test_profile_registered_not_eth_fallback(self):
        profile = breath_profiles.get_breath_profile("XPT")
        self.assertEqual(profile["name"], "XPT")
        self.assertNotEqual(profile, breath_profiles.get_breath_profile("__UNKNOWN__"))

    def test_profile_matches_binance_side_numbers(self):
        """跟币安eth-webhook-server侧的BREATH_XPT应该是同一份校准结果
        (同一批真实K线数据算出来的，理应完全一致)。"""
        profile = breath_profiles.get_breath_profile("XPT")
        self.assertEqual(profile["breath_tp12"], 2.71)
        self.assertEqual(profile["breath_tp23"], 3.91)
        self.assertEqual(profile["max_mult"], 6.0)
        self.assertEqual(profile["min_mult"], 4.7)

    def test_get_tier_params_compat_shim(self):
        profile = breath_profiles.get_breath_profile("XPT")
        self.assertEqual(profile.get_tier_params("2"), profile)


class TestXptReentryAndWeekendPause(unittest.TestCase):
    def test_reentry_window_registered(self):
        from reentry_profiles import ReentryProfile
        rp = ReentryProfile("XPT")
        self.assertEqual(rp.get_reentry_window("XPT"), 2)

    def test_weekend_pause_default_list(self):
        """不直接import position_supervisor_coinw.py(见项目规矩：不import
        position_supervisor_*，只做只读/静态检查)，改用源码文本核对默认值。"""
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "position_supervisor_coinw.py")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        self.assertIn('os.getenv("WEEKEND_PAUSE_SYMBOLS", "OPENAI,XPD,SNDK,XPT")', src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
