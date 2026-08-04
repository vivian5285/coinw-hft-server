#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
岗位交接桥 - CoinW单系统 v16.22.1

各岗位之间的协调和数据传递
"""

from __future__ import annotations

import logging
from typing import Dict, Optional, Any
from pipeline_ledger import Phase, Role

logger = logging.getLogger(__name__)


class PipelineBridge:
    """
    流水线岗位交接桥
    协调各模块之间的数据流
    """

    def __init__(self, supervisor):
        self.supervisor = supervisor

    # ==================== 信号官 -> 仓位稽查员 ====================

    def handover_to_clear(self, signal_data: dict) -> dict:
        """
        信号官 -> 仓位稽查员
        返回清理所需数据
        """
        return {
            "symbol": signal_data.get("symbol", "ETH"),
            "direction": signal_data.get("action"),
            "reason": "pre_open_clear",
        }

    # ==================== 仓位稽查员 -> 执行官 ====================

    def handover_to_execution(self, ledger_state: dict, signal_data: dict) -> dict:
        """
        仓位稽查员 -> 执行官
        返回开仓所需数据
        """
        symbol = ledger_state.get("symbol", "ETH")

        # 计算仓位
        from defense_profiles import get_defense_profile
        profile = get_defense_profile(symbol)

        entry_price = signal_data.get("price", 0)
        balance = self.supervisor._get_balance()

        qty = profile.calc_position_size(balance, entry_price)

        # 检查TV qty soft-cap
        tv_qty = signal_data.get("qty")
        if tv_qty and tv_qty > 0 and tv_qty < qty:
            qty = tv_qty

        return {
            "symbol": symbol,
            "direction": signal_data.get("action"),
            "qty": qty,
            "entry_price": entry_price,
            "leverage": signal_data.get("leverage", 20),
            "atr": signal_data.get("atr", 0),
            "stop_loss": signal_data.get("stop_loss", 0),
            "tp1": signal_data.get("tp1", 0),
            "tp2": signal_data.get("tp2", 0),
            "tp3": signal_data.get("tp3", 0),
            "tier": signal_data.get("tier", "1"),
        }

    # ==================== 执行官 -> 雷达值守员 ====================

    def handover_to_radar(self, ledger_state: dict, entry_result: dict) -> dict:
        """
        执行官 -> 雷达值守员
        返回雷达启动所需数据
        """
        return {
            "symbol": ledger_state.get("symbol", "ETH"),
            "direction": ledger_state.get("side"),
            "entry_price": entry_result.get("entry_price", 0),
            "qty": entry_result.get("qty", 0),
            "position_id": entry_result.get("position_id", ""),
            "atr": entry_result.get("atr", 0),
            "tp1": ledger_state.get("tp1", {}).get("px", 0),
            "tp2": ledger_state.get("tp2", {}).get("px", 0),
            "tier": ledger_state.get("tier", "1"),
            "hard_sl_price": entry_result.get("hard_sl_price", 0),
        }

    # ==================== 督察官 -> 通讯官 ====================

    def handover_to_comms(self, ledger_state: dict, audit_result: dict) -> dict:
        """
        督察官 -> 通讯官
        返回通知所需数据
        """
        return {
            "symbol": ledger_state.get("symbol", "ETH"),
            "direction": ledger_state.get("side"),
            "entry_price": ledger_state.get("entry", 0),
            "qty": ledger_state.get("qty", 0),
            "hard_sl_price": ledger_state.get("hard_sl_px", 0),
            "tp1": ledger_state.get("tp1", {}).get("px", 0),
            "tp2": ledger_state.get("tp2", {}).get("px", 0),
            "tier": ledger_state.get("tier", ""),
            "tier_label": self._get_tier_label(ledger_state.get("tier", "")),
            "audit_ok": audit_result.get("ok", True),
            "audit_fails": audit_result.get("hard_fails", []),
        }

    def _get_tier_label(self, tier: str) -> str:
        """获取档位标签"""
        tier = str(tier or "1")
        labels = {
            "0": "弱趋势(T0)",
            "1": "中趋势(T1)",
            "2": "强趋势(T2)",
        }
        return labels.get(tier, f"档位{tier}")

    # ==================== 平仓时序 ====================

    def on_position_zero(self, symbol: str):
        """
        仓位归零回调
        清空所有状态
        """
        logger.info(f"仓位归零: {symbol}")

        # 清除雷达
        from breath_stop import get_radar
        radar = get_radar(symbol)
        radar.reset()

        # 清除再入状态
        from radar_reentry_mixin import get_radar_mixin
        mixin = get_radar_mixin()
        mixin.clear_reentry_in_progress(symbol)

    def on_tp_filled(self, symbol: str, tp_level: str, remaining_qty: float):
        """
        TP成交回调
        更新剩余仓位
        """
        logger.info(f"TP{tp_level}成交: {symbol}, 剩余: {remaining_qty}")

        # 雷达数量同步收缩
        from breath_stop import get_radar
        radar = get_radar(symbol)

        # 更新状态
        from pipeline_ledger import get_pipeline
        ledger = get_pipeline(symbol, "coinw")

        if tp_level == "1":
            ledger.data["tp1"]["filled"] = True
        elif tp_level == "2":
            ledger.data["tp2"]["filled"] = True

        ledger.data["qty"] = remaining_qty
        ledger.data["updated_ts"] = time.time()


# 导入time
import time
