#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
流水线状态机单元测试 - CoinW单系统 v16.22.1
"""

import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from pipeline_ledger import PipelineLedger, Phase, Role, soft_gates_enabled


class TestPipelineLedger(unittest.TestCase):
    """测试流水线账本"""

    def setUp(self):
        self.ledger = PipelineLedger("ETH", "coinw")

    def test_initial_phase(self):
        """初始阶段应为IDLE"""
        self.assertEqual(self.ledger.phase, Phase.IDLE)

    def test_signal_to_pending_clear(self):
        """信号登记后进入PENDING_CLEAR"""
        ok, msg = self.ledger.advance(
            Phase.SIGNAL_RECEIVED, Role.SIGNAL,
            note="test signal"
        )
        self.assertTrue(ok)
        self.assertEqual(self.ledger.phase, Phase.SIGNAL_RECEIVED)

        ok, msg = self.ledger.advance(
            Phase.PENDING_CLEAR, Role.AUDITOR_POS,
            note="start clear"
        )
        self.assertTrue(ok)
        self.assertEqual(self.ledger.phase, Phase.PENDING_CLEAR)

    def test_full_flow(self):
        """完整流程"""
        # IDLE -> SIGNAL_RECEIVED
        self.ledger.advance(Phase.SIGNAL_RECEIVED, Role.SIGNAL, note="signal")

        # -> PENDING_CLEAR
        self.ledger.advance(Phase.PENDING_CLEAR, Role.AUDITOR_POS, note="clear")

        # -> CLEARED
        self.ledger.advance(Phase.CLEARED, Role.AUDITOR_POS, note="cleared")

        # -> ENTRY_SUBMITTED
        self.ledger.advance(Phase.ENTRY_SUBMITTED, Role.EXECUTION, note="submit")

        # -> ENTRY_CONFIRMED
        self.ledger.advance(Phase.ENTRY_CONFIRMED, Role.EXECUTION, note="confirm")

        # -> ORDERS_PLACED
        self.ledger.advance(Phase.ORDERS_PLACED, Role.EXECUTION, note="orders")

        # -> VERIFIED
        self.ledger.advance(Phase.VERIFIED, Role.CHIEF, note="verified")

        # -> REPORTED
        self.ledger.advance(Phase.REPORTED, Role.COMMS, note="reported")

        # -> MONITORING
        self.ledger.advance(Phase.MONITORING, Role.RADAR, note="monitoring")

        self.assertEqual(self.ledger.phase, Phase.MONITORING)

    def test_failed_transition(self):
        """失败转换"""
        self.ledger.advance(Phase.SIGNAL_RECEIVED, Role.SIGNAL, note="signal")
        self.ledger.advance(Phase.FAILED, Role.AUDITOR_POS, note="failed")

        self.assertEqual(self.ledger.phase, Phase.FAILED)

    def test_reset_idle(self):
        """重置到IDLE"""
        self.ledger.advance(Phase.SIGNAL_RECEIVED, Role.SIGNAL)
        self.ledger.reset_idle()

        self.assertEqual(self.ledger.phase, Phase.IDLE)

    def test_sync_position(self):
        """同步持仓"""
        self.ledger.sync_position(
            side="LONG",
            qty=1.0,
            entry=1900.0,
            position_id="123",
            allow_initial=True
        )

        self.assertEqual(self.ledger.data["side"], "LONG")
        self.assertEqual(self.ledger.data["qty"], 1.0)
        self.assertEqual(self.ledger.data["entry"], 1900.0)
        self.assertEqual(self.ledger.data["position_id"], "123")
        self.assertEqual(self.ledger.data["initial_qty"], 1.0)

    def test_tp_fields(self):
        """TP字段"""
        self.ledger.data["tp1"] = {"px": 1950, "qty": 0.1}
        self.ledger.data["tp2"] = {"px": 1970, "qty": 0.2}

        self.assertEqual(self.ledger.data["tp1"]["px"], 1950)
        self.assertEqual(self.ledger.data["tp2"]["qty"], 0.2)

    def test_audit_fields(self):
        """审计字段"""
        self.ledger.set_audit(True, [], ["warning1"])

        audit = self.ledger.data["audit"]
        self.assertTrue(audit["ok"])
        self.assertEqual(len(audit["warns"]), 1)

    def test_to_dict(self):
        """序列化"""
        d = self.ledger.to_dict()
        self.assertIn("schema", d)
        self.assertIn("phase", d)
        self.assertEqual(d["symbol"], "ETH")


if __name__ == "__main__":
    unittest.main()
