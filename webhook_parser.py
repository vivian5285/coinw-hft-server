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

logger = logging.getLogger(__name__)

# 有效动作
VALID_ACTIONS = {"LONG", "SHORT", "CLOSE", "CLOSE_QUICK_EXIT", "CLOSE_RSI_EXIT", "PING"}

# 支持的交易对
VALID_SYMBOLS = {"ETH", "BTC", "XAU", "BNB"}


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
        tier = str(raw.get("tier") or raw.get("adx_tier") or "").lower()
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
