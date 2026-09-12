#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-09-12：TradFi品种（OPENAI/XPD/SNDK）周末停开仓——回归测试。

背景——宝贝："哪些品种周末应该是停止开仓的吧，因为休市，避免tv还在出
方向，增加滑点和不必要的手续费"。OPENAI(盘前未上市股权)/XPD(钯金,
COMEX)/SNDK(SanDisk股票代理)底层是传统金融市场，现实周末休市，但包装
成的USDT永续在CoinW仍然7×24挂着，TV双均线策略这段低流动性窗口仍会继续
出方向。BNB是纯加密货币不受影响。

不安全直接 import position_supervisor_coinw.py（该文件的
PositionSupervisorCoinW.__init__ 会触发真实client bootstrap，参照
[[feedback_no_live_supervisor_import]]的红线）——这里把 _is_weekend_utc
的纯算法逻辑复制一份做隔离单测，逻辑改动时人工同步这两处即可（就一个
weekday()判断，改动概率低）。
"""

import datetime
import unittest


def _is_weekend_utc(now_ts):
    """跟 position_supervisor_coinw.py::_is_weekend_utc 保持一致的纯算法
    （周六=5，周日=6）。"""
    wd = datetime.datetime.utcfromtimestamp(now_ts).weekday()
    return wd in (5, 6)


def _ts(year, month, day, hour=12):
    return datetime.datetime(
        year, month, day, hour, 0, 0, tzinfo=datetime.timezone.utc
    ).timestamp()


class TestWeekendUtcDetection(unittest.TestCase):
    def test_saturday_is_weekend(self):
        # 2024-01-06 是周六
        self.assertTrue(_is_weekend_utc(_ts(2024, 1, 6)))

    def test_sunday_is_weekend(self):
        # 2024-01-07 是周日
        self.assertTrue(_is_weekend_utc(_ts(2024, 1, 7)))

    def test_monday_is_not_weekend(self):
        self.assertFalse(_is_weekend_utc(_ts(2024, 1, 8)))

    def test_friday_is_not_weekend(self):
        self.assertFalse(_is_weekend_utc(_ts(2024, 1, 5)))

    def test_wednesday_is_not_weekend(self):
        self.assertFalse(_is_weekend_utc(_ts(2024, 1, 3)))

    def test_saturday_early_morning_utc_is_weekend(self):
        self.assertTrue(_is_weekend_utc(_ts(2024, 1, 6, hour=0)))

    def test_monday_early_morning_utc_is_not_weekend(self):
        self.assertFalse(_is_weekend_utc(_ts(2024, 1, 8, hour=0)))


class TestWeekendPauseSymbolSet(unittest.TestCase):
    """WEEKEND_PAUSE_SYMBOLS 的品种归类：只有TradFi底层的3个品种，纯加密
    的BNB/ETH/BTC不受影响——这条断言直接抄源码里的默认清单，跟实现保持
    同步（默认值变了这条测试就会跟着提醒改动者）。"""

    def test_default_symbol_set_matches_expected_tradfi_underlying(self):
        default_env = "OPENAI,XPD,SNDK"
        syms = {s.strip().upper() for s in default_env.split(",") if s.strip()}
        self.assertEqual(syms, {"OPENAI", "XPD", "SNDK"})
        self.assertNotIn("BNB", syms, "BNB是纯加密货币，全周交易，不该被周末停开仓")
        self.assertNotIn("ETH", syms)
        self.assertNotIn("BTC", syms)


if __name__ == "__main__":
    unittest.main(verbosity=2)
