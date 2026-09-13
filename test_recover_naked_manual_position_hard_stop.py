#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-09-14：recover_on_start() 补算裸仓综合硬止损的回归测试。

背景——实盘复现(XAUUSDT/XPTUSDT，宝贝在CoinW APP手工补开仓位)：交易所
上这类仓位往往没有任何止损记录(既没有addTpsl分批止盈/止损记录，也没有
position本身的stopLossPrice标量字段)。housekeep()发现"有仓但无人管"时
会调用recover_on_start()接管——此前接管只会照抄交易所现有的止损记录，
查不到就原样记0，形同裸仓交给下游"裸单守护"，但裸单守护只会重挂一个
已经算好、缓存在账本里的止损价，对手工开的仓位从没算过，等于什么都
不做，真实裸奔。

修复：recover_on_start()查不到任何已有止损(addTpsl记录 + position自身
stopLossPrice标量都没有)时，现拉真实K线用综合硬止损公式(结构摆动点+
ATR分档，固定tier=1中档估算)现算一个并立刻挂到交易所。

不碰任何真实账户/持仓，self.client/self.pipeline全部用测试替身，
self.radar用真实BreathStop实例，atr_scenario.calc_smart_hard_stop_price
用真实纯函数+合成K线。
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("COINW_SKIP_BOOTSTRAP", "1")

import position_supervisor_coinw as psc  # noqa: E402
from breath_stop import BreathStop  # noqa: E402


class _FakePipeline:
    def __init__(self):
        self.data = {}

    def sync_position(self, **kwargs):
        self.data.update(kwargs)

    def advance(self, *args, **kwargs):
        pass


def _mk_supervisor(symbol="XAU", side="LONG"):
    s = object.__new__(psc.PositionSupervisorCoinW)
    s.symbol = symbol
    s.pipeline = _FakePipeline()
    s.radar = BreathStop(symbol)
    s.client = MagicMock()
    s._safe_alert = MagicMock()
    s._start_monitoring = MagicMock()
    s._recompute_atr_150m = MagicMock(return_value=3.30)
    s._live_side = MagicMock(return_value=side)
    s._catchup_blocked_until = 0.0
    return s


def _make_bars(n=90, start=4300.0, step=0.6, period_min=15):
    """单调上涨的合成K线，保证fractal pivot能找到摆动低点，
    calc_smart_hard_stop_price能正常算出一个真实数字。"""
    bars = []
    t0 = 1_700_000_000_000
    px = start
    for i in range(n):
        px += step
        bars.append([t0 + i * period_min * 60000, px - step, px + 0.4, px - 0.4, px, 100.0])
    return bars


class TestNakedManualPositionGetsFreshHardStop(unittest.TestCase):
    def test_no_existing_stop_computes_and_places_fresh_hard_stop(self):
        """复现XAU/XPT手工补仓场景：exchange既无addTpsl记录也无position
        自身stopLossPrice标量——现算综合硬止损并调用set_sl_tp挂上。"""
        s = _mk_supervisor(side="LONG")
        s.client.get_position = MagicMock(return_value={
            "baseSize": 42.69, "openPrice": 4356.37, "id": "pos_manual_xau",
            "stopLossPrice": None,
        })
        s.client.get_tp_sl_info = MagicMock(return_value=[])
        s._fetch_dual_ma_exit_klines = MagicMock(return_value=_make_bars())
        s._get_current_price = MagicMock(return_value=4356.37)

        s.recover_on_start()

        self.assertGreater(s.pipeline.data.get("hard_sl_px", 0), 0,
                            "应该现算出一个>0的综合硬止损，不能仍是裸仓0")
        s.client.set_sl_tp.assert_called_once()
        _, kwargs = s.client.set_sl_tp.call_args
        self.assertEqual(kwargs["position_id"], "pos_manual_xau")
        self.assertAlmostEqual(kwargs["stop_loss_price"], s.pipeline.data["hard_sl_px"], places=2)
        self.assertLess(kwargs["stop_loss_price"], 4356.37, "LONG的止损必须在entry下方")
        # recover_on_start末尾还有一条既有的"重建监控"汇总报警，这里只关心
        # 我方新增的"检测到无保护仓位"这一条确实发出去了。
        alert_texts = [c[0][0] for c in s._safe_alert.call_args_list]
        self.assertTrue(any("手工开仓" in t for t in alert_texts))

    def test_position_scalar_stop_loss_price_respected_no_recompute(self):
        """position自身已经带着stopLossPrice标量(另一套止损系统)——直接
        采信，不重新计算、不重复挂单。"""
        s = _mk_supervisor(side="LONG")
        s.client.get_position = MagicMock(return_value={
            "baseSize": 43.03, "openPrice": 1792.78, "id": "pos_manual_xpt",
            "stopLossPrice": 1788.20,
        })
        s.client.get_tp_sl_info = MagicMock(return_value=[])
        s._fetch_dual_ma_exit_klines = MagicMock()
        s._get_current_price = MagicMock(return_value=1792.78)

        s.recover_on_start()

        self.assertAlmostEqual(s.pipeline.data.get("hard_sl_px", 0), 1788.20, places=2)
        s._fetch_dual_ma_exit_klines.assert_not_called()
        s.client.set_sl_tp.assert_not_called()

    def test_addtpsl_hard_stop_still_takes_priority_existing_behavior(self):
        """既有行为不能被破坏：addTpsl记录里的硬止损优先于现算，也不
        触发K线拉取。"""
        s = _mk_supervisor(side="SHORT")
        s.client.get_position = MagicMock(return_value={
            "baseSize": 0.36, "openPrice": 734.47, "id": "pos789",
            "stopLossPrice": None,
        })
        s.client.get_tp_sl_info = MagicMock(return_value=[
            {"stopType": 2, "stopLossPrice": 738.06, "triggerStatus": 0},
        ])
        s._fetch_dual_ma_exit_klines = MagicMock()
        s._get_current_price = MagicMock(return_value=734.0)

        s.recover_on_start()

        self.assertAlmostEqual(s.pipeline.data.get("hard_sl_px", 0), 738.06, places=2)
        s._fetch_dual_ma_exit_klines.assert_not_called()
        s.client.set_sl_tp.assert_not_called()

    def test_klines_or_calc_failure_alerts_and_stays_naked(self):
        """K线拉取/计算失败时——不能装作没事发生，必须报警且明确仍是
        裸仓，不能悄悄吞掉。"""
        s = _mk_supervisor(side="LONG")
        s.client.get_position = MagicMock(return_value={
            "baseSize": 42.69, "openPrice": 4356.37, "id": "pos_fail",
            "stopLossPrice": None,
        })
        s.client.get_tp_sl_info = MagicMock(return_value=[])
        s._fetch_dual_ma_exit_klines = MagicMock(return_value=[])  # 空K线→算不出来
        s._get_current_price = MagicMock(return_value=4356.37)

        s.recover_on_start()

        self.assertEqual(s.pipeline.data.get("hard_sl_px", 0), 0)
        s.client.set_sl_tp.assert_not_called()
        alert_texts = [c[0][0] for c in s._safe_alert.call_args_list]
        self.assertTrue(any("人工核查" in t for t in alert_texts))


if __name__ == "__main__":
    unittest.main(verbosity=2)
