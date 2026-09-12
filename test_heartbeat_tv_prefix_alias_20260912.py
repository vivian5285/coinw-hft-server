#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-09-12：HEARTBEAT 心跳字段 tv_ 前缀别名回归测试。

背景——冒烟测试实测发现：宝贝给的新TV策略"Webhook 对齐版 + tier 动态分档"
（新测试策略源码.txt）心跳消息用的字段是 tv_side/tv_entry/tv_stop/
tv_tp1/tv_tp2/tv_tp3（第十五节"心跳持仓同步"），这跟币安
eth-webhook-server 的 webhook_parser.py 完全一致（那边心跳/开仓两条路径
都认 tp_i 和 tv_tp_i 互为别名）。但 CoinW 这份 webhook_parser.py 修复前
只认裸字段名 side/price/stop_loss/tp1/tp2/tp3——冒烟测试直接发一条真实
心跳payload给运行中的 coinw-engine，日志显示 side 解析成了 "UNKNOWN"
（应为 FLAT），不是解析bug而是字段名对不上，会让 TV 心跳追回/对账功能
对这个新策略完全失效。

只测 webhook_parser 纯函数，不碰任何真实持仓/下单/网络。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from webhook_parser import WebhookParser  # noqa: E402


class TestHeartbeatTvPrefixAlias(unittest.TestCase):
    def setUp(self):
        os.environ["WEBHOOK_SECRET"] = "test-secret-hbtv"
        self.parser = WebhookParser()

    def test_real_strategy_heartbeat_shape_parses_correctly(self):
        """新策略十五节"心跳持仓同步"的真实payload形状（LONG持仓中）。"""
        payload = {
            "action": "HEARTBEAT",
            "secret": "test-secret-hbtv",
            "symbol": "OPENAIUSDT.P",
            "tv_side": "LONG",
            "tv_entry": 1500.0,
            "tv_stop": 1462.0,
            "tv_tp1": 1525.5,
            "tv_tp2": 1551.0,
            "tv_tp3": 1576.5,
        }
        sig = self.parser.parse(payload)
        self.assertTrue(sig.valid)
        self.assertEqual(sig.side, "LONG", "tv_side 应该被正确识别，不是 UNKNOWN")
        self.assertEqual(sig.price, 1500.0)
        self.assertEqual(sig.stop_loss, 1462.0)
        self.assertEqual(sig.tp1, 1525.5)
        self.assertEqual(sig.tp2, 1551.0)
        self.assertEqual(sig.tp3, 1576.5)

    def test_real_strategy_heartbeat_flat_shape(self):
        """新策略空仓时的心跳：tv_side="FLAT"，其余tv_*都是0。"""
        payload = {
            "action": "HEARTBEAT", "secret": "test-secret-hbtv",
            "symbol": "OPENAIUSDT.P", "tv_side": "FLAT",
            "tv_entry": 0.0, "tv_stop": 0.0,
            "tv_tp1": 0.0, "tv_tp2": 0.0, "tv_tp3": 0.0,
        }
        sig = self.parser.parse(payload)
        self.assertTrue(sig.valid)
        self.assertEqual(sig.side, "FLAT", "显式tv_side=FLAT不应该被当成UNKNOWN")

    def test_legacy_bare_side_field_still_works(self):
        """回归：老策略用裸 side 字段的路径不能被这次改动破坏。"""
        payload = {
            "action": "HEARTBEAT", "secret": "test-secret-hbtv",
            "symbol": "OPENAIUSDT.P", "side": "SHORT",
            "price": 100.0, "stop_loss": 105.0,
            "tp1": 95.0, "tp2": 90.0, "tp3": 85.0,
        }
        sig = self.parser.parse(payload)
        self.assertEqual(sig.side, "SHORT")
        self.assertEqual(sig.price, 100.0)
        self.assertEqual(sig.tp1, 95.0)

    def test_no_side_key_at_all_still_unknown(self):
        """回归：真的没带任何side/tv_side字段，兜底行为不变（UNKNOWN）。"""
        payload = {"action": "HEARTBEAT", "secret": "test-secret-hbtv", "symbol": "ETHUSDT"}
        sig = self.parser.parse(payload)
        self.assertEqual(sig.side, "UNKNOWN")

    def test_bare_field_takes_priority_when_both_present(self):
        """两套字段都存在时，裸字段(老规矩)优先，tv_前缀作降级兜底。"""
        payload = {
            "action": "HEARTBEAT", "secret": "test-secret-hbtv", "symbol": "ETHUSDT",
            "side": "LONG", "tv_side": "SHORT",
            "price": 100.0, "tv_entry": 200.0,
        }
        sig = self.parser.parse(payload)
        self.assertEqual(sig.side, "LONG")
        self.assertEqual(sig.price, 100.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
