#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
订单幂等控制 - CoinW单系统 v16.22.1

防叠单铁律：
1. 本地标签未释放 -> 绝对拒挂
2. fail-closed：查单失败禁止补挂
3. 同价去重：120s本地缓存
4. 硬上限5：未成交挂单>=5熔断
"""

from __future__ import annotations

import time
import threading
from typing import Dict, Optional, Set


class OrderIdempotency:
    """订单幂等控制器"""

    def __init__(self):
        self._lock = threading.Lock()

        # 标签 -> 订单ID
        self._tags: Dict[str, str] = {}

        # 订单ID -> 标签
        self._order_tags: Dict[str, str] = {}

        # 同价缓存: (symbol, side, price) -> (ts, order_id)
        self._price_cache: Dict[tuple, tuple] = {}

        # 挂单计数
        self._open_count: Dict[str, int] = {}  # symbol -> count

    def can_place(self, tag: str = None, symbol: str = None,
                   side: str = None, price: float = None,
                   open_count: int = 0) -> tuple:
        """
        检查是否可以下单

        Returns:
            (can_place, reason)
        """
        with self._lock:
            # 1) 标签检查
            if tag and tag in self._tags:
                return False, f"tag_pending:{tag}"

            # 2) 硬上限检查
            if open_count >= 5:
                return False, f"max_orders:{open_count}>=5"

            # 3) 同价缓存检查
            if symbol and side and price:
                key = (symbol.upper(), side.upper(), round(price, 2))
                cached = self._price_cache.get(key)
                if cached:
                    age = time.time() - float(cached[0])
                    if age < 120:
                        return False, f"price_cached:{age:.0f}s_ago"

            return True, "ok"

    def mark_placed(self, tag: str = None, order_id: str = None,
                   symbol: str = None, side: str = None, price: float = None):
        """标记已下单"""
        with self._lock:
            if tag and order_id:
                self._tags[tag] = order_id
                self._order_tags[order_id] = tag

            if symbol and side and price:
                key = (symbol.upper(), side.upper(), round(price, 2))
                self._price_cache[key] = (time.time(), order_id or "")

            # 清理过期缓存
            self._cleanup()

    def mark_filled(self, order_id: str):
        """标记已成交"""
        with self._lock:
            tag = self._order_tags.pop(order_id, None)
            if tag:
                self._tags.pop(tag, None)

            # 清理价格缓存
            expired = [
                k for k, v in self._price_cache.items()
                if v[1] == order_id
            ]
            for k in expired:
                self._price_cache.pop(k, None)

    def mark_cancelled(self, order_id: str):
        """标记已取消"""
        with self._lock:
            tag = self._order_tags.pop(order_id, None)
            if tag:
                self._tags.pop(tag, None)

            # 清理价格缓存
            expired = [
                k for k, v in self._price_cache.items()
                if v[1] == order_id
            ]
            for k in expired:
                self._price_cache.pop(k, None)

    def get_tag_for_order(self, order_id: str) -> Optional[str]:
        """获取订单的标签"""
        with self._lock:
            return self._order_tags.get(order_id)

    def _cleanup(self):
        """清理过期数据"""
        now = time.time()
        cutoff = now - 120

        # 清理过期标签
        expired_tags = [t for t, oid in self._tags.items() if oid.startswith("_")]
        for t in expired_tags:
            self._tags.pop(t, None)

        # 清理价格缓存
        expired_keys = [
            k for k, v in self._price_cache.items()
            if float(v[0]) < cutoff
        ]
        for k in expired_keys:
            self._price_cache.pop(k, None)

    def reset(self):
        """重置全部状态"""
        with self._lock:
            self._tags.clear()
            self._order_tags.clear()
            self._price_cache.clear()
            self._open_count.clear()


# 单例
_idempotency: Optional[OrderIdempotency] = None
_idem_lock = threading.Lock()


def get_idempotency() -> OrderIdempotency:
    global _idempotency
    with _idem_lock:
        if _idempotency is None:
            _idempotency = OrderIdempotency()
        return _idempotency
