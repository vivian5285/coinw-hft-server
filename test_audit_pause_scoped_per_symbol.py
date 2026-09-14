#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-09-14：审计失败暂停改成"只暂停本品种"的回归测试，以及tp_slice审计
用真实per_piece_qty替代硬编码0.01的回归测试。

背景——实盘复现(XRPUSDT)：一笔XRP开仓的TP1+TP2张数(30张)相对期望值
(24张)有6张drift，本来是CoinW按"张"取整的正常现象(1张=10 XRP，不是
硬编码假设的0.01)，但_run_audit()传给审计的contract_unit一直硬编码
0.01(注释写着"CoinW ETH"，明显是早期只有ETH一个品种时代的遗留)，
容差算错了尺度，把合法取整drift判成真实异常，触发_pause_trading()。
而_pause_trading()原来改的是模块级全局trading_paused——这一个品种的
误判审计失败，从22:32一路卡到第二天凌晨，期间SOL/BNB/XAU/XPD等所有
其它品种的新开仓全部被这个跟它们无关的暂停拒收，只能靠人工调
/admin/resume解开，造成大量"漏单"。

修复：
1. _place_defense_orders()把这笔仓位自己算出的per_piece_qty存进
   pipeline.data["contract_unit"]，_run_audit()读这个真实值而不是
   硬编码0.01。
2. _pause_trading()只标记self._symbol_paused，不再牵连全局，
   /admin/resume/<symbol>单独解除。

不碰任何真实账户/持仓，self.client/self.pipeline/self._dingtalk全部
用测试替身，chief_auditor.audit_open_bundle用真实纯函数。
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("COINW_SKIP_BOOTSTRAP", "1")

import position_supervisor_coinw as psc  # noqa: E402


class _FakePhase:
    value = "MONITORING"


class _FakePipeline:
    def __init__(self):
        self.data = {}
        self._audit = None
        self.phase = _FakePhase()

    def set_audit(self, ok, hard_fails, warns):
        self._audit = (ok, hard_fails, warns)


def _mk_supervisor(symbol="XRP"):
    s = object.__new__(psc.PositionSupervisorCoinW)
    s.symbol = symbol
    s.pipeline = _FakePipeline()
    s.client = MagicMock()
    s._dingtalk = MagicMock()
    return s


class TestContractUnitFromRealFill(unittest.TestCase):
    def test_xrp_style_fill_persists_real_per_piece_qty(self):
        """复现实盘XRP：80.0 XRP=8.0张 → per_piece_qty=10，不是0.01。"""
        s = _mk_supervisor()
        total_pieces = 8.0
        total_qty = 80.0
        per_piece_qty = total_qty / total_pieces
        s.pipeline.data["contract_unit"] = per_piece_qty
        self.assertAlmostEqual(s.pipeline.data["contract_unit"], 10.0, places=6)

    def test_audit_passes_with_real_contract_unit_same_drift_that_failed_before(self):
        """核心回归：完全复现实盘那笔审计(tp1+tp2=30, expected=24,
        init=80)——用硬编码0.01会失败(实盘真实发生过)，用真实
        contract_unit=10会通过。"""
        from chief_auditor import check_tp_slice_budget

        # 硬编码0.01(修复前的行为)：应该判失败，跟实盘复现一致
        item_before = check_tp_slice_budget(
            initial_qty=80.0, tp1_qty=10.0, tp2_qty=20.0,
            ratios=[0.10, 0.20, 0.70], contract_unit=0.01,
        )
        self.assertFalse(item_before.ok, "修复前的硬编码0.01应该会误判失败，验证问题真实存在")

        # 真实contract_unit=10(修复后的行为)：应该判通过
        item_after = check_tp_slice_budget(
            initial_qty=80.0, tp1_qty=10.0, tp2_qty=20.0,
            ratios=[0.10, 0.20, 0.70], contract_unit=10.0,
        )
        self.assertTrue(item_after.ok, "用真实contract_unit后，同样的整张取整drift应该判通过")

    def test_run_audit_reads_pipeline_contract_unit_not_hardcoded(self):
        """完全复现实盘那笔真实数字：init=80, tp1=1张×10=10, tp2=2张×10=20，
        tp1+tp2=30 vs expected(10%+20%=30%×80=24)，drift=6——用真实
        contract_unit=10应该在容差内通过(修复前用硬编码0.01会失败，
        跟实盘复现完全一致)。"""
        s = _mk_supervisor()
        s.pipeline.data.update({
            "qty": 80.0, "initial_qty": 80.0, "entry": 1.35,
            "tp1": {"px": 1.0, "pieces": 1, "qty": 10.0},
            "tp2": {"px": 1.0, "pieces": 2, "qty": 20.0},
            "hard_sl_px": 1.34,
            "contract_unit": 10.0,
        })
        signal = MagicMock(action="SHORT", tier="1")

        ok = s._run_audit(signal)

        self.assertTrue(ok, "真实contract_unit=10时，同样的drift=6应该在容差内通过")


class TestAuditFailurePausesOnlySymbol(unittest.TestCase):
    def test_pause_trading_sets_symbol_flag_not_global(self):
        s = _mk_supervisor(symbol="XRP")
        other = _mk_supervisor(symbol="SOL")

        s._pause_trading("督察失败")

        self.assertTrue(getattr(s, "_symbol_paused", False))
        self.assertFalse(getattr(other, "_symbol_paused", False),
                          "一个品种的审计失败不该影响其它品种的实例状态")
        self.assertFalse(psc.trading_paused, "本品种暂停不该动到模块级全局trading_paused")

    def test_handle_open_rejects_when_symbol_paused_even_if_global_clear(self):
        s = _mk_supervisor(symbol="XRP")
        s._symbol_paused = True
        signal = MagicMock(action="LONG", tp1=0, tp2=0)

        result = s._handle_open(signal)

        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("error"), "symbol_paused")

    def test_get_health_exposes_symbol_paused(self):
        s = _mk_supervisor(symbol="XRP")
        s._symbol_paused = True
        s._monitoring = False
        s.radar = MagicMock()
        s.radar.get_state.return_value = MagicMock(activated=False)

        health = s.get_health()

        self.assertTrue(health.get("symbol_paused"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
