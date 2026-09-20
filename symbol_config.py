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

import os
from typing import Dict, List, Optional

# 真正的"活跃品种"唯一权威清单——2026-09-12新增，取代此前散落在
# webhook_parser.py/app.py/console_api.py/state_manager.py/
# position_supervisor_coinw.py 五个文件里各自独立硬编码的同款清单（这次
# 排查发现 BNB 在其中两处——position_supervisor_coinw.py 的
# recover_all_on_start() 重启恢复循环、app.py 的周期housekeep巡检——压根
# 没被列进去，属于既存漏洞：BNB 名义上"支持"但重启不恢复、巡检不覆盖。
# 五处调用点已改为从这里导入，不再各自维护一份，防止再出现同类遗漏。
# 2026-09-13：新增 XPT（铂金，跟XAU/XPD同族贵金属永续）——核实过CoinW
# 公开行情接口(/v1/perpumPublic/ticker?instrument=XPT)，contract_id=195，
# 真实挂着USDT永续合约(fair_price≈1794.51, max_leverage=120)。跟币安B
# 系统同批上线，45分钟周期，同一份BREATH_XPT。
# 2026-09-13（同一天再新增）：新增 XRP/SOL（主流加密货币，不是贵金属/
# TradFi类）——核实过/v1/perpumPublic/ticker，XRP contract_id=15
# (fair_price≈1.35, max_leverage=100)，SOL contract_id=24
# (fair_price≈100.63, max_leverage=110)，都真实挂着USDT永续合约。跟
# 币安B系统同批上线，45分钟周期。
# 2026-09-15：宝贝拍板"精细化做好这几个"——只留BNB/XPD/SNDK/OPENAI/XAU
# 这5个精细打磨，ETH/BTC/XPT/XRP/SOL暂停(不是删除，恢复直接取消注释加
# 回列表即可，跟币安symbol_config.py同批改、同一套可逆写法)。暂停只挡
# webhook_parser.py::VALID_SYMBOLS新开仓入口，已有仓位(如SOL当时还有
# 持仓)交给引擎自己的硬止损/雷达管到自然平仓，不强制清仓——跟币安
# 0deff95既定语义一致。
# 2026-09-20：宝贝要求把MU重新加回来(usdt永续合约)，币安B系统+CoinW都
# 新增，周期91分钟。核实过CoinW公开行情接口(/v1/perpumPublic/ticker?
# instrument=MU)，contract_id=219，真实挂着USDT永续合约
# (name=MUUSDT, fair_price≈1005.72, max_leverage=200)。
# 2026-09-21：改成env驱动(COINW_ACTIVE_SYMBOLS)，跟币安B系统
# (BINANCE_SYMBOLS_B)同一套模式——宝贝要在dashboard/binance-dashboard
# 控制面板里给CoinW也加一份可勾选的白名单开关，不用再改代码+redeploy才
# 能调整。默认值维持这里代码写的这份(当前基准XAU/BNB/XPD——宝贝同一天
# 把SNDK/OPENAI/MU暂停，手工自己开单，VPS不再接管，见recover_all_on_
# start()里_symbols_with_orphaned_live_positions()的白名单外检测+告警
# 机制，同一套2026-09-19起已经生效的既定语义)。
_ACTIVE_SYMBOLS_DEFAULT = "XAU,BNB,XPD"
_active_symbols_raw = os.getenv("COINW_ACTIVE_SYMBOLS", "").strip()
ACTIVE_SYMBOLS: List[str] = (
    [s.strip().upper() for s in _active_symbols_raw.split(",") if s.strip()]
    if _active_symbols_raw
    else _ACTIVE_SYMBOLS_DEFAULT.split(",")
)


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
        "XPT": "XPT",
        "XRP": "XRP",
        "SOL": "SOL",
        "MU": "MU",
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
        "XPT": 2,
        "XRP": 4,
        "SOL": 2,
        "MU": 2,
    }

    QTY_PRECISION = {
        "ETH": 4,
        "BTC": 4,
        "XAU": 4,
        "BNB": 4,
        "OPENAI": 4,
        "SNDK": 4,
        "XPD": 4,
        "XPT": 4,
        "XRP": 4,
        "SOL": 4,
        "MU": 4,
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
        "XPT": 1.0,
        "XRP": 1.0,
        "SOL": 1.0,
        "MU": 1.0,
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
