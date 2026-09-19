#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-09-19新增：_symbols_with_orphaned_live_positions()的回归测试。

背景：ACTIVE_SYMBOLS白名单外但交易所真实有仓位的品种，此前引擎完全不
会发现。这里补上账户级批量持仓核对——但**同一天**实盘复现宝贝自己手工
开的ZEC/ETH一补建supervisor接管就被硬止损/雷达强平了好几次，宝贝明确
叫停"自动接管"这个行为：现在这个函数只做检测+告警，recover_all_on_
start()/app.py周期housekeep巡检都不再拿它的结果去补建supervisor。

不碰任何真实账户/持仓，mock coinw_client.get_all_positions，用
symbol_config.SymbolConfig.SYMBOL_MAP真实内容验证"认识的品种才检测、
不认识的跳过"；dingtalk.send_alert在测试环境未配置TELEGRAM/DINGTALK
的webhook时天然是安全no-op，不会真的发网络请求。
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("COINW_SKIP_BOOTSTRAP", "1")

import position_supervisor_coinw as psc  # noqa: E402


class TestOrphanedLivePositions(unittest.TestCase):
    def test_paused_symbol_with_real_position_is_orphaned(self):
        """核心回归：ETH(2026-09-15暂停)有真实非零仓位、但不在
        ACTIVE_SYMBOLS里 → 必须被识别为需要补建/唤醒supervisor的孤儿
        仓位。"""
        fake_client = MagicMock()
        fake_client.get_all_positions = MagicMock(return_value={
            "ETH": {"quantity": "-0.620"},
            "BNB": {"quantity": "0.5"},   # 白名单内，不算孤儿
            "XAU": {"quantity": "0.0"},   # 已空仓，不算孤儿
        })
        with patch("coinw_client.coinw_client", fake_client):
            out = psc._symbols_with_orphaned_live_positions()
        self.assertEqual(out, ["ETH"])

    def test_unknown_ticker_skipped(self):
        """交易所返回一个本地symbol_config不认识的ticker(比如已下架/
        重命名) → 不该被拉去建supervisor，交由人工核查，不能因为不认识
        就崩。"""
        fake_client = MagicMock()
        fake_client.get_all_positions = MagicMock(return_value={
            "TOTALLYUNKNOWN": {"quantity": "1.0"},
        })
        with patch("coinw_client.coinw_client", fake_client):
            out = psc._symbols_with_orphaned_live_positions()
        self.assertEqual(out, [])

    def test_all_flat_or_whitelisted_returns_empty(self):
        """回归：正常情况(白名单品种有仓，非白名单全部空仓)不应该产生
        任何孤儿列表，避免每轮巡检都误建一堆不需要的supervisor。"""
        fake_client = MagicMock()
        fake_client.get_all_positions = MagicMock(return_value={
            "BNB": {"quantity": "0.5"},
            "XPD": {"quantity": "0.0"},
            "ETH": {"quantity": "0"},
        })
        with patch("coinw_client.coinw_client", fake_client):
            out = psc._symbols_with_orphaned_live_positions()
        self.assertEqual(out, [])

    def test_rest_query_failure_fails_safe_empty(self):
        """账户级持仓核对失败(REST异常/None) → 不能让housekeep巡检循环
        本身崩掉，宁可这轮跳过孤儿仓位扫描，下一轮(HOUSEKEEP_SEC后)再试。"""
        fake_client = MagicMock()
        fake_client.get_all_positions = MagicMock(return_value=None)
        with patch("coinw_client.coinw_client", fake_client):
            out = psc._symbols_with_orphaned_live_positions()
        self.assertEqual(out, [])

        fake_client.get_all_positions = MagicMock(side_effect=RuntimeError("boom"))
        with patch("coinw_client.coinw_client", fake_client):
            out = psc._symbols_with_orphaned_live_positions()
        self.assertEqual(out, [])

    def test_positionamt_fallback_key_also_supported(self):
        """字段名兜底：quantity缺失时退回positionAmt(跟币安字段名对齐的
        防御性兜底，不假设CoinW响应字段一定叫quantity)。"""
        fake_client = MagicMock()
        fake_client.get_all_positions = MagicMock(return_value={
            "ETH": {"positionAmt": "0.3"},
        })
        with patch("coinw_client.coinw_client", fake_client):
            out = psc._symbols_with_orphaned_live_positions()
        self.assertEqual(out, ["ETH"])


class TestRecoverAllOnStartDoesNotAdoptOrphans(unittest.TestCase):
    def test_recover_all_on_start_only_touches_whitelist(self):
        """2026-09-19宝贝叫停自动接管后的核心回归：recover_all_on_
        start()只给ACTIVE_SYMBOLS建supervisor，孤儿品种(哪怕检测到了)
        绝不会被拿去recover_on_start()——不能有任何线程碰宝贝自己手工
        开的非白名单仓位。"""
        fake_sup = MagicMock()
        with patch.object(psc, "_symbols_with_orphaned_live_positions",
                           return_value=["ETH", "XPT"]) as mock_detect, \
             patch("app.get_supervisor", return_value=fake_sup) as mock_get_sup:
            psc.recover_all_on_start()
            called_syms = [c.args[0] for c in mock_get_sup.call_args_list]
        mock_detect.assert_called_once()  # 检测仍然要跑(供告警用)
        self.assertEqual(called_syms, list(psc.ACTIVE_SYMBOLS))
        self.assertNotIn("ETH", called_syms)
        self.assertNotIn("XPT", called_syms)
        self.assertEqual(fake_sup.recover_on_start.call_count, len(psc.ACTIVE_SYMBOLS))

    def test_orphan_detection_failure_does_not_block_whitelist_recovery(self):
        """检测本身意外异常(非函数内部已处理的REST失败，而是更底层的bug)
        不该拖垮白名单品种的正常启动恢复。"""
        fake_sup = MagicMock()
        with patch.object(psc, "_symbols_with_orphaned_live_positions",
                           side_effect=RuntimeError("boom")), \
             patch("app.get_supervisor", return_value=fake_sup) as mock_get_sup:
            psc.recover_all_on_start()  # 不该抛异常
            called_syms = [c.args[0] for c in mock_get_sup.call_args_list]
        self.assertEqual(called_syms, list(psc.ACTIVE_SYMBOLS))


if __name__ == "__main__":
    unittest.main(verbosity=2)
