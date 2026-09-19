#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-09-19：CoinW"风险计算"类K线统一改拉币安公开数据(_get_risk_klines)
的专用回归测试。

背景见position_supervisor_coinw.py::_get_risk_klines()顶部注释——OPENAI
/XPD/XAU两边算出来的综合硬止损经常对不上，根源是CoinW自己的行情深度比
币安薄，偶尔一笔稍大的单子就能在CoinW自己的K线上制造一个"假摆动点"。
宝贝拍板：统一改拉币安公开K线做风险计算，CoinW自己的K线只做兜底。

这里验证：
1. 主路径——币安公开K线可用时，正确拼symbol(f"{symbol}USDT")+周期
   字符串(f"{interval_min}m")，正确转换回[[t,o,h,l,c,v],...]格式。
2. 兜底路径——币安拉取异常/为空时，原生粒度落到CoinW自己的get_klines，
   45/75分钟这类非原生粒度落到15分钟合成。
3. 45分钟死取数bug回归——_maybe_trend_reentry此前直接用self.client.
   get_klines(self.symbol, 45, ...)，CoinW原生粒度集合里根本没有45，
   一直在默默拉空列表；现在经_get_risk_klines()统一入口后能真正拿到
   K线(币安主路径命中)。

不碰任何真实账户/持仓，self.client全部mock；binance_klines.get_bars
用mock构造好的已知K线验证，不发真实网络请求。
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
    s.client = MagicMock()
    return s


def _bn_bar(t, o, h, l, c, v):
    return {"t": t, "o": o, "h": h, "l": l, "c": c, "v": v, "tb": 0.0}


class TestGetRiskKlinesBinancePrimary(unittest.TestCase):
    def test_uses_binance_public_klines_when_available(self):
        """核心场景：币安公开K线可用——应该直接用，不碰CoinW自己的
        get_klines。"""
        s = _mk_supervisor(symbol="OPENAI")
        bn_bars = [_bn_bar(1_700_000_000_000 + i * 60000, 1400 + i, 1401 + i,
                            1399 + i, 1400.5 + i, 10.0) for i in range(5)]
        with patch("binance_klines.get_bars", return_value=bn_bars) as mock_get:
            out = s._get_risk_klines(45, 5)

        mock_get.assert_called_once_with("OPENAIUSDT", "45m", limit=5)
        s.client.get_klines.assert_not_called()
        self.assertEqual(len(out), 5)
        self.assertEqual(out[0], [bn_bars[0]["t"], bn_bars[0]["o"], bn_bars[0]["h"],
                                   bn_bars[0]["l"], bn_bars[0]["c"], bn_bars[0]["v"]])

    def test_symbol_and_interval_string_construction(self):
        """品种映射跟币安B系统symbol_config.py早就验证过的{symbol}USDT
        完全一致；周期字符串是纯数字分钟数+'m'。"""
        s = _mk_supervisor(symbol="XPD")
        with patch("binance_klines.get_bars", return_value=[]) as mock_get:
            s._get_risk_klines(30, 400)
        mock_get.assert_called_once_with("XPDUSDT", "30m", limit=400)


class TestGetRiskKlinesFallback(unittest.TestCase):
    def test_binance_empty_falls_back_to_coinw_native(self):
        """币安返回空列表(限流/网络问题) + 原生粒度(30分钟) → 落到
        CoinW自己的get_klines。"""
        s = _mk_supervisor(symbol="OPENAI")
        native_bars = [[1, 2, 3, 4, 5, 6]]
        s.client.get_klines = MagicMock(return_value=native_bars)
        with patch("binance_klines.get_bars", return_value=[]):
            out = s._get_risk_klines(30, 400)
        s.client.get_klines.assert_called_once_with("OPENAI", 30, 400)
        self.assertEqual(out, native_bars)

    def test_binance_exception_falls_back_to_coinw_native(self):
        """币安公开K线拉取直接抛异常(网络不通)——不能让整个调用崩溃，
        安全降级到CoinW自己的K线。"""
        s = _mk_supervisor(symbol="XAU")
        native_bars = [[1, 2, 3, 4, 5, 6]]
        s.client.get_klines = MagicMock(return_value=native_bars)
        with patch("binance_klines.get_bars", side_effect=RuntimeError("网络不通")):
            out = s._get_risk_klines(60, 400)
        s.client.get_klines.assert_called_once_with("XAU", 60, 400)
        self.assertEqual(out, native_bars)

    def test_binance_empty_45m_falls_back_to_15m_synthesis(self):
        """核心回归——45分钟这类CoinW非原生粒度：币安拉不到时，不能
        直接返回空，要落到CoinW自己15分钟K线合成这条二级兜底。"""
        s = _mk_supervisor(symbol="OPENAI")
        s._synth_klines_via_coinw_15m = MagicMock(return_value=[[9, 9, 9, 9, 9, 9]])
        with patch("binance_klines.get_bars", return_value=[]):
            out = s._get_risk_klines(45, 60)
        s._synth_klines_via_coinw_15m.assert_called_once_with(45, 60)
        self.assertEqual(out, [[9, 9, 9, 9, 9, 9]])

    def test_both_binance_and_coinw_fallback_unavailable_returns_empty(self):
        """币安拉不到 + 非原生/非45/75的怪异周期 → 安全返回空列表，
        不崩溃。"""
        s = _mk_supervisor(symbol="OPENAI")
        with patch("binance_klines.get_bars", return_value=[]):
            out = s._get_risk_klines(50, 60)
        self.assertEqual(out, [])


class TestTrendReentry45mDeadFetchRegression(unittest.TestCase):
    """2026-09-15自引入的真实回归bug：TREND_REENTRY_KLINE_INTERVAL_MIN
    从30改成45之后，_maybe_trend_reentry原来直接调用self.client.
    get_klines(self.symbol, 45, ...)——45不在CoinW原生粒度集合{1,3,5,
    15,30,60,120,240,360,480,1440,10080}里，一直在默默拉空列表，"趋势
    确认多次重入"机制在CoinW上从未真正跑起来过。这里验证修复前的样子
    确实会死取数，修复后(经_get_risk_klines统一入口)币安主路径能正常
    拿到K线。"""

    def test_45_not_in_coinw_native_granularity(self):
        """复现bug本身：45压根不在CoinW原生支持的K线粒度集合里。"""
        s = _mk_supervisor(symbol="OPENAI")
        self.assertNotIn(45, s._COINW_NATIVE_GRAN)

    def test_old_direct_call_pattern_would_return_empty(self):
        """修复前的调用方式——直接传45分钟给CoinW自己的get_klines，
        真实CoinW SDK会拒绝/返回空(这里用mock模拟"不支持的粒度返回
        空"这一真实行为)。"""
        s = _mk_supervisor(symbol="OPENAI")

        def fake_get_klines(symbol, interval_min, limit):
            if interval_min not in s._COINW_NATIVE_GRAN:
                return []
            return [[1, 2, 3, 4, 5, 6]]

        s.client.get_klines = MagicMock(side_effect=fake_get_klines)
        self.assertEqual(s.client.get_klines(s.symbol, 45, 60), [])

    def test_get_risk_klines_fixes_45m_via_binance_primary_path(self):
        """修复后：_get_risk_klines(45, ...)经币安公开K线主路径正常
        拿到数据，不再依赖CoinW原生粒度集合。"""
        s = _mk_supervisor(symbol="OPENAI")
        bn_bars = [_bn_bar(1_700_000_000_000 + i * 45 * 60000, 1400 + i,
                            1401 + i, 1399 + i, 1400.5 + i, 10.0) for i in range(60)]
        with patch("binance_klines.get_bars", return_value=bn_bars):
            out = s._get_risk_klines(45, 60)
        self.assertEqual(len(out), 60)
        s.client.get_klines.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
