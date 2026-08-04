#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
雷达再入引擎 - CoinW单系统 v16.22.1

被动雷达 + 智能再入闭环
"""

from __future__ import annotations

import time
import threading
import logging
from typing import Dict, Optional, Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RadarContext:
    symbol: str
    direction: str
    entry_price: float
    tp1_filled: bool
    tp2_filled: bool
    current_price: float
    atr: float
    tier: str
    reentry_count: int
    radar_sl: float


class RadarReentryMixin:
    """
    雷达再入混合类
    供position_supervisor继承使用
    """

    def __init__(self):
        self._reentry_lock = threading.Lock()
        self._reentry_state: Dict[str, dict] = {}

        # 再入标签 -> 订单ID映射
        self._order_tags: Dict[str, str] = {}
        self._tags_by_order: Dict[str, str] = {}

    # ==================== 再入状态管理 ====================

    def mark_reentry_in_progress(self, symbol: str, reentry_price: float):
        """标记再入进行中"""
        with self._reentry_lock:
            self._reentry_state[symbol.upper()] = {
                "in_progress": True,
                "reentry_price": reentry_price,
                "ts": time.time(),
            }

    def clear_reentry_in_progress(self, symbol: str):
        """清除再入状态"""
        with self._reentry_lock:
            self._reentry_state.pop(symbol.upper(), None)

    def is_reentry_in_progress(self, symbol: str) -> bool:
        """检查再入是否进行中"""
        with self._reentry_lock:
            state = self._reentry_state.get(symbol.upper(), {})
            return bool(state.get("in_progress", False))

    def get_reentry_state(self, symbol: str) -> Optional[dict]:
        """获取再入状态"""
        with self._reentry_lock:
            return self._reentry_state.get(symbol.upper(), {}).copy()

    # ==================== 订单标签管理 ====================

    def register_order_tag(self, tag: str, order_id: str):
        """注册订单标签"""
        with self._reentry_lock:
            self._order_tags[tag] = order_id
            self._tags_by_order[order_id] = tag

    def release_order_tag(self, order_id: str):
        """释放订单标签（成交后）"""
        with self._reentry_lock:
            tag = self._tags_by_order.pop(order_id, None)
            if tag:
                self._order_tags.pop(tag, None)

    def is_tag_pending(self, tag: str) -> bool:
        """检查标签是否待处理"""
        with self._reentry_lock:
            return tag in self._order_tags

    def get_pending_tags(self) -> Dict[str, str]:
        """获取所有待处理标签"""
        with self._reentry_lock:
            return dict(self._order_tags)

    # ==================== 再入决策 ====================

    def check_reentry_opportunity(self, ctx: RadarContext) -> tuple:
        """
        检查再入机会

        Returns:
            (can_reenter, reason, reentry_price)
        """
        from smart_reentry_engine import (
            should_reenter, calc_reentry_price, calc_reentry_quantity
        )
        from reentry_profiles import get_reentry_profile

        profile = get_reentry_profile(ctx.symbol)

        # 检查是否进行中
        if self.is_reentry_in_progress(ctx.symbol):
            return False, "reentry_in_progress", 0

        # 检查是否允许再入
        can, reason = should_reenter(
            current_price=ctx.current_price,
            entry_price=ctx.entry_price,
            atr=ctx.atr,
            direction=ctx.direction,
            tier=ctx.tier,
            tp1_filled=ctx.tp1_filled,
            reentry_count=ctx.reentry_count,
            max_reentry=profile.max_reentry,
            tier_params={"reentry_zone_pct": profile.reentry_zone_pct},
        )

        if not can:
            return False, reason, 0

        # 计算再入价格
        reentry_price = calc_reentry_price(
            current_price=ctx.current_price,
            entry_price=ctx.entry_price,
            atr=ctx.atr,
            direction=ctx.direction,
            tier_params={"reentry_zone_pct": profile.reentry_zone_pct},
        )

        # 计算再入数量
        reentry_qty = calc_reentry_quantity(
            original_qty=ctx.entry_price * ctx.current_price,  # 估算
            reentry_count=ctx.reentry_count,
            tier=ctx.tier,
        )

        return True, "ok", reentry_price, reentry_qty

    def on_reentry_success(self, symbol: str):
        """再入成功后放宽雷达"""
        logger.info(f"再入成功: {symbol}, 放宽雷达档位")
        # 实际放宽逻辑在breath_stop中

    def on_reentry_failed(self, symbol: str):
        """再入失败"""
        logger.warning(f"再入失败: {symbol}")
        self.clear_reentry_in_progress(symbol)


# 单例
_radar_mixin: Optional[RadarReentryMixin] = None
_mixin_lock = threading.Lock()


def get_radar_mixin() -> RadarReentryMixin:
    global _radar_mixin
    with _mixin_lock:
        if _radar_mixin is None:
            _radar_mixin = RadarReentryMixin()
        return _radar_mixin
