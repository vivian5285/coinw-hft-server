#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
符号配置 - CoinW单系统 v16.22.1

支持币种和参数映射
"""

from __future__ import annotations

from typing import Dict, Optional


class SymbolConfig:
    """符号配置"""

    # CoinW品种映射
    SYMBOL_MAP = {
        "ETH": "ETH",
        "BTC": "BTC",
        "XAU": "XAU",
        "BNB": "BNB",
    }

    # 品种精度
    PRICE_PRECISION = {
        "ETH": 2,
        "BTC": 2,
        "XAU": 2,
        "BNB": 2,
    }

    QTY_PRECISION = {
        "ETH": 4,
        "BTC": 4,
        "XAU": 4,
        "BNB": 4,
    }

    # 默认杠杆
    DEFAULT_LEVERAGE = 20

    # 最小下单量
    MIN_NOTIONAL = {
        "ETH": 1.0,   # USDT
        "BTC": 1.0,
        "XAU": 1.0,
        "BNB": 1.0,
    }

    @classmethod
    def normalize_symbol(cls, symbol: str) -> str:
        """标准化符号"""
        s = str(symbol or "").upper().strip()
        # 去掉后缀
        s = s.replace("USDT", "").replace("USDC", "").replace("_USDT", "").replace("-USDT", "")
        return s

    @classmethod
    def get_symbol(cls, symbol: str) -> str:
        """获取品种"""
        s = cls.normalize_symbol(symbol)
        return cls.SYMBOL_MAP.get(s, s)

    @classmethod
    def get_price_precision(cls, symbol: str) -> int:
        """获取价格精度"""
        s = cls.normalize_symbol(symbol)
        return cls.PRICE_PRECISION.get(s, 2)

    @classmethod
    def get_qty_precision(cls, symbol: str) -> int:
        """获取数量精度"""
        s = cls.normalize_symbol(symbol)
        return cls.QTY_PRECISION.get(s, 4)

    @classmethod
    def get_min_notional(cls, symbol: str) -> float:
        """获取最小名义价值"""
        s = cls.normalize_symbol(symbol)
        return cls.MIN_NOTIONAL.get(s, 1.0)

    @classmethod
    def is_valid_symbol(cls, symbol: str) -> bool:
        """检查是否有效"""
        s = cls.normalize_symbol(symbol)
        return s in cls.SYMBOL_MAP


# 全局配置
DEFAULT_SYMBOL_CONFIG = SymbolConfig()


def get_symbol_config(symbol: str) -> SymbolConfig:
    """获取符号配置（总是返回同一实例）"""
    return DEFAULT_SYMBOL_CONFIG
