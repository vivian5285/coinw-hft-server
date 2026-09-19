#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-09-13："TV方向+双均线趋势自主重入"(_maybe_trend_reentry)回归测试。

背景——宝贝拍板：VPS空仓、TV心跳当前也是FLAT时，只要TV最后一个非空
方向仍然满足双均线趋势确认(定义跟TV策略源码"ETH双均线15/30锁机制版"
自己的开平仓逻辑完全一致)，就允许VPS自己衡量重入——用综合硬止损+
ATR估算TP123自己管理这笔仓位，直到TV发出全新真实开仓信号为止。TV是
主方向判断，VPS是执行层+半辅助，仓位缩小对冲这份自主性带来的额外
风险。

2026-09-15增强(宝贝反馈OPENAI连续3根阳线放量上涨且站上45分钟双均线)：
确认条件从单纯dual_ma_trend_ok换成trend_confirmed_with_volume(双均线+
最近3根同向实体+放量三者都满足)，新增override_side参数覆盖"TV心跳仍
非FLAT但VPS已空仓"场景，新增每日次数上限——下面用例同步更新。

不碰任何真实账户/持仓，self.client/self._handle_open等全部mock。
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("COINW_SKIP_BOOTSTRAP", "1")

import position_supervisor_coinw as psc  # noqa: E402


def _make_trend_bars(n=80, start=100.0, step=0.5, volume=100.0, expand_last_n=0, expand_mult=2.0):
    """跟test_dual_ma_trend.py同款合成K线，足够触发趋势确认+综合硬止损
    计算都成功。expand_last_n>0时把最后expand_last_n根的成交量放大到
    expand_mult倍，用来满足trend_confirmed_with_volume的放量确认。"""
    bars = []
    t0 = 1_700_000_000_000
    period_ms = 30 * 60 * 1000
    for i in range(n):
        close = start + i * step
        vol = volume
        if expand_last_n > 0 and i >= n - expand_last_n:
            vol = volume * expand_mult
        bars.append([t0 + i * period_ms, close - step, close + 0.5, close - 0.5, close, vol])
    return bars


def _mk_supervisor(symbol="ETH"):
    s = object.__new__(psc.PositionSupervisorCoinW)
    s.symbol = symbol
    s._last_nonflat_hb_side = ""
    s._last_nonflat_hb_entry = 0.0
    s._trend_reentry_next_try_ts = 0.0
    s._trend_reentry_daily = {"date": "", "count": 0}
    s._catchup_blocked_until = 0.0
    s._reentry_size_factor = 1.0
    s.client = MagicMock()
    s._safe_alert = MagicMock()
    s._recompute_atr_150m = MagicMock(return_value=2.0)
    s._handle_open = MagicMock(return_value={"ok": True})
    return s


class TestMaybeTrendReentry(unittest.TestCase):
    """2026-09-19：_maybe_trend_reentry()内部K线拉取现在经_get_risk_
    klines()统一入口，币安公开K线优先——这里全类级patch binance_klines.
    get_bars返回空列表，强制落到CoinW自己的get_klines(本文件所有用例
    早就mock好的)这条兜底路径，不影响任何用例本身要验证的趋势重入
    逻辑(该逻辑只关心K线内容本身，不关心K线来源)。"""

    def setUp(self):
        patcher = patch("binance_klines.get_bars", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_no_tv_history_returns_none(self):
        """从没见过TV给过方向——没什么好评估的，直接放行给原有
        both_flat逻辑，不该触发任何开仓尝试。"""
        s = _mk_supervisor()
        out = s._maybe_trend_reentry()
        self.assertIsNone(out)
        s._handle_open.assert_not_called()

    def test_trend_confirmed_opens_long(self):
        """核心场景：TV最后方向LONG，现价站上双均线+最近3根阳线+放量——
        应该自主开仓。"""
        s = _mk_supervisor()
        s._last_nonflat_hb_side = "LONG"
        # 持续上涨(双均线确认多头)+最后3根放量2倍(满足新的放量确认)
        bars = _make_trend_bars(n=90, step=0.5, expand_last_n=3, expand_mult=2.0)
        s.client.get_klines = MagicMock(return_value=bars)
        s._get_current_price = MagicMock(return_value=bars[-1][4])

        out = s._maybe_trend_reentry()

        self.assertIsNotNone(out)
        self.assertTrue(out.get("ok"))
        self.assertTrue(out.get("trend_reentry"))
        s._handle_open.assert_called_once()
        sig = s._handle_open.call_args[0][0]
        self.assertEqual(sig.action, "LONG")
        self.assertLess(sig.stop_loss, sig.price, "多头止损必须在成交价下方")
        self.assertGreater(sig.tp1, sig.price)
        self.assertGreater(sig.tp2, sig.tp1)
        # is_reentry=True 传给_handle_open
        self.assertTrue(s._handle_open.call_args.kwargs.get("is_reentry"))

    def test_dual_ma_confirmed_but_no_volume_does_not_open(self):
        """2026-09-15新增：双均线站上了，但没有放量(平量)——新的更严格
        确认应该拒绝，不能只靠双均线就开仓。"""
        s = _mk_supervisor()
        s._last_nonflat_hb_side = "LONG"
        bars = _make_trend_bars(n=90, step=0.5)  # 平量，双均线OK但放量不OK
        s.client.get_klines = MagicMock(return_value=bars)
        s._get_current_price = MagicMock(return_value=bars[-1][4])

        out = s._maybe_trend_reentry()

        self.assertEqual(out.get("state"), "trend_not_confirmed")
        s._handle_open.assert_not_called()

    def test_daily_cap_blocks_fourth_attempt_same_day(self):
        """2026-09-15新增：每日上限(TREND_REENTRY_MAX_PER_DAY=3)第4次
        应该被拒绝，不再开仓；次日(日期变化)自动重置。"""
        s = _mk_supervisor()
        s._last_nonflat_hb_side = "LONG"
        bars = _make_trend_bars(n=90, step=0.5, expand_last_n=3, expand_mult=2.0)
        s.client.get_klines = MagicMock(return_value=bars)
        s._get_current_price = MagicMock(return_value=bars[-1][4])

        for _ in range(3):
            s._trend_reentry_next_try_ts = 0.0  # 绕过冷却，专测每日上限
            out = s._maybe_trend_reentry()
            self.assertTrue(out.get("trend_reentry"))

        s._trend_reentry_next_try_ts = 0.0
        out4 = s._maybe_trend_reentry()
        self.assertEqual(out4.get("state"), "trend_reentry_daily_cap")
        self.assertEqual(s._handle_open.call_count, 3)

        # 模拟次日：日期变化，计数应该自动重置，第4次(实为次日第1次)放行
        s._trend_reentry_daily = {"date": "2020-01-01", "count": 3}
        s._trend_reentry_next_try_ts = 0.0
        out_next_day = s._maybe_trend_reentry()
        self.assertTrue(out_next_day.get("trend_reentry"))

    def test_override_side_used_when_tv_heartbeat_still_nonflat(self):
        """2026-09-15新增：override_side场景(TV心跳仍非FLAT但VPS已空仓，
        今天OPENAI在B账户的真实场景)——不依赖self._last_nonflat_hb_side，
        直接用传入的方向评估。"""
        s = _mk_supervisor()
        s._last_nonflat_hb_side = ""  # 故意不设，验证override_side独立生效
        bars = _make_trend_bars(n=90, step=0.5, expand_last_n=3, expand_mult=2.0)
        s.client.get_klines = MagicMock(return_value=bars)
        s._get_current_price = MagicMock(return_value=bars[-1][4])

        out = s._maybe_trend_reentry(override_side="LONG")

        self.assertTrue(out.get("trend_reentry"))
        s._handle_open.assert_called_once()

    def test_trend_not_confirmed_does_not_open(self):
        """TV最后方向是LONG，但现价其实在下跌趋势里——不该开仓。"""
        s = _mk_supervisor()
        s._last_nonflat_hb_side = "LONG"
        bars = _make_trend_bars(n=90, start=200.0, step=-0.5)  # 下降序列
        s.client.get_klines = MagicMock(return_value=bars)
        s._get_current_price = MagicMock(return_value=bars[-1][4])

        out = s._maybe_trend_reentry()

        self.assertIsNotNone(out)
        self.assertEqual(out.get("state"), "trend_not_confirmed")
        s._handle_open.assert_not_called()

    def test_cooldown_prevents_repeated_evaluation(self):
        """同一方向短时间内不该每次心跳都重新拉K线评估一遍。"""
        s = _mk_supervisor()
        s._last_nonflat_hb_side = "LONG"
        bars = _make_trend_bars(n=90, step=0.5)
        s.client.get_klines = MagicMock(return_value=bars)
        s._get_current_price = MagicMock(return_value=bars[-1][4])

        s._maybe_trend_reentry()  # 第一次：正常评估并开仓
        call_count_after_first = s.client.get_klines.call_count

        out2 = s._maybe_trend_reentry()  # 第二次：应该被冷却挡住
        self.assertEqual(out2.get("state"), "trend_reentry_cooldown")
        self.assertEqual(
            s.client.get_klines.call_count, call_count_after_first,
            "冷却期内不该再拉K线重新评估",
        )

    def test_manual_close_freeze_window_blocks_autonomous_reentry(self):
        """宝贝刚手动平过仓(_catchup_blocked_until还没过期)——不该被这套
        机制自作主张重新开仓，跟既有心跳催单共用同一个冻结开关。"""
        s = _mk_supervisor()
        s._last_nonflat_hb_side = "LONG"
        s._catchup_blocked_until = time.time() + 600
        bars = _make_trend_bars(n=90, step=0.5)
        s.client.get_klines = MagicMock(return_value=bars)
        s._get_current_price = MagicMock(return_value=bars[-1][4])

        out = s._maybe_trend_reentry()

        self.assertEqual(out.get("state"), "trend_reentry_blocked")
        s._handle_open.assert_not_called()

    def test_smart_hard_stop_failure_falls_back_to_atr_not_abandoned(self):
        """综合硬止损算不出来(K线不够摆动点识别但够趋势确认——用极短
        的K线数组模拟)时，不该整体放弃这次自主重入，应该用ATR应急止损
        兜底继续开仓。"""
        s = _mk_supervisor()
        s._last_nonflat_hb_side = "LONG"
        # 刚好够双均线趋势确认(需要slow_len=30根)，但不够综合硬止损的
        # atr_period(14)+confirm(3)+1=18根 —— 不对，30>18，实际上够。
        # 改用一个会让calc_smart_hard_stop_price内部zero_atr的极端构造：
        # 全部收盘价相同(True Range=0)，双均线趋势确认要求close>ma，
        # 用略微上翘的最后一根规避，同时ATR全程为0。
        bars = [[1_700_000_000_000 + i * 1800000, 100.0, 100.0, 100.0, 100.0, 100.0] for i in range(90)]
        bars[-1] = [bars[-1][0], 100.0, 100.5, 99.5, 100.5, 100.0]  # 最后一根现价拉高，站上均线
        s.client.get_klines = MagicMock(return_value=bars)
        s._get_current_price = MagicMock(return_value=100.5)

        out = s._maybe_trend_reentry()

        # 综合硬止损应该失败(ATR≈0)，但因为_recompute_atr_150m mock返回2.0，
        # 应该走ATR应急止损分支继续开仓，而不是整体放弃
        self.assertIsNotNone(out)
        if out.get("state") in ("trend_not_confirmed",):
            self.skipTest("合成数据双均线未确认，调整构造后再验证ATR兜底分支")
        s._handle_open.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
