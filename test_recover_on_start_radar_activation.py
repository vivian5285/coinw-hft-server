#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-09-13：recover_on_start() 雷达激活状态恢复的回归测试。

背景——宝贝实盘复现(BNBUSDT.P，2026-09-12晚)：BNB空单开仓后雷达真的
激活过(日志"雷达激活: 方向=SHORT...初始SL=733.87")，把交易所止损从
开仓时的738.06移到了盈利区间733.87。紧接着一次引擎重启，
recover_on_start()原来只靠"现价有没有过用ATR估算的tp1_est/tp2_est
现算出来的gate"这一条判断"重启前雷达是不是已经激活过"——这条判断跟
真实历史无关，只是重启这一刻的价格快照，稍微差一点(或者估算的TP跟
当初真实TP对不上)就会误判"还没激活"，把已经进入trail阶段的雷达打回
activated=False。而BreathStop.update()一开头就是
"if not st.activated: return None"——之后雷达再也不会推进，止损永远
锁死在733.87不会再收紧，白白丢失"趋势强度系数不断锁住利润"这个雷达
最核心的能力。

修复：交易所现有止损本身就是最权威的"有没有激活过"证据——全新开仓的
硬止损必然在亏损方向，只要止损已经越过entry进到盈利方向，就百分百
证明雷达之前真的动过手，直接判定为已激活，不用再靠现价对gate的瞬时
快照去猜。

不碰任何真实账户/持仓，self.client/self.pipeline/self.radar全部用
测试替身，self.radar用真实BreathStop实例(验证真实的activated/
current_sl状态转换，不是mock调用记录)。
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("COINW_SKIP_BOOTSTRAP", "1")

import position_supervisor_coinw as psc  # noqa: E402
from breath_stop import BreathStop  # noqa: E402


class _FakePipeline:
    """recover_on_start只用得到.data(dict)/.sync_position(...)/.advance(...)，
    不需要真实PipelineBridge的Phase/Role状态机校验。"""

    def __init__(self):
        self.data = {}

    def sync_position(self, **kwargs):
        self.data.update(kwargs)

    def advance(self, *args, **kwargs):
        pass


def _mk_supervisor(symbol="BNB"):
    s = object.__new__(psc.PositionSupervisorCoinW)
    s.symbol = symbol
    s.pipeline = _FakePipeline()
    s.radar = BreathStop(symbol)
    s.client = MagicMock()
    s._safe_alert = MagicMock()
    s._start_monitoring = MagicMock()
    s._recompute_atr_150m = MagicMock(return_value=3.30)
    s._live_side = MagicMock(return_value="SHORT")
    s._catchup_blocked_until = 0.0
    return s


class TestRecoverOnStartRadarActivation(unittest.TestCase):
    def test_bnb_real_incident_stop_already_in_profit_marks_activated(self):
        """核心回归：BNB真实复现数值——entry=734.47(SHORT)，交易所现存
        止损733.87已经在盈利方向(低于entry)，即使重启这一刻价格没有
        越过重算的gate，也必须判定雷达重启前已激活，而不是打回待命。"""
        s = _mk_supervisor("BNB")
        s.client.get_position = MagicMock(return_value={
            "baseSize": 0.36, "openPrice": 734.47, "id": "pos123",
        })
        # 交易所没有真实TP记录(小仓位常见)，只有一张止损单，价格已在盈利区
        s.client.get_tp_sl_info = MagicMock(return_value=[
            {"stopType": 2, "stopLossPrice": 733.87, "triggerStatus": 0},
        ])
        # 重启这一刻现价刻意给一个"还没到重算gate"的值，验证不靠这个判断
        s._get_current_price = MagicMock(return_value=731.0)

        s.recover_on_start()

        state = s.radar.get_state()
        self.assertTrue(
            state.activated,
            "交易所止损已在盈利方向，必须判定雷达重启前已激活",
        )
        self.assertAlmostEqual(state.current_sl, 733.87, places=2)

    def test_fresh_position_stop_still_on_loss_side_stays_not_activated(self):
        """回归：真正全新的、雷达确实还没激活过的仓位(止损仍在亏损方向、
        现价也没过gate)——不该被这次改动误伤，维持原有"未激活"判断。"""
        s = _mk_supervisor("BNB")
        s.client.get_position = MagicMock(return_value={
            "baseSize": 0.36, "openPrice": 734.47, "id": "pos456",
        })
        # 止损738.06明显在SHORT的亏损方向(高于entry)——典型刚开仓状态
        s.client.get_tp_sl_info = MagicMock(return_value=[
            {"stopType": 2, "stopLossPrice": 738.06, "triggerStatus": 0},
        ])
        s._get_current_price = MagicMock(return_value=734.0)  # 现价也没到gate

        s.recover_on_start()

        state = s.radar.get_state()
        self.assertFalse(state.activated, "止损仍在亏损方向、现价未过gate时不该判定已激活")
        self.assertAlmostEqual(state.current_sl, 738.06, places=2)

    def test_long_side_symmetric_check(self):
        """多头方向对称验证：止损已经高于entry(盈利方向)即判定已激活。"""
        s = _mk_supervisor("XAU")
        s.client.get_position = MagicMock(return_value={
            "baseSize": 0.01, "openPrice": 4400.0, "id": "pos789",
        })
        s.client.get_tp_sl_info = MagicMock(return_value=[
            {"stopType": 2, "stopLossPrice": 4405.0, "triggerStatus": 0},  # 高于entry=已锁盈利
        ])
        s._live_side = MagicMock(return_value="LONG")
        s._get_current_price = MagicMock(return_value=4402.0)  # 现价故意给一个没过重算gate的值

        s.recover_on_start()

        state = s.radar.get_state()
        self.assertTrue(state.activated)
        self.assertAlmostEqual(state.current_sl, 4405.0, places=2)

    def test_still_activates_via_price_gate_when_stop_not_moved_yet(self):
        """回归：止损还没被移动过(在亏损方向)，但重启这一刻现价确实已经
        越过重算的激活gate——原有"现价过gate即激活"这条判断必须继续生效，
        新增的止损方向检查是补充条件，不是替换。"""
        s = _mk_supervisor("BNB")
        s.client.get_position = MagicMock(return_value={
            "baseSize": 0.36, "openPrice": 734.47, "id": "posABC",
        })
        s.client.get_tp_sl_info = MagicMock(return_value=[
            {"stopType": 2, "stopLossPrice": 738.06, "triggerStatus": 0},  # 仍在亏损方向
        ])
        # 现价给一个明显低于entry很多的值，确保能越过(entry - k*atr)量级的gate估算
        s._get_current_price = MagicMock(return_value=700.0)

        s.recover_on_start()

        state = s.radar.get_state()
        self.assertTrue(state.activated, "现价已越过重算的激活gate时仍应正常激活")


if __name__ == "__main__":
    unittest.main(verbosity=2)
