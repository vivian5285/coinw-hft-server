#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
静态逻辑检查 - CoinW单系统 v16.22.1

部署前门禁检查
"""

import os
import sys

def check_vps_logic():
    """检查关键逻辑"""
    errors = []
    warnings = []

    # 检查环境变量
    required_vars = ["COINW_API_KEY", "COINW_API_SECRET", "WEBHOOK_SECRET"]
    for var in required_vars:
        if not os.getenv(var):
            warnings.append(f"环境变量 {var} 未设置")

    # 检查核心模块
    modules = [
        "coinw_client",
        "pipeline_ledger",
        "chief_auditor",
        "risk_manager",
        "webhook_parser",
        "defense_profiles",
        "atr_scenario",
        "breath_profiles",
        "breath_stop",
        "radar_reentry_mixin",
        "smart_reentry_engine",
        "order_idempotency",
        "position_supervisor_coinw",
    ]

    for mod in modules:
        try:
            __import__(mod)
        except ImportError as e:
            errors.append(f"模块 {mod} 导入失败: {e}")

    # 输出结果
    if errors:
        print("ERRORS:")
        for e in errors:
            print(f"  - {e}")
        return False

    if warnings:
        print("WARNINGS:")
        for w in warnings:
            print(f"  - {w}")

    print("All checks passed!")
    return True


if __name__ == "__main__":
    success = check_vps_logic()
    sys.exit(0 if success else 1)
