#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
幂等控制测试 - CoinW单系统 v16.22.1
"""

import unittest
import sys
import os
import time

sys.path.insert(0, os.path.dirname(__file__))

from order_idempotency import OrderIdempotency


class TestIdempotency(unittest.TestCase):
    """测试幂等控制"""

    def setUp(self):
        self.idem = OrderIdempotency()

    def test_can_place_initially(self):
        """初始可下单"""
        can, reason = self.idem.can_place(symbol="ETH", side="LONG", price=1900)
        self.assertTrue(can)

    def test_tag_pending_blocks(self):
        """标签待处理阻止下单"""
        self.idem.mark_placed(tag="test_tag", order_id="123")

        can, reason = self.idem.can_place(tag="test_tag")
        self.assertFalse(can)
        self.assertIn("tag_pending", reason)

    def test_price_cache_blocks(self):
        """同价缓存阻止下单"""
        self.idem.mark_placed(
            symbol="ETH", side="LONG", price=1900, order_id="456"
        )

        can, reason = self.idem.can_place(
            symbol="ETH", side="LONG", price=1900
        )
        self.assertFalse(can)
        self.assertIn("price_cached", reason)

    def test_max_orders(self):
        """最大订单数限制"""
        can, reason = self.idem.can_place(
            symbol="ETH", side="LONG", price=1900, open_count=5
        )
        self.assertFalse(can)
        self.assertIn("max_orders", reason)

    def test_mark_filled_releases(self):
        """成交释放标签"""
        self.idem.mark_placed(tag="tag1", order_id="order1")
        self.idem.mark_filled("order1")

        can, reason = self.idem.can_place(tag="tag1")
        self.assertTrue(can)

    def test_reset_clears_all(self):
        """重置清空全部"""
        self.idem.mark_placed(tag="tag1", order_id="order1")
        self.idem.reset()

        can, reason = self.idem.can_place(tag="tag1")
        self.assertTrue(can)


if __name__ == "__main__":
    unittest.main()
