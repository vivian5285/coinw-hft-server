#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TV信号序列器 - CoinW单系统 v16.22.1

15s铁律：
- OPEN先到+CLOSE在15s内到 -> 丢弃CLOSE
- CLOSE先到+OPEN在15s内到 -> 先平后开
- 超15s的CLOSE -> 独立平仓
"""

from __future__ import annotations

import time
import threading
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class SignalEntry:
    action: str          # LONG/SHORT/CLOSE
    symbol: str
    price: float
    ts: float
    raw: dict = field(default_factory=dict)


class TvSeq:
    """TV信号序列器"""

    def __init__(self, window_sec: float = 15.0):
        self._window_sec = float(window_sec)

        self._lock = threading.Lock()
        self._last_signal: Dict[str, SignalEntry] = {}  # symbol -> SignalEntry
        self._pending_open: Dict[str, SignalEntry] = {}  # symbol -> SignalEntry

    def feed(self, action: str, symbol: str, price: float, raw: dict = None) -> Tuple[str, Optional[SignalEntry]]:
        """
        喂入信号
        返回 (decision, previous_pending)
            decision: "process" / "discard" / "hold" / "flush"
            previous_pending: 之前挂起的信号（如果有）
        """
        action = str(action or "").upper()
        symbol = str(symbol or "").upper()
        now = time.time()

        with self._lock:
            # CLOSE信号
            if action in ("CLOSE", "CLOSE_QUICK_EXIT", "CLOSE_RSI_EXIT"):
                last = self._last_signal.get(symbol)
                pending = self._pending_open.pop(symbol, None)

                if last and last.action in ("LONG", "SHORT"):
                    elapsed = now - last.ts
                    if elapsed <= self._window_sec:
                        # 15s内OPEN+CLOSE -> 先平后开
                        self._last_signal[symbol] = SignalEntry(action, symbol, price, now, raw or {})
                        return "flush", pending

                # 独立CLOSE
                self._last_signal[symbol] = SignalEntry(action, symbol, price, now, raw or {})
                return "process", None

            # OPEN信号 (LONG/SHORT)
            if action in ("LONG", "SHORT"):
                last = self._last_signal.get(symbol)
                pending = self._pending_open.get(symbol)

                if last and last.action == "CLOSE" and last.action not in ("LONG", "SHORT"):
                    elapsed = now - last.ts
                    if elapsed <= self._window_sec:
                        # CLOSE先到+15s内OPEN -> 先平后开（hold，等CLOSE执行完）
                        self._pending_open[symbol] = SignalEntry(action, symbol, price, now, raw or {})
                        return "hold", None

                # 普通OPEN
                self._last_signal[symbol] = SignalEntry(action, symbol, price, now, raw or {})
                return "process", None

            # 未知动作 -> 丢弃
            return "discard", None

    def release_pending(self, symbol: str) -> Optional[SignalEntry]:
        """释放挂起的OPEN信号"""
        with self._lock:
            entry = self._pending_open.pop(symbol, None)
            if entry:
                self._last_signal[symbol] = entry
            return entry

    def get_pending(self, symbol: str) -> Optional[SignalEntry]:
        """获取挂起的信号"""
        with self._lock:
            return self._pending_open.get(symbol)

    def clear(self, symbol: str = ""):
        """清除序列状态"""
        with self._lock:
            if symbol:
                self._last_signal.pop(symbol, None)
                self._pending_open.pop(symbol, None)
            else:
                self._last_signal.clear()
                self._pending_open.clear()

    def get_last(self, symbol: str) -> Optional[SignalEntry]:
        """获取最后信号"""
        with self._lock:
            return self._last_signal.get(symbol)

    def get_status(self) -> Dict:
        """获取状态"""
        with self._lock:
            return {
                "window_sec": self._window_sec,
                "last_signals": {
                    k: {"action": v.action, "price": v.price, "ts": v.ts}
                    for k, v in self._last_signal.items()
                },
                "pending_opens": {
                    k: {"action": v.action, "price": v.price, "ts": v.ts}
                    for k, v in self._pending_open.items()
                },
            }


# 单例（支持多品种）
_SEQS: Dict[str, TvSeq] = {}
_SEQ_LOCK = threading.Lock()


def get_tv_seq(symbol: str = "ETH") -> TvSeq:
    """获取信号序列器"""
    sym = str(symbol or "ETH").upper()
    with _SEQ_LOCK:
        if sym not in _SEQS:
            _SEQS[sym] = TvSeq()
        return _SEQS[sym]


def feed_signal(action: str, symbol: str, price: float, raw: dict = None) -> Tuple[str, Optional[SignalEntry]]:
    """全局喂入信号"""
    return get_tv_seq(symbol).feed(action, symbol, price, raw)
