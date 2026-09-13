#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-09-13："突发放量反转K线快速锁保本"(_maybe_fast_lock_on_impulse_candle)
回归测试——跟币安B系统(eth-webhook-server::test_impulse_candle_lock.py)
同一套用例，验证CoinW侧的移植版本。

背景见position_supervisor_coinw.py::IMPULSE_EXIT_*常量顶部注释：宝贝
实盘截图复盘发现"等阳线站上双均线再平仓就已经晚了"，这是三层防线里
最快的一层——不等双均线正式突破确认，只看最新一根K线自己够不够
"决定性"(实体够大+真放量)，够的话立刻锁到保本价。

不碰任何真实账户/持仓，self.client/self.radar/self.pipeline全部用测试
替身，breath_stop.initial_stop_price用真实纯函数。直接mock
_fetch_dual_ma_exit_klines(跳过CoinW 45/75分钟的15分钟合成细节，不是
这组测试关心的点，那部分already由test_dual_ma_fast_exit.py专门覆盖)。
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


def _make_bars(n=25, base_vol=100.0, last_body_ratio=0.7, last_vol_mult=2.0,
               bullish_last=True, period_min=45):
    bars = []
    t0 = 1_700_000_000_000
    period_ms = period_min * 60 * 1000
    px = 100.0
    for i in range(n - 1):
        o = px
        c = px - 0.1
        h = max(o, c) + 1.0
        l = min(o, c) - 1.0
        bars.append([t0 + i * period_ms, o, h, l, c, base_vol])
        px = c
    o = px
    rng = 5.0
    body = rng * last_body_ratio
    wick_each = (rng - body) / 2.0
    if bullish_last:
        c = o + body
        h = c + wick_each
        l = o - wick_each
    else:
        c = o - body
        h = o + wick_each
        l = c - wick_each
    bars.append([t0 + (n - 1) * period_ms, o, h, l, c, base_vol * last_vol_mult])
    return bars


class _FakePipeline:
    def __init__(self, side="SHORT", entry=100.0):
        self.data = {"side": side, "entry": entry}


class _FakeRadarState:
    def __init__(self, current_sl=200.0, initial_atr=2.0):
        self.current_sl = current_sl
        self.initial_atr = initial_atr


def _mk_supervisor(symbol="BNB", side="SHORT", current_sl=200.0):
    s = object.__new__(psc.PositionSupervisorCoinW)
    s.symbol = symbol
    s.pipeline = _FakePipeline(side)
    s.client = MagicMock()
    s.radar = MagicMock()
    s.radar.get_state.return_value = _FakeRadarState(current_sl=current_sl)
    s._safe_alert = MagicMock()
    s._update_radar_sl = MagicMock()
    s._fetch_dual_ma_exit_klines = MagicMock(return_value=[])
    s._impulse_exit_last_check_ts = 0.0
    s._impulse_exit_alerted_bar = 0
    return s


class TestImpulseCandleLock(unittest.TestCase):
    def test_flag_off_does_nothing(self):
        s = _mk_supervisor()
        psc.IMPULSE_EXIT_ENABLED = False
        try:
            s._maybe_fast_lock_on_impulse_candle(90.0)
            s._fetch_dual_ma_exit_klines.assert_not_called()
        finally:
            psc.IMPULSE_EXIT_ENABLED = True

    def test_no_position_does_nothing(self):
        s = _mk_supervisor(side="")
        s._maybe_fast_lock_on_impulse_candle(90.0)
        s._fetch_dual_ma_exit_klines.assert_not_called()

    def test_decisive_bullish_candle_with_volume_locks_breakeven_for_short(self):
        s = _mk_supervisor(side="SHORT")
        bars = _make_bars(bullish_last=True, last_body_ratio=0.9, last_vol_mult=2.0)
        s._fetch_dual_ma_exit_klines = MagicMock(return_value=bars)
        s._maybe_fast_lock_on_impulse_candle(bars[-1][4])
        s._update_radar_sl.assert_called_once_with(99.91)

    def test_decisive_bearish_candle_with_volume_locks_breakeven_for_long(self):
        s = _mk_supervisor(side="LONG", current_sl=0.0)
        bars = _make_bars(bullish_last=False, last_body_ratio=0.9, last_vol_mult=2.0)
        s._fetch_dual_ma_exit_klines = MagicMock(return_value=bars)
        s._maybe_fast_lock_on_impulse_candle(bars[-1][4])
        s._update_radar_sl.assert_called_once_with(100.09)

    def test_small_body_indecisive_candle_no_action(self):
        s = _mk_supervisor(side="SHORT")
        bars = _make_bars(bullish_last=True, last_body_ratio=0.2, last_vol_mult=2.0)
        s._fetch_dual_ma_exit_klines = MagicMock(return_value=bars)
        s._maybe_fast_lock_on_impulse_candle(bars[-1][4])
        s._update_radar_sl.assert_not_called()

    def test_decisive_candle_without_volume_no_action(self):
        s = _mk_supervisor(side="SHORT")
        bars = _make_bars(bullish_last=True, last_body_ratio=0.9, last_vol_mult=1.0)
        s._fetch_dual_ma_exit_klines = MagicMock(return_value=bars)
        s._maybe_fast_lock_on_impulse_candle(bars[-1][4])
        s._update_radar_sl.assert_not_called()

    def test_decisive_candle_in_favor_of_position_no_action(self):
        s = _mk_supervisor(side="SHORT")
        bars = _make_bars(bullish_last=False, last_body_ratio=0.9, last_vol_mult=2.0)
        s._fetch_dual_ma_exit_klines = MagicMock(return_value=bars)
        s._maybe_fast_lock_on_impulse_candle(bars[-1][4])
        s._update_radar_sl.assert_not_called()

    def test_does_not_loosen_already_tighter_candidate(self):
        s = _mk_supervisor(side="SHORT", current_sl=50.0)
        bars = _make_bars(bullish_last=True, last_body_ratio=0.9, last_vol_mult=2.0)
        s._fetch_dual_ma_exit_klines = MagicMock(return_value=bars)
        s._maybe_fast_lock_on_impulse_candle(bars[-1][4])
        s._update_radar_sl.assert_not_called()

    def test_throttle_skips_refetch_within_window(self):
        s = _mk_supervisor()
        s._impulse_exit_last_check_ts = time.time()
        s._maybe_fast_lock_on_impulse_candle(90.0)
        s._fetch_dual_ma_exit_klines.assert_not_called()

    def test_empty_klines_is_safe_noop(self):
        """_fetch_dual_ma_exit_klines自己内部已经吞掉了取K线异常(见
        test_dual_ma_fast_exit.py同款测试)，返回空列表——这里验证空
        输入不会让本方法出错或误触发。"""
        s = _mk_supervisor()
        s._fetch_dual_ma_exit_klines = MagicMock(return_value=[])
        s._maybe_fast_lock_on_impulse_candle(90.0)
        s._update_radar_sl.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
