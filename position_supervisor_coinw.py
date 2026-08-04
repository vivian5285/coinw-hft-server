#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CoinW仓位监控器 - v16.22.1-coinw-init
唯一生产大脑

流水线阶段：
IDLE -> SIGNAL_RECEIVED -> PENDING_CLEAR -> CLEARED ->
ENTRY_SUBMITTED -> ENTRY_CONFIRMED -> ORDERS_PLACED ->
VERIFIED -> REPORTED -> MONITORING
"""

import os
import time
import json
import logging
import threading
from typing import Optional, Dict, Any

from dotenv import load_dotenv
load_dotenv()

# 版本号
COINW_SUPERVISOR_VERSION = "v16.22.1-coinw-init"

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] CoinW: %(message)s'
)
logger = logging.getLogger(__name__)

# 交易暂停标志
trading_paused = False


class PositionSupervisorCoinW:
    """
    CoinW唯一生产大脑
    每symbol一实例
    """

    def __init__(self, symbol: str = "ETH"):
        self.symbol = str(symbol or "ETH").upper()
        self._lock = threading.RLock()

        # 状态
        self._monitoring = False
        self._monitor_thread: Optional[threading.Thread] = None

        # 初始化模块
        self._init_modules()

        logger.info(f"CoinW Supervisor {COINW_SUPERVISOR_VERSION} 就绪: {self.symbol}")

    def _init_modules(self):
        """初始化各模块"""
        # 延迟导入避免循环依赖
        from coinw_client import coinw_client, is_position_query_failed
        from pipeline_ledger import get_pipeline, Phase, Role
        from pipeline_bridge import PipelineBridge
        from chief_auditor import audit_open_bundle, should_hard_pause
        from risk_manager import get_risk_manager
        from webhook_parser import parse_webhook
        from defense_profiles import get_defense_profile
        from atr_scenario import calc_hard_stop_price
        from breath_stop import get_radar
        from radar_reentry_mixin import get_radar_mixin
        from order_idempotency import get_idempotency
        from api_throttle import get_throttle
        import dingtalk

        self.client = coinw_client
        self.pipeline = get_pipeline(self.symbol, "coinw")
        self.bridge = PipelineBridge(self)
        self.risk_mgr = get_risk_manager()
        self.radar = get_radar(self.symbol)
        self.radar_mixin = get_radar_mixin()
        self.idempotency = get_idempotency()
        self.throttle = get_throttle("coinw")
        self._dingtalk = dingtalk

    def _get_balance(self) -> float:
        """获取余额"""
        return self.client.get_available_balance()

    def _get_current_price(self) -> float:
        """获取当前价格"""
        return self.client.get_current_price(self.symbol)

    # ==================== 信号处理入口 ====================

    def handle_signal(self, payload: dict) -> dict:
        """
        处理TV webhook信号
        """
        global trading_paused

        with self._lock:
            # 解析信号
            from webhook_parser import parse_webhook
            signal = parse_webhook(payload)

            if not signal.valid:
                logger.warning(f"信号解析失败: {signal.error}")
                return {"ok": False, "error": signal.error}

            logger.info(f"收到信号: {signal.action} {signal.symbol} @ {signal.price}")

            # CLOSE信号
            if signal.action in ("CLOSE", "CLOSE_QUICK_EXIT", "CLOSE_RSI_EXIT"):
                return self._handle_close(signal)

            # LONG/SHORT信号
            if signal.action in ("LONG", "SHORT"):
                return self._handle_open(signal)

            return {"ok": False, "error": "unknown_action"}

    def _handle_open(self, signal) -> dict:
        """处理开仓信号"""
        global trading_paused

        if trading_paused:
            logger.warning("交易暂停中，拒绝开仓")
            return {"ok": False, "error": "trading_paused"}

        # 1) 信号官登记
        self.pipeline.advance(
            Phase.SIGNAL_RECEIVED,
            Role.SIGNAL,
            note=f"{signal.action} @ {signal.price}",
            action=signal.action,
            price=signal.price,
            atr=signal.atr,
            stop_loss=signal.stop_loss,
            tp1=signal.tp1,
            tp2=signal.tp2,
            tier=signal.tier,
        )

        # 2) 仓位稽查员 - 先平后开
        self.pipeline.advance(Phase.PENDING_CLEAR, Role.AUDITOR_POS, note="开始清场")
        cleared = self._clear_position(f"预开仓 {signal.action}")

        if not cleared:
            self.pipeline.mark_failed(Role.AUDITOR_POS, "清场失败")
            return {"ok": False, "error": "clear_failed"}

        self.pipeline.advance(Phase.CLEARED, Role.AUDITOR_POS, note="清场完成")

        # 3) 计算仓位
        balance = self._get_balance()
        entry_price = signal.price
        qty = self._calc_position_size(balance, entry_price)

        # 检查TV qty soft-cap
        if signal.qty and signal.qty > 0 and signal.qty < qty:
            qty = signal.qty

        # 4) 开仓
        self.pipeline.advance(Phase.ENTRY_SUBMITTED, Role.EXECUTION, note="提交开仓")
        entry_result = self._execute_open(signal.action, entry_price, qty, signal)

        if not entry_result.get("ok"):
            self.pipeline.mark_failed(Role.EXECUTION, entry_result.get("error", "开仓失败"))
            return entry_result

        # 5) 同步持仓
        self.pipeline.sync_position(
            side=signal.action,
            qty=entry_result.get("qty", qty),
            entry=entry_result.get("entry_price", entry_price),
            position_id=entry_result.get("position_id", ""),
            allow_initial=True,
        )

        self.pipeline.advance(Phase.ENTRY_CONFIRMED, Role.EXECUTION,
                           note=f"开仓确认 {entry_result.get('entry_price')} x {entry_result.get('qty')}")

        # 6) 设置防线
        orders_placed = self._place_defense_orders(signal, entry_result)

        if not orders_placed:
            self.pipeline.mark_failed(Role.EXECUTION, "防线设置失败")
            return {"ok": False, "error": "defense_failed"}

        self.pipeline.advance(Phase.ORDERS_PLACED, Role.EXECUTION, note="防线就绪")

        # 7) 督察官复查
        audit_ok = self._run_audit(signal)

        if not audit_ok:
            self._pause_trading("督察失败")
            self.pipeline.mark_failed(Role.CHIEF, "审计失败")
            return {"ok": False, "error": "audit_failed"}

        self.pipeline.advance(Phase.VERIFIED, Role.CHIEF, note="督察通过")

        # 8) 通讯官通知
        self._report_open(signal, entry_result)
        self.pipeline.advance(Phase.REPORTED, Role.COMMS, note="已通知")

        # 9) 进入监控
        self.pipeline.advance(Phase.MONITORING, Role.RADAR, note="开始监控")
        self._start_monitoring()

        return {
            "ok": True,
            "entry_price": entry_result.get("entry_price"),
            "qty": entry_result.get("qty"),
            "position_id": entry_result.get("position_id"),
        }

    def _handle_close(self, signal) -> dict:
        """处理平仓信号"""
        logger.info(f"收到平仓信号: {signal.action}")

        # 停止监控
        self._stop_monitoring()

        # 清仓
        success = self._clear_position(f"TV平仓 {signal.action}")

        # 重置流水线
        self.pipeline.reset_idle("tv_close")

        return {
            "ok": success,
            "action": signal.action,
        }

    # ==================== 开仓执行 ====================

    def _calc_position_size(self, balance: float, entry_price: float) -> float:
        """计算仓位"""
        from defense_profiles import get_defense_profile
        profile = get_defense_profile(self.symbol)

        return profile.calc_position_size(balance, entry_price)

    def _execute_open(self, action: str, price: float, qty: float, signal) -> dict:
        """执行开仓"""
        try:
            # 获取当前价格作为参考
            current_price = self._get_current_price()

            # 市价开仓
            result = self.client.place_market_order(
                side=action,
                quantity=qty,
                instrument=self.symbol,
            )

            if not result or result.get("code") != 0:
                error = result.get("msg", "开仓失败") if result else "无响应"
                logger.error(f"开仓失败: {error}")
                return {"ok": False, "error": error}

            # 获取持仓信息
            time.sleep(0.5)  # 等待成交
            pos = self.client.get_position(self.symbol)

            if not pos:
                return {"ok": False, "error": "持仓未找到"}

            position_id = pos.get("id", "")
            entry_price = float(pos.get("openPrice", current_price))
            actual_qty = float(pos.get("quantity", qty))

            logger.info(f"开仓成功: {action} {actual_qty} @ {entry_price}")

            return {
                "ok": True,
                "entry_price": entry_price,
                "qty": actual_qty,
                "position_id": position_id,
                "atr": signal.atr,
            }

        except Exception as e:
            logger.error(f"开仓异常: {e}")
            return {"ok": False, "error": str(e)}

    # ==================== 防线设置 ====================

    def _place_defense_orders(self, signal, entry_result: dict) -> bool:
        """设置三层防线"""
        try:
            position_id = entry_result.get("position_id", "")
            entry_price = entry_result.get("entry_price", 0)
            direction = signal.action

            # 1) 硬止损
            hard_sl_price, dist, ok, err = calc_hard_stop_price(
                tv_price=signal.price,
                tv_stop_loss=signal.stop_loss,
                entry_price=entry_price,
                direction=direction,
            )

            if not ok:
                logger.error(f"硬止损计算失败: {err}")
                return False

            # 设置止损（通过TPSL接口）
            sl_result = self.client.set_sl_tp(
                position_id=position_id,
                instrument=self.symbol,
                stop_loss_price=hard_sl_price,
                stop_from=2,  # 市价触发
                price_type=3,  # 标记价格
            )

            self.pipeline.data["hard_sl_px"] = hard_sl_price

            # 2) TP1 + TP2
            tp1_qty = entry_result.get("qty", 0) * 0.10
            tp2_qty = entry_result.get("qty", 0) * 0.20

            if signal.tp1 > 0:
                # TP1限价单
                self.client.place_limit_order(
                    side=direction,
                    quantity=tp1_qty,
                    price=signal.tp1,
                    instrument=self.symbol,
                    reduce_only=True,
                )
                self.pipeline.data["tp1"] = {
                    "px": signal.tp1,
                    "qty": tp1_qty,
                }

            if signal.tp2 > 0:
                # TP2限价单
                self.client.place_limit_order(
                    side=direction,
                    quantity=tp2_qty,
                    price=signal.tp2,
                    instrument=self.symbol,
                    reduce_only=True,
                )
                self.pipeline.data["tp2"] = {
                    "px": signal.tp2,
                    "qty": tp2_qty,
                }

            # 3) 雷达初始化（休眠状态）
            self.radar.set_atr(signal.atr)
            self.radar.reset()

            logger.info(f"防线就绪: SL={hard_sl_price}, TP1={signal.tp1}, TP2={signal.tp2}")

            return True

        except Exception as e:
            logger.error(f"防线设置异常: {e}")
            return False

    # ==================== 监控循环 ====================

    def _start_monitoring(self):
        """启动监控"""
        if self._monitoring:
            return

        self._monitoring = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name=f"coinw-monitor-{self.symbol}"
        )
        self._monitor_thread.start()
        logger.info(f"监控启动: {self.symbol}")

    def _stop_monitoring(self):
        """停止监控"""
        self._monitoring = False

    def _monitor_loop(self):
        """监控循环"""
        import breath_profiles
        from smart_reentry_engine import should_reenter

        while self._monitoring:
            try:
                # 1) 检查持仓
                pos = self.client.get_position(self.symbol)
                current_price = self._get_current_price()

                if not pos:
                    # 仓位归零
                    self._on_position_zero()
                    break

                # 2) 检查TP成交
                tp1_filled = self.pipeline.data.get("tp1", {}).get("filled", False)
                tp2_filled = self.pipeline.data.get("tp2", {}).get("filled", False)

                # 3) 雷达激活检查
                if not self.radar.get_state().activated and tp2_filled:
                    # TP2成交后激活雷达
                    should, reason = self.radar.should_activate(current_price, tp2_filled)
                    if should:
                        self._activate_radar(entry_result)

                # 4) 雷达止损更新
                tier = self.pipeline.data.get("tier", "1")
                params = breath_profiles.get_breath_profile(self.symbol).get_tier_params(tier)
                new_sl = self.radar.update(current_price, params)

                if new_sl:
                    self._update_radar_sl(new_sl)

                # 等待
                time.sleep(4)  # 雷达间隔

            except Exception as e:
                logger.error(f"监控异常: {e}")
                time.sleep(5)

    def _activate_radar(self, entry_result: dict):
        """激活雷达"""
        tp2_px = self.pipeline.data.get("tp2", {}).get("px", 0)
        tier = self.pipeline.data.get("tier", "1")
        direction = self.pipeline.data.get("side", "LONG")

        self.radar.activate(
            entry_price=entry_result.get("entry_price", 0),
            tp2_price=tp2_px,
            tier=tier,
            direction=direction,
        )

        # 设置初始止损为保本
        entry = entry_result.get("entry_price", 0)
        if direction == "LONG":
            initial_sl = entry - 0.01  # 保本起步
        else:
            initial_sl = entry + 0.01

        self.client.set_sl_tp(
            position_id=entry_result.get("position_id", ""),
            instrument=self.symbol,
            stop_loss_price=round(initial_sl, 2),
        )

        logger.info(f"雷达激活: 方向={direction}, TP2={tp2_px}, 初始SL={initial_sl}")

    def _update_radar_sl(self, new_sl: float):
        """更新雷达止损"""
        position_id = self.pipeline.data.get("position_id", "")
        if not position_id:
            return

        self.client.set_sl_tp(
            position_id=position_id,
            instrument=self.symbol,
            stop_loss_price=new_sl,
        )

        logger.info(f"雷达止损更新: {new_sl}")

    def _on_position_zero(self):
        """仓位归零"""
        logger.info(f"仓位归零: {self.symbol}")

        # 停止监控
        self._monitoring = False

        # 清除挂单
        self.client.cancel_all_orders(self.symbol)

        # 清除雷达
        self.radar.reset()

        # 通知
        self._dingtalk.report_coinw_tp("仓位归零", 0)

        # 重置流水线
        self.pipeline.reset_idle("position_zero")

    # ==================== 清仓 ====================

    def _clear_position(self, reason: str) -> bool:
        """清仓"""
        logger.info(f"清仓: {reason}")

        # 1) 撤单
        self.client.cancel_all_orders(self.symbol)

        # 2) 平仓
        success = self.client.close_all_positions(self.symbol)

        # 3) 等待确认
        for _ in range(5):
            time.sleep(1)
            pos = self.client.get_position(self.symbol)
            if not pos:
                return True

        return False

    # ==================== 审计 ====================

    def _run_audit(self, signal) -> bool:
        """运行督察官审计"""
        from chief_auditor import audit_open_bundle, should_hard_pause

        facts = {
            "symbol": self.symbol,
            "signal_side": signal.action,
            "live_side": signal.action,
            "live_qty": self.pipeline.data.get("qty", 0),
            "initial_qty": self.pipeline.data.get("initial_qty", 0),
            "entry": self.pipeline.data.get("entry", 0),
            "tp1_qty": self.pipeline.data.get("tp1", {}).get("qty", 0),
            "tp2_qty": self.pipeline.data.get("tp2", {}).get("qty", 0),
            "hard_sl_px": self.pipeline.data.get("hard_sl_px", 0),
            "hard_sl_live": True,
            "tier": signal.tier,
        }

        result = audit_open_bundle(facts)
        self.pipeline.set_audit(
            result.ok,
            result.hard_fails,
            result.warns,
        )

        if result.hard_fails:
            logger.warning(f"审计失败: {result.hard_fails}")

        return result.ok

    # ==================== 通知 ====================

    def _report_open(self, signal, entry_result: dict):
        """发送开仓通知"""
        try:
            self._dingtalk.report_coinw_open(
                action=signal.action,
                entry_price=entry_result.get("entry_price"),
                qty=entry_result.get("qty"),
                tp_dict={"tp1": signal.tp1, "tp2": signal.tp2},
                margin=0,
            )
        except Exception as e:
            logger.error(f"通知失败: {e}")

    # ==================== 暂停 ====================

    def _pause_trading(self, reason: str):
        """暂停交易"""
        global trading_paused
        trading_paused = True
        logger.warning(f"交易暂停: {reason}")

        self._dingtalk.send_alert(f"交易暂停: {reason}")

    # ==================== 健康检查 ====================

    def get_health(self) -> dict:
        """获取健康状态"""
        return {
            "version": COINW_SUPERVISOR_VERSION,
            "symbol": self.symbol,
            "pipeline": self.pipeline.phase.value,
            "trading_paused": trading_paused,
            "monitoring": self._monitoring,
            "radar": self.radar.get_state().activated,
            "position_id": self.pipeline.data.get("position_id", ""),
        }


# ==================== 全局暂停控制 ====================

def pause_all_trading(reason: str):
    """暂停所有交易"""
    global trading_paused
    trading_paused = True
    logger.warning(f"全局暂停: {reason}")


def resume_all_trading():
    """恢复所有交易"""
    global trading_paused
    trading_paused = False
    logger.info("交易恢复")


def is_trading_paused() -> bool:
    """检查是否暂停"""
    return trading_paused
