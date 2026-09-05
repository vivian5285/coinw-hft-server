#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
影子竞赛 —— CoinW ETH：TV 实盘腿 vs VPS 自主指标腿。

VPS 腿【纯模拟，永不下单】：自己拉币赢 K 线跑趋势指标，记录"本该怎么开/平"，
出场机制（TP1/TP2 + 硬止损 + 雷达追踪）与实盘 breath_stop / defense_profiles
完全一致，所以擂台只比"信号质量"。

TV 腿计分：轮询 /v1/perpum/positions/history 的已平仓行（netProfit 是净额）。

策略（可调旋钮见 CONFIG）：
  周期 60m（≈59m TV 周期）；唐奇安 N 根通道突破定方向；ADX(14) 门控 + 分档
  （<门槛不做；弱/中/强 -> tier 0/1/2 -> 复用 TIER_NOTIONAL_MULT 定模拟仓位）。
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(BASE_DIR, "contest_state.json")

CONFIG: Dict[str, Any] = {
    "symbol": "ETH",
    "tf_min": 60,             # 目标周期（≈ETH TV 59m，用 60m 原生近似）
    "src_min": 60,            # 60m 原生，无需合成
    "donchian_n": 20,         # 通道突破回看根数
    "adx_period": 14,
    "atr_period": 14,
    "adx_gate": 20.0,         # ADX 低于此不进场
    "adx_mid": 25.0,          # >=gate <mid -> 弱(0)；>=mid <strong -> 中(1)
    "adx_strong": 35.0,       # >=strong -> 强(2)
    "hard_sl_atr_mult": 2.0,  # 合成止损 = entry ∓ 该倍数×ATR（再过 defense ×1.15 呼吸垫）
    "shadow_equity": 1000.0,  # 模拟腿计分基准本金（固定，不复利，便于按%对比）
    "taker_fee": 0.0006,      # CoinW 合约 taker 单边
    "rebate": 0.90,           # 手续费返佣比例（用户 90%）
    "slippage_ticks": 1,
    "tick": 0.01,
    "tp1_ratio": 0.10,
    "tp2_ratio": 0.20,
    "src_limit": 1000,        # 60m×1000 ≈ 41 天，够 20/14 指标
    "equity_curve_cap": 3000,
}


# ----------------------- 指标（纯 Python，无 numpy） -----------------------

def _synth(bars: List[list], factor: int) -> List[list]:
    """把原始 K 线按整数倍聚合；丢掉未收满的最后一桶。"""
    out = []
    n = len(bars)
    full = n - (n % factor)
    for i in range(0, full, factor):
        chunk = bars[i:i + factor]
        out.append([
            chunk[0][0], chunk[0][1],
            max(c[2] for c in chunk),
            min(c[3] for c in chunk),
            chunk[-1][4],
            sum(c[5] for c in chunk),
        ])
    return out


def _true_ranges(bars: List[list]) -> List[float]:
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i][2], bars[i][3], bars[i - 1][4]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return trs


def _atr(bars: List[list], period: int) -> float:
    trs = _true_ranges(bars)
    if len(trs) < period:
        return 0.0
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def _adx(bars: List[list], period: int) -> float:
    """Wilder ADX。"""
    if len(bars) < period * 2 + 1:
        return 0.0
    plus_dm, minus_dm, tr = [], [], []
    for i in range(1, len(bars)):
        up = bars[i][2] - bars[i - 1][2]
        dn = bars[i - 1][3] - bars[i][3]
        plus_dm.append(up if (up > dn and up > 0) else 0.0)
        minus_dm.append(dn if (dn > up and dn > 0) else 0.0)
        h, l, pc = bars[i][2], bars[i][3], bars[i - 1][4]
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))

    def _wilder(seq):
        s = sum(seq[:period])
        out = [s]
        for v in seq[period:]:
            s = s - s / period + v
            out.append(s)
        return out

    atr_s = _wilder(tr)
    pdm_s = _wilder(plus_dm)
    mdm_s = _wilder(minus_dm)
    dx = []
    for a, p, m in zip(atr_s, pdm_s, mdm_s):
        if a <= 0:
            continue
        pdi = 100.0 * p / a
        mdi = 100.0 * m / a
        denom = pdi + mdi
        dx.append(100.0 * abs(pdi - mdi) / denom if denom > 0 else 0.0)
    if len(dx) < period:
        return 0.0
    adx = sum(dx[:period]) / period
    for v in dx[period:]:
        adx = (adx * (period - 1) + v) / period
    return adx


def _donchian(bars: List[list], n: int, upto: int) -> tuple:
    """[upto-n, upto) 区间的最高高、最低低。"""
    lo = max(0, upto - n)
    seg = bars[lo:upto]
    if not seg:
        return 0.0, 0.0
    return max(c[2] for c in seg), min(c[3] for c in seg)


def _tier_from_adx(adx: float) -> Optional[str]:
    c = CONFIG
    if adx < c["adx_gate"]:
        return None
    if adx < c["adx_mid"]:
        return "0"
    if adx < c["adx_strong"]:
        return "1"
    return "2"


# ----------------------------- 竞赛引擎 -----------------------------

class ShadowContest:
    def __init__(self):
        self._lock = threading.Lock()
        self.state = self._load()

    # ---- 持久化 ----
    def _blank(self) -> Dict[str, Any]:
        return {
            "started_ts": time.time(),
            "updated_ts": 0.0,
            "config": dict(CONFIG),
            "shadow": {
                "open": None,
                "closed": [],
                "equity": CONFIG["shadow_equity"],
                "equity_curve": [],
            },
            "tv": {
                "closed": [],
                "seen_ids": [],
                "equity_curve": [],
                "equity0": None,
            },
            "last_bar_ts": 0,
            "last_price": 0.0,
        }

    def _load(self) -> Dict[str, Any]:
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                st = json.load(f)
            for k in ("shadow", "tv"):
                st.setdefault(k, self._blank()[k])
            return st
        except Exception:
            return self._blank()

    def _save(self):
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False)
        os.replace(tmp, STATE_PATH)

    # ---- 费用 ----
    def _fee(self, notional: float) -> float:
        return abs(notional) * CONFIG["taker_fee"] * (1.0 - CONFIG["rebate"])

    def _slip(self) -> float:
        return CONFIG["slippage_ticks"] * CONFIG["tick"]

    # ---- 策略评估（用最后一根已收盘 60m）----
    def _entry_signal(self, bars: List[list]) -> Optional[Dict[str, Any]]:
        c = CONFIG
        need = max(c["donchian_n"], c["adx_period"] * 2, c["atr_period"]) + 3
        if len(bars) < need:
            return None
        i = len(bars) - 1  # 最后一根已收盘
        close = bars[i][4]
        hh, ll = _donchian(bars, c["donchian_n"], i)  # 不含当根
        adx = _adx(bars[: i + 1], c["adx_period"])
        atr = _atr(bars[: i + 1], c["atr_period"])
        if atr <= 0:
            return None
        tier = _tier_from_adx(adx)
        if tier is None:
            return None
        side = None
        if close > hh:
            side = "LONG"
        elif close < ll:
            side = "SHORT"
        if side is None:
            return None
        return {"side": side, "tier": tier, "entry": close, "atr": atr,
                "adx": round(adx, 1), "bar_ts": bars[i][0]}

    def _exit_by_flip(self, bars: List[list], side: str) -> bool:
        c = CONFIG
        i = len(bars) - 1
        close = bars[i][4]
        hh, ll = _donchian(bars, c["donchian_n"], i)
        return (side == "LONG" and close < ll) or (side == "SHORT" and close > hh)

    # ---- 开/平模拟仓 ----
    def _open_shadow(self, sig: Dict[str, Any]):
        import defense_profiles as dp
        import breath_stop as bs
        c = CONFIG
        side, tier, entry, atr = sig["side"], sig["tier"], sig["entry"], sig["atr"]
        prof = _breath_profile()
        qty = dp.get_defense_profile(c["symbol"]).calc_position_size(
            c["shadow_equity"], entry, tier
        )
        if qty <= 0:
            return
        slip = self._slip()
        fill = entry + slip if side == "LONG" else entry - slip
        # 合成 TV 止损 -> defense 硬止损（×1.15 呼吸垫）
        raw_sl = fill - c["hard_sl_atr_mult"] * atr if side == "LONG" else fill + c["hard_sl_atr_mult"] * atr
        hard_sl = dp.get_defense_profile(c["symbol"]).calc_hard_stop(fill, raw_sl)
        tp1_a = float(prof.get("tp1_atr") or 1.35)
        tp2_a = float(prof.get("tp2_atr") or 2.5)
        if side == "LONG":
            tp1, tp2 = fill + tp1_a * atr, fill + tp2_a * atr
        else:
            tp1, tp2 = fill - tp1_a * atr, fill - tp2_a * atr
        init_stop = bs.initial_stop_price(side, fill, profile=prof)
        open_fee = self._fee(qty * fill)
        self.state["shadow"]["open"] = {
            "side": side, "tier": tier, "entry": round(fill, 2), "atr": round(atr, 4),
            "adx": sig["adx"], "qty": round(qty, 6), "qty_left": round(qty, 6),
            "hard_sl": hard_sl, "tp1": round(tp1, 2), "tp2": round(tp2, 2),
            "tp1_done": False, "tp2_done": False,
            "cur_stop": init_stop, "init_stop": init_stop,
            "best": round(fill, 2), "open_ts": time.time(), "bar_ts": sig["bar_ts"],
            "fees": round(open_fee, 6), "realized": 0.0,
        }

    def _close_slice(self, pos: Dict[str, Any], px: float, ratio_of_orig: float, reason: str):
        """按【原始】qty 的比例平一部分，累加已实现盈亏与费用。"""
        c = CONFIG
        qty = min(pos["qty_left"], pos["qty"] * ratio_of_orig)
        if qty <= 0:
            return
        side = pos["side"]
        gross = (px - pos["entry"]) * qty if side == "LONG" else (pos["entry"] - px) * qty
        fee = self._fee(qty * px)
        pos["qty_left"] = round(pos["qty_left"] - qty, 8)
        pos["realized"] = round(pos["realized"] + gross, 6)
        pos["fees"] = round(pos["fees"] + fee, 6)
        pos.setdefault("legs", []).append(
            {"px": round(px, 2), "qty": round(qty, 6), "reason": reason,
             "gross": round(gross, 4), "ts": time.time()}
        )

    def _finalize(self, pos: Dict[str, Any], reason: str):
        net = round(pos["realized"] - pos["fees"], 4)
        rec = {
            "side": pos["side"], "tier": pos["tier"], "adx": pos["adx"],
            "entry": pos["entry"], "atr": pos["atr"], "qty": pos["qty"],
            "open_ts": pos["open_ts"], "close_ts": time.time(),
            "gross": round(pos["realized"], 4), "fees": round(pos["fees"], 6),
            "net": net, "reason": reason,
            "ret_pct": round(net / CONFIG["shadow_equity"] * 100.0, 4),
            "legs": pos.get("legs", []),
        }
        sh = self.state["shadow"]
        sh["closed"].append(rec)
        sh["equity"] = round(sh["equity"] + net, 4)
        sh["equity_curve"].append([rec["close_ts"], sh["equity"]])
        sh["equity_curve"] = sh["equity_curve"][-CONFIG["equity_curve_cap"]:]
        sh["open"] = None

    def _manage_shadow(self, bars: List[list], last_price: float):
        import breath_stop as bs
        pos = self.state["shadow"]["open"]
        if not pos:
            return
        side, px = pos["side"], last_price
        prof = _breath_profile()
        # 更新 best
        pos["best"] = round(max(pos["best"], px), 2) if side == "LONG" else round(min(pos["best"], px), 2)
        # 雷达推进（激活线 = (tp1+tp2)/2 中点）
        gate = (pos["tp1"] + pos["tp2"]) / 2.0
        activated = (px >= gate) if side == "LONG" else (px <= gate)
        if activated:
            res = bs.calculate_breath_stop(
                side=side, price=px, entry_price=pos["entry"], initial_atr=pos["atr"],
                initial_stop=pos["init_stop"], current_stop=pos["cur_stop"],
                best_price=pos["best"], breakeven_phase=False, profile=prof,
                tp1_px=pos["tp1"], tp2_px=pos["tp2"],
            )
            ns = float(res.get("stop") or 0)
            if ns > 0:
                if side == "LONG" and ns > pos["cur_stop"]:
                    pos["cur_stop"] = round(ns, 2)
                elif side == "SHORT" and (pos["cur_stop"] <= 0 or ns < pos["cur_stop"]):
                    pos["cur_stop"] = round(ns, 2)
        # TP1 / TP2 触价（近似：last_price 越过即成交在 TP 价）
        if not pos["tp1_done"] and ((side == "LONG" and px >= pos["tp1"]) or (side == "SHORT" and px <= pos["tp1"])):
            self._close_slice(pos, pos["tp1"], CONFIG["tp1_ratio"], "TP1")
            pos["tp1_done"] = True
        if not pos["tp2_done"] and ((side == "LONG" and px >= pos["tp2"]) or (side == "SHORT" and px <= pos["tp2"])):
            self._close_slice(pos, pos["tp2"], CONFIG["tp2_ratio"], "TP2")
            pos["tp2_done"] = True
        # 硬止损 / 雷达止损
        stop = pos["cur_stop"] if activated and pos["cur_stop"] > 0 else pos["hard_sl"]
        hit = (px <= stop) if side == "LONG" else (px >= stop)
        if hit and pos["qty_left"] > 0:
            self._close_slice(pos, stop, 1.0, "STOP" if activated else "HARD_SL")
            self._finalize(pos, "STOP" if activated else "HARD_SL")
            return
        # 反向通道突破 -> 平剩余
        if pos["qty_left"] > 0 and self._exit_by_flip(bars, side):
            self._close_slice(pos, px - self._slip() if side == "LONG" else px + self._slip(), 1.0, "FLIP")
            self._finalize(pos, "FLIP")
            return
        if pos["qty_left"] <= 1e-9:
            self._finalize(pos, "TP_ALL")

    # ---- TV 实盘腿计分 ----
    def _poll_tv(self, client):
        rows = client.get_position_history(CONFIG["symbol"], 50)
        tv = self.state["tv"]
        seen = set(tv.get("seen_ids") or [])
        start_ts = float(self.state.get("started_ts") or 0)
        added = 0
        for r in rows:
            if str(r.get("status") or "").lower() != "close":
                continue
            oid = str(r.get("openId") or r.get("orderId") or "")
            if not oid or oid in seen:
                continue
            # 只算竞赛开始之后开的仓；开始前的历史单不计入
            o_ts = int(r.get("tradeStartDate") or 0) / 1000.0
            if start_ts > 0 and o_ts > 0 and o_ts < start_ts:
                seen.add(oid)
                continue
            try:
                net = float(r.get("netProfit") or 0)
                fee = float(r.get("fee") or 0)
                op = float(r.get("avgOpenPrice") or 0)
                cp = float(r.get("avgClosePrice") or 0)
            except (TypeError, ValueError):
                continue
            tv["closed"].append({
                "side": str(r.get("direction") or "").upper(),
                "entry": op, "exit": cp, "net": round(net, 4),
                "gross": round(net + fee, 4), "fees": round(fee, 6),
                "margin": float(r.get("margin") or 0),
                "leverage": float(r.get("leverage") or 0),
                "reason": str(r.get("liquidateBy") or ""),
                "open_ts": int(r.get("tradeStartDate") or 0) / 1000.0,
                "close_ts": time.time(),
                "ret_pct": (round(net / float(r.get("margin")) * 100.0, 4)
                            if float(r.get("margin") or 0) > 0 else 0.0),
                "openId": oid,
            })
            seen.add(oid)
            added += 1
        if added:
            tv["closed"].sort(key=lambda x: x["open_ts"])
            tv["seen_ids"] = list(seen)[-500:]
            eq = 0.0
            tv["equity_curve"] = []
            for t in tv["closed"]:
                eq = round(eq + t["net"], 4)
                tv["equity_curve"].append([t["close_ts"], eq])
            tv["equity_curve"] = tv["equity_curve"][-CONFIG["equity_curve_cap"]:]

    # ---- 主循环单步 ----
    def run_once(self, client) -> Dict[str, Any]:
        with self._lock:
            raw = client.get_klines(CONFIG["symbol"], CONFIG["src_min"], CONFIG["src_limit"])
            price = float(client.get_current_price(CONFIG["symbol"]) or 0)
            if price <= 0 and raw:
                price = raw[-1][4]
            self.state["last_price"] = price
            if raw and len(raw) >= CONFIG["src_min"]:
                bars = _synth(raw, CONFIG["tf_min"] // CONFIG["src_min"])
                if bars:
                    self.state["last_bar_ts"] = bars[-1][0]
                    if self.state["shadow"]["open"]:
                        self._manage_shadow(bars, price)
                    if not self.state["shadow"]["open"]:
                        sig = self._entry_signal(bars)
                        if sig:
                            self._open_shadow(sig)
            try:
                self._poll_tv(client)
            except Exception:
                pass
            self.state["updated_ts"] = time.time()
            self._save()
            return self.snapshot()

    # ---- 指标汇总 ----
    @staticmethod
    def _metrics(trades: List[dict], base_equity: float) -> Dict[str, Any]:
        n = len(trades)
        if n == 0:
            return {"n": 0, "win_rate": 0, "net": 0, "ret_pct": 0, "profit_factor": 0,
                    "avg_win": 0, "avg_loss": 0, "expectancy": 0, "max_dd": 0}
        nets = [float(t["net"]) for t in trades]
        wins = [x for x in nets if x > 0]
        losses = [x for x in nets if x <= 0]
        gp = sum(wins)
        gl = abs(sum(losses))
        eq, peak, dd = 0.0, 0.0, 0.0
        for x in nets:
            eq += x
            peak = max(peak, eq)
            dd = min(dd, eq - peak)
        return {
            "n": n,
            "win_rate": round(len(wins) / n * 100.0, 1),
            "net": round(sum(nets), 4),
            "ret_pct": round(sum(nets) / base_equity * 100.0, 2) if base_equity else 0,
            "profit_factor": round(gp / gl, 2) if gl > 0 else (999.0 if gp > 0 else 0),
            "avg_win": round(gp / len(wins), 2) if wins else 0,
            "avg_loss": round(-gl / len(losses), 2) if losses else 0,
            "expectancy": round(sum(nets) / n, 3),
            "max_dd": round(dd, 2),
        }

    def snapshot(self) -> Dict[str, Any]:
        st = self.state
        sh, tv = st["shadow"], st["tv"]
        tv_base = 0.0
        if tv["closed"]:
            ms = [t.get("margin", 0) for t in tv["closed"] if t.get("margin", 0) > 0]
            tv_base = (sum(ms) / len(ms)) if ms else CONFIG["shadow_equity"]
        return {
            "updated_ts": st["updated_ts"],
            "started_ts": st["started_ts"],
            "last_price": st["last_price"],
            "last_bar_ts": st["last_bar_ts"],
            "config": st["config"],
            "shadow": {
                "open": sh["open"],
                "equity": sh["equity"],
                "equity_curve": sh["equity_curve"][-400:],
                "closed": sh["closed"][-40:],
                "metrics": self._metrics(sh["closed"], CONFIG["shadow_equity"]),
            },
            "tv": {
                "equity_curve": tv["equity_curve"][-400:],
                "closed": tv["closed"][-40:],
                "metrics": self._metrics(tv["closed"], tv_base or CONFIG["shadow_equity"]),
                "base_equity": round(tv_base, 2),
            },
        }


def _breath_profile():
    from breath_profiles import get_breath_profile
    return get_breath_profile(CONFIG["symbol"])


_CONTEST: Optional[ShadowContest] = None
_CONTEST_LOCK = threading.Lock()


def get_contest() -> ShadowContest:
    global _CONTEST
    with _CONTEST_LOCK:
        if _CONTEST is None:
            _CONTEST = ShadowContest()
        return _CONTEST


def run_once() -> Dict[str, Any]:
    from coinw_client import coinw_client
    return get_contest().run_once(coinw_client)


def snapshot() -> Dict[str, Any]:
    return get_contest().snapshot()
