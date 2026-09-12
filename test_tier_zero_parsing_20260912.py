#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-09-12：webhook_parser 的 tier 解析在 tier 是裸 JSON 整数 0 时的回归测试。

背景——宝贝给的新策略"Webhook 对齐版 + tier 动态分档"（新测试策略源码.txt）
发的 payload 是 `"tier":0`（Pine `str.tostring(tierLong)` 直接拼进JSON，
不带引号，是裸数字，不是字符串"0"）。修复前 `tier = str(raw.get("tier")
or raw.get("adx_tier") or "").lower()` 这条 `or` 链会把 JSON 整数 0
当 falsy 跳过，最终 tier 变成空串 ""——defense_profiles.get_tier_risk_pct
对空串按强档兜底(DEFAULT_RISK_PCT=0.40)，等于弱信号(tier=0，该给20%×5x)
被静默放大成强档仓位(40%×5x，2倍名义)，纯粹解析层的bug，不是仓位公式
本身的问题。

只测 webhook_parser 这个纯函数模块，不碰任何真实持仓/下单/网络。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from webhook_parser import WebhookParser  # noqa: E402


class TestTierZeroIntNotSwallowed(unittest.TestCase):
    def setUp(self):
        os.environ["WEBHOOK_SECRET"] = "test-secret-tier0"
        self.parser = WebhookParser()

    def _payload(self, tier_value):
        p = {
            "secret": "test-secret-tier0",
            "action": "LONG",
            "symbol": "OPENAIUSDT.P",
            "price": 1500.0,
            "atr": 20.0,
            "stop_loss": 1450.0,
            "tp1": 1520.0,
            "tp2": 1540.0,
        }
        if tier_value is not None:
            p["tier"] = tier_value
        return p

    def test_bare_int_zero_tier_parses_as_zero_not_empty(self):
        """回归核心：新策略发的是裸JSON整数0，不是字符串"0"。"""
        sig = self.parser.parse(self._payload(0))
        self.assertTrue(sig.valid, f"应该解析成功，实际 error={sig.error!r}")
        self.assertEqual(sig.tier, "0", "tier=0(int) 不应该被 `or` 链吞成空串")

    def test_string_zero_tier_still_works(self):
        """回归：老策略发字符串"0"的路径不能被这次改动破坏。"""
        sig = self.parser.parse(self._payload("0"))
        self.assertEqual(sig.tier, "0")

    def test_int_one_and_two_still_work(self):
        for v, expect in ((1, "1"), (2, "2")):
            sig = self.parser.parse(self._payload(v))
            self.assertEqual(sig.tier, expect, f"tier={v}(int) 应该解析成 {expect!r}")

    def test_missing_tier_still_falls_back_to_empty(self):
        """回归：真的没给tier字段，兜底行为不变（空串，交由下游按强档兜底）。"""
        sig = self.parser.parse(self._payload(None))
        self.assertEqual(sig.tier, "")

    def test_heartbeat_bare_int_zero_tier_also_fixed(self):
        """HEARTBEAT 分支是独立的一份同款逻辑，同样要修。"""
        payload = {
            "secret": "test-secret-tier0",
            "action": "HEARTBEAT",
            "symbol": "OPENAIUSDT.P",
            "side": "LONG",
            "tier": 0,
        }
        sig = self.parser.parse(payload)
        self.assertTrue(sig.valid)
        self.assertEqual(sig.tier, "0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
