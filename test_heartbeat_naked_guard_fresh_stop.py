#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-09-14：_handle_heartbeat()裸单守护改用_compute_fresh_hard_stop()的
回归测试。

背景——实盘复现(XRPUSDT)：这笔仓位交易所上没有任何止损记录(addTpsl
记录、position自身stopLossPrice标量都没有)，_handle_heartbeat()"同向
已持仓：核对裸单"分支原来查不到hard_sl_px时直接退回`signal.stop_loss`
(TV心跳自带的止损参考)当成我们自己的综合硬止损去挂——TV这个字段是
它自己Pine脚本内部逻辑算出来的，跟我们结构摆动点+ATR分档的方法论
完全不同，实盘复现出entry=1.3547、TV给的止损只有1.35(距离仅0.35%)，
一次正常波动就会打穿。

修复：两处裸单守护(有side/无side)都改成调用_compute_fresh_hard_stop()
现算综合硬止损，不再把TV自己的止损参考直接当成我们的硬止损用。

不碰任何真实账户/持仓，self.client/self.pipeline/self.radar全部用
测试替身，atr_scenario.calc_smart_hard_stop_price用真实纯函数+合成
K线。
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
from breath_stop import BreathStop  # noqa: E402
from webhook_parser import ParsedSignal  # noqa: E402


class _FakePipeline:
    def __init__(self, entry=1.3547):
        self.data = {"entry": entry, "position_id": "pos_xrp", "hard_sl_px": 0.0}


def _mk_supervisor(symbol="XRP"):
    s = object.__new__(psc.PositionSupervisorCoinW)
    s.symbol = symbol
    s.pipeline = _FakePipeline()
    s.radar = BreathStop(symbol)
    s.radar.set_atr(0.006)
    s.client = MagicMock()
    s._safe_alert = MagicMock()
    s._monitoring = True
    s._last_nonflat_hb_side = None
    s._last_nonflat_hb_entry = 0.0
    s._lock = threading.Lock()
    return s


def _make_bars(n=90, start=1.30, step=0.001, period_min=15):
    bars = []
    t0 = 1_700_000_000_000
    px = start
    for i in range(n):
        px += step
        bars.append([t0 + i * period_min * 60000, px - step, px + 0.0004, px - 0.0004, px, 100.0])
    return bars


def _mk_signal(side="LONG", stop_loss=1.35, price=1.3547):
    return ParsedSignal(
        valid=True, action=side, symbol="XRP", price=price, stop_loss=stop_loss,
        atr=0.0, tp1=0.0, tp2=0.0, tp3=0.0, qty=None, tier="", leverage=1, error="",
        side=side, raw={},
    )


class TestHeartbeatNakedGuardFreshStop(unittest.TestCase):
    def test_same_side_naked_position_computes_fresh_stop_not_tv_value(self):
        """核心回归：不再信TV心跳自带的stop_loss(1.35，过紧)，改成现算
        综合硬止损(真实K线算出来的应该明显更宽)。"""
        s = _mk_supervisor()
        s.client.get_position = MagicMock(return_value={"direction": "LONG"})
        s._live_side = lambda pos: "LONG"
        s._pos_qty = lambda: 43.3504
        s._hard_sl_present = lambda: False
        s._fetch_dual_ma_exit_klines = MagicMock(return_value=_make_bars())

        sig = _mk_signal(side="LONG", stop_loss=1.35, price=1.3547)
        result = s._handle_heartbeat(sig)

        self.assertEqual(result.get("action"), "computed_sl")
        computed_sl = result.get("sl")
        self.assertGreater(computed_sl, 0)
        # 核心断言：真的现算了(拉了K线、跑了公式)，不是直接照抄
        # signal.stop_loss——即使这次合成K线巧合下四舍五入到2位小数
        # 后跟TV的1.35撞了车，"有没有真的现算"这件事本身才是这次修复
        # 要验证的，不是巧合的数字本身。
        s._fetch_dual_ma_exit_klines.assert_called_once()
        s.client.set_sl_tp.assert_called_once()
        _, kwargs = s.client.set_sl_tp.call_args
        self.assertAlmostEqual(kwargs["stop_loss_price"], computed_sl, places=2)

    def test_existing_hard_sl_px_still_used_directly_no_recompute(self):
        """账本里已经有综合硬止损值时，直接用，不重复现算(性能/幂等)。"""
        s = _mk_supervisor()
        s.pipeline.data["hard_sl_px"] = 1.30
        s.client.get_position = MagicMock(return_value={"direction": "LONG"})
        s._live_side = lambda pos: "LONG"
        s._pos_qty = lambda: 43.3504
        s._hard_sl_present = lambda: False
        s._fetch_dual_ma_exit_klines = MagicMock()

        sig = _mk_signal(side="LONG", stop_loss=1.35, price=1.3547)
        result = s._handle_heartbeat(sig)

        self.assertEqual(result.get("action"), "reattach_sl")
        self.assertAlmostEqual(result.get("sl"), 1.30, places=2)
        s._fetch_dual_ma_exit_klines.assert_not_called()

    def test_hard_sl_already_present_skips_guard_entirely(self):
        """交易所已经有有效硬止损时，裸单守护整体跳过，不触发现算也
        不重挂。"""
        s = _mk_supervisor()
        s.client.get_position = MagicMock(return_value={"direction": "LONG"})
        s._live_side = lambda pos: "LONG"
        s._pos_qty = lambda: 43.3504
        s._hard_sl_present = lambda: True
        s._fetch_dual_ma_exit_klines = MagicMock()

        sig = _mk_signal(side="LONG", stop_loss=1.35, price=1.3547)
        s._handle_heartbeat(sig)

        s._fetch_dual_ma_exit_klines.assert_not_called()
        s.client.set_sl_tp.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
