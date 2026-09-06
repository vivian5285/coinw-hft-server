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

from pipeline_ledger import PipelineLedger, get_pipeline, Phase, Role

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

# ==================== 开仓滑点阶梯（被动限价 -> 可成交限价 -> 市价兜底）====================
# 目标：TV 信号到达后先挂对我们最有利的限价（不劣于 TV 价），给一小段时间做 maker；
# 没成交就让利到滑点上限的可成交限价；仍不成交才市价兜底。现价逆向跑过头则放弃这次信号。
ENTRY_LADDER_ENABLED = os.getenv("ENTRY_LADDER", "1").lower() in ("1", "true", "yes")
ENTRY_PASSIVE_SEC = float(os.getenv("ENTRY_PASSIVE_SEC", "25"))      # 阶段1：TV 价被动限价，做 maker
ENTRY_MARKETABLE_SEC = float(os.getenv("ENTRY_MARKETABLE_SEC", "45"))  # 阶段2：让利到滑点上限的可成交限价
ENTRY_SLIP_CAP_PCT = float(os.getenv("ENTRY_SLIP_CAP_PCT", "0.0012"))  # 阶段2 最多相对 TV 价让 0.12%
ENTRY_ABORT_PCT = float(os.getenv("ENTRY_ABORT_PCT", "0.004"))        # 现价比 TV 价逆向跑超 0.4% -> 放弃信号
ENTRY_POLL_SEC = float(os.getenv("ENTRY_POLL_SEC", "3"))
# 强趋势(tier=2)立即进入：跳过①被动限价（单边突破里等回踩=纯负收益，对齐币安
# _try_better_than_tv_limit_entry 的 tier>=2 跳过），直接可成交限价(短窗)+市价。
ENTRY_STRONG_IMMEDIATE = os.getenv("ENTRY_STRONG_IMMEDIATE", "1").lower() in ("1", "true", "yes")
ENTRY_STRONG_MARKETABLE_SEC = float(os.getenv("ENTRY_STRONG_MARKETABLE_SEC", "8"))

# ==================== 心跳催单 / 启动恢复 / 裸单守护 ====================
HEARTBEAT_CATCHUP_ENABLED = os.getenv("HEARTBEAT_CATCHUP", "1").lower() in ("1", "true", "yes")
CATCHUP_MAX_DRIFT_PCT = float(os.getenv("CATCHUP_MAX_DRIFT_PCT", "0.006"))  # 现价偏离心跳entry超此 -> 不补开
HEARTBEAT_FLAT_CLOSE = os.getenv("HEARTBEAT_FLAT_CLOSE", "0").lower() in ("1", "true", "yes")  # TV空/VPS有仓是否自动补平
CATCHUP_BLOCK_SEC = float(os.getenv("CATCHUP_BLOCK_SEC", "1800"))  # 手动平/TV平后多久内不被心跳补开
STARTUP_RECOVERY_ENABLED = os.getenv("STARTUP_RECOVERY", "1").lower() in ("1", "true", "yes")
NAKED_GUARD_ENABLED = os.getenv("NAKED_GUARD", "1").lower() in ("1", "true", "yes")

# ==================== 止损后冷却 + 智能再入 ====================
COOLDOWN_SEC = float(os.getenv("COOLDOWN_SEC", "1800"))          # 止损后同向 TV 信号冷却
COOLDOWN_IGNORE_TV = os.getenv("COOLDOWN_IGNORE_TV", "1").lower() in ("1", "true", "yes")
REENTRY_ENABLED = os.getenv("REENTRY_ENABLED", "1").lower() in ("1", "true", "yes")
REENTRY_MAX = int(os.getenv("REENTRY_MAX", "1"))
REENTRY_DELAY_SEC = float(os.getenv("REENTRY_DELAY_SEC", "300"))   # 止损后先等这么久才开始找再入机会
REENTRY_WINDOW_SEC = float(os.getenv("REENTRY_WINDOW_SEC", "18000"))  # 再入机会窗口(默认5h=2根150m)
REENTRY_POLL_SEC = float(os.getenv("REENTRY_POLL_SEC", "30"))
REENTRY_SIZE_FACTOR = float(os.getenv("REENTRY_SIZE_FACTOR", "0.6"))
REENTRY_ADX_GATE = float(os.getenv("REENTRY_ADX_GATE", "20"))
REENTRY_MAX_CHASE_PCT = float(os.getenv("REENTRY_MAX_CHASE_PCT", "0.006"))
REENTRY_HARD_SL_ATR = float(os.getenv("REENTRY_HARD_SL_ATR", "2.0"))

# ==================== 高潮否决 / 反转锁利 ====================
CLIMAX_VETO_ENABLED = os.getenv("CLIMAX_VETO", "1").lower() in ("1", "true", "yes")
CLIMAX_ATR_MULT = float(os.getenv("CLIMAX_ATR_MULT", "3.0"))
OVEREXT_ATR_MULT = float(os.getenv("OVEREXT_ATR_MULT", "4.0"))
REVLOCK_ENABLED = os.getenv("REVLOCK", "1").lower() in ("1", "true", "yes")
REVLOCK_BODY_ATR = float(os.getenv("REVLOCK_BODY_ATR", "1.1"))
REVLOCK_VOL_MULT = float(os.getenv("REVLOCK_VOL_MULT", "1.4"))
REVLOCK_MIN_PROFIT_ATR = float(os.getenv("REVLOCK_MIN_PROFIT_ATR", "0.8"))  # 至少这么多浮盈才收保本

# ==================== 追单确认观察窗 / 孤儿单清扫 ====================
CHASE_WATCH_ENABLED = os.getenv("CHASE_WATCH", "1").lower() in ("1", "true", "yes")
CHASE_CONFIRM_COUNT = int(os.getenv("CHASE_CONFIRM_COUNT", "3"))     # 连续 N 次合格心跳
CHASE_CONFIRM_MIN_SEC = float(os.getenv("CHASE_CONFIRM_MIN_SEC", "120"))  # 且至少观察这么久
CHASE_STALE_SEC = float(os.getenv("CHASE_STALE_SEC", "600"))         # 心跳断这么久 -> 观察窗作废
CHASE_3TF_REQUIRED = int(os.getenv("CHASE_3TF_REQUIRED", "3"))       # 3 个周期里至少几个同向
HOUSEKEEP_SEC = float(os.getenv("HOUSEKEEP_SEC", "300"))

# ==================== regime(ADX档位)自适应雷达 + watchdog ====================
REGIME_ADAPT_ENABLED = os.getenv("REGIME_ADAPT", "1").lower() in ("1", "true", "yes")
# tier 0弱/1中/2强 -> 步进系数 / 呼吸系数（强趋势给跑者更多空间，弱趋势收快点）
REGIME_STEP_MULT = {"0": 0.85, "1": 1.0, "2": 1.20}
REGIME_BREATH_MULT = {"0": 0.90, "1": 1.0, "2": 1.15}
WATCHDOG_STALE_SEC = float(os.getenv("WATCHDOG_STALE_SEC", "120"))   # 监控循环这么久没跳 -> 重启


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
        self._catchup_blocked_until = 0.0   # 手动平/TV平后，这段时间内心跳不补开
        self._naked_tick = 0                 # 裸单守护节流计数
        self._cooldown_until = 0.0           # 止损后同向信号冷却截止
        self._reentry_count = 0             # 当前 episode 已再入次数
        self._last_exit = {}                # 上次出局: side/entry/atr/tier/reason/ts
        self._intentional_close = False    # True = TV平/手动平（不触发再入/冷却）
        self._reentry_thread: Optional[threading.Thread] = None
        self._reentry_size_factor = 1.0
        self._revlock_bar_ts = 0           # 已查过的最近 4h K线 open_ts（反转锁利节流）
        self._chase_watch = {}            # 追单确认观察窗: {side,first_ts,count,last_ts}
        self._chase_confirmed = False     # 人工 /admin/confirm_catchup 强制放行
        self._loop_beat = 0.0            # 监控循环心跳（watchdog 用）

        # 初始化模块
        self._init_modules()

        logger.info(f"CoinW Supervisor {COINW_SUPERVISOR_VERSION} 就绪: {self.symbol}")

    def _init_modules(self):
        """初始化各模块"""
        # 延迟导入避免循环依赖
        from coinw_client import coinw_client, is_position_query_failed
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
        # 注意：AccountThrottle.acquire() 目前全仓库无调用方——真正生效的限流是
        # coinw_client.py 的 _throttle_rest()（阻塞式最小间隔）+ IP限流退避，
        # 已在约10处REST调用点接好。self.throttle 是 v16.22.1-coinw-init 那次
        # 整体复刻币安架构时带过来的预算滑动窗口，从初始commit起就没接线，是
        # 冗余 scaffold 不是失效的防护——2026-08-10 评估过，暂不接入（见
        # deepcoin_coinw对齐币安_检查清单.md 第H项）。
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

            # PING信号 - 心跳检测
            if signal.action == "PING":
                logger.info("收到PING心跳信号")
                return {
                    "ok": True,
                    "status": "pong",
                    "message": "system_alive",
                    "trading_paused": trading_paused,
                }

            # HEARTBEAT - 心跳催单（漏开补开 / 止损漂了补挂 / 反向翻转补救）
            if signal.action == "HEARTBEAT":
                return self._handle_heartbeat(signal)

            return {"ok": False, "error": "unknown_action"}

    def _handle_open(self, signal, is_reentry: bool = False) -> dict:
        """处理开仓信号"""
        global trading_paused

        if trading_paused:
            logger.warning("交易暂停中，拒绝开仓")
            return {"ok": False, "error": "trading_paused"}

        # 止损后冷却：非再入的同向 TV 信号在冷却期内忽略（防抖，再入走独立通道）
        if (not is_reentry and COOLDOWN_IGNORE_TV
                and time.time() < self._cooldown_until
                and str(signal.action).upper() == str(self._last_exit.get("side") or "").upper()):
            left = self._cooldown_until - time.time()
            logger.warning(f"止损后冷却中({left:.0f}s)，忽略同向信号 {signal.action}")
            return {"ok": False, "error": "cooldown", "cooldown_left": round(left)}

        # 新的真实 TV 信号 = 新 episode：清零再入计数、结束再入看守、解除冷却与心跳冻结
        if not is_reentry:
            self._reentry_count = 0
            self._cooldown_until = 0.0
            self._intentional_close = False
        self._reentry_size_factor = REENTRY_SIZE_FACTOR if is_reentry else 1.0

        # 1) 信号官登记——注意：pipeline.data里的"tp1"/"tp2"是结构化状态
        # ({"px":...,"pieces":...})，这里如果直接传tp1=signal.tp1(一个纯
        # float)会被_apply_fields原样写进self.data["tp1"]，把dict形状覆盖
        # 成float。后面督察官审计取self.data.get("tp1",{}).get(...)时，
        # 如果TP1因仓位太小被跳过(没有重新写回dict)，这个float就会一路存活
        # 到这里，'float' object has no attribute 'get'直接崩溃(2026-08-08
        # 真实测试复现)。这里只是想把TV原始价位记进历史，改用不冲突的字段名。
        self.pipeline.advance(
            Phase.SIGNAL_RECEIVED,
            Role.SIGNAL,
            note=f"{signal.action} @ {signal.price}",
            action=signal.action,
            price=signal.price,
            atr=signal.atr,
            stop_loss=signal.stop_loss,
            tv_tp1=signal.tp1,
            tv_tp2=signal.tp2,
            tier=signal.tier,
        )

        # 2) 仓位稽查员 - 先平后开
        self.pipeline.advance(Phase.PENDING_CLEAR, Role.AUDITOR_POS, note="开始清场")
        cleared = self._clear_position(f"预开仓 {signal.action}")

        if not cleared:
            self.pipeline.mark_failed(Role.AUDITOR_POS, "清场失败")
            return {"ok": False, "error": "clear_failed"}

        self.pipeline.advance(Phase.CLEARED, Role.AUDITOR_POS, note="清场完成")

        # 3) 计算仓位（按 TV 趋势强弱档位 signal.tier 缩放名义，对齐币安）
        balance = self._get_balance()
        entry_price = signal.price
        qty = self._calc_position_size(balance, entry_price, signal.tier)

        # 再入仓位缩小
        _rf = float(getattr(self, "_reentry_size_factor", 1.0) or 1.0)
        if _rf != 1.0:
            qty = qty * _rf
            logger.info(f"再入仓位系数 {_rf} -> qty={qty:.6f}")

        # 检查TV qty soft-cap
        if signal.qty and signal.qty > 0 and signal.qty < qty:
            qty = signal.qty

        # 3.5) 高潮插针否决 / 过度延伸告警
        if CLIMAX_VETO_ENABLED:
            veto, warn, det = self._climax_check(signal.action, entry_price)
            if warn:
                logger.warning(f"进场过度延伸告警: {det}")
            if veto:
                self._safe_alert(f"高潮插针否决进场 {signal.action}: {det}")
                self.pipeline.mark_failed(Role.EXECUTION, f"climax_veto:{det}")
                return {"ok": False, "error": f"climax_veto:{det}"}

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

        # TV 主动平仓：不触发再入 / 不算止损冷却，结束再入看守
        self._intentional_close = True
        self._cooldown_until = 0.0
        self._reentry_count = 0

        # 停止监控
        self._stop_monitoring()

        # 清仓
        success = self._clear_position(f"TV平仓 {signal.action}")

        # 重置流水线
        self.pipeline.reset_idle("tv_close")

        # 刚平的仓，一段时间内不让滞后的心跳把它又补开
        self._catchup_blocked_until = time.time() + CATCHUP_BLOCK_SEC

        return {
            "ok": success,
            "action": signal.action,
        }

    # ==================== 心跳催单 ====================

    def _synthesize_open_signal(self, hb_signal, side: str, entry: float, px: float):
        """把心跳 payload 拼成一个开仓信号，走 _handle_open。"""
        from webhook_parser import ParsedSignal
        raw = hb_signal.raw or {}

        def _f(k, d=0.0):
            try:
                return float(raw.get(k) or d)
            except (TypeError, ValueError):
                return d

        return ParsedSignal(
            valid=True, action=side, symbol=self.symbol,
            price=(entry or px), stop_loss=(hb_signal.stop_loss or _f("stop_loss")),
            atr=(hb_signal.atr or _f("atr")),
            tp1=(hb_signal.tp1 or _f("tp1")), tp2=(hb_signal.tp2 or _f("tp2")),
            tp3=(hb_signal.tp3 or _f("tp3")),
            qty=None, tier=(hb_signal.tier or ""), leverage=20, error="",
            side=side, raw=raw,
        )

    def _hard_sl_present(self) -> bool:
        """交易所是否已挂着一张有效硬止损（stopType!=1、未触发、stopLossPrice>0）。"""
        pid = self.pipeline.data.get("position_id")
        if not pid:
            return False
        try:
            for r in self.client.get_tp_sl_info(pid):
                if int(r.get("stopType") or 0) != 1 and float(r.get("stopLossPrice") or 0) > 0 \
                        and int(r.get("triggerStatus") or 0) == 0:
                    return True
        except Exception:
            return True  # 查不到就别乱补，避免重复挂
        return False

    def _live_side(self, pos: dict) -> str:
        s = str((pos or {}).get("direction") or "").upper()
        if s in ("LONG", "BUY"):
            return "LONG"
        if s in ("SHORT", "SELL"):
            return "SHORT"
        return ""

    def _handle_heartbeat(self, signal) -> dict:
        """心跳催单：以 TV 上报的应有持仓意图为准，补齐 VPS 的漏动作。"""
        if not HEARTBEAT_CATCHUP_ENABLED:
            return {"ok": True, "status": "heartbeat", "catchup": "disabled"}

        hb_side = (signal.side or "FLAT").upper()
        raw = signal.raw or {}
        try:
            hb_entry = float(raw.get("entry") or raw.get("entry_price") or signal.price or 0)
        except (TypeError, ValueError):
            hb_entry = 0.0

        with self._lock:
            have = self._pos_qty()
            pos = None
            live = ""
            if have != 0:
                pos = self.client.get_position(self.symbol, prefer_ws=False, force_rest=True)
                live = self._live_side(pos)

            # 两边都空
            if hb_side == "FLAT" and have == 0:
                return {"ok": True, "status": "heartbeat", "state": "both_flat"}

            # TV 空、VPS 有仓：TV 平了我们漏了
            if hb_side == "FLAT" and have != 0:
                self._safe_alert("心跳：TV已空但VPS仍持仓")
                if HEARTBEAT_FLAT_CLOSE:
                    self._stop_monitoring()
                    ok = self._clear_position("心跳催单-补平(TV已空)")
                    self.pipeline.reset_idle("hb_flat_close")
                    self._catchup_blocked_until = time.time() + CATCHUP_BLOCK_SEC
                    return {"ok": ok, "status": "heartbeat", "action": "flat_close"}
                return {"ok": True, "status": "heartbeat", "state": "tv_flat_vps_open",
                        "note": "仅告警，未自动平（HEARTBEAT_FLAT_CLOSE=0）"}

            # 同向已持仓：核对裸单
            if have != 0 and live == hb_side:
                if NAKED_GUARD_ENABLED and not self.radar.get_state().activated \
                        and not self._hard_sl_present():
                    sl = float(self.pipeline.data.get("hard_sl_px") or 0) or float(signal.stop_loss or 0)
                    pid = self.pipeline.data.get("position_id")
                    if sl > 0 and pid:
                        self.client.set_sl_tp(position_id=pid, instrument=self.symbol,
                                              stop_loss_price=round(sl, 2))
                        logger.warning(f"心跳裸单守护：补挂硬止损 @{sl}")
                        return {"ok": True, "status": "heartbeat", "action": "reattach_sl", "sl": sl}
                if not self._monitoring:
                    self._start_monitoring()
                return {"ok": True, "status": "heartbeat", "state": "in_sync"}

            # 反向持仓：TV 翻转我们漏了 -> 先平
            if have != 0 and live and live != hb_side:
                logger.warning(f"心跳催单：反向翻转 {live} -> {hb_side}，先平旧仓")
                self._stop_monitoring()
                self._clear_position(f"心跳催单-反向翻转 {live}->{hb_side}")
                self.pipeline.reset_idle("hb_flip")
                have = 0

            # TV 有仓、VPS 空：补开（经追单确认观察窗）
            if have == 0:
                if time.time() < self._catchup_blocked_until:
                    self._chase_watch = {}
                    return {"ok": True, "status": "heartbeat", "state": "catchup_blocked",
                            "until": round(self._catchup_blocked_until, 0)}
                px = float(self._get_current_price() or 0)
                hb_sig = self._synthesize_open_signal(signal, hb_side, hb_entry, px)
                if float(hb_sig.atr or 0) <= 0:
                    self._safe_alert("心跳催单放弃：缺 ATR，无法管理")
                    return {"ok": True, "status": "heartbeat", "state": "no_atr"}
                if hb_entry > 0 and px > 0 and abs(px - hb_entry) / hb_entry > CATCHUP_MAX_DRIFT_PCT:
                    self._chase_watch = {}
                    self._safe_alert(f"心跳催单放弃：现价{px} 偏离 entry{hb_entry} 超 "
                                     f"{CATCHUP_MAX_DRIFT_PCT:.2%}")
                    return {"ok": True, "status": "heartbeat", "state": "drift_too_large"}

                ready, why = self._chase_watch_step(hb_side)
                if not ready:
                    return {"ok": True, "status": "heartbeat", "state": "chase_watch",
                            "detail": why, "count": self._chase_watch.get("count", 0)}

                logger.warning(f"追单确认通过（{why}）：补开 {hb_side} @现价{px}")
                self._chase_watch = {}
                self._chase_confirmed = False
                res = self._handle_open(hb_sig)
                res["catchup"] = True
                return res

            return {"ok": True, "status": "heartbeat"}

    # ==================== 追单确认观察窗 ====================

    def _trend_confirm_3tf(self, side: str) -> tuple:
        """30m / 60m / 4h 三周期方向一致性。返回 (同向数, 详情)。"""
        from smart_reentry_engine import _adx, _donchian
        agree = 0
        parts = []
        for tf, code, n in (("30m", 30, 400), ("60m", 60, 400), ("4h", 240, 200)):
            try:
                bars = self.client.get_klines(self.symbol, code, n)
            except Exception:
                bars = []
            if not bars or len(bars) < 25:
                parts.append(f"{tf}:?")
                continue
            hh, ll, mid = _donchian(bars, 20)
            close = bars[-1][4]
            ok = (side == "LONG" and close > mid and close > ll) or \
                 (side == "SHORT" and close < mid and close < hh)
            agree += 1 if ok else 0
            parts.append(f"{tf}:{'✓' if ok else '✗'}")
        return agree, " ".join(parts)

    def _chase_watch_step(self, hb_side: str) -> tuple:
        """推进观察窗。返回 (是否放行, 详情)。"""
        now = time.time()
        if self._chase_confirmed:
            return True, "人工确认"
        if not CHASE_WATCH_ENABLED:
            agree, det = self._trend_confirm_3tf(hb_side)
            return (agree >= CHASE_3TF_REQUIRED), f"3TF {agree}/3 {det}"

        cw = self._chase_watch
        if cw and (cw.get("side") != hb_side or now - cw.get("last_ts", 0) > CHASE_STALE_SEC):
            cw = {}
        agree, det = self._trend_confirm_3tf(hb_side)
        if agree < CHASE_3TF_REQUIRED:
            self._chase_watch = {}
            return False, f"3TF不足 {agree}/{CHASE_3TF_REQUIRED} {det}"

        if not cw:
            self._chase_watch = {"side": hb_side, "first_ts": now, "count": 1, "last_ts": now}
            self._safe_alert(f"追单确认观察窗开启 {hb_side}（3TF {agree}/3）— "
                             f"需连续{CHASE_CONFIRM_COUNT}次/{CHASE_CONFIRM_MIN_SEC:.0f}s 或 /admin/confirm_catchup")
            return False, f"watch_started 3TF{agree}/3"
        cw["count"] = cw.get("count", 0) + 1
        cw["last_ts"] = now
        self._chase_watch = cw
        if cw["count"] >= CHASE_CONFIRM_COUNT and now - cw["first_ts"] >= CHASE_CONFIRM_MIN_SEC:
            return True, f"连续{cw['count']}次/{now-cw['first_ts']:.0f}s 3TF{agree}/3"
        return False, f"观察中 {cw['count']}/{CHASE_CONFIRM_COUNT}"

    def _safe_alert(self, msg: str):
        logger.warning(msg)
        try:
            self._dingtalk.report_coinw_tp(msg, 0)
        except Exception:
            pass

    # ==================== 开仓执行 ====================

    def _calc_position_size(self, balance: float, entry_price: float, tier=None) -> float:
        """计算仓位（tier=0/1/2 时按趋势强弱缩放名义，对齐币安）"""
        from defense_profiles import get_defense_profile
        profile = get_defense_profile(self.symbol)

        return profile.calc_position_size(balance, entry_price, tier)

    def _is_retryable_open_rejection(self, code, error_msg) -> bool:
        """只有短暂性拒单(如资金费结算窗口)才值得用限价单重试；保证金不足/
        参数错误等重试也没用，直接判失败更清楚，避免无意义地占用限价单
        名额(交易所挂单硬上限5笔)。"""
        try:
            if int(code) == 9010:
                return True
        except (TypeError, ValueError):
            pass
        msg = str(error_msg or "")
        return "funding" in msg.lower() or "结算" in msg

    def _retry_open_with_limit(self, action: str, tv_price: float, qty: float,
                                timeout_sec: float = 60.0, poll_interval: float = 3.0) -> dict:
        """市价开仓被拒(如资金费结算窗口)的兜底：改挂限价单，价格不劣于TV
        信号价——多单最高只出TV价的99.7%，空单最低只收TV价的100.3%，
        绝不比TV当时想要的价格更差。限定时间内轮询是否成交，超时未成交
        就撤单放弃，不留孤儿挂单长期追单(2026-08-08 实盘：BNB因资金费
        结算窗口被拒单后直接放弃，错过一次开仓信号)。"""
        from coinw_client import is_orders_query_failed

        side_u = str(action).upper()
        if side_u == "LONG":
            limit_price = round(float(tv_price) * 0.997, 2)
        else:
            limit_price = round(float(tv_price) * 1.003, 2)

        logger.warning(
            f"限价重试开仓: {side_u} {qty} @{limit_price} "
            f"(TV价{tv_price}，让利0.3%，不追差价)"
        )

        order = self.client.place_limit_order(
            side=action, quantity=qty, price=limit_price,
            instrument=self.symbol, reduce_only=False,
        )
        if not order or order.get("code") != 0:
            return {
                "ok": False,
                "error": f"限价重试提交失败: {(order or {}).get('msg', '无响应')}",
            }

        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            time.sleep(poll_interval)
            pos = self.client.get_position(self.symbol, prefer_ws=False, force_rest=True)
            if pos and float(pos.get("positionAmt") or pos.get("quantity") or 0) != 0:
                logger.info(f"限价重试成交: {side_u} @{limit_price}")
                return {"ok": True}

        logger.warning(f"限价重试超时({timeout_sec:.0f}s)未成交，撤单放弃")
        orders = self.client.get_open_orders(self.symbol, position_type="plan")
        if not is_orders_query_failed(orders):
            for o in orders:
                try:
                    opx = round(float(o.get("openPrice", 0) or o.get("orderPrice", 0)), 2)
                except (TypeError, ValueError):
                    continue
                if abs(opx - limit_price) <= 0.02 and o.get("id"):
                    self.client.cancel_order(o.get("id"), self.symbol)
                    break
        return {"ok": False, "error": "限价重试超时未成交"}

    # ---------- 开仓滑点阶梯 ----------

    _MIN_ORDER_ETH = 0.011  # < 1 张(0.01 ETH)的残量无法再挂单，视为已完成

    def _pos_qty(self) -> float:
        """当前实盘持仓的标的货币数量（强制 REST，绕缓存）。"""
        pos = self.client.get_position(self.symbol, prefer_ws=False, force_rest=True)
        if not pos:
            return 0.0
        return float(pos.get("baseSize") or pos.get("positionAmt") or pos.get("quantity") or 0)

    def _cancel_open_limits(self):
        from coinw_client import is_orders_query_failed
        orders = self.client.get_open_orders(self.symbol, position_type="plan")
        if is_orders_query_failed(orders) or not orders:
            return
        for o in orders:
            if o.get("id"):
                self.client.cancel_order(o.get("id"), self.symbol)

    def _adverse_gap_pct(self, action: str, tv_price: float) -> float:
        """现价相对 TV 价的【逆向】偏离比例（>0 表示对我们不利：多单买贵/空单卖便宜）。"""
        last = float(self._get_current_price() or 0)
        if last <= 0 or tv_price <= 0:
            return 0.0
        if str(action).upper() == "LONG":
            return (last - tv_price) / tv_price
        return (tv_price - last) / tv_price

    def _wait_fill(self, action: str, tv_price: float, deadline: float, want_qty: float):
        """轮询到成交 / deadline / 逆向放弃。返回 (状态, 已成交量)。"""
        while time.time() < deadline:
            time.sleep(ENTRY_POLL_SEC)
            have = self._pos_qty()
            if have >= want_qty - self._MIN_ORDER_ETH:
                return "filled", have
            if self._adverse_gap_pct(action, tv_price) > ENTRY_ABORT_PCT:
                return "abort", have
        return "timeout", self._pos_qty()

    def _open_with_ladder(self, action: str, tv_price: float, qty: float,
                          tier: str = None) -> dict:
        """
        TV 信号进场：被动限价(TV价, maker) -> 可成交限价(让利≤滑点上限) -> 市价兜底。
        强趋势 tier=2：跳过①被动限价，直接②可成交限价(短窗)+③市价 —— 立即进入。
        现价逆向跑过 ENTRY_ABORT_PCT 则撤单放弃这次信号。返回 {ok, via, error, aborted}。
        """
        side_u = str(action).upper()
        strong = ENTRY_STRONG_IMMEDIATE and str(tier or "").strip() == "2"
        if not ENTRY_LADDER_ENABLED:
            r = self.client.place_market_order(side=action, quantity=qty, instrument=self.symbol)
            if r and r.get("code") == 0:
                return {"ok": True, "via": "market_direct"}
            code = (r or {}).get("code")
            msg = (r or {}).get("msg", "无响应")
            if self._is_retryable_open_rejection(code, msg):
                rr = self._retry_open_with_limit(action, tv_price, qty)
                return {"ok": bool(rr.get("ok")), "via": "limit_retry", "error": rr.get("error", "")}
            return {"ok": False, "via": "market_direct", "error": msg}

        t0 = time.time()
        tvp = float(tv_price)
        remaining = float(qty)

        # 阶段1：TV 价被动限价（做 maker，绝不劣于 TV 价）—— 强趋势档跳过
        if strong:
            logger.info(f"[开仓阶梯] 强趋势档 tier=2 → 跳过①被动限价，立即可成交限价+市价")
        else:
            px1 = round(tvp, 2)
            logger.info(f"[开仓阶梯] ①被动限价 {side_u} {qty} @{px1} (TV价 · {ENTRY_PASSIVE_SEC:.0f}s)")
            o1 = self.client.place_limit_order(side=action, quantity=qty, price=px1,
                                               instrument=self.symbol, reduce_only=False)
            if o1 and (o1.get("code") == 0 or o1.get("id")):
                st, have = self._wait_fill(action, tvp, t0 + ENTRY_PASSIVE_SEC, qty)
                remaining = max(0.0, float(qty) - have)
                if st == "filled":
                    logger.info("[开仓阶梯] ①成交(被动限价, 0 滑点)")
                    return {"ok": True, "via": "passive_limit"}
                if st == "abort":
                    self._cancel_open_limits()
                    return {"ok": False, "via": "passive_limit", "aborted": True,
                            "error": f"信号逆向跑过 {ENTRY_ABORT_PCT:.2%}，放弃进场"}
            self._cancel_open_limits()

        # 阶段2：让利到滑点上限的可成交限价（强趋势档用短窗）
        mk_deadline = (t0 + ENTRY_STRONG_MARKETABLE_SEC) if strong else (t0 + ENTRY_MARKETABLE_SEC)
        if remaining >= self._MIN_ORDER_ETH:
            px2 = round(tvp * (1.0 + ENTRY_SLIP_CAP_PCT), 2) if side_u == "LONG" \
                else round(tvp * (1.0 - ENTRY_SLIP_CAP_PCT), 2)
            logger.info(f"[开仓阶梯] ②可成交限价 {side_u} {remaining:.6f} @{px2} "
                        f"(让利≤{ENTRY_SLIP_CAP_PCT:.2%} · 到{mk_deadline - t0:.0f}s)")
            o2 = self.client.place_limit_order(side=action, quantity=remaining, price=px2,
                                               instrument=self.symbol, reduce_only=False)
            if o2 and (o2.get("code") == 0 or o2.get("id")):
                st, have = self._wait_fill(action, tvp, mk_deadline, qty)
                remaining = max(0.0, float(qty) - have)
                if st == "filled":
                    logger.info("[开仓阶梯] ②成交(可成交限价, 滑点已封顶)")
                    return {"ok": True, "via": "marketable_limit"}
                if st == "abort":
                    self._cancel_open_limits()
                    return {"ok": False, "via": "marketable_limit", "aborted": True,
                            "error": f"信号逆向跑过 {ENTRY_ABORT_PCT:.2%}，放弃进场"}
            self._cancel_open_limits()

        # 阶段3：市价兜底（仅剩余量）
        if remaining < self._MIN_ORDER_ETH:
            return {"ok": True, "via": "limit_all"}
        if self._adverse_gap_pct(action, tvp) > ENTRY_ABORT_PCT:
            return {"ok": False, "via": "market_fallback", "aborted": True,
                    "error": f"兜底前信号已逆向跑过 {ENTRY_ABORT_PCT:.2%}，放弃进场"}
        logger.warning(f"[开仓阶梯] ③市价兜底 {side_u} {remaining:.6f}")
        r = self.client.place_market_order(side=action, quantity=remaining, instrument=self.symbol)
        if r and r.get("code") == 0:
            return {"ok": True, "via": "market_fallback"}
        code = (r or {}).get("code")
        msg = (r or {}).get("msg", "无响应")
        if self._is_retryable_open_rejection(code, msg):
            rr = self._retry_open_with_limit(action, tvp, remaining, timeout_sec=20.0)
            return {"ok": bool(rr.get("ok")), "via": "market_fallback_retry", "error": rr.get("error", "")}
        return {"ok": False, "via": "market_fallback", "error": msg}

    def _execute_open(self, action: str, price: float, qty: float, signal) -> dict:
        """执行开仓"""
        try:
            # 获取当前价格作为参考
            current_price = self._get_current_price()

            # 进场滑点阶梯：被动限价 -> 可成交限价 -> 市价兜底
            led = self._open_with_ladder(action, price, qty, tier=getattr(signal, "tier", None))
            if not led.get("ok"):
                logger.error(f"开仓未成交: {led.get('error')} (via={led.get('via')})")
                return {"ok": False, "error": led.get("error", "开仓未成交"),
                        "aborted": bool(led.get("aborted"))}
            logger.info(f"进场方式: {led.get('via')}")

            # 获取持仓信息——开仓前_clear_position()已经把本地持仓缓存写成
            # "无持仓"(POSITION_CACHE_TTL_SEC=8s内有效)，这里如果沿用默认的
            # prefer_ws=True/force_rest=False，大概率直接读到那份下单前的
            # 陈旧缓存，把刚成交的仓位误判成"没有"。必须force_rest=True绕开
            # 缓存；交易所侧成交回报也可能有轻微延迟，所以做几次重试。
            pos = None
            for _ in range(3):
                time.sleep(0.5)  # 等待成交/交易所侧持仓数据落地
                pos = self.client.get_position(self.symbol, prefer_ws=False, force_rest=True)
                if pos and float(pos.get("positionAmt") or pos.get("quantity") or 0) != 0:
                    break

            # get_position()可能返回两种形状：REST原始行(quantity字段)或
            # WS缓存行(positionAmt字段)——都要检查，否则缓存了旧的"已归零"
            # 记录时not pos判断不出来(非空dict恒真)
            if not pos or float(pos.get("positionAmt") or pos.get("quantity") or 0) == 0:
                return {"ok": False, "error": "持仓未找到"}

            position_id = pos.get("id", "")
            entry_price = float(pos.get("openPrice", current_price))
            # pos["quantity"]不是真实ETH数量——真实持仓验证过(2026-08-08)：
            # 那是张数相关的内部值(quantityUnit=1场景下的原始委托量)，实际
            # 持有的标的货币数量就是baseSize本身(已经是持仓总量，不是"每张
            # 面值"，实测1张=0.01 ETH时baseSize=0.01，5张=0.05 ETH时
            # baseSize=0.05，乘以totalPiece会再放大成倍——之前那版乘了
            # totalPiece，把5张仓位算成0.25 ETH，比真实的0.05 ETH大5倍)。
            base_size = float(pos.get("baseSize", 0) or 0)
            total_pieces = float(pos.get("totalPiece", pos.get("currentPiece", 0)) or 0)
            actual_qty = base_size if base_size else float(pos.get("quantity", qty))

            logger.info(f"开仓成功: {action} {actual_qty} @ {entry_price} ({total_pieces}张)")

            return {
                "ok": True,
                "entry_price": entry_price,
                "qty": actual_qty,
                "total_pieces": total_pieces,
                "position_id": position_id,
                "atr": signal.atr,
            }

        except Exception as e:
            logger.error(f"开仓异常: {e}")
            return {"ok": False, "error": str(e)}

    # ==================== 防线设置 ====================

    def _place_defense_orders(self, signal, entry_result: dict) -> bool:
        """设置三层防线"""
        from atr_scenario import calc_hard_stop_price

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
            if not sl_result or sl_result.get("code") != 0:
                logger.error(f"硬止损挂单失败: {sl_result}")

            self.pipeline.data["hard_sl_px"] = hard_sl_price

            # 2) TP1 + TP2 —— 改用CoinW原生分批止盈接口(/v1/perpum/addTpsl,
            # stopType=1分批)，按position_id+张数(closePiece)设置，由交易所
            # 在触发价自动平掉对应张数。之前用"同方向限价单模拟reduce_only"
            # 的方式是错的：CoinW下单接口没有reduce_only语义，方向填的是
            # signal.action(跟开仓同向)，等于挂了两个"买入"限价单，价格又都
            # 在开仓价上方——一旦挂上就被当成可成交的买单直接成交，变成两次
            # 加仓而不是止盈(2026-08-08真实下单验证复现，仓位被从0.01 ETH
            # 加到0.29 ETH)。原有qty计算还用错了字段，进一步放大了这个问题。
            total_pieces = float(entry_result.get("total_pieces", 0) or 0)
            total_qty = float(entry_result.get("qty", 0) or 0)
            per_piece_qty = (total_qty / total_pieces) if total_pieces > 0 else 0.0
            tp1_pieces = round(total_pieces * 0.10)
            tp2_pieces = round(total_pieces * 0.20)

            if signal.tp1 > 0:
                if tp1_pieces > 0:
                    tp1_result = self.client.set_batch_sl_tp(
                        position_id=position_id,
                        instrument=self.symbol,
                        stop_profit_price=signal.tp1,
                        close_piece=tp1_pieces,
                        stop_type=1,  # 分批止盈
                        stop_from=2,  # 市价触发
                        price_type=3,  # 标记价格
                    )
                    if not tp1_result or tp1_result.get("code") != 0:
                        logger.error(f"TP1挂单失败: {tp1_result}")
                    # qty字段保留给_run_audit的tp_slice一致性检查用(ETH等值)，
                    # pieces是CoinW原生张数，两个都存，缺一个督察官那边就读不到
                    self.pipeline.data["tp1"] = {"px": signal.tp1, "pieces": tp1_pieces, "qty": tp1_pieces * per_piece_qty}
                else:
                    logger.warning(f"TP1跳过: 仓位仅{total_pieces}张，10%不足1张最小单位")
                    self.pipeline.data["tp1"] = {"px": signal.tp1, "pieces": 0, "qty": 0.0}

            if signal.tp2 > 0:
                if tp2_pieces > 0:
                    tp2_result = self.client.set_batch_sl_tp(
                        position_id=position_id,
                        instrument=self.symbol,
                        stop_profit_price=signal.tp2,
                        close_piece=tp2_pieces,
                        stop_type=1,
                        stop_from=2,
                        price_type=3,
                    )
                    if not tp2_result or tp2_result.get("code") != 0:
                        logger.error(f"TP2挂单失败: {tp2_result}")
                    self.pipeline.data["tp2"] = {"px": signal.tp2, "pieces": tp2_pieces, "qty": tp2_pieces * per_piece_qty}
                else:
                    logger.warning(f"TP2跳过: 仓位仅{total_pieces}张，20%不足1张最小单位")
                    self.pipeline.data["tp2"] = {"px": signal.tp2, "pieces": 0, "qty": 0.0}

            # 3) 雷达初始化（休眠状态）——武装TP1/TP2价格供should_activate算
            # 激活线((TP1+TP2)/2中点)，不依赖TP1/TP2是否真的成交
            self.radar.set_atr(signal.atr)
            self.radar.reset()
            self.radar.arm(tp1_price=signal.tp1, tp2_price=signal.tp2, direction=direction)

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
                self._loop_beat = time.time()  # watchdog 心跳
                # 1) 检查持仓
                pos = self.client.get_position(self.symbol)
                current_price = self._get_current_price()

                if not pos or float(pos.get("positionAmt") or pos.get("quantity") or 0) == 0:
                    # 仓位归零
                    self._on_position_zero()
                    break

                # 2) 检查TP成交——仅用于账本记录/日志核对，不再作为雷达激活
                # 的前提条件(对齐币安v2.1规格：TP是否成交只是核对项，不是
                # 激活门槛)。CoinW的/v1/perpum/TPSL查询接口直接给
                # triggerStatus(0未触发/1已触发)，比自己猜靠谱，仍然查一下
                # 存进pipeline方便审计/复盘。
                self._check_tp_fills()

                # 2.5) 裸单守护：持仓在场但交易所没有有效硬止损、雷达也没接管
                #      -> 补挂硬止损（每 ~24s 查一次，限流）
                self._naked_tick += 1
                if NAKED_GUARD_ENABLED and self._naked_tick % 6 == 0 \
                        and not self.radar.get_state().activated:
                    try:
                        if not self._hard_sl_present():
                            sl = float(self.pipeline.data.get("hard_sl_px") or 0)
                            pid = self.pipeline.data.get("position_id")
                            if sl > 0 and pid:
                                self.client.set_sl_tp(position_id=pid, instrument=self.symbol,
                                                      stop_loss_price=round(sl, 2))
                                logger.warning(f"裸单守护：补挂硬止损 @{sl}")
                    except Exception as _e:
                        logger.debug(f"裸单守护检查异常: {_e}")

                # 3) 雷达激活检查——纯价格判断：现价到没到激活线
                # ((TP1+TP2)/2中点，首次开仓)，不等TP1/TP2真的成交。CoinW
                # 小仓位下TP1经常因不足1张最小单位被跳过，继续拿"TP成交"当
                # 前提会导致雷达永远激活不了(2026-08-08真实测试发现此问题)。
                if not self.radar.get_state().activated:
                    should, reason = self.radar.should_activate(current_price)
                    if should:
                        self._activate_radar()

                # 4) 雷达止损更新（币安 v2.1 价格分区 + regime 自适应 + 三条硬地板 + tp2_patience）
                profile = self._regime_profile(breath_profiles.get_breath_profile(self.symbol))
                tp1_px = float((self.pipeline.data.get("tp1") or {}).get("px", 0) or 0)
                tp2_px = float((self.pipeline.data.get("tp2") or {}).get("px", 0) or 0)
                _tp3 = self.pipeline.data.get("tp3")
                tp3_px = float(_tp3.get("px", 0) or 0) if isinstance(_tp3, dict) else float(_tp3 or 0)
                # TV 止损空间 = |entry − 硬止损|，喂给「雷达最多比 TV 紧 35%」硬地板
                _entry = float(self.pipeline.data.get("entry") or 0)
                _hsl = float(self.pipeline.data.get("hard_sl_px") or 0)
                tv_stop_dist = abs(_entry - _hsl) if (_entry > 0 and _hsl > 0) else 0.0
                new_sl = self.radar.update(
                    current_price, profile,
                    tp1_px=tp1_px, tp2_px=tp2_px, tp3_px=tp3_px,
                    tv_stop_dist=tv_stop_dist,
                )

                if new_sl:
                    self._update_radar_sl(new_sl)

                # 5) 反转锁利：4h 逆向放量反转 + 浮盈中 -> 收保本
                if REVLOCK_ENABLED:
                    try:
                        self._apply_reversal_lock(current_price)
                    except Exception as _e:
                        logger.debug(f"反转锁利异常: {_e}")

                # 等待
                time.sleep(4)  # 雷达间隔

            except Exception as e:
                logger.error(f"监控异常: {e}")
                time.sleep(5)

    def _check_tp_fills(self) -> tuple:
        """
        查交易所原生SL/TP记录，核对TP1/TP2是否真的成交(triggerStatus==1)。
        按挂单时记的px匹配对应记录(浮点直接比较——CoinW原样回显我们发送的
        stopProfitPrice，不存在自己内部再做四舍五入的问题)。跳过的档位
        (pieces==0，没真挂过)不查、直接当未成交处理。
        """
        position_id = self.pipeline.data.get("position_id", "")
        tp1_state = self.pipeline.data.get("tp1") or {}
        tp2_state = self.pipeline.data.get("tp2") or {}
        tp1_filled = bool(tp1_state.get("filled"))
        tp2_filled = bool(tp2_state.get("filled"))

        if not position_id or (tp1_filled and tp2_filled):
            return tp1_filled, tp2_filled
        if not tp1_state.get("pieces") and not tp2_state.get("pieces"):
            return tp1_filled, tp2_filled

        records = self.client.get_tp_sl_info(position_id)
        for r in records:
            if int(r.get("stopType") or 0) != 1:  # 只看分批止盈(TP1/TP2)，不是整仓硬止损
                continue
            px = float(r.get("stopProfitPrice") or 0)
            triggered = int(r.get("triggerStatus") or 0) == 1
            if not tp1_filled and tp1_state.get("pieces") and abs(px - float(tp1_state.get("px", 0))) < 1e-6:
                tp1_filled = triggered
            if not tp2_filled and tp2_state.get("pieces") and abs(px - float(tp2_state.get("px", 0))) < 1e-6:
                tp2_filled = triggered

        if tp1_filled and not tp1_state.get("filled"):
            self.pipeline.data["tp1"]["filled"] = True
            logger.info(f"TP1成交确认: {self.symbol} @{tp1_state.get('px')}")
        if tp2_filled and not tp2_state.get("filled"):
            self.pipeline.data["tp2"]["filled"] = True
            logger.info(f"TP2成交确认: {self.symbol} @{tp2_state.get('px')}")

        return tp1_filled, tp2_filled

    def _activate_radar(self):
        """激活雷达"""
        import breath_profiles
        entry_price = float(self.pipeline.data.get("entry", 0) or 0)
        position_id = self.pipeline.data.get("position_id", "")
        tp2_px = self.pipeline.data.get("tp2", {}).get("px", 0)
        tier = self.pipeline.data.get("tier", "1")
        direction = self.pipeline.data.get("side", "LONG")

        profile = breath_profiles.get_breath_profile(self.symbol)
        self.radar.activate(
            entry_price=entry_price,
            tp2_price=tp2_px,
            tier=tier,
            direction=direction,
            profile=profile,
        )

        # 初始止损 = 雷达算出的保本起步位（entry ± tick ± entry×fee_cover_pct）
        initial_sl = self.radar.get_state().current_sl
        if not initial_sl or initial_sl <= 0:
            initial_sl = entry_price - 0.01 if direction == "LONG" else entry_price + 0.01

        self.client.set_sl_tp(
            position_id=position_id,
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

        # 出局分类：非 TV平/手动平 -> 视为止损出局，记录并启动冷却 + 再入看守
        stopped_out = not self._intentional_close
        exit_side = str(self.pipeline.data.get("side") or "").upper()
        exit_entry = float(self.pipeline.data.get("entry") or 0)

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

        if stopped_out and exit_side in ("LONG", "SHORT") and exit_entry > 0:
            self._last_exit = {
                "side": exit_side, "entry": exit_entry, "reason": "stop",
                "tier": str(self.pipeline.data.get("tier") or ""), "ts": time.time(),
            }
            self._cooldown_until = time.time() + COOLDOWN_SEC
            logger.warning(f"止损出局 {exit_side}@{exit_entry}；冷却 {COOLDOWN_SEC:.0f}s"
                           f"{'，启动再入看守' if REENTRY_ENABLED else ''}")
            if REENTRY_ENABLED and self._reentry_count < REENTRY_MAX:
                self._start_reentry_watcher()
        self._intentional_close = False

    # ==================== 智能再入看守 ====================

    def _start_reentry_watcher(self):
        if self._reentry_thread and self._reentry_thread.is_alive():
            return
        self._reentry_thread = threading.Thread(
            target=self._reentry_watch_loop, daemon=True, name=f"coinw-reentry-{self.symbol}")
        self._reentry_thread.start()

    def _reentry_watch_loop(self):
        from smart_reentry_engine import reentry_gate
        ex = dict(self._last_exit or {})
        if not ex:
            return
        t_end = time.time() + REENTRY_WINDOW_SEC
        time.sleep(REENTRY_DELAY_SEC)
        while time.time() < t_end:
            try:
                # 已有仓 / 新 TV 信号进来了 / 冷却被清了 -> 结束看守
                if self._pos_qty() != 0 or self._last_exit is not ex and self._last_exit != ex:
                    return
                if self.pipeline.phase.value not in ("IDLE", "position_zero", ""):
                    # 有新信号在处理
                    if self._pos_qty() != 0:
                        return
                if self._reentry_count >= REENTRY_MAX:
                    return
                bars = self.client.get_klines(self.symbol, 60, 400)
                px = float(self._get_current_price() or 0)
                if bars and px > 0:
                    ok, reason = reentry_gate(
                        bars, ex["side"], ex["entry"], px, self._reentry_count,
                        cfg={"max_reentry": REENTRY_MAX, "adx_gate": REENTRY_ADX_GATE,
                             "max_chase_pct": REENTRY_MAX_CHASE_PCT},
                    )
                    if ok:
                        logger.warning(f"智能再入触发：{ex['side']} @现价{px} ({reason})")
                        self._do_reentry(ex, px, bars)
                        return
                    logger.debug(f"再入未达标: {reason}")
            except Exception as e:
                logger.error(f"再入看守异常: {e}")
            time.sleep(REENTRY_POLL_SEC)
        logger.info("再入机会窗口结束，未再入")

    def _synth_150(self, raw):
        f = 5
        if not raw or len(raw) < f:
            return []
        n = len(raw) - (len(raw) % f)
        out = []
        for i in range(0, n, f):
            ch = raw[i:i + f]
            out.append([ch[0][0], ch[0][1], max(c[2] for c in ch),
                        min(c[3] for c in ch), ch[-1][4], sum(c[5] for c in ch)])
        return out

    # ==================== regime 自适应雷达 ====================

    def _regime_profile(self, base: dict) -> dict:
        """按开仓锁定的 tier(0/1/2) 微调雷达步进/呼吸系数。"""
        if not REGIME_ADAPT_ENABLED or not isinstance(base, dict):
            return base
        tier = str(self.pipeline.data.get("tier") or "1")
        sm = REGIME_STEP_MULT.get(tier, 1.0)
        bm = REGIME_BREATH_MULT.get(tier, 1.0)
        if sm == 1.0 and bm == 1.0:
            return base
        p = dict(base)
        p["step_trigger_atr"] = round(float(base.get("step_trigger_atr", 0.96)) * sm, 3)
        p["step_advance_atr"] = round(float(base.get("step_advance_atr", 0.62)) * sm, 3)
        p["breath_tp12"] = round(float(base.get("breath_tp12", 2.56)) * bm, 3)
        p["breath_tp23"] = round(float(base.get("breath_tp23", 3.45)) * bm, 3)
        return p

    # ==================== 高潮否决 / 反转锁利 ====================

    def _climax_check(self, side: str, price: float):
        """进场前：(veto, warn, detail)。"""
        try:
            bars = self.client.get_klines(self.symbol, 60, 400)
            if not bars:
                return False, False, "no_bars"
            from market_overlays import climax_check
            return climax_check(bars, side, float(price or 0),
                                cfg={"climax_atr_mult": CLIMAX_ATR_MULT,
                                     "overext_atr_mult": OVEREXT_ATR_MULT})
        except Exception as e:
            logger.debug(f"climax_check异常: {e}")
            return False, False, "err"

    def _apply_reversal_lock(self, current_price: float):
        """持仓中：4h 逆向放量反转K线 + 有浮盈 -> 止损收到保本（只进不退）。"""
        if not REVLOCK_ENABLED:
            return
        st = self.radar.get_state()
        side = str(self.pipeline.data.get("side") or "").upper()
        entry = float(self.pipeline.data.get("entry") or 0)
        atr = float(st.initial_atr or getattr(self.radar, "_atr", 0) or 0)
        px = float(current_price or 0)
        if side not in ("LONG", "SHORT") or entry <= 0 or atr <= 0 or px <= 0:
            return
        mfe = (px - entry) if side == "LONG" else (entry - px)
        if mfe < REVLOCK_MIN_PROFIT_ATR * atr:
            return
        try:
            raw4h = self.client.get_klines(self.symbol, 240, 120)
        except Exception:
            return
        if not raw4h or len(raw4h) < 20:
            return
        last_closed_ts = raw4h[-2][0] if len(raw4h) >= 2 else raw4h[-1][0]
        if last_closed_ts <= self._revlock_bar_ts:
            return
        self._revlock_bar_ts = last_closed_ts
        from market_overlays import reversal_candle
        hit, det = reversal_candle(raw4h, side, cfg={"body_atr_mult": REVLOCK_BODY_ATR,
                                                     "vol_mult": REVLOCK_VOL_MULT})
        if not hit:
            return
        from breath_stop import initial_stop_price
        from breath_profiles import get_breath_profile
        be = initial_stop_price(side, entry, profile=get_breath_profile(self.symbol))
        cur = float(st.current_sl or 0)
        new_sl = None
        if side == "LONG":
            if be > cur:
                new_sl = round(be, 2)
        else:
            if cur <= 0 or be < cur:
                new_sl = round(be, 2)
        if new_sl:
            self.radar.seed_stop(new_sl)
            self._update_radar_sl(new_sl)
            self._safe_alert(f"反转锁利：4h逆向放量反转({det})，止损收到保本 {new_sl}")

    def _do_reentry(self, ex: dict, px: float, bars_150: list):
        from webhook_parser import ParsedSignal
        atr = self._recompute_atr_150m()
        if atr <= 0:
            logger.warning("再入放弃：ATR 不可用")
            return
        side = ex["side"]
        sl = px - REENTRY_HARD_SL_ATR * atr if side == "LONG" else px + REENTRY_HARD_SL_ATR * atr
        tp1 = px + 1.35 * atr if side == "LONG" else px - 1.35 * atr
        tp2 = px + 2.5 * atr if side == "LONG" else px - 2.5 * atr
        # 再入档位沿用上次；缺失则按 ADX 粗分
        tier = ex.get("tier") or ""
        sig = ParsedSignal(
            valid=True, action=side, symbol=self.symbol, price=px,
            stop_loss=round(sl, 2), atr=round(atr, 4),
            tp1=round(tp1, 2), tp2=round(tp2, 2), tp3=0.0,
            qty=None, tier=tier, leverage=20, error="",
            side=side, raw={"_reentry": True},
        )
        res = self._handle_open(sig, is_reentry=True)
        if res.get("ok"):
            self._reentry_count += 1
            self._safe_alert(f"智能再入成功 #{self._reentry_count}：{side} @{px} "
                             f"(仓位×{REENTRY_SIZE_FACTOR})")
        else:
            logger.warning(f"再入开仓失败: {res.get('error')}")

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
            if not pos or float(pos.get("positionAmt") or pos.get("quantity") or 0) == 0:
                return True

        return False

    # ==================== 审计 ====================

    def _run_audit(self, signal) -> bool:
        """运行督察官审计"""
        from chief_auditor import audit_open_bundle, should_hard_pause

        # pipeline.data["tp1"]/["tp2"]理应恒为dict，但曾经被其它advance()调用
        # 误传同名标量字段直接覆盖成float(2026-08-08修过一次)。这里读取时
        # 兜底类型检查，避免同类问题再次出现时变成崩溃而不是审计不通过。
        tp1_state = self.pipeline.data.get("tp1")
        tp2_state = self.pipeline.data.get("tp2")
        if not isinstance(tp1_state, dict):
            tp1_state = {}
        if not isinstance(tp2_state, dict):
            tp2_state = {}

        # check_tp_slice_budget默认按10%/20%全额期望TP1+TP2——但CoinW最小
        # 交易单位是1张(0.01 ETH)，账户小的时候10%(甚至20%)会被四舍五入成
        # 0张而合理跳过(见_place_defense_orders)。跳过的那一档就不该再被
        # 审计要求凑齐，否则小账户每次开仓都会被这条硬性审计判失败、误触发
        # 交易暂停(2026-08-08真实测试复现)。按实际挂没挂出来动态给ratios。
        tp1_ratio = 0.10 if tp1_state.get("pieces", 0) else 0.0
        tp2_ratio = 0.20 if tp2_state.get("pieces", 0) else 0.0

        facts = {
            "symbol": self.symbol,
            "signal_side": signal.action,
            "live_side": signal.action,
            "live_qty": self.pipeline.data.get("qty", 0),
            "initial_qty": self.pipeline.data.get("initial_qty", 0),
            "entry": self.pipeline.data.get("entry", 0),
            "tp1_qty": tp1_state.get("qty", 0),
            "tp2_qty": tp2_state.get("qty", 0),
            "ratios": [tp1_ratio, tp2_ratio, 1.0 - tp1_ratio - tp2_ratio],
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

    # ==================== 启动恢复 ====================

    def _recompute_atr_150m(self) -> float:
        """重启后 TV 锁定的 ATR 已丢，用币赢 60m 原生 K线重算 ATR(14) 兜底（≈59m TV 周期）。"""
        try:
            bars = self.client.get_klines(self.symbol, 60, 400)
            if len(bars) < 16:
                return 0.0
            trs = []
            for i in range(1, len(bars)):
                h, l, pc = bars[i][2], bars[i][3], bars[i - 1][4]
                trs.append(max(h - l, abs(h - pc), abs(l - pc)))
            p = 14
            atr = sum(trs[:p]) / p
            for tr in trs[p:]:
                atr = (atr * (p - 1) + tr) / p
            return round(atr, 4)
        except Exception as e:
            logger.warning(f"重算ATR失败: {e}")
            return 0.0

    def recover_on_start(self):
        """引擎重启时，如交易所仍有在场持仓，重建 pipeline + 雷达并恢复监控。
        止损锚定交易所现值（只进不退），绝不因恢复而放松。"""
        if not STARTUP_RECOVERY_ENABLED:
            return
        try:
            pos = self.client.get_position(self.symbol, prefer_ws=False, force_rest=True)
        except Exception as e:
            logger.warning(f"启动恢复：查持仓失败 {e}")
            return
        amt = 0.0
        if pos:
            amt = float(pos.get("baseSize") or pos.get("positionAmt") or pos.get("quantity") or 0)
        if not pos or amt == 0:
            logger.info("启动恢复：无在场持仓")
            return

        side = self._live_side(pos) or "LONG"
        entry = float(pos.get("openPrice") or 0)
        pid = str(pos.get("id") or "")
        logger.warning(f"启动恢复：发现在场持仓 {side} {amt} @{entry} id={pid}，重建监控")

        atr = self._recompute_atr_150m()
        hard_sl = tp1_px = tp2_px = 0.0
        tp1_f = tp2_f = False
        try:
            for r in (self.client.get_tp_sl_info(pid) or []):
                spx = float(r.get("stopProfitPrice") or 0)
                slx = float(r.get("stopLossPrice") or 0)
                trg = int(r.get("triggerStatus") or 0) == 1
                if int(r.get("stopType") or 0) == 1 and spx > 0:
                    if not tp1_px or abs(spx - entry) < abs(tp1_px - entry):
                        tp2_px, tp2_f = tp1_px, tp1_f
                        tp1_px, tp1_f = spx, trg
                    else:
                        tp2_px, tp2_f = spx, trg
                elif slx > 0 and not trg:
                    hard_sl = slx
        except Exception as e:
            logger.warning(f"启动恢复：查TPSL失败 {e}")

        self.pipeline.sync_position(side=side, qty=amt, entry=entry,
                                    position_id=pid, allow_initial=True)
        self.pipeline.data["hard_sl_px"] = hard_sl
        self.pipeline.data["tp1"] = {"px": tp1_px, "pieces": 1 if tp1_px else 0,
                                     "filled": tp1_f, "qty": 0.0}
        self.pipeline.data["tp2"] = {"px": tp2_px, "pieces": 1 if tp2_px else 0,
                                     "filled": tp2_f, "qty": 0.0}
        self.pipeline.data.setdefault("tier", "")

        self.radar.reset()
        if atr > 0:
            self.radar.set_atr(atr)
        self.radar.arm(tp1_price=tp1_px, tp2_price=(tp2_px or entry), direction=side)
        px = float(self._get_current_price() or entry)
        gate = ((tp1_px + tp2_px) / 2.0) if (tp1_px and tp2_px) else (tp2_px or entry)
        if atr > 0 and gate > 0 and (
            (side == "LONG" and px >= gate) or (side == "SHORT" and px <= gate)
        ):
            self.radar.mark_activated(entry_price=entry, tp2_price=(tp2_px or entry), direction=side)
        # 无论是否激活，都把雷达止损锚到交易所现有硬止损（只进不退守卫在 update 里）
        if hard_sl > 0:
            self.radar.seed_stop(hard_sl)

        self._start_monitoring()
        self._catchup_blocked_until = 0.0
        self._safe_alert(f"启动恢复：{side} {amt}@{entry} 已重建监控 "
                         f"(ATR≈{atr:.2f} SL={hard_sl or '?'} 雷达={'已激活' if self.radar.get_state().activated else '待命'})")

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


def block_catchup(symbol: str = "ETH", seconds: float = None):
    """人工中止心跳催单：这段时间内心跳不再把该品种补开。"""
    from app import get_supervisor  # 延迟导入避免循环
    sup = get_supervisor(symbol)
    sec = float(seconds if seconds is not None else CATCHUP_BLOCK_SEC)
    sup._catchup_blocked_until = time.time() + sec
    logger.warning(f"[{symbol}] 心跳催单已人工中止 {sec:.0f}s")
    return sup._catchup_blocked_until


def recover_all_on_start():
    """引擎启动时对所有活跃品种做一次在场持仓恢复。"""
    from app import get_supervisor
    for sym in ("ETH",):
        try:
            get_supervisor(sym).recover_on_start()
        except Exception as e:
            logger.error(f"[{sym}] 启动恢复异常: {e}")


def confirm_catchup(symbol: str = "ETH"):
    """人工确认追单：下一次合格心跳立即补开。"""
    from app import get_supervisor
    sup = get_supervisor(symbol)
    sup._chase_confirmed = True
    logger.warning(f"[{symbol}] 追单已人工确认")
    return True


def cancel_chase_watch(symbol: str = "ETH"):
    """人工中止追单确认观察窗，并冻结补开一段时间。"""
    from app import get_supervisor
    sup = get_supervisor(symbol)
    sup._chase_watch = {}
    sup._chase_confirmed = False
    sup._catchup_blocked_until = time.time() + CATCHUP_BLOCK_SEC
    logger.warning(f"[{symbol}] 追单观察窗已中止，冻结补开 {CATCHUP_BLOCK_SEC:.0f}s")
    return sup._catchup_blocked_until


def housekeep(symbol: str = "ETH"):
    """周期巡检：空仓清孤儿单；有仓但无人管 -> 兜底恢复。"""
    from app import get_supervisor
    from coinw_client import is_orders_query_failed
    sup = get_supervisor(symbol)
    try:
        have = sup._pos_qty()
        if have == 0:
            if not sup._monitoring:
                orders = sup.client.get_open_orders(symbol, position_type="plan")
                if not is_orders_query_failed(orders) and orders:
                    n = sup.client.cancel_all_orders(symbol)
                    logger.warning(f"[{symbol}] housekeep：清孤儿单 {n} 笔")
        elif not sup._monitoring:
            logger.warning(f"[{symbol}] housekeep：发现无人管持仓，触发恢复")
            sup.recover_on_start()
        elif sup._loop_beat and (time.time() - sup._loop_beat) > WATCHDOG_STALE_SEC:
            stale = time.time() - sup._loop_beat
            logger.error(f"[{symbol}] watchdog：监控循环 {stale:.0f}s 未跳，重启监控线程")
            sup._safe_alert(f"watchdog：监控循环停跳 {stale:.0f}s，已重启")
            sup._monitoring = False
            time.sleep(1)
            sup._start_monitoring()
    except Exception as e:
        logger.error(f"[{symbol}] housekeep 异常: {e}")
