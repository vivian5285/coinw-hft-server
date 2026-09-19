#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-09-19新增：平仓原因(exit_source)落journal + 控制面板/console/status
的回归测试(本周问题总结item6"控制面板显示每笔平仓原因")。

背景：exit_source此前只进了_safe_alert告警文案，从没被持久化成可查询
的结构化记录。新增_journal_close()把每次仓位归零落一条结构化journal
记录(新增_journal_path/_append_journal/_iter_journal_entries，跟币安
B系统position_supervisor_binance.py同一套设计，两仓库保持结构一致)，
_on_position_zero()里exit_side/exit_entry>0时调用。app.py新增
_recent_exit_history_coinw()跨ACTIVE_SYMBOLS聚合读出来，接进新注册的
/console/status路由(排查中顺手发现这个路径此前从未注册过，console页面
loadStatus()一直在fetch一个404，页面卡在"检查中..."，一并修好)。

不碰任何真实账户/持仓，client/radar/pipeline全部用测试替身。
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("COINW_SKIP_BOOTSTRAP", "1")

import position_supervisor_coinw as psc  # noqa: E402


def _mk_supervisor(symbol="OPENAI"):
    s = object.__new__(psc.PositionSupervisorCoinW)
    s.symbol = symbol
    return s


class TestJournalHelpers(unittest.TestCase):
    def test_journal_close_writes_expected_record(self):
        s = _mk_supervisor("OPENAI")
        with patch.object(s, "_append_journal") as mock_append, \
             patch.object(s, "_journal_path", return_value="logs/coinw_close_journal_OPENAI.jsonl") as mock_path:
            s._journal_close("LONG", 1491.75, 1475.75, "vps_hard_sl", tier="1")
        mock_path.assert_called_once_with("close")
        mock_append.assert_called_once()
        args, kwargs = mock_append.call_args
        path, record = args
        self.assertEqual(path, "logs/coinw_close_journal_OPENAI.jsonl")
        self.assertEqual(record["side"], "LONG")
        self.assertAlmostEqual(record["entry_px"], 1491.75, places=2)
        self.assertAlmostEqual(record["exit_px"], 1475.75, places=2)
        self.assertEqual(record["exit_source"], "vps_hard_sl")
        self.assertEqual(record["tier"], "1")

    def test_append_journal_roundtrips_through_real_tempfile(self):
        """跟_journal_close的mock版不同，这里真的写一个临时文件再读回来，
        验证_append_journal/_iter_journal_entries这两个真实文件IO helper
        本身没写错(json格式/换行/ts字段都对)。"""
        import tempfile
        s = _mk_supervisor("OPENAI")
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "close.jsonl")
            s._append_journal(path, {"side": "SHORT", "exit_source": "tv_close"})
            s._append_journal(path, {"side": "LONG", "exit_source": "radar_be"})
            with patch.object(s, "_journal_path", return_value=path):
                entries = s._iter_journal_entries("close")
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["side"], "SHORT")
        self.assertEqual(entries[0]["symbol"], "OPENAI")
        self.assertIn("ts", entries[0])
        self.assertEqual(entries[1]["side"], "LONG")

    def test_append_journal_exception_is_safe_noop(self):
        s = _mk_supervisor("OPENAI")
        # 无效路径(目录名混进非法字符在大多数平台会失败) 或直接mock os.makedirs抛异常
        with patch("os.makedirs", side_effect=OSError("boom")):
            s._append_journal("logs/whatever.jsonl", {"side": "LONG"})  # 不该抛异常

    def test_iter_journal_entries_missing_file_returns_empty(self):
        s = _mk_supervisor("OPENAI")
        with patch.object(s, "_journal_path", return_value="logs/definitely_not_exist_xyz.jsonl"):
            self.assertEqual(s._iter_journal_entries("close"), [])


class TestOnPositionZeroJournals(unittest.TestCase):
    def test_journals_on_stopped_out_close(self):
        s = _mk_supervisor("OPENAI")
        s.pipeline = MagicMock()
        s.pipeline.data = {"side": "SHORT", "entry": 100.0, "tier": "2"}
        s._intentional_close = False
        s._resolve_exit_source_coinw = MagicMock(return_value="vps_hard_sl")
        s._monitoring = True
        s.client = MagicMock()
        s.radar = MagicMock()
        s._dingtalk = MagicMock()
        s._journal_close = MagicMock()
        s._reentry_count = 0
        s._cooldown_until = 0.0

        s._on_position_zero(curr_px=101.5)

        s._journal_close.assert_called_once_with("SHORT", 100.0, 101.5, "vps_hard_sl", tier="2")

    def test_journals_on_tv_intentional_close_too(self):
        """跟_last_exit只记录"非TV平仓"不同——控制面板要看到每一笔，
        包括TV自己平掉的那些(exit_source=tv_close)。"""
        s = _mk_supervisor("OPENAI")
        s.pipeline = MagicMock()
        s.pipeline.data = {"side": "LONG", "entry": 200.0, "tier": "0"}
        s._intentional_close = True
        s._resolve_exit_source_coinw = MagicMock(return_value="tv_close")
        s._monitoring = True
        s.client = MagicMock()
        s.radar = MagicMock()
        s._dingtalk = MagicMock()
        s._journal_close = MagicMock()

        s._on_position_zero(curr_px=205.0)

        s._journal_close.assert_called_once_with("LONG", 200.0, 205.0, "tv_close", tier="0")

    def test_no_journal_when_no_real_position_existed(self):
        """entry<=0(压根没有真实持仓过的收尾，比如从未成交的挂单被撤)
        不该产生journal记录。"""
        s = _mk_supervisor("OPENAI")
        s.pipeline = MagicMock()
        s.pipeline.data = {"side": "", "entry": 0.0}
        s._intentional_close = False
        s._resolve_exit_source_coinw = MagicMock(return_value="manual")
        s._monitoring = True
        s.client = MagicMock()
        s.radar = MagicMock()
        s._dingtalk = MagicMock()
        s._journal_close = MagicMock()

        s._on_position_zero(curr_px=100.0)

        s._journal_close.assert_not_called()


class TestRecentExitHistoryAggregation(unittest.TestCase):
    def test_aggregates_across_symbols_sorted_desc_and_respects_limit(self):
        import app as coinw_app

        sup_a = MagicMock()
        sup_a._iter_journal_entries = MagicMock(return_value=[
            {"ts": "2026-09-19 10:00:00", "side": "LONG", "exit_source": "tv_close",
             "entry_px": 100.0, "exit_px": 105.0, "tier": "1"},
        ])
        sup_b = MagicMock()
        sup_b._iter_journal_entries = MagicMock(return_value=[
            {"ts": "2026-09-19 12:00:00", "side": "SHORT", "exit_source": "vps_hard_sl",
             "entry_px": 200.0, "exit_px": 210.0, "tier": "2"},
        ])
        fake_supervisors = {"BNB": sup_a, "XAU": sup_b}
        with patch.object(coinw_app, "ACTIVE_SYMBOLS", ["BNB", "XAU"]), \
             patch.object(coinw_app, "_supervisors", fake_supervisors):
            out = coinw_app._recent_exit_history_coinw(limit=40)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["symbol"], "XAU")  # 12:00比10:00新，排前面
        self.assertEqual(out[0]["exit_source"], "vps_hard_sl")
        self.assertEqual(out[1]["symbol"], "BNB")

    def test_symbol_never_instantiated_is_skipped_not_crash(self):
        import app as coinw_app
        with patch.object(coinw_app, "ACTIVE_SYMBOLS", ["BNB"]), \
             patch.object(coinw_app, "_supervisors", {}):
            out = coinw_app._recent_exit_history_coinw(limit=40)
        self.assertEqual(out, [])

    def test_one_symbol_journal_read_failure_does_not_break_others(self):
        import app as coinw_app
        sup_good = MagicMock()
        sup_good._iter_journal_entries = MagicMock(return_value=[
            {"ts": "2026-09-19 09:00:00", "side": "LONG", "exit_source": "tv_close"},
        ])
        sup_bad = MagicMock()
        sup_bad._iter_journal_entries = MagicMock(side_effect=RuntimeError("boom"))
        with patch.object(coinw_app, "ACTIVE_SYMBOLS", ["GOOD", "BAD"]), \
             patch.object(coinw_app, "_supervisors", {"GOOD": sup_good, "BAD": sup_bad}):
            out = coinw_app._recent_exit_history_coinw(limit=40)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["symbol"], "GOOD")


if __name__ == "__main__":
    unittest.main(verbosity=2)
