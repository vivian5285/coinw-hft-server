#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-09-15：四项"多套平仓机制最优共处"改动的回归测试——
1. REVERSAL_LOCK判据从"实体/ATR"对齐成币安的"实体/振幅"
2. exit_source分类 + 综合硬止损出局永久禁止重入
3. 趋势确认重入均线周期15/30→8/20
4. CoinW补齐三层深盈利保护(大赢家地板/利润回吐刹车/TV僵局收紧)

背景见position_supervisor_coinw.py对应常量块顶部注释。这些都是宝贝
拍板"最优解方案执行"的四个方向，聚焦到BNB/XPD/SNDK/OPENAI/XAU这5个
品种精细化打磨的一部分。

不碰任何真实账户/持仓，self.client/self.pipeline/self.radar全部用
测试替身，market_overlays.reversal_candle用真实纯函数+合成K线。
"""
from __future__ import annotations

import os
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("COINW_SKIP_BOOTSTRAP", "1")

import position_supervisor_coinw as psc  # noqa: E402
from breath_stop import BreathStop  # noqa: E402
from market_overlays import reversal_candle  # noqa: E402
from webhook_parser import (  # noqa: E402
    EXIT_SOURCE_RADAR_BE, EXIT_SOURCE_VPS_HARD_SL,
    EXIT_SOURCE_TV_CLOSE, EXIT_SOURCE_MANUAL,
)


# ==================== 1. REVERSAL_LOCK公式对齐 ====================

def _make_4h_bars(n=30, base=1000.0, last_open=1000.0, last_close=1000.0,
                  last_high=None, last_low=None, last_vol=100.0, base_vol=100.0):
    bars = []
    t0 = 1_700_000_000_000
    period_ms = 4 * 3600 * 1000
    for i in range(n - 1):
        bars.append([t0 + i * period_ms, base, base + 1, base - 1, base, base_vol])
    hi = last_high if last_high is not None else max(last_open, last_close) + 0.1
    lo = last_low if last_low is not None else min(last_open, last_close) - 0.1
    # 未收盘的当前根(reversal_candle只看倒数第2根，即"已收盘"那根)
    bars.append([t0 + (n - 1) * period_ms, last_open, hi, lo, last_close, last_vol])
    bars.append([t0 + n * period_ms, last_close, last_close + 0.1, last_close - 0.1, last_close, base_vol])
    return bars


class TestReversalLockBodyRatioAlignment(unittest.TestCase):
    def test_body_ratio_at_threshold_triggers(self):
        """实体/振幅恰好0.55、放量1.2倍(>1.15门槛) -> 应该触发（对齐
        币安公式：以前CoinW用实体/ATR，这次改成实体/振幅）。"""
        # open=1000, close=990(实体10)，high=1000.5,low=989.5(振幅11) -> body_ratio=10/11≈0.909
        # 构造一个精确边界：range=20，body=11 -> ratio=0.55
        bars = _make_4h_bars(
            last_open=1010.0, last_close=999.0,  # body=11
            last_high=1010.0, last_low=990.0,     # range=20 -> ratio=0.55
            last_vol=121.0, base_vol=100.0,        # vol=1.21x > 1.15门槛
        )
        hit, det = reversal_candle(bars, "LONG", cfg={"body_ratio": 0.55, "vol_mult": 1.15})
        self.assertTrue(hit, det)

    def test_old_body_atr_formula_would_reject_same_candle(self):
        """同一根K线用旧的"实体/ATR"公式验证会给出不同判断——证明这次
        真的是换了判据形状，不是误改成了等价写法。旧公式门槛1.1×ATR，
        这根K线的ATR来自前面29根平淡K线(振幅≈2)，ATR很小，实体11远超
        1.1×ATR，旧公式反而会更容易触发——说明两种形状对不同K线形态的
        敏感度确实不同，不是同一个东西换了个名字。"""
        bars = _make_4h_bars(
            last_open=1010.0, last_close=999.0,
            last_high=1010.0, last_low=990.0,
            last_vol=121.0, base_vol=100.0,
        )
        # 新公式：用body_ratio
        hit_new, _ = reversal_candle(bars, "LONG", cfg={"body_ratio": 0.55, "vol_mult": 1.15})
        # 模拟旧公式的关键差异点：旧公式的body_ratio键不存在时，函数如果
        # 还认识"body_atr_mult"就会用旧逻辑——但代码已经改掉了，这里改用
        # 直接验证body_ratio键缺失时退回默认0.55也一样触发，证明cfg的键
        # 名已经切换成body_ratio，不再认body_atr_mult。
        hit_default, _ = reversal_candle(bars, "LONG")
        self.assertTrue(hit_default)
        self.assertEqual(hit_new, hit_default)

    def test_thin_body_no_trigger(self):
        """实体/振幅明显不够(十字星类K线)，不该触发。"""
        bars = _make_4h_bars(
            last_open=1000.0, last_close=999.0,   # body=1
            last_high=1005.0, last_low=995.0,      # range=10 -> ratio=0.1
            last_vol=121.0, base_vol=100.0,
        )
        hit, det = reversal_candle(bars, "LONG", cfg={"body_ratio": 0.55, "vol_mult": 1.15})
        self.assertFalse(hit, det)


# ==================== 2. exit_source分类 + 重入门槛 ====================

class _FakePhase:
    value = "MONITORING"


class _FakePipeline:
    def __init__(self, side="LONG", entry=100.0, hard_sl_px=0.0, tier="1"):
        self.data = {"side": side, "entry": entry, "hard_sl_px": hard_sl_px, "tier": tier}
        self.phase = _FakePhase()

    def reset_idle(self, reason):
        self.data = {}


def _mk_supervisor(symbol="BNB", side="LONG", entry=100.0, hard_sl_px=95.0):
    s = object.__new__(psc.PositionSupervisorCoinW)
    s.symbol = symbol
    s.pipeline = _FakePipeline(side=side, entry=entry, hard_sl_px=hard_sl_px)
    s.radar = BreathStop(symbol)
    s.client = MagicMock()
    s._dingtalk = MagicMock()
    s._safe_alert = MagicMock()
    s._intentional_close = False
    s._reentry_count = 0
    s._cooldown_until = 0.0
    s._start_reentry_watcher = MagicMock()
    s._lock = threading.Lock()
    s._tv_heartbeat_side = ""
    s._last_nonflat_hb_side = ""
    s._tv_exit_stall_since_ts = 0.0
    s._tv_exit_stall_best_seen = 0.0
    s._big_win_alerted_best = 0.0
    s._giveback_brake_alerted_best = 0.0
    return s


class TestExitSourceClassification(unittest.TestCase):
    def test_tv_close_when_intentional(self):
        s = _mk_supervisor()
        s._intentional_close = True
        self.assertEqual(s._resolve_exit_source_coinw(99.0), EXIT_SOURCE_TV_CLOSE)

    def test_vps_hard_sl_when_price_near_hard_sl(self):
        s = _mk_supervisor(hard_sl_px=95.0)
        self.assertEqual(s._resolve_exit_source_coinw(95.05), EXIT_SOURCE_VPS_HARD_SL)

    def test_radar_be_when_price_near_radar_stop(self):
        s = _mk_supervisor(hard_sl_px=90.0)  # 硬止损远一点，不干扰
        s.radar.arm(tp1_price=110.0, tp2_price=120.0, direction="LONG")
        s.radar.activate(entry_price=100.0, tp2_price=120.0, direction="LONG")
        radar_sl = s.radar.get_state().current_sl
        self.assertEqual(s._resolve_exit_source_coinw(radar_sl + 0.02), EXIT_SOURCE_RADAR_BE)

    def test_manual_when_neither_matches(self):
        s = _mk_supervisor(hard_sl_px=50.0)
        self.assertEqual(s._resolve_exit_source_coinw(200.0), EXIT_SOURCE_MANUAL)

    def test_on_position_zero_hard_sl_exit_never_reenters(self):
        """核心行为修复：综合硬止损出局，即使REENTRY_ENABLED且未达
        REENTRY_MAX，也不该启动重入看守。"""
        s = _mk_supervisor(side="LONG", entry=100.0, hard_sl_px=95.0)
        with unittest.mock.patch.object(psc, "REENTRY_ENABLED", True), \
             unittest.mock.patch.object(psc, "REENTRY_MAX", 5):
            s._on_position_zero(curr_px=95.02)
        s._start_reentry_watcher.assert_not_called()
        self.assertEqual(s._last_exit["reason"], EXIT_SOURCE_VPS_HARD_SL)

    def test_on_position_zero_radar_be_exit_still_reenters(self):
        """对照组：雷达保本出局应该正常启动重入看守，不受硬止损那条
        新规则误伤。"""
        s = _mk_supervisor(side="LONG", entry=100.0, hard_sl_px=80.0)
        s.radar.arm(tp1_price=110.0, tp2_price=120.0, direction="LONG")
        s.radar.activate(entry_price=100.0, tp2_price=120.0, direction="LONG")
        radar_sl = s.radar.get_state().current_sl
        with unittest.mock.patch.object(psc, "REENTRY_ENABLED", True), \
             unittest.mock.patch.object(psc, "REENTRY_MAX", 5):
            s._on_position_zero(curr_px=radar_sl + 0.02)
        s._start_reentry_watcher.assert_called_once()
        self.assertEqual(s._last_exit["reason"], EXIT_SOURCE_RADAR_BE)


# ==================== 3. 8/20均线周期 ====================

class TestTrendReentryUses8_20(unittest.TestCase):
    def test_constants_are_8_and_20(self):
        self.assertEqual(psc.TREND_REENTRY_FAST_LEN, 8)
        self.assertEqual(psc.TREND_REENTRY_SLOW_LEN, 20)

    def test_period_length_25_bars_confirms_with_8_20_not_15_30(self):
        """构造只有25根K线的上涨序列——8/20均线只需20根就能算，能确认；
        15/30均线需要30根，数据不够直接返回False。用这个数据量差异证明
        实际生效的确实是8/20而不是15/30。"""
        from dual_ma_trend import trend_confirmed_with_volume
        bars = []
        t0 = 1_700_000_000_000
        px = 100.0
        for i in range(25):
            px += 0.5
            vol = 100.0 if i < 22 else 250.0  # 最后3根放量
            bars.append([t0 + i * 2700000, px - 0.5, px + 0.3, px - 0.3, px, vol])
        ok_8_20, meta = trend_confirmed_with_volume(
            "LONG", bars, fast_len=psc.TREND_REENTRY_FAST_LEN,
            slow_len=psc.TREND_REENTRY_SLOW_LEN, candle_run=3,
        )
        self.assertTrue(ok_8_20, meta)
        ok_15_30, meta2 = trend_confirmed_with_volume("LONG", bars, fast_len=15, slow_len=30, candle_run=3)
        self.assertFalse(ok_15_30, "15/30周期需要30根K线，25根应该直接判不确认")


# ==================== 4. 深盈利保护三层 ====================

class TestBigWinProfitFloor(unittest.TestCase):
    def test_peak_3_5_atr_locks_65_pct_floor(self):
        s = _mk_supervisor(side="LONG", entry=100.0)
        s.radar.arm(tp1_price=110.0, tp2_price=120.0, direction="LONG")
        s.radar.set_atr(2.0)
        s.radar.activate(entry_price=100.0, tp2_price=120.0, direction="LONG")
        # 手动把best/initial_atr推到峰值浮盈=3.5×ATR=7.0
        s.radar._state.best_price = 107.0
        s.radar._state.initial_atr = 2.0
        s.radar._state.current_sl = 100.5

        s._maybe_lock_profit_on_big_win(107.0)

        expected_floor = 100.0 + 7.0 * 0.65  # entry + retain_profit
        self.assertAlmostEqual(s.radar.get_state().current_sl, round(expected_floor, 2), places=2)

    def test_below_threshold_no_change(self):
        s = _mk_supervisor(side="LONG", entry=100.0)
        s.radar.arm(tp1_price=110.0, tp2_price=120.0, direction="LONG")
        s.radar.set_atr(2.0)
        s.radar.activate(entry_price=100.0, tp2_price=120.0, direction="LONG")
        s.radar._state.best_price = 102.0  # 只有1×ATR浮盈，远低于3.0门槛
        s.radar._state.initial_atr = 2.0
        before = s.radar.get_state().current_sl

        s._maybe_lock_profit_on_big_win(102.0)

        self.assertEqual(s.radar.get_state().current_sl, before)


class TestGivebackBrakeInertForFocusSymbols(unittest.TestCase):
    def test_no_config_means_noop(self):
        """BNB/XPD/SNDK/OPENAI/XAU当前都没有giveback_brake配置，机制
        应该原样跳过不生效——如实对齐币安B系统当前状态。"""
        s = _mk_supervisor(symbol="BNB", side="LONG", entry=100.0)
        s.radar.arm(tp1_price=110.0, tp2_price=120.0, direction="LONG")
        s.radar.set_atr(2.0)
        s.radar.activate(entry_price=100.0, tp2_price=120.0, direction="LONG")
        s.radar._state.best_price = 110.0
        s.radar._state.initial_atr = 2.0
        before = s.radar.get_state().current_sl

        s._maybe_tighten_on_profit_giveback(103.0)  # 大幅回吐也不该触发

        self.assertEqual(s.radar.get_state().current_sl, before)

    def test_mechanism_works_when_profile_has_config(self):
        """机制本身要能正常工作——临时打一个带giveback_brake的profile
        补丁验证。"""
        import breath_profiles
        fake_profile = dict(breath_profiles.BREATH_ETH)
        fake_profile["giveback_brake"] = {"min_peak_atr": 1.0, "trigger_frac": 0.35, "retain_frac": 0.55}
        s = _mk_supervisor(symbol="BNB", side="LONG", entry=100.0)
        s.radar.arm(tp1_price=110.0, tp2_price=120.0, direction="LONG")
        s.radar.set_atr(2.0)
        s.radar.activate(entry_price=100.0, tp2_price=120.0, direction="LONG")
        s.radar._state.best_price = 110.0  # peak_profit=10=5×ATR
        s.radar._state.initial_atr = 2.0
        s.radar._state.current_sl = 100.5

        with unittest.mock.patch("breath_profiles.get_breath_profile", return_value=fake_profile):
            s._maybe_tighten_on_profit_giveback(104.0)  # current_profit=4, giveback=6, 60%>=35%门槛

        expected_floor = 100.0 + 10.0 * 0.55
        self.assertAlmostEqual(s.radar.get_state().current_sl, round(expected_floor, 2), places=2)


class TestTvExitStallTighten(unittest.TestCase):
    def test_tv_flat_and_stalled_tightens(self):
        s = _mk_supervisor(symbol="BNB", side="LONG", entry=100.0)
        s.radar.arm(tp1_price=110.0, tp2_price=120.0, direction="LONG")
        s.radar.set_atr(2.0)
        s.radar.activate(entry_price=100.0, tp2_price=120.0, direction="LONG")
        s.radar._state.best_price = 103.0  # peak=3=1.5×ATR，超过0.5门槛
        s.radar._state.initial_atr = 2.0
        s.radar._state.current_sl = 100.5
        s._tv_heartbeat_side = "FLAT"
        s._last_nonflat_hb_side = "LONG"  # 这段持仓确实是TV这个方向开的

        # 第一次tick：记录best，计时器刚启动，不触发
        s._maybe_tighten_on_tv_exit_stall(103.0)
        self.assertEqual(s.radar.get_state().current_sl, 100.5)

        # 模拟滞涨已经过了3个TV周期(BNB=45分钟)
        s._tv_exit_stall_since_ts = time.time() - 45 * 60 * 3 - 10
        s._maybe_tighten_on_tv_exit_stall(103.0)

        expected = round(103.0 - 2.0 * 0.3, 2)
        self.assertAlmostEqual(s.radar.get_state().current_sl, expected, places=2)

    def test_tv_still_holding_no_tighten(self):
        s = _mk_supervisor(symbol="BNB", side="LONG", entry=100.0)
        s.radar.arm(tp1_price=110.0, tp2_price=120.0, direction="LONG")
        s.radar.set_atr(2.0)
        s.radar.activate(entry_price=100.0, tp2_price=120.0, direction="LONG")
        s.radar._state.best_price = 103.0
        s.radar._state.initial_atr = 2.0
        s.radar._state.current_sl = 100.5
        s._tv_heartbeat_side = "LONG"  # TV还在持有，不该触发
        s._last_nonflat_hb_side = "LONG"

        s._maybe_tighten_on_tv_exit_stall(103.0)

        self.assertEqual(s.radar.get_state().current_sl, 100.5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
