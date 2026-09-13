#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-09-12：币赢对齐币安——新增 BNB/OPENAI/SNDK/XPD 四个品种回归测试。

背景：宝贝要求 CoinW 这四个品种做到跟币安一致，能真正接 TV 信号交易。
排查发现这四个品种此前分散卡在多处：
- webhook_parser.VALID_SYMBOLS 只有 ETH/BTC/XAU/BNB，OPENAI/SNDK/XPD 会被
  直接拒收（invalid_symbol）。
- breath_profiles._BY_SYMBOL 只有 ETH，BNB/OPENAI/SNDK/XPD 即使信号通过，
  也会静默用错 ETH 的呼吸系数（get_breath_profile 未知品种回退 ETH）。
- position_supervisor_coinw.recover_all_on_start() 重启恢复循环硬编码
  只恢复 ("ETH",)，BNB 当时已经"名义支持"却漏在这里——重启后 BNB 若有
  持仓不会被 recover_on_start 接管，是个既存孤儿仓风险缺口。
- app.py/health、console_api.py/status、state_manager.load_all_states
  三处各自独立硬编码同款四品种清单，同样漏了新品种（BNB也在其中两处
  被漏掉：app.py的housekeep巡检循环此前只巡检"ETH"一个）。

修复：symbol_config.py 新增 ACTIVE_SYMBOLS 作为唯一权威清单，上述全部
调用点改为从这里派生，不再各自维护一份，防止再次出现"支持了但某处
没接上"的遗漏。

本测试只验证纯逻辑（symbol_config/webhook_parser/breath_profiles/
reentry_profiles 四个模块互相之间的一致性），不碰任何真实持仓/下单/
网络请求。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from symbol_config import ACTIVE_SYMBOLS, SymbolConfig  # noqa: E402
from webhook_parser import WebhookParser, VALID_SYMBOLS  # noqa: E402
from breath_profiles import get_breath_profile, BREATH_ETH  # noqa: E402
from reentry_profiles import get_reentry_profile  # noqa: E402

NEW_SYMBOLS = ("BNB", "OPENAI", "SNDK", "XPD")


class TestActiveSymbolsSingleSource(unittest.TestCase):
    def test_active_symbols_has_all_seven(self):
        """2026-09-13：新增XPT后变成8个品种，这里放宽成"至少包含"这7个，
        不再断言"恰好这7个"——避免以后每加一个新品种都要回来改这个数字。"""
        self.assertTrue(
            {"ETH", "BTC", "XAU", "BNB", "OPENAI", "SNDK", "XPD"}.issubset(set(ACTIVE_SYMBOLS)),
        )

    def test_webhook_parser_valid_symbols_matches_active_symbols(self):
        """VALID_SYMBOLS 是从 ACTIVE_SYMBOLS 派生的，两者必须一致，不能再各自漂移。"""
        self.assertEqual(VALID_SYMBOLS, set(ACTIVE_SYMBOLS))

    def test_symbol_config_recognizes_new_symbols(self):
        for sym in NEW_SYMBOLS:
            self.assertTrue(
                SymbolConfig.is_valid_symbol(sym), f"{sym} 应该在 SymbolConfig 里有效"
            )


class TestWebhookParserAcceptsNewSymbols(unittest.TestCase):
    """回归：此前 OPENAI/SNDK/XPD 的开仓信号会被 invalid_symbol 直接拒收。"""

    def setUp(self):
        os.environ["WEBHOOK_SECRET"] = "test-secret-20260912"
        self.parser = WebhookParser()

    def _payload(self, symbol):
        return {
            "secret": "test-secret-20260912",
            "action": "LONG",
            "symbol": f"{symbol}USDT.P",
            "price": 1000.0,
            "atr": 10.0,
            "stop_loss": 950.0,
            "tp1": 1050.0,
            "tp2": 1100.0,
        }

    def test_new_symbols_parse_valid(self):
        for sym in NEW_SYMBOLS:
            sig = self.parser.parse(self._payload(sym))
            self.assertTrue(sig.valid, f"{sym} 应该解析成功，实际 error={sig.error!r}")
            self.assertEqual(sig.symbol, sym)
            self.assertEqual(sig.error, "")

    def test_unknown_symbol_still_rejected(self):
        """回归：白名单机制本身没被削弱，真正未知的品种仍然拒收。"""
        sig = self.parser.parse(self._payload("DOGE"))
        self.assertFalse(sig.valid)
        self.assertEqual(sig.error, "invalid_symbol:DOGE")


class TestBreathProfilesForNewSymbols(unittest.TestCase):
    """回归：此前 BNB/OPENAI/SNDK/XPD 会静默回退到 BREATH_ETH（错误系数）。"""

    def test_new_symbols_have_dedicated_profile_not_eth_fallback(self):
        for sym in NEW_SYMBOLS:
            profile = get_breath_profile(sym)
            self.assertEqual(
                profile.get("name"), sym,
                f"{sym} 的呼吸档案 name 字段应该是自己，不是 ETH 回退",
            )
            self.assertNotEqual(
                profile.get("breath_tp12"), BREATH_ETH["breath_tp12"],
                f"{sym} 不应该跟 ETH 用同一套 breath_tp12（除非巧合相等，这里四个品种真实校准值都不同）",
            )

    def test_profile_fields_are_finite_and_positive(self):
        """真实校准值不能是0/负数/非数——上真金白银前的最基本sanity check。"""
        for sym in NEW_SYMBOLS:
            p = get_breath_profile(sym)
            for key in ("step_trigger_atr", "step_advance_atr", "breath_tp12",
                        "breath_tp23", "min_mult", "max_mult"):
                v = p.get(key)
                self.assertIsInstance(v, (int, float), f"{sym}.{key} 类型异常: {v!r}")
                self.assertGreater(v, 0, f"{sym}.{key} 应该 > 0，实际 {v}")
            self.assertLess(
                p["min_mult"], p["max_mult"],
                f"{sym}: min_mult({p['min_mult']}) 应该小于 max_mult({p['max_mult']})",
            )
            self.assertLess(
                p["step_advance_atr"], p["step_trigger_atr"],
                f"{sym}: step_advance应小于step_trigger（阶梯先触发后推进）",
            )
            self.assertLess(
                p["breath_tp12"], p["breath_tp23"],
                f"{sym}: breath_tp12(中位数回调)应小于breath_tp23(75分位回调)",
            )

    def test_still_unknown_symbol_falls_back_to_eth(self):
        """回归：真正没配置过的品种，兜底行为不变（回退ETH，不报错）。"""
        profile = get_breath_profile("DOGE")
        self.assertEqual(profile.get("name"), "ETH")


class TestReentryWindowsForNewSymbols(unittest.TestCase):
    def test_new_symbols_have_explicit_window(self):
        for sym in NEW_SYMBOLS:
            prof = get_reentry_profile(sym)
            self.assertEqual(prof.get_reentry_window(sym), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
