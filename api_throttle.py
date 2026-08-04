#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API限流阀 - CoinW单系统 v16.22.1

账号级REST预算控制，防止触发交易所限流
"""

from __future__ import annotations

import os
import time
import threading
from typing import Dict, Optional, Tuple


class AccountThrottle:
    """账号级限流阀"""

    def __init__(self, account_id: str = "coinw", budget_per_min: int = 48):
        self._account_id = str(account_id)
        self._budget_per_min = int(budget_per_min)
        self._window_sec = 60.0

        # 滑动窗口
        self._timestamps: list = []
        self._lock = threading.Lock()

        # 静默状态
        self._silence_until: float = 0.0
        self._silence_reason: str = ""

        # 冷却追踪
        self._cooldown_until: float = 0.0
        self._cooldown_reason: str = ""

    def acquire(self, kind: str = "rest", force: bool = False, symbol: str = "") -> Tuple[bool, str]:
        """
        尝试获取REST预算
        返回 (ok, detail)
        """
        with self._lock:
            now = time.time()

            # 检查静默
            if now < self._silence_until:
                rem = self._silence_until - now
                return False, f"silence:{rem:.1f}s ({self._silence_reason})"

            # 检查冷却
            if now < self._cooldown_until:
                rem = self._cooldown_until - now
                return False, f"cooldown:{rem:.1f}s ({self._cooldown_reason})"

            # 清理过期时间戳
            cutoff = now - self._window_sec
            self._timestamps = [ts for ts in self._timestamps if ts > cutoff]

            # 检查预算
            if len(self._timestamps) >= self._budget_per_min and not force:
                oldest = min(self._timestamps)
                wait = (oldest + self._window_sec) - now
                return False, f"budget_full:wait{wait:.1f}s"

            # 获取预算
            self._timestamps.append(now)
            return True, "ok"

    def enter_silence(self, seconds: float, reason: str = ""):
        """进入静默期"""
        with self._lock:
            until = time.time() + max(10.0, float(seconds))
            self._silence_until = max(self._silence_until, until)
            self._silence_reason = str(reason)

    def enter_cooldown(self, seconds: float, reason: str = ""):
        """进入冷却期"""
        with self._lock:
            until = time.time() + max(10.0, float(seconds))
            self._cooldown_until = max(self._cooldown_until, until)
            self._cooldown_reason = str(reason)

    def clear_silence(self):
        """清除静默"""
        with self._lock:
            self._silence_until = 0.0
            self._silence_reason = ""

    def clear_cooldown(self):
        """清除冷却"""
        with self._lock:
            self._cooldown_until = 0.0
            self._cooldown_reason = ""

    def get_status(self) -> Dict:
        """获取状态"""
        with self._lock:
            now = time.time()
            cutoff = now - self._window_sec
            active = [ts for ts in self._timestamps if ts > cutoff]

            return {
                "account": self._account_id,
                "budget_per_min": self._budget_per_min,
                "used_in_window": len(active),
                "remaining": max(0, self._budget_per_min - len(active)),
                "silence_until": self._silence_until,
                "cooldown_until": self._cooldown_until,
                "silence_reason": self._silence_reason,
                "cooldown_reason": self._cooldown_reason,
            }

    def recent_count(self) -> int:
        """最近60s使用次数"""
        with self._lock:
            now = time.time()
            cutoff = now - self._window_sec
            return len([ts for ts in self._timestamps if ts > cutoff])


# 全局限流器
_THROTTLES: Dict[str, AccountThrottle] = {}
_THROTTLE_LOCK = threading.Lock()


def get_throttle(account_id: str = "coinw") -> AccountThrottle:
    """获取限流器单例"""
    with _THROTTLE_LOCK:
        if account_id not in _THROTTLES:
            budget = int(os.getenv("API_BUDGET_PER_MIN", "48"))
            _THROTTLES[account_id] = AccountThrottle(account_id, budget)
        return _THROTTLES[account_id]


def get_all_throttle_status() -> Dict[str, Dict]:
    """获取所有限流器状态"""
    with _THROTTLE_LOCK:
        return {k: v.get_status() for k, v in _THROTTLES.items()}
