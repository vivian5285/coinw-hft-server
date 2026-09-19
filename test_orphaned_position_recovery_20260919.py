#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-09-19新增：_symbols_with_orphaned_live_positions()的回归测试
(本周问题总结item5"手动补单自动配置硬止损+雷达")。

背景：跟币安B系统同一天同一个思路移植——ACTIVE_SYMBOLS白名单只该决定
"接不接受TV新开仓/平仓信号"，不该决定"要不要继续照看交易所上真实存在
的仓位"。宝贝手动开/补一笔暂停品种(比如ETH/XPT/SOL/XRP/BTC，2026-09-15
精细化聚焦5个品种后被暂停)的仓位时，此前引擎完全不会发现，只有交易所
上早先挂好的静态止损单裸奔兜底。这里补上账户级批量持仓核对，发现白名单
外但真实有仓位的品种，接进recover_all_on_start()(启动时)+app.py周期
housekeep巡检(不需要重启，下一轮巡检内就能被自动接管)。

不碰任何真实账户/持仓，mock coinw_client.get_all_positions，用
symbol_config.SymbolConfig.SYMBOL_MAP真实内容验证"认识的品种才补建、
不认识的跳过"。
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


class TestRecoverAllOnStartIncludesOrphans(unittest.TestCase):
    def test_recover_all_on_start_unions_whitelist_and_orphaned(self):
        """验证recover_all_on_start()真正拼装的启动清单：白名单 + 孤儿
        仓位品种去重合并，不重复、不遗漏。"""
        fake_sup = MagicMock()
        with patch.object(psc, "_symbols_with_orphaned_live_positions",
                           return_value=["ETH", "XPT"]), \
             patch("app.get_supervisor", return_value=fake_sup) as mock_get_sup:
            psc.recover_all_on_start()
            called_syms = [c.args[0] for c in mock_get_sup.call_args_list]
        self.assertEqual(
            called_syms,
            list(psc.ACTIVE_SYMBOLS) + ["ETH", "XPT"],
        )
        self.assertEqual(fake_sup.recover_on_start.call_count, len(called_syms))


if __name__ == "__main__":
    unittest.main(verbosity=2)
