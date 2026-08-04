#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
硬止损公式测试 - CoinW单系统 v16.22.1
"""

import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from atr_scenario import calc_hard_stop_price, verify_hard_stop


class TestHardStop(unittest.TestCase):
    """测试硬止损计算"""

    def test_long_hard_stop(self):
        """多头硬止损"""
        price, dist, ok, err = calc_hard_stop_price(
            tv_price=1900,
            tv_stop_loss=1880,
            entry_price=1895,
            direction="LONG",
            buffer=1.15
        )

        self.assertTrue(ok)
        self.assertGreater(price, 0)
        self.assertLess(price, 1895)  # 止损应在开仓价下方

    def test_short_hard_stop(self):
        """空头硬止损"""
        price, dist, ok, err = calc_hard_stop_price(
            tv_price=1900,
            tv_stop_loss=1920,
            entry_price=1895,
            direction="SHORT",
            buffer=1.15
        )

        self.assertTrue(ok)
        self.assertGreater(price, 1895)  # 止损应在开仓价上方

    def test_missing_stop_loss(self):
        """缺少stop_loss"""
        price, dist, ok, err = calc_hard_stop_price(
            tv_price=1900,
            tv_stop_loss=0,
            direction="LONG"
        )

        self.assertFalse(ok)
        self.assertEqual(err, "missing_stop_loss")

    def test_verify_hard_stop_long(self):
        """验证多头硬止损"""
        ok, detail = verify_hard_stop(
            hard_stop_price=1880,
            entry_price=1900,
            direction="LONG",
        )

        self.assertTrue(ok)

    def test_verify_hard_stop_invalid(self):
        """验证无效止损"""
        ok, detail = verify_hard_stop(
            hard_stop_price=1950,  # 高于开仓价
            entry_price=1900,
            direction="LONG",
        )

        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
