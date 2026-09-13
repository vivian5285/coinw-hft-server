#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-09-13：CoinW新增XRP/SOL品种上线回归测试——跟币安B系统同批，同一份
45分钟校准。

验证：
  1) symbol_config.ACTIVE_SYMBOLS/SYMBOL_MAP/等辅助表都登记了XRP/SOL。
  2) webhook_parser能正确把TV的"XRPUSDT.P"/"SOLUSDT.P"归一化并判定为
     合法品种。
  3) breath_profiles能查到XRP/SOL的呼吸档，且不是回退到ETH默认档，
     数值跟币安侧完全一致(同一批真实K线算出来的)。
  4) reentry_profiles显式登记了XRP/SOL的再入窗口。
  5) DUAL_MA_EXIT_INTERVAL_MIN登记了45分钟周期。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import symbol_config  # noqa: E402
import breath_profiles  # noqa: E402


class TestXrpSolSymbolConfig(unittest.TestCase):
    def test_active_symbols(self):
        self.assertIn("XRP", symbol_config.ACTIVE_SYMBOLS)
        self.assertIn("SOL", symbol_config.ACTIVE_SYMBOLS)

    def test_symbol_map(self):
        self.assertEqual(symbol_config.SymbolConfig.get_symbol("XRPUSDT"), "XRP")
        self.assertEqual(symbol_config.SymbolConfig.get_symbol("SOLUSDT"), "SOL")

    def test_min_notional_present(self):
        self.assertIn("XRP", symbol_config.SymbolConfig.MIN_NOTIONAL)
        self.assertIn("SOL", symbol_config.SymbolConfig.MIN_NOTIONAL)

    def test_is_valid_symbol(self):
        self.assertTrue(symbol_config.SymbolConfig.is_valid_symbol("XRPUSDT"))
        self.assertTrue(symbol_config.SymbolConfig.is_valid_symbol("SOLUSDT"))


class TestXrpSolWebhookParsing(unittest.TestCase):
    def test_normalize_and_valid(self):
        from webhook_parser import WebhookParser, VALID_SYMBOLS
        self.assertIn("XRP", VALID_SYMBOLS)
        self.assertIn("SOL", VALID_SYMBOLS)
        p = WebhookParser()
        self.assertEqual(p._normalize_symbol("XRPUSDT.P"), "XRP")
        self.assertEqual(p._normalize_symbol("SOLUSDT.P"), "SOL")


class TestXrpSolBreathProfile(unittest.TestCase):
    def test_profile_registered_not_eth_fallback(self):
        for sym in ("XRP", "SOL"):
            profile = breath_profiles.get_breath_profile(sym)
            self.assertEqual(profile["name"], sym)

    def test_profile_matches_binance_side_numbers(self):
        xrp = breath_profiles.get_breath_profile("XRP")
        self.assertEqual(xrp["breath_tp12"], 2.42)
        self.assertEqual(xrp["breath_tp23"], 3.50)
        self.assertEqual(xrp["max_mult"], 5.3)
        self.assertEqual(xrp["min_mult"], 3.8)
        sol = breath_profiles.get_breath_profile("SOL")
        self.assertEqual(sol["breath_tp12"], 2.46)
        self.assertEqual(sol["breath_tp23"], 3.48)
        self.assertEqual(sol["max_mult"], 5.3)
        self.assertEqual(sol["min_mult"], 3.8)

    def test_get_tier_params_compat_shim(self):
        for sym in ("XRP", "SOL"):
            profile = breath_profiles.get_breath_profile(sym)
            self.assertEqual(profile.get_tier_params("2"), profile)


class TestXrpSolReentryAndInterval(unittest.TestCase):
    def test_reentry_window_registered(self):
        from reentry_profiles import ReentryProfile
        self.assertEqual(ReentryProfile("XRP").get_reentry_window("XRP"), 2)
        self.assertEqual(ReentryProfile("SOL").get_reentry_window("SOL"), 2)

    def test_dual_ma_exit_interval_is_45m(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "position_supervisor_coinw.py")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        self.assertIn('"XRP": 45, "SOL": 45,', src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
