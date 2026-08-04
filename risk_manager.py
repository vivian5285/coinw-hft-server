#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
风险管理器 - CoinW单系统 v16.22.1

日熔断：日亏5.5%、连续亏3次、日交易8次、回撤12%
开仓闸门：默认关闭（生产防误挡）
"""

from __future__ import annotations

import os
import time
import threading
from typing import Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class DailyStats:
    trades: int = 0
    wins: int = 0
    losses: int = 0
    pnl: float = 0.0
    max_drawdown: float = 0.0
    start_equity: float = 0.0
    trades_detail: List[dict] = field(default_factory=list)


@dataclass
class RiskConfig:
    daily_loss_pct: float = 0.055       # 日亏5.5%
    max_consecutive_losses: int = 3      # 连续亏3次
    max_daily_trades: int = 8           # 日交易8次
    max_drawdown_pct: float = 0.12      # 回撤12%
    open_gate_enabled: bool = False      # 开仓闸门（默认关闭）


class RiskManager:
    """风险管理器"""

    def __init__(self, config: RiskConfig = None):
        self._config = config or RiskConfig()
        self._lock = threading.Lock()

        # 当日统计
        self._daily: Dict[str, DailyStats] = {}  # symbol -> DailyStats
        self._daily_date: str = ""  # 当前日期YYYY-MM-DD

        # 全局连续亏损
        self._consecutive_losses: int = 0

    def _check_date(self):
        """检查日期切换"""
        today = time.strftime("%Y-%m-%d")
        if today != self._daily_date:
            with self._lock:
                if today != self._daily_date:
                    self._daily.clear()
                    self._daily_date = today
                    self._consecutive_losses = 0

    def can_open(self, symbol: str, equity: float, risk_pct: float = 0.20) -> tuple:
        """
        检查是否可以开仓
        返回 (ok, reason)
        """
        self._check_date()

        with self._lock:
            sym = str(symbol or "ETH").upper()
            stats = self._daily.get(sym, DailyStats())
            self._daily[sym] = stats

            # 1) 日交易次数
            if stats.trades >= self._config.max_daily_trades:
                return False, f"daily_trades_limit:{stats.trades}>={self._config.max_daily_trades}"

            # 2) 连续亏损
            if self._consecutive_losses >= self._config.max_consecutive_losses:
                return False, f"consecutive_losses:{self._consecutive_losses}>={self._config.max_consecutive_losses}"

            # 3) 日亏
            if stats.start_equity > 0:
                daily_loss_pct = abs(stats.pnl) / stats.start_equity
                if daily_loss_pct >= self._config.daily_loss_pct:
                    return False, f"daily_loss:{daily_loss_pct:.2%}>={self._config.daily_loss_pct:.2%}"

            # 4) 回撤（如果有起始权益）
            if stats.start_equity > 0:
                peak = stats.start_equity + max(0, stats.pnl)
                current = stats.start_equity + stats.pnl
                drawdown = (peak - current) / peak if peak > 0 else 0
                if drawdown >= self._config.max_drawdown_pct:
                    return False, f"drawdown:{drawdown:.2%}>={self._config.max_drawdown_pct:.2%}"

            # 闸门检查（如果启用）
            if self._config.open_gate_enabled:
                if stats.trades >= self._config.max_daily_trades:
                    return False, "open_gate_closed"

            return True, "ok"

    def record_trade(self, symbol: str, pnl: float, entry_price: float, exit_price: float,
                    direction: str, qty: float):
        """记录交易"""
        self._check_date()

        with self._lock:
            sym = str(symbol or "ETH").upper()
            stats = self._daily.get(sym, DailyStats())

            # 记录起始权益（首次）
            if stats.start_equity <= 0:
                stats.start_equity = abs(pnl) + 10  # 估算

            stats.trades += 1
            stats.pnl += pnl

            if pnl > 0:
                stats.wins += 1
                self._consecutive_losses = 0
            else:
                stats.losses += 1
                self._consecutive_losses += 1

            # 更新最大回撤
            peak = stats.start_equity + max(0, max(s["pnl"] for s in stats.trades_detail) if stats.trades_detail else 0)
            current = stats.start_equity + stats.pnl
            stats.max_drawdown = max(stats.max_drawdown, (peak - current) / peak if peak > 0 else 0)

            # 记录详情
            stats.trades_detail.append({
                "ts": time.time(),
                "pnl": pnl,
                "entry": entry_price,
                "exit": exit_price,
                "direction": direction,
                "qty": qty,
            })

            # 只保留最近50条
            stats.trades_detail = stats.trades_detail[-50:]

            self._daily[sym] = stats

    def get_status(self, symbol: str = "") -> dict:
        """获取状态"""
        self._check_date()

        with self._lock:
            if symbol:
                sym = str(symbol).upper()
                stats = self._daily.get(sym, DailyStats())
                return {
                    "date": self._daily_date,
                    "symbol": sym,
                    "trades": stats.trades,
                    "wins": stats.wins,
                    "losses": stats.losses,
                    "pnl": stats.pnl,
                    "win_rate": stats.wins / stats.trades if stats.trades > 0 else 0,
                    "max_drawdown": stats.max_drawdown,
                    "consecutive_losses": self._consecutive_losses,
                    "config": {
                        "daily_loss_pct": self._config.daily_loss_pct,
                        "max_consecutive_losses": self._config.max_consecutive_losses,
                        "max_daily_trades": self._config.max_daily_trades,
                        "max_drawdown_pct": self._config.max_drawdown_pct,
                        "open_gate_enabled": self._config.open_gate_enabled,
                    }
                }
            else:
                return {
                    "date": self._daily_date,
                    "symbols": {
                        sym: {
                            "trades": s.trades,
                            "wins": s.wins,
                            "losses": s.losses,
                            "pnl": s.pnl,
                        }
                        for sym, s in self._daily.items()
                    },
                    "consecutive_losses": self._consecutive_losses,
                }

    def reset(self, symbol: str = ""):
        """重置统计"""
        with self._lock:
            if symbol:
                sym = str(symbol).upper()
                self._daily.pop(sym, None)
            else:
                self._daily.clear()
                self._consecutive_losses = 0


# 单例
_risk_manager: Optional[RiskManager] = None
_risk_lock = threading.Lock()


def get_risk_manager() -> RiskManager:
    global _risk_manager
    with _risk_lock:
        if _risk_manager is None:
            # 从环境变量读取配置
            config = RiskConfig(
                daily_loss_pct=float(os.getenv("RISK_DAILY_LOSS_PCT", "0.055")),
                max_consecutive_losses=int(os.getenv("RISK_MAX_CONSECUTIVE_LOSSES", "3")),
                max_daily_trades=int(os.getenv("RISK_MAX_DAILY_TRADES", "8")),
                max_drawdown_pct=float(os.getenv("RISK_MAX_DRAWDOWN_PCT", "0.12")),
                open_gate_enabled=str(os.getenv("CIRCUIT_BREAKER_OPEN_GATE_ENABLED", "False")).lower() == "true",
            )
            _risk_manager = RiskManager(config)
        return _risk_manager
