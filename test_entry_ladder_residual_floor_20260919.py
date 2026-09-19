#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-09-19：开仓滑点阶梯(_wait_fill/_open_with_ladder)误判成交的回归
测试——实盘复现XAUUSDT。

背景：XAUUSDT一笔空单信号，被动限价挂单后(want_qty=0.009135，金价太
高导致基础货币数量天然很小)，_wait_fill()第一次轮询(have仍是0，压根
没等到任何成交)就被判定"①成交(被动限价,0滑点)"——根源是_MIN_ORDER_
ETH是ETH时代遗留的绝对量(0.011)，比这笔XAU订单的want_qty本身还大，
"have>=want_qty-_MIN_ORDER_ETH"算出的阈值是负数，have=0也恒满足。
之后按"已经开仓成功"的分支往下走，查真实持仓却"持仓未找到"，整个
开仓流程当场报错中止，真正挂在交易所上的限价单反而没人管，一分钟后
才被housekeep当孤儿单撤掉——这笔TV信号完全没开成仓。

修复：新增_entry_residual_floor(qty)，用"绝对量跟相对量(qty×10%)取
更小者"替代直接用_MIN_ORDER_ETH，且_wait_fill()新增have>0硬性前提。

不碰任何真实账户/持仓，self.client/self._pos_qty/self._get_current_price
全部mock。
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

# 复现实盘XAUUSDT真实数字
XAU_WANT_QTY = 0.009134957037758799
XAU_TV_PRICE = 4382.29


def _mk_supervisor(symbol="XAU"):
    s = object.__new__(psc.PositionSupervisorCoinW)
    s.symbol = symbol
    s.client = MagicMock()
    return s


class TestEntryResidualFloor(unittest.TestCase):
    def test_small_xau_qty_floor_is_relative_not_absolute(self):
        """核心回归：XAU这种小额下单，floor应该是qty的10%，不是绝对量
        0.011(比整笔下单量还大)。"""
        s = _mk_supervisor()
        floor = s._entry_residual_floor(XAU_WANT_QTY)
        self.assertAlmostEqual(floor, XAU_WANT_QTY * 0.1, places=8)
        self.assertLess(floor, XAU_WANT_QTY, "floor不该比整笔下单量还大")

    def test_large_eth_qty_floor_stays_absolute(self):
        """大额下单(远超0.11)时，floor应该是原来的绝对量0.011(取更小
        者不变，行为不受影响)。"""
        s = _mk_supervisor()
        floor = s._entry_residual_floor(0.5)
        self.assertAlmostEqual(floor, 0.011, places=6)

    def test_zero_qty_defensive_fallback(self):
        s = _mk_supervisor()
        self.assertEqual(s._entry_residual_floor(0), 0.011)


class TestWaitFillNoFalsePositive(unittest.TestCase):
    def test_zero_fill_never_reports_filled_for_small_qty(self):
        """核心回归：XAU这笔单want_qty本身小于旧的绝对阈值0.011时，
        have=0(压根没成交)不该被判定filled——这正是实盘复现的那个bug。"""
        s = _mk_supervisor("XAU")
        s._pos_qty = MagicMock(return_value=0.0)
        s._adverse_gap_pct = MagicMock(return_value=0.0)

        with patch("time.sleep"):
            status, have = s._wait_fill(
                "SHORT", XAU_TV_PRICE, time.time() + 0.01, XAU_WANT_QTY,
            )

        self.assertEqual(status, "timeout")
        self.assertEqual(have, 0.0)

    def test_real_fill_still_reports_filled(self):
        """对照组：真的成交时，仍然应该正常判定filled，不能矫枉过正。"""
        s = _mk_supervisor("XAU")
        s._pos_qty = MagicMock(return_value=XAU_WANT_QTY)
        s._adverse_gap_pct = MagicMock(return_value=0.0)

        with patch("time.sleep"):
            status, have = s._wait_fill(
                "SHORT", XAU_TV_PRICE, time.time() + 0.01, XAU_WANT_QTY,
            )

        self.assertEqual(status, "filled")
        self.assertAlmostEqual(have, XAU_WANT_QTY, places=6)

    def test_partial_fill_below_90_pct_not_reported_as_filled(self):
        """部分成交但远低于90%时，不该被判定filled(旧公式对XAU这种小
        额单会把任何非零成交都当成"差不多了"，新公式要求真正接近
        完整成交)。"""
        s = _mk_supervisor("XAU")
        s._pos_qty = MagicMock(return_value=XAU_WANT_QTY * 0.5)  # 只成交了50%
        s._adverse_gap_pct = MagicMock(return_value=0.0)

        with patch("time.sleep"):
            status, have = s._wait_fill(
                "SHORT", XAU_TV_PRICE, time.time() + 0.01, XAU_WANT_QTY,
            )

        self.assertEqual(status, "timeout")


class TestOpenWithLadderEndToEnd(unittest.TestCase):
    def test_no_fill_at_all_falls_through_to_market_fallback(self):
        """端到端复现：被动限价+可成交限价全程没有任何真实成交，应该
        最终落到市价兜底，而不是在半路谎报ok=True。"""
        s = _mk_supervisor("XAU")
        s.client.place_limit_order = MagicMock(return_value={"code": 0, "id": "o1"})
        s.client.place_market_order = MagicMock(return_value={"code": 0})
        s._cancel_open_limits = MagicMock()
        s._pos_qty = MagicMock(return_value=0.0)  # 全程没有任何真实成交
        s._adverse_gap_pct = MagicMock(return_value=0.0)
        s._get_current_price = MagicMock(return_value=XAU_TV_PRICE)

        # 把阶梯各阶段窗口压到接近0，测试跑得快
        with patch.object(psc, "ENTRY_PASSIVE_SEC", 0.01), \
             patch.object(psc, "ENTRY_MARKETABLE_SEC", 0.01), \
             patch.object(psc, "ENTRY_STRONG_MARKETABLE_SEC", 0.01), \
             patch("time.sleep"):
            result = s._open_with_ladder("SHORT", XAU_TV_PRICE, XAU_WANT_QTY, tier="1")

        self.assertTrue(result.get("ok"))
        self.assertEqual(result.get("via"), "market_fallback")
        s.client.place_market_order.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
