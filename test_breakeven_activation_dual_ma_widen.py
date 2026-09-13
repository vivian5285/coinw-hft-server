#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-09-14："保本激活双均线加宽"(_dual_ma_activation_anchor +
_activate_radar里的组合逻辑)回归测试——跟币安B系统同一套用例，验证
CoinW侧的移植版本。

背景见position_supervisor_coinw.py::DUAL_MA_ACTIVATION_GATE_*常量顶部
注释：实盘复现(XPTUSDT)同一笔TV信号币安B/CoinW同时开空，币安B的雷达
激活公式(entry∓tick∓fee)完全按entry锚定、不看现价/ATR/趋势结构，价格
才刚朝有利方向走一点点就摸到激活线，止损立刻锁死在纯手续费保本位，
随后一次很正常的回踩就把这条贴着保本的止损打穿。CoinW用的是同一个
initial_stop_price公式，理论上有一样的风险。

方案：只在首次开仓(reentry_count==0)触发激活的那一刻，多看一眼双均线
状态——趋势仍成立时用"现价±0.5×ATR"替换纯保本位，取两者中更松的那个，
不松于综合硬止损，不紧于纯保本。

不碰任何真实账户/持仓，self.client/self.pipeline全部用测试替身，
self.radar用真实BreathStop实例(验证真实的activated/current_sl状态
转换)，dual_ma_trend用真实纯函数+合成K线。
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

ENTRY = 1790.88
ATR = 3.0007
ACTIVATION_PX = 1788.48


def _make_bars(decline_n=40, decline_step=-1.0, rally_n=0, rally_step=3.0,
               start=1830.0, period_min=15):
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
        bars.append([t0 + i * period_ms, px - rally_step, px + 0.5, px - 0.5, px, 100.0])
        i += 1
    return bars


class _FakePipeline:
    def __init__(self, side="SHORT", entry=ENTRY, hard_sl_px=1794.44):
        self.data = {
            "entry": entry,
            "side": side,
            "tier": "1",
            "position_id": "pos1",
            "tp2": {"px": entry - 4.0 if side == "SHORT" else entry + 4.0},
            "hard_sl_px": hard_sl_px,
        }


def _mk_supervisor(symbol="XPT", side="SHORT", entry=ENTRY, hard_sl_px=1794.44):
    s = object.__new__(psc.PositionSupervisorCoinW)
    s.symbol = symbol
    s.pipeline = _FakePipeline(side=side, entry=entry, hard_sl_px=hard_sl_px)
    s.radar = BreathStop(symbol)
    s.radar.set_atr(ATR)
    s.client = MagicMock()
    return s


def _breakeven(side, entry):
    from breath_stop import initial_stop_price
    import breath_profiles
    profile = breath_profiles.get_breath_profile(symbol="XPT")
    return round(float(initial_stop_price(side, entry, profile=profile)), 2)


class TestActivationWidenModeGate(unittest.TestCase):
    def setUp(self):
        os.environ.pop("DUAL_MA_ACTIVATION_GATE", None)
        psc.DUAL_MA_ACTIVATION_GATE_ENABLED = True

    def test_gate_off_no_klines_fetch_pure_breakeven(self):
        s = _mk_supervisor()
        s._fetch_dual_ma_exit_klines = MagicMock()
        psc.DUAL_MA_ACTIVATION_GATE_ENABLED = False
        try:
            s._activate_radar(ACTIVATION_PX)
        finally:
            psc.DUAL_MA_ACTIVATION_GATE_ENABLED = True
        s._fetch_dual_ma_exit_klines.assert_not_called()
        self.assertAlmostEqual(s.radar.get_state().current_sl, _breakeven("SHORT", ENTRY), places=2)


class TestActivationWidenBMode(unittest.TestCase):
    def test_first_open_trend_intact_widens_beyond_breakeven(self):
        """复现XPT实盘场景：双均线仍在保护内 → 止损从纯保本加宽到
        现价+0.5×ATR，而不是贴着保本被正常回踩打穿。"""
        s = _mk_supervisor()
        bars = _make_bars(decline_n=50, rally_n=0)  # 纯下跌，双均线判定空头趋势仍成立
        s._fetch_dual_ma_exit_klines = MagicMock(return_value=bars)
        s._activate_radar(ACTIVATION_PX)
        expected = ACTIVATION_PX + 0.5 * ATR
        self.assertAlmostEqual(s.radar.get_state().current_sl, round(expected, 2), places=2)
        self.assertGreater(s.radar.get_state().current_sl, _breakeven("SHORT", ENTRY))

    def test_reentry_not_widened_stays_pure_breakeven(self):
        s = _mk_supervisor()
        s.radar.set_reentry_count(1)
        bars = _make_bars(decline_n=50, rally_n=0)
        s._fetch_dual_ma_exit_klines = MagicMock(return_value=bars)
        s._activate_radar(ACTIVATION_PX)
        s._fetch_dual_ma_exit_klines.assert_not_called()
        self.assertAlmostEqual(s.radar.get_state().current_sl, _breakeven("SHORT", ENTRY), places=2)

    def test_trend_broken_falls_back_to_pure_breakeven(self):
        s = _mk_supervisor()
        bars = _make_bars(decline_n=30, rally_n=15, rally_step=3.0)  # 尾部大幅拉回，站上双均线
        s._fetch_dual_ma_exit_klines = MagicMock(return_value=bars)
        s._activate_radar(ACTIVATION_PX)
        self.assertAlmostEqual(s.radar.get_state().current_sl, _breakeven("SHORT", ENTRY), places=2)

    def test_klines_fetch_failure_falls_back_to_pure_breakeven(self):
        s = _mk_supervisor()
        s._fetch_dual_ma_exit_klines = MagicMock(side_effect=RuntimeError("boom"))
        s._activate_radar(ACTIVATION_PX)
        self.assertAlmostEqual(s.radar.get_state().current_sl, _breakeven("SHORT", ENTRY), places=2)

    def test_widen_never_exceeds_hard_stop_ceiling(self):
        s = _mk_supervisor(hard_sl_px=1789.60)  # 比正常加宽结果(1789.98)更紧
        bars = _make_bars(decline_n=50, rally_n=0)
        s._fetch_dual_ma_exit_klines = MagicMock(return_value=bars)
        s._activate_radar(ACTIVATION_PX)
        self.assertAlmostEqual(s.radar.get_state().current_sl, 1789.60, places=2)

    def test_widen_never_tighter_than_breakeven(self):
        s = _mk_supervisor()
        bars = _make_bars(decline_n=50, rally_n=0)
        s._fetch_dual_ma_exit_klines = MagicMock(return_value=bars)
        deep_px = 1780.0  # 现价已经远比激活线更有利，现价+0.5×ATR比纯保本更紧
        s._activate_radar(deep_px)
        self.assertAlmostEqual(s.radar.get_state().current_sl, _breakeven("SHORT", ENTRY), places=2)

    def test_long_side_mirrors_short_logic(self):
        s = _mk_supervisor(side="LONG", hard_sl_px=ENTRY - 5.0)
        act_px = ENTRY + 2.4
        bars = _make_bars(decline_n=0, rally_n=50, rally_step=1.0, start=1780.0)
        s._fetch_dual_ma_exit_klines = MagicMock(return_value=bars)
        s._activate_radar(act_px)
        breakeven = _breakeven("LONG", ENTRY)
        expected = round(min(breakeven, act_px - 0.5 * ATR), 2)
        self.assertAlmostEqual(s.radar.get_state().current_sl, expected, places=2)
        self.assertLess(s.radar.get_state().current_sl, breakeven)


if __name__ == "__main__":
    unittest.main(verbosity=2)
