#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
状态管理器 - CoinW单系统 v16.22.1

状态持久化到JSON文件
"""

import os
import json
import threading
import time
from typing import Dict, Optional


class StateManager:
    """状态管理器"""

    def __init__(self, symbol: str, exchange: str = "coinw"):
        self.symbol = str(symbol or "ETH").upper()
        self.exchange = str(exchange or "coinw").lower()
        self._lock = threading.RLock()

        # 状态目录
        self._data_dir = os.path.join(
            os.path.dirname(__file__),
            'data'
        )
        os.makedirs(self._data_dir, exist_ok=True)

        # 状态文件
        self._state_file = os.path.join(
            self._data_dir,
            f'{self.exchange}_vps_state_{self.symbol}.json'
        )

        self._cache: Dict = {}
        self._cache_dirty = False
        self._last_save = 0

    def load(self) -> Dict:
        """加载状态"""
        with self._lock:
            if os.path.exists(self._state_file):
                try:
                    with open(self._state_file, 'r') as f:
                        self._cache = json.load(f)
                    return self._cache
                except Exception:
                    pass
            return {}

    def save(self, state: Dict = None):
        """保存状态"""
        with self._lock:
            if state:
                self._cache = state
                self._cache_dirty = True

            if self._cache_dirty:
                try:
                    with open(self._state_file, 'w') as f:
                        json.dump(self._cache, f, indent=2)
                    self._cache_dirty = False
                    self._last_save = time.time()
                except Exception:
                    pass

    def update(self, **kwargs):
        """更新状态字段"""
        with self._lock:
            self._cache.update(kwargs)
            self._cache_dirty = True

    def get(self, key: str, default=None):
        """获取状态值"""
        with self._lock:
            return self._cache.get(key, default)

    def flush(self):
        """强制刷新到磁盘"""
        self.save()

    def get_pipeline_state(self) -> Dict:
        """获取流水线状态"""
        with self._lock:
            return self._cache.get("pipeline", {})

    def set_pipeline_state(self, state: Dict):
        """设置流水线状态"""
        with self._lock:
            self._cache["pipeline"] = state
            self._cache_dirty = True


# 全局状态管理器
_STATE_MANAGERS: Dict[str, StateManager] = {}
_STATE_LOCK = threading.Lock()


def get_state_manager(symbol: str = "ETH", exchange: str = "coinw") -> StateManager:
    """获取状态管理器"""
    key = f"{exchange}:{symbol.upper()}"
    with _STATE_LOCK:
        if key not in _STATE_MANAGERS:
            _STATE_MANAGERS[key] = StateManager(symbol, exchange)
        return _STATE_MANAGERS[key]


def save_all_states():
    """保存所有状态"""
    with _STATE_LOCK:
        for mgr in _STATE_MANAGERS.values():
            mgr.save()


def load_all_states():
    """加载所有状态"""
    for sym in ["ETH", "BTC", "XAU", "BNB"]:
        mgr = get_state_manager(sym)
        mgr.load()
