#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Webhook解析器 - CoinW单系统 v16.22.1

动作白名单：LONG/SHORT/CLOSE/CLOSE_QUICK_EXIT/CLOSE_RSI_EXIT/PING
验证：secret、必填字段、RISK20仓位公式
"""

from __future__ import annotations

import os
import time
import hashlib
import logging
from typing import Any, Dict, Optional, Tuple
from dataclasses import dataclass

from symbol_config import ACTIVE_SYMBOLS

logger = logging.getLogger(__name__)

# 有效动作
# HEARTBEAT：TV 周期性上报当前应有的持仓意图（side/entry/tp/sl/atr/tier），
# VPS 用来做「心跳催单」——漏了开仓信号就补开、止损漂了就补挂。
VALID_ACTIONS = {"LONG", "SHORT", "CLOSE", "CLOSE_QUICK_EXIT", "CLOSE_RSI_EXIT",
                 "PING", "HEARTBEAT"}

# 支持的交易对——2026-09-12改为从 symbol_config.ACTIVE_SYMBOLS 派生，不再
# 本地单独维护一份（这里是全系统真正的品种白名单闸门，跟 app.py/
# console_api.py/state_manager.py/position_supervisor_coinw.py 里另外4处
# 曾经各自独立硬编码同款清单——已改用同一权威来源）。
VALID_SYMBOLS = set(ACTIVE_SYMBOLS)


@dataclass
class ParsedSignal:
    valid: bool
    action: str
    symbol: str
    price: float
    stop_loss: float
    atr: float
    tp1: float
    tp2: float
    tp3: float
    qty: Optional[float]
    tier: str
    leverage: int
    error: str
    side: str = ""                       # LONG/SHORT/FLAT —— HEARTBEAT 用
    raw: Optional[Dict[str, Any]] = None  # 原始 payload —— HEARTBEAT 直接读


class WebhookParser:
    """Webhook解析器"""

    def __init__(self):
        self._secret = os.getenv("WEBHOOK_SECRET", os.getenv("TV_WEBHOOK_SECRET", ""))
        self._secret_cache: Dict[str, float] = {}  # secret -> last_used_ts

        # 缓存折叠（1s内同信号去重）
        self._signal_cache: Dict[str, float] = {}
        self._cache_lock = {}

    def _validate_secret(self, secret: str) -> bool:
        """验证密钥"""
        if not secret:
            return False

        # 简单密钥直接比较
        if self._secret and secret == self._secret:
            return True

        # 也支持token字段
        token = os.getenv("WEBHOOK_TOKEN", "")
        if token and secret == token:
            return True

        return False

    def _normalize_symbol(self, symbol: str) -> str:
        """标准化交易对"""
        s = str(symbol or "").upper().strip()
        # 去掉TradingView永续合约后缀（如 BNBUSDT.P -> BNBUSDT）
        if s.endswith(".P"):
            s = s[:-2]
        # 去掉USDT后缀
        s = s.replace("USDT", "").replace("USDC", "").replace("_USDT", "")
        return s

    def parse(self, raw: dict) -> ParsedSignal:
        """
        解析Webhook payload
        """
        raw = dict(raw or {})

        # 1) 验证密钥
        secret = raw.get("secret") or raw.get("token") or ""
        if not self._validate_secret(secret):
            return ParsedSignal(
                valid=False, action="", symbol="", price=0,
                stop_loss=0, atr=0, tp1=0, tp2=0, tp3=0,
                qty=None, tier="", leverage=20,
                error="invalid_secret",
            )

        # 2) 动作
        action = str(raw.get("action") or "").upper()
        if action not in VALID_ACTIONS:
            return ParsedSignal(
                valid=False, action=action, symbol="", price=0,
                stop_loss=0, atr=0, tp1=0, tp2=0, tp3=0,
                qty=None, tier="", leverage=20,
                error=f"invalid_action:{action}",
            )

        # PING不检查其他字段
        if action == "PING":
            return ParsedSignal(
                valid=True, action=action, symbol="", price=0,
                stop_loss=0, atr=0, tp1=0, tp2=0, tp3=0,
                qty=None, tier="", leverage=20,
                error="",
            )

        # HEARTBEAT：宽松解析，缺字段不拒；side/entry/tp/sl 供心跳催单核对
        if action == "HEARTBEAT":
            # 2026-09-12修复：此前只认 side/price/stop_loss/tp1/tp2/tp3，
            # 跟币安 eth-webhook-server 的 webhook_parser.py 不一致——币安
            # 那边心跳字段是 tv_side/tv_entry/tv_stop/tv_tp1/tv_tp2/tv_tp3，
            # 且 tp_i / tv_tp_i 互为别名。宝贝新策略"Webhook 对齐版 + tier
            # 动态分档"（新测试策略源码.txt）心跳payload用的正是tv_前缀这套
            # （跟币安一致，不是CoinW这边原来认的裸字段名）——冒烟测试实测
            # 过：不加这个别名，心跳side解析结果是"UNKNOWN"，entry/stop/tp
            # 全部读成0，TV心跳追回/对账功能对这个新策略完全失效。现在两套
            # 字段名都认，跟币安对齐。
            _has_side_key = (
                ("side" in raw) or ("direction" in raw) or ("tv_side" in raw)
            )
            side = str(
                raw.get("side") or raw.get("direction") or raw.get("tv_side") or ""
            ).upper()
            if side in ("LONG", "BUY"):
                side = "LONG"
            elif side in ("SHORT", "SELL"):
                side = "SHORT"
            elif side in ("FLAT", "NONE", "IDLE"):
                side = "FLAT"
            elif side == "" and _has_side_key:
                side = "FLAT"          # 显式发了空 side = 明确"TV 空仓"
            else:
                side = "UNKNOWN"       # 心跳没带 side -> 不当作 TV 空仓，只做存活/裸单核对
            def _f(k, alt=None):
                try:
                    v = raw.get(k)
                    if v is None and alt:
                        v = raw.get(alt)
                    return float(v or 0)
                except (TypeError, ValueError):
                    return 0.0
            # 同款 tier=0 falsy 修复见下方"9) Tier"注释
            _tier_hb_raw = raw.get("tier")
            if _tier_hb_raw is None:
                _tier_hb_raw = raw.get("adx_tier")
            tier_hb = str(_tier_hb_raw if _tier_hb_raw is not None else "").lower()
            tier_hb = {"0": "0", "弱": "0", "weak": "0", "1": "1", "中": "1",
                       "medium": "1", "2": "2", "强": "2", "strong": "2"}.get(tier_hb, "")
            return ParsedSignal(
                valid=True, action=action,
                symbol=self._normalize_symbol(raw.get("symbol", "ETH")),
                price=_f("price", "tv_entry"), stop_loss=_f("stop_loss", "tv_stop"),
                atr=_f("atr"),
                tp1=_f("tp1", "tv_tp1"), tp2=_f("tp2", "tv_tp2"), tp3=_f("tp3", "tv_tp3"),
                qty=None, tier=tier_hb, leverage=20, error="",
                side=side, raw=dict(raw),
            )

        # 3) 交易对
        symbol = self._normalize_symbol(raw.get("symbol", "ETH"))
        if symbol not in VALID_SYMBOLS:
            return ParsedSignal(
                valid=False, action=action, symbol=symbol, price=0,
                stop_loss=0, atr=0, tp1=0, tp2=0, tp3=0,
                qty=None, tier="", leverage=20,
                error=f"invalid_symbol:{symbol}",
            )

        # 4) 价格
        try:
            price = float(raw.get("price") or 0)
        except (TypeError, ValueError):
            price = 0.0

        if price <= 0:
            return ParsedSignal(
                valid=False, action=action, symbol=symbol, price=0,
                stop_loss=0, atr=0, tp1=0, tp2=0, tp3=0,
                qty=None, tier="", leverage=20,
                error="missing_price",
            )

        # 5) ATR（开仓必填）
        try:
            atr = float(raw.get("atr") or 0)
        except (TypeError, ValueError):
            atr = 0.0

        if atr <= 0 and action in ("LONG", "SHORT"):
            return ParsedSignal(
                valid=False, action=action, symbol=symbol, price=price,
                stop_loss=0, atr=0, tp1=0, tp2=0, tp3=0,
                qty=None, tier="", leverage=20,
                error="missing_atr",
            )

        # 6) Stop Loss
        try:
            stop_loss = float(raw.get("stop_loss") or 0)
        except (TypeError, ValueError):
            stop_loss = 0.0

        # 7) TP
        try:
            tp1 = float(raw.get("tp1") or 0)
        except (TypeError, ValueError):
            tp1 = 0.0

        try:
            tp2 = float(raw.get("tp2") or 0)
        except (TypeError, ValueError):
            tp2 = 0.0

        try:
            tp3 = float(raw.get("tp3") or 0)
        except (TypeError, ValueError):
            tp3 = 0.0

        # 8) 可选qty
        qty = None
        if raw.get("qty") is not None:
            try:
                qty = float(raw.get("qty"))
            except (TypeError, ValueError):
                pass

        # 9) Tier（趋势档位）
        # 2026-09-12修复：`or` 链在 tier 是 JSON 整数 0 时会被当 falsy 跳过
        # （新策略"Webhook 对齐版 + tier 动态分档"发的是裸数字 "tier":0，
        # 不是老信号常见的字符串"0"），此前会一路落到 else 分支变成空串
        # ""，get_tier_risk_pct(defense_profiles.py) 对空串按强档
        # (DEFAULT_RISK_PCT=0.40) 兜底——等于把弱信号仓位悄悄放大到本该
        # 强信号才有的2倍名义，静默超配。改用 is not None 判定，不再用
        # 真值判定。
        _tier_raw = raw.get("tier")
        if _tier_raw is None:
            _tier_raw = raw.get("adx_tier")
        tier = str(_tier_raw if _tier_raw is not None else "").lower()
        if tier in ("0", "弱", "weak"):
            tier = "0"
        elif tier in ("1", "中", "medium"):
            tier = "1"
        elif tier in ("2", "强", "strong"):
            tier = "2"
        else:
            tier = ""

        # 10) 杠杆
        try:
            leverage = int(float(raw.get("leverage") or 20))
        except (TypeError, ValueError):
            leverage = 20

        return ParsedSignal(
            valid=True,
            action=action,
            symbol=symbol,
            price=price,
            stop_loss=stop_loss,
            atr=atr,
            tp1=tp1,
            tp2=tp2,
            tp3=tp3,
            qty=qty,
            tier=tier,
            leverage=leverage,
            error="",
            side=action if action in ("LONG", "SHORT") else "",
            raw=dict(raw),
        )

    def is_duplicate(self, action: str, symbol: str, price: float) -> bool:
        """检查1s内重复信号"""
        key = f"{action}:{symbol}:{price}"
        now = time.time()

        # 清理过期
        cutoff = now - 1.0
        expired = [k for k, ts in self._signal_cache.items() if ts < cutoff]
        for k in expired:
            self._signal_cache.pop(k, None)

        if key in self._signal_cache:
            return True

        self._signal_cache[key] = now
        return False


# 单例
_parser: Optional[WebhookParser] = None
_parser_lock = None


def get_parser() -> WebhookParser:
    global _parser
    if _parser is None:
        _parser = WebhookParser()
    return _parser


def parse_webhook(raw: dict) -> ParsedSignal:
    """快捷解析函数"""
    return get_parser().parse(raw)
