#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-09-13："双均线破位快速平仓"(_maybe_fast_exit_on_dual_ma_break)回归
测试——跟币安B系统(eth-webhook-server::test_dual_ma_fast_exit.py)同一套
用例，验证CoinW侧的移植版本。

背景见position_supervisor_coinw.py::DUAL_MA_EXIT_*常量顶部注释：币安B
系统OPENAI靠ATR跟踪止损雷达在反弹时被打出，CoinW的OPENAI止损还没被打
到、仍在持仓——宝贝要求雷达主动看这个品种自己真实周期的裸K是否跌破/
站上快慢双均线(8/20)，真实放量确认破位时直接快速平仓，没确认时只适度
收紧止损，不强平。

不碰任何真实账户/持仓，self.client/self.radar/self.pipeline全部用测试
替身，dual_ma_trend/_volume_confirmed用真实纯函数+合成K线。
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("COINW_SKIP_BOOTSTRAP", "1")

import position_supervisor_coinw as psc  # noqa: E402


def _make_bars(decline_n=40, decline_step=-1.0, rally_n=10, rally_step=3.0,
               start=100.0, surge=False, period_min=15):
    # 2026-09-13：默认符号OPENAI从120分钟(原生直取)改成45分钟(15分钟合成)
    # 后，默认K线间距也要跟着从120改成15，否则合成分桶对不上时间戳。
    bars = []
    t0 = 1_700_000_000_000
    period_ms = period_min * 60 * 1000
    px = start
    i = 0
    for _ in range(decline_n):
        px += decline_step
        bars.append([t0 + i * period_ms, px - decline_step, px + 0.5, px - 0.5, px, 100.0])
        i += 1
    for j in range(rally_n):
        px += rally_step
        vol = 300.0 if (surge and j >= rally_n - 3) else 100.0
        bars.append([t0 + i * period_ms, px - rally_step, px + 0.5, px - 0.5, px, vol])
        i += 1
    return bars


class _FakePipeline:
    def __init__(self, side="SHORT"):
        self.data = {"side": side}


class _FakeRadarState:
    def __init__(self, current_sl=200.0, initial_atr=2.0):
        self.current_sl = current_sl
        self.initial_atr = initial_atr


def _mk_supervisor(symbol="OPENAI", side="SHORT"):
    s = object.__new__(psc.PositionSupervisorCoinW)
    s.symbol = symbol
    s.pipeline = _FakePipeline(side)
    s.client = MagicMock()
    s.radar = MagicMock()
    s.radar.get_state.return_value = _FakeRadarState()
    s._safe_alert = MagicMock()
    s._clear_position = MagicMock()
    s._update_radar_sl = MagicMock()
    s._dual_ma_exit_last_check_ts = 0.0
    s._dual_ma_exit_closed_bar = 0
    return s


class TestDualMaFastExit(unittest.TestCase):
    def test_flag_off_does_nothing(self):
        s = _mk_supervisor()
        psc.DUAL_MA_EXIT_ENABLED = False
        try:
            s.client.get_klines = MagicMock()
            s._maybe_fast_exit_on_dual_ma_break(90.0)
            s.client.get_klines.assert_not_called()
        finally:
            psc.DUAL_MA_EXIT_ENABLED = True

    def test_no_position_does_nothing(self):
        s = _mk_supervisor(side="")
        s.client.get_klines = MagicMock()
        s._maybe_fast_exit_on_dual_ma_break(90.0)
        s.client.get_klines.assert_not_called()

    def test_trend_still_intact_no_action(self):
        """空头仍在双均线下方(纯下跌，没有拉回)——不触发任何动作。"""
        s = _mk_supervisor()
        bars = _make_bars(decline_n=50, rally_n=0)
        # 2026-09-13：直接mock _fetch_dual_ma_exit_klines(已合成好的最终
        # K线)，跟趋势判定逻辑本身解耦，不受默认符号OPENAI改45分钟(15分钟
        # 合成)影响——同test_impulse_candle_lock.py已验证过的手法。
        s._fetch_dual_ma_exit_klines = MagicMock(return_value=bars)
        s._maybe_fast_exit_on_dual_ma_break(bars[-1][4])
        s._clear_position.assert_not_called()
        s._update_radar_sl.assert_not_called()

    def test_break_with_volume_confirmed_triggers_clear_position(self):
        """空头收盘价拉回站上双均线 + 真实放量确认 → 直接清仓。"""
        s = _mk_supervisor()
        bars = _make_bars(decline_n=40, rally_n=10, surge=True)
        s._fetch_dual_ma_exit_klines = MagicMock(return_value=bars)
        s._maybe_fast_exit_on_dual_ma_break(bars[-1][4])
        s._clear_position.assert_called_once()
        self.assertIn("双均线破位", s._clear_position.call_args[0][0])
        s._update_radar_sl.assert_not_called()

    def test_break_without_volume_confirmation_only_tightens(self):
        """破位但量能没有真实放大(疑似假突破)——不清仓，只适度收紧止损。"""
        s = _mk_supervisor()
        s.radar.get_state.return_value = _FakeRadarState(current_sl=999.0, initial_atr=2.0)
        bars = _make_bars(decline_n=40, rally_n=10, surge=False)
        close_px = bars[-1][4]
        s._fetch_dual_ma_exit_klines = MagicMock(return_value=bars)
        s._maybe_fast_exit_on_dual_ma_break(close_px)
        s._clear_position.assert_not_called()
        s._update_radar_sl.assert_called_once()
        tightened = s._update_radar_sl.call_args[0][0]
        self.assertAlmostEqual(tightened, round(close_px + 0.3 * 2.0, 2), places=2)

    def test_soft_tighten_never_weaker_than_breakeven(self):
        """2026-09-13新增(宝贝拍板："双均线权重大于反转锁盈")：破位但放量
        未确认时，收紧结果不能比反转锁利本来会给的保本线更松——entry=100
        的SHORT，close刚好拉回到100(close+0.3×ATR=100.6比保本价99.91
        更松)，最终应该采用更紧的保本价99.91。"""
        s = _mk_supervisor()
        s.pipeline.data["entry"] = 100.0
        s.radar.get_state.return_value = _FakeRadarState(current_sl=200.0, initial_atr=2.0)
        bars = _make_bars(decline_n=25, decline_step=-1.0, rally_n=10, rally_step=1.0,
                           start=115.0, surge=False)
        self.assertEqual(bars[-1][4], 100.0)
        s._fetch_dual_ma_exit_klines = MagicMock(return_value=bars)
        s._maybe_fast_exit_on_dual_ma_break(bars[-1][4])
        s._clear_position.assert_not_called()
        s._update_radar_sl.assert_called_once()
        tightened = s._update_radar_sl.call_args[0][0]
        self.assertAlmostEqual(tightened, 99.91, places=2)

    def test_break_confirmed_same_bar_not_retriggered(self):
        s = _mk_supervisor()
        bars = _make_bars(decline_n=40, rally_n=10, surge=True)
        s._fetch_dual_ma_exit_klines = MagicMock(return_value=bars)
        s._maybe_fast_exit_on_dual_ma_break(bars[-1][4])
        s._dual_ma_exit_last_check_ts = 0.0  # 模拟节流窗口已过期
        s._maybe_fast_exit_on_dual_ma_break(bars[-1][4])
        s._clear_position.assert_called_once()

    def test_throttle_skips_refetch_within_window(self):
        s = _mk_supervisor()
        s._dual_ma_exit_last_check_ts = time.time()
        s.client.get_klines = MagicMock()
        s._maybe_fast_exit_on_dual_ma_break(90.0)
        s.client.get_klines.assert_not_called()

    def test_synthesizes_45m_from_15m_for_openai(self):
        """2026-09-13起：OPENAI从120分钟改成45分钟，不再原生直取，改用
        15分钟合成(跟BNB/XPD/XAU/XPT/XRP/SOL同一套)。"""
        s = _mk_supervisor(symbol="OPENAI")
        bars = _make_bars(decline_n=50, rally_n=0, period_min=15)
        s.client.get_klines = MagicMock(return_value=bars)
        s._maybe_fast_exit_on_dual_ma_break(bars[-1][4])
        args, kwargs = s.client.get_klines.call_args
        self.assertEqual(args[1], 15)  # 用15分钟原生base

    def test_synthesizes_45m_from_15m_for_bnb(self):
        s = _mk_supervisor(symbol="BNB")
        bars = _make_bars(decline_n=50, rally_n=0, period_min=15)
        s.client.get_klines = MagicMock(return_value=bars)
        s._maybe_fast_exit_on_dual_ma_break(bars[-1][4])
        args, kwargs = s.client.get_klines.call_args
        self.assertEqual(args[1], 15)  # 用15分钟原生base

    def test_synthesizes_75m_from_15m_for_sndk(self):
        s = _mk_supervisor(symbol="SNDK")
        bars = _make_bars(decline_n=80, rally_n=0, period_min=15)
        s.client.get_klines = MagicMock(return_value=bars)
        s._maybe_fast_exit_on_dual_ma_break(bars[-1][4])
        args, kwargs = s.client.get_klines.call_args
        self.assertEqual(args[1], 15)

    def test_klines_fetch_failure_is_safe_noop(self):
        s = _mk_supervisor()
        s.client.get_klines = MagicMock(side_effect=RuntimeError("boom"))
        s._maybe_fast_exit_on_dual_ma_break(90.0)
        s._clear_position.assert_not_called()

    def _sym_or(self, default):
        return default


if __name__ == "__main__":
    unittest.main(verbosity=2)
