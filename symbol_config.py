#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
符号配置 - CoinW单系统 v16.22.1

支持币种和参数映射

2026-09-12：宝贝要求币赢对齐币安，新增 OPENAIUSDT/SNDKUSDT/XPDUSDT 三个
品种（BNB 之前已经在名义上"支持"但从未真正接线——见下方 ACTIVE_SYMBOLS
注释）。核实过 CoinW 公开行情接口(/v1/perpumPublic/ticker)，这四个品种
真实挂着 USDT 永续合约（contract_id: BNB=25 OPENAI=218 SNDK=223 XPD=194）。

排查发现：SymbolConfig 这个类本身全仓库零调用方（grep 全部 *.py 无引用），
是从未接线的冗余 scaffold——真正下单格式化在 coinw_client.py 的
_format_quantity/_format_price 里，是全局固定 round(qty,4)/round(price,2)，
不查这里的 PRICE_PRECISION/QTY_PRECISION（这两个字段名字骗人，跟 H 项
AccountThrottle 同一个模式，见2026-08-10对齐检查memory）。这里仍然把新
品种补齐是为了保持内部一致（万一以后真的接线），不代表现在真的按这个
精度下单。
"""

from __future__ import annotations

from typing import Dict, List, Optional

# 真正的"活跃品种"唯一权威清单——2026-09-12新增，取代此前散落在
# webhook_parser.py/app.py/console_api.py/state_manager.py/
# position_supervisor_coinw.py 五个文件里各自独立硬编码的同款清单（这次
# 排查发现 BNB 在其中两处——position_supervisor_coinw.py 的
# recover_all_on_start() 重启恢复循环、app.py 的周期housekeep巡检——压根
# 没被列进去，属于既存漏洞：BNB 名义上"支持"但重启不恢复、巡检不覆盖。
# 五处调用点已改为从这里导入，不再各自维护一份，防止再出现同类遗漏。
ACTIVE_SYMBOLS: List[str] = ["ETH", "BTC", "XAU", "BNB", "OPENAI", "SNDK", "XPD"]


class SymbolConfig:
    """符号配置"""

    # CoinW品种映射
    SYMBOL_MAP = {
        "ETH": "ETH",
        "BTC": "BTC",
        "XAU": "XAU",
        "BNB": "BNB",
        "OPENAI": "OPENAI",
        "SNDK": "SNDK",
        "XPD": "XPD",
    }

    # 品种精度（见上方class docstring：当前未被实际下单路径读取）
    PRICE_PRECISION = {
        "ETH": 2,
        "BTC": 2,
        "XAU": 2,
        "BNB": 2,
        "OPENAI": 2,
        "SNDK": 2,
        "XPD": 2,
    }

    QTY_PRECISION = {
        "ETH": 4,
        "BTC": 4,
        "XAU": 4,
        "BNB": 4,
        "OPENAI": 4,
        "SNDK": 4,
        "XPD": 4,
    }

    # 默认杠杆
    DEFAULT_LEVERAGE = 20

    # 最小下单量
    MIN_NOTIONAL = {
        "ETH": 1.0,   # USDT
        "BTC": 1.0,
        "XAU": 1.0,
        "BNB": 1.0,
        "OPENAI": 1.0,
        "SNDK": 1.0,
        "XPD": 1.0,
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
