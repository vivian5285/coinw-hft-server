#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-09-15：_handle_heartbeat()"TV有仓、VPS空"分支新增的趋势确认快速
入口回归测试。

背景——今天OPENAI在B账户(币安)被误判止损后TV其实还在持有，等了几个
小时多周期确认一直没通过，账户一直空仓。CoinW这边同一个分支原来只有
_chase_watch_step(3周期持续确认窗口)，现在在它前面插一个更严格但能
更快确认的技术信号(双均线+3根同向+放量)：满足就直接开仓，不满足就
原样落回既有的追单确认流程，不打断它。

不碰任何真实账户/持仓，self.client/self.pipeline/self._maybe_trend_
reentry/self._chase_watch_step全部用测试替身。
"""
from __future__ import annotations

import os
import sys
import threading
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("COINW_SKIP_BOOTSTRAP", "1")

import position_supervisor_coinw as psc  # noqa: E402
from webhook_parser import ParsedSignal  # noqa: E402


class _FakePipeline:
    def __init__(self):
        self.data = {"entry": 0.0, "position_id": "", "hard_sl_px": 0.0}


def _mk_supervisor(symbol="OPENAI"):
    s = object.__new__(psc.PositionSupervisorCoinW)
    s.symbol = symbol
    s.pipeline = _FakePipeline()
    s.client = MagicMock()
    s.client.get_position = MagicMock(return_value=None)  # have==0
    s._safe_alert = MagicMock()
    s._lock = threading.Lock()
    s._monitoring = False
    s._last_nonflat_hb_side = ""
    s._last_nonflat_hb_entry = 0.0
    s._catchup_blocked_until = 0.0
    s._chase_watch = {}
    s._get_current_price = MagicMock(return_value=1420.0)
    return s


def _mk_signal(side="LONG", entry=1402.64, price=1420.0):
    return ParsedSignal(
        valid=True, action=side, symbol="OPENAIUSDT", price=price,
        stop_loss=0.0, atr=0.0, tp1=0.0, tp2=0.0, tp3=0.0,
        qty=None, tier="", leverage=20, error="", side=side,
        raw={"entry": entry},
    )


class TestTrendReentryFastPathInHeartbeat(unittest.TestCase):
    def test_confirmed_trend_reentry_short_circuits_before_chase_watch(self):
        """复现今天OPENAI场景：TV心跳仍是LONG、VPS空仓——趋势确认通过时
        应该直接走这条快速入口开仓，不该再去等_chase_watch_step的持续
        确认窗口。"""
        s = _mk_supervisor()
        s._maybe_trend_reentry = MagicMock(
            return_value={"ok": True, "status": "heartbeat", "trend_reentry": True,
                          "action": "trend_reentry_open"}
        )
        s._chase_watch_step = MagicMock(return_value=(True, "不该被调用到"))

        result = s._handle_heartbeat(_mk_signal(side="LONG"))

        s._maybe_trend_reentry.assert_called_once_with(override_side="LONG")
        s._chase_watch_step.assert_not_called()
        self.assertTrue(result.get("trend_reentry"))

    def test_unconfirmed_trend_reentry_falls_through_to_chase_watch(self):
        """趋势确认没通过(或冷却中/日上限)时，应该原样落回既有的
        _chase_watch_step追单确认流程，不能吞掉这次心跳。"""
        s = _mk_supervisor()
        s._maybe_trend_reentry = MagicMock(
            return_value={"ok": True, "status": "heartbeat", "state": "trend_not_confirmed"}
        )
        s._chase_watch_step = MagicMock(return_value=(False, "3TF不足 1/3"))
        # _synthesize_open_signal/ATR是这条既有流程自己的事，跟这次新增
        # 的快速入口无关——直接mock掉，只验证"落回_chase_watch_step"这
        # 一步是否发生。
        s._synthesize_open_signal = MagicMock(
            return_value=_mk_signal(side="LONG", entry=1402.64, price=1402.64)
        )
        s._synthesize_open_signal.return_value.atr = 20.0
        s._get_current_price = MagicMock(return_value=1403.0)  # 贴近entry，不触发偏离拒绝

        result = s._handle_heartbeat(_mk_signal(side="LONG", entry=1402.64))

        s._maybe_trend_reentry.assert_called_once_with(override_side="LONG")
        s._chase_watch_step.assert_called_once()
        self.assertEqual(result.get("state"), "chase_watch")

    def test_catchup_blocked_window_skips_fast_path_too(self):
        """人工平仓冻结窗口内，快速入口也不该被触发(跟既有追单确认
        共用同一道闸门)。"""
        import time
        s = _mk_supervisor()
        s._catchup_blocked_until = time.time() + 600
        s._maybe_trend_reentry = MagicMock()

        result = s._handle_heartbeat(_mk_signal(side="LONG"))

        s._maybe_trend_reentry.assert_not_called()
        self.assertEqual(result.get("state"), "catchup_blocked")


if __name__ == "__main__":
    unittest.main(verbosity=2)
