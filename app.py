#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Flask Webhook入口 - CoinW单系统 v16.22.1
"""

import os
import sys
import json
import time
import logging
import threading
from flask import Flask, request, jsonify

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(__file__))

# 版本
COINW_WEBHOOK_VERSION = "v16.22.1-coinw-init"

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] app: %(message)s'
)
logger = logging.getLogger(__name__)

# Flask应用
app = Flask(__name__)

# 端口
PORT = int(os.getenv("PORT", "5004"))

# Supervisor实例缓存
_supervisors = {}
_supervisor_lock = threading.Lock()


def get_supervisor(symbol: str = "ETH"):
    """获取Supervisor实例"""
    sym = str(symbol or "ETH").upper()

    with _supervisor_lock:
        if sym not in _supervisors:
            from position_supervisor_coinw import PositionSupervisorCoinW
            _supervisors[sym] = PositionSupervisorCoinW(sym)
        return _supervisors[sym]


# ==================== Webhook路由 ====================

@app.route('/webhook', methods=['POST'])
def webhook():
    """TV Webhook入口"""
    # 1) 解析JSON
    data = request.get_json(force=True, silent=True)
    if not data:
        try:
            raw_data = request.get_data(as_text=True)
            data = json.loads(raw_data)
        except Exception:
            return jsonify({"status": "error", "message": "无效的JSON数据"}), 400

    # 2) 验证secret
    from webhook_parser import parse_webhook
    signal = parse_webhook(data)

    if not signal.valid:
        logger.warning(f"Webhook鉴权失败: {signal.error}")
        return jsonify({"status": "error", "message": "Invalid secret"}), 403

    logger.info(f"Webhook收到信号: {signal.action} {signal.symbol}")

    # 3) 获取对应的Supervisor
    supervisor = get_supervisor(signal.symbol)

    # 4) 异步处理
    def process():
        try:
            result = supervisor.handle_signal(data)
            logger.info(f"信号处理完成: {result}")
        except Exception as e:
            logger.error(f"信号处理异常: {e}")

    threading.Thread(target=process, daemon=True).start()

    return jsonify({
        "status": "success",
        "message": "Signal processing started",
        "version": COINW_WEBHOOK_VERSION,
    }), 200


# ==================== 健康检查 ====================

@app.route('/health', methods=['GET'])
def health():
    """健康检查"""
    from position_supervisor_coinw import COINW_SUPERVISOR_VERSION, trading_paused
    from pipeline_ledger import get_pipeline

    from pipeline_ledger import Phase

    symbols = ["ETH", "BTC", "XAU", "BNB"]
    pipelines = {}

    for sym in symbols:
        p = get_pipeline(sym, "coinw")
        pipelines[sym] = p.phase.value

    # 部署安全阀：任一品种的pipeline阶段不在IDLE/MONITORING/FAILED这三个
    # "静息"态时不应重启——中间那几个阶段(SIGNAL_RECEIVED~REPORTED)代表
    # 信号正在处理中(市价单可能已成交但仓位查询/防线绑定尚未走完)，重启
    # 会撞上这个窗口，把仓位打成孤儿仓。跟binance/deepcoin的_open_in_progress
    # 同一个用途，coinw这边直接复用已有的pipeline状态机，不用额外加字段
    # （对齐binance f162ede）。
    _RESTING_PHASES = {Phase.IDLE, Phase.MONITORING, Phase.FAILED}
    in_progress = {
        sym: (phase_val not in {p.value for p in _RESTING_PHASES})
        for sym, phase_val in pipelines.items()
    }

    return jsonify({
        "version": COINW_WEBHOOK_VERSION,
        "supervisor_version": COINW_SUPERVISOR_VERSION,
        "trading_paused": trading_paused,
        "pipelines": pipelines,
        "open_in_progress": in_progress,
        "deploy_safe": not any(in_progress.values()),
        "uptime": time.time(),
    })


# ==================== 管理接口 ====================

@app.route('/admin/pause', methods=['POST'])
def admin_pause():
    """暂停交易"""
    from position_supervisor_coinw import pause_all_trading

    payload = request.get_json() or {}
    reason = payload.get("reason", "管理员暂停")

    pause_all_trading(reason)
    return jsonify({"ok": True, "trading_paused": True})


@app.route('/admin/resume', methods=['POST'])
def admin_resume():
    """恢复交易"""
    from position_supervisor_coinw import resume_all_trading

    resume_all_trading()
    return jsonify({"ok": True, "trading_paused": False})


@app.route('/admin/clear/<symbol>', methods=['POST'])
def admin_clear(symbol):
    """清仓指定品种（并临时冻结心跳催单，避免刚清就被补开）"""
    supervisor = get_supervisor(symbol)

    def clear():
        supervisor._intentional_close = True   # 手动清仓：不触发再入/冷却
        supervisor._cooldown_until = 0.0
        supervisor._stop_monitoring()
        supervisor._clear_position("管理员清仓")
        supervisor.pipeline.reset_idle("admin_clear")
        try:
            from position_supervisor_coinw import block_catchup
            block_catchup(symbol)
        except Exception:
            pass

    threading.Thread(target=clear, daemon=True).start()

    return jsonify({"ok": True, "symbol": symbol})


@app.route('/admin/abort_catchup', methods=['POST'])
def admin_abort_catchup():
    """人工中止心跳催单：一段时间内心跳不再把该品种补开。"""
    payload = request.get_json(silent=True) or {}
    symbol = payload.get("symbol", "ETH")
    seconds = payload.get("seconds")
    from position_supervisor_coinw import block_catchup
    until = block_catchup(symbol, float(seconds) if seconds else None)
    return jsonify({"ok": True, "symbol": symbol, "blocked_until": until})


@app.route('/admin/confirm_catchup', methods=['POST'])
def admin_confirm_catchup():
    """人工确认追单：下一次合格心跳立即补开。"""
    symbol = (request.get_json(silent=True) or {}).get("symbol", "ETH")
    from position_supervisor_coinw import confirm_catchup
    confirm_catchup(symbol)
    return jsonify({"ok": True, "symbol": symbol, "confirmed": True})


@app.route('/admin/cancel_chase_watch', methods=['POST'])
def admin_cancel_chase_watch():
    """人工中止追单确认观察窗。"""
    symbol = (request.get_json(silent=True) or {}).get("symbol", "ETH")
    from position_supervisor_coinw import cancel_chase_watch
    until = cancel_chase_watch(symbol)
    return jsonify({"ok": True, "symbol": symbol, "blocked_until": until})


# ==================== Console管理页 ====================

@app.route('/console', methods=['GET'])
def console_index():
    """Console管理页"""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>CoinW Console</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; }
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                min-height: 100vh;
                color: #fff;
                padding: 20px;
            }
            .container { max-width: 1200px; margin: 0 auto; }
            h1 { font-size: 2em; margin-bottom: 20px; color: #00d4ff; }
            .card {
                background: rgba(255,255,255,0.1);
                border-radius: 12px;
                padding: 20px;
                margin-bottom: 20px;
                backdrop-filter: blur(10px);
            }
            .card h2 { font-size: 1.2em; margin-bottom: 15px; color: #00d4ff; }
            .status-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; }
            .status-item {
                background: rgba(0,0,0,0.3);
                border-radius: 8px;
                padding: 15px;
            }
            .status-item .label { font-size: 0.8em; color: #888; margin-bottom: 5px; }
            .status-item .value { font-size: 1.2em; font-weight: bold; }
            .btn {
                background: #00d4ff;
                color: #000;
                border: none;
                padding: 10px 20px;
                border-radius: 8px;
                cursor: pointer;
                font-weight: bold;
            }
            .btn:hover { background: #00b8e6; }
            .btn.danger { background: #ff4757; color: #fff; }
            .btn.success { background: #2ed573; }
            table { width: 100%; border-collapse: collapse; }
            th, td { padding: 10px; text-align: left; border-bottom: 1px solid rgba(255,255,255,0.1); }
            th { color: #00d4ff; }
            .phase { padding: 4px 8px; border-radius: 4px; }
            .phase.IDLE { background: #666; }
            .phase.MONITORING { background: #2ed573; }
            .phase.FAILED { background: #ff4757; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>CoinW Console v""" + COINW_WEBHOOK_VERSION + """</h1>

            <div class="card">
                <h2>系统状态</h2>
                <div class="status-grid">
                    <div class="status-item">
                        <div class="label">版本</div>
                        <div class="value" id="version">""" + COINW_WEBHOOK_VERSION + """</div>
                    </div>
                    <div class="status-item">
                        <div class="label">交易状态</div>
                        <div class="value" id="paused">检查中...</div>
                    </div>
                </div>
            </div>

            <div class="card">
                <h2>流水线状态</h2>
                <table>
                    <thead>
                        <tr>
                            <th>品种</th>
                            <th>阶段</th>
                            <th>方向</th>
                            <th>数量</th>
                            <th>开仓价</th>
                            <th>操作</th>
                        </tr>
                    </thead>
                    <tbody id="pipelines">
                    </tbody>
                </table>
            </div>

            <div class="card">
                <h2>控制</h2>
                <button class="btn" onclick="pauseAll()">暂停交易</button>
                <button class="btn success" onclick="resumeAll()">恢复交易</button>
            </div>
        </div>

        <script>
            async function loadStatus() {
                const resp = await fetch('/console/status');
                const data = await resp.json();

                document.getElementById('version').textContent = data.version;
                document.getElementById('paused').textContent = data.trading_paused ? '已暂停' : '交易中';
                document.getElementById('paused').style.color = data.trading_paused ? '#ff4757' : '#2ed573';

                const tbody = document.getElementById('pipelines');
                tbody.innerHTML = '';
                for (const [sym, p] of Object.entries(data.pipelines)) {
                    tbody.innerHTML += `
                        <tr>
                            <td>${sym}</td>
                            <td><span class="phase ${p.phase}">${p.phase}</span></td>
                            <td>${p.side || '-'}</td>
                            <td>${p.qty || '-'}</td>
                            <td>${p.entry || '-'}</td>
                            <td><button class="btn danger" onclick="clearPos('${sym}')">清仓</button></td>
                        </tr>
                    `;
                }
            }

            async function pauseAll() {
                await fetch('/admin/pause', {method: 'POST'});
                loadStatus();
            }

            async function resumeAll() {
                await fetch('/admin/resume', {method: 'POST'});
                loadStatus();
            }

            async function clearPos(sym) {
                if (confirm('确定要清仓 ' + sym + ' 吗？')) {
                    await fetch('/admin/clear/' + sym, {method: 'POST'});
                    loadStatus();
                }
            }

            loadStatus();
            setInterval(loadStatus, 5000);
        </script>
    </body>
    </html>
    """
    return html, 200, {'Content-Type': 'text/html; charset=utf-8'}


# ==================== 影子竞赛（TV 实盘 vs VPS 自主指标） ====================

@app.route('/contest', methods=['GET'])
def contest_json():
    try:
        import shadow_contest
        return jsonify(shadow_contest.snapshot())
    except Exception as e:
        logger.error(f"contest_json 失败: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/contest/view', methods=['GET'])
def contest_view():
    try:
        import shadow_contest
        from contest_dashboard import DASHBOARD_HTML
        boot = json.dumps(shadow_contest.snapshot(), ensure_ascii=False)
    except Exception as e:
        logger.error(f"contest_view 失败: {e}")
        boot = json.dumps({"error": str(e)})
        from contest_dashboard import DASHBOARD_HTML
    html = DASHBOARD_HTML.replace("__BOOT__", boot)
    return html, 200, {'Content-Type': 'text/html; charset=utf-8'}


_contest_started = False
_contest_lock = threading.Lock()


def _start_contest_loop():
    """后台线程：每 60s 跑一次影子竞赛单步。纯模拟，不下单。"""
    global _contest_started
    with _contest_lock:
        if _contest_started:
            return
        if os.getenv("CONTEST_ENABLED", "1") not in ("1", "true", "yes"):
            logger.info("影子竞赛已禁用 (CONTEST_ENABLED)")
            return
        _contest_started = True

    def _loop():
        import shadow_contest
        time.sleep(8)  # 等 worker 起稳
        while True:
            try:
                snap = shadow_contest.run_once()
                m = snap.get("shadow", {}).get("metrics", {})
                logger.info(f"[竞赛] 影子 {m.get('n',0)}笔 净{m.get('net',0)}U | "
                            f"TV {snap.get('tv',{}).get('metrics',{}).get('n',0)}笔")
            except Exception as e:
                logger.error(f"[竞赛] run_once 异常: {e}")
            time.sleep(60)

    threading.Thread(target=_loop, daemon=True, name="shadow-contest").start()
    logger.info("影子竞赛后台线程已启动 (60s/次)")


def _start_housekeeping():
    """启动恢复 + 周期巡检（孤儿单清扫 / 无人管持仓兜底）。后台线程。"""
    def _run():
        time.sleep(5)
        try:
            from position_supervisor_coinw import recover_all_on_start
            recover_all_on_start()
        except Exception as e:
            logger.error(f"启动恢复异常: {e}")
        from position_supervisor_coinw import housekeep, HOUSEKEEP_SEC
        while True:
            time.sleep(HOUSEKEEP_SEC)
            try:
                housekeep("ETH")
            except Exception as e:
                logger.error(f"housekeep 异常: {e}")
    threading.Thread(target=_run, daemon=True, name="coinw-housekeeping").start()


# gunicorn 导入即启动
_start_contest_loop()
_start_housekeeping()


# ==================== 启动 ====================

if __name__ == '__main__':
    logger.info(f"CoinW Webhook Server {COINW_WEBHOOK_VERSION} 启动")
    logger.info(f"端口: {PORT}")
    logger.info(f"Webhook: http://0.0.0.0:{PORT}/webhook")
    logger.info(f"Console: http://0.0.0.0:{PORT}/console")
    logger.info(f"Health: http://0.0.0.0:{PORT}/health")

    app.run(host='0.0.0.0', port=PORT, debug=False)
