# CoinW 单系统 (eth-webhook-server CoinW版)

**当前版本: `v16.22.1-coinw-init`**
**TV策略schema: `v6.5.6`** (与币安系统兼容)

---

## 概述

CoinW单系统是币安单账户系统的CoinW交易所复刻版本，保持与原系统相同的架构和交易逻辑。

### 核心功能
- 三层防线: 永久硬止损 + TP1/TP2限价止盈 + 雷达呼吸止损
- TP分腿: 10% / 20% / 70%
- 雷达追踪: TP2成交后激活，保本起步阶梯跟随
- 流水线状态机: 9阶段管控
- 防叠单机制: 幂等铁律

### 支持品种
- ETHUSDT
- BTCUSDT
- XAUUSDT
- BNBUSDT

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
# 创建.env文件
cat > .env << EOF
COINW_API_KEY=your_api_key
COINW_API_SECRET=your_api_secret
WEBHOOK_SECRET=your_webhook_secret
PORT=5004
TELEGRAM_BOT_TOKEN=your_telegram_token
TELEGRAM_CHAT_ID=your_chat_id
EOF
```

### 3. 启动服务

```bash
python app.py
```

### 4. 验证

```bash
# 健康检查
curl http://127.0.0.1:5004/health

# 启动日志
python app.py
```

---

## Webhook格式

```json
{
  "action": "LONG",
  "symbol": "ETH",
  "price": 1930.49,
  "atr": 14.5,
  "stop_loss": 1916.75,
  "tp1": 1953.51,
  "tp2": 1971.50,
  "tp3": 1988.71,
  "tier": "1",
  "leverage": 20,
  "secret": "your_secret"
}
```

### 有效action
- `LONG` - 开多
- `SHORT` - 开空
- `CLOSE` - 平仓
- `CLOSE_QUICK_EXIT` - 快速平仓
- `CLOSE_RSI_EXIT` - RSI平仓
- `PING` - 心跳

---

## API端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/webhook` | POST | TradingView Webhook |
| `/health` | GET | 健康检查 |
| `/console` | GET | 管理界面 |
| `/admin/pause` | POST | 暂停交易 |
| `/admin/resume` | POST | 恢复交易 |
| `/admin/clear/<symbol>` | POST | 清仓指定品种 |

---

## 三层防线

### 1. 硬止损
- 公式: `|TV价 - stop_loss| × 1.15`
- 挂在成交价外侧
- 仓位归零前永不撤销

### 2. TP止盈 (TP1/TP2)
- TP1: 10%仓位
- TP2: 20%仓位
- TP3 (70%): 交给雷达管理

### 3. 雷达止损
- 激活条件: TP2成交 + 现价达到TP2水平
- 保本起步
- 阶梯跟随 + 动态追踪

---

## 架构

```
TV Webhook
    │
    ▼
app.py (Flask)
    │
    ▼
position_supervisor_coinw.py (唯一大脑)
    ├── pipeline_ledger.py (状态机)
    ├── chief_auditor.py (督察官)
    ├── coinw_client.py (API客户端)
    └── breath_stop.py (雷达引擎)
```

---

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `COINW_API_KEY` | - | API密钥 |
| `COINW_API_SECRET` | - | API密钥 |
| `WEBHOOK_SECRET` | - | Webhook密钥 |
| `PORT` | 5004 | 服务端口 |
| `PIPELINE_SOFT_GATES` | 1 | 软闸门 |
| `PIPELINE_AUDITOR_HARD_PAUSE` | 1 | 督察硬暂停 |
| `API_BUDGET_PER_MIN` | 48 | API预算/分钟 |
| `REST_MIN_INTERVAL_SEC` | 2.0 | REST最小间隔 |
| `HARD_STOP_BUFFER` | 1.15 | 硬止损呼吸垫 |
| `TELEGRAM_BOT_TOKEN` | - | Telegram机器人 |
| `TELEGRAM_CHAT_ID` | - | Telegram聊天ID |
| `DINGTALK_WEBHOOK` | - | 钉钉Webhook |
| `DINGTALK_DISABLE` | True | 禁用钉钉 |

---

## 文件结构

```
coinw-hft-server/
├── app.py                          # Flask入口
├── coinw_client.py                 # API客户端
├── position_supervisor_coinw.py    # 主大脑
├── pipeline_ledger.py             # 状态机
├── pipeline_bridge.py             # 岗位交接
├── chief_auditor.py               # 督察官
├── api_throttle.py                 # 限流阀
├── tv_seq.py                       # 信号序
├── webhook_parser.py               # Webhook解析
├── atr_scenario.py                 # 硬止损公式
├── breath_profiles.py             # 呼吸参数
├── breath_stop.py                 # 雷达引擎
├── radar_reentry_mixin.py         # 雷达+再入
├── smart_reentry_engine.py        # 再入决策
├── reentry_profiles.py            # 再入配置
├── order_idempotency.py           # 幂等控制
├── risk_manager.py                # 风险管理
├── defense_profiles.py            # 防御参数
├── symbol_config.py               # 品种配置
├── dingtalk.py                    # 通知
├── console_api.py                 # Console API
├── state_manager.py               # 状态持久化
├── check_vps_logic.py            # 静态检查
├── requirements.txt               # 依赖
├── config/
│   └── reentry_tiers.json        # 再入配置
└── coinw-engine.service          # systemd服务
```

---

## 与币安系统对比

| 功能 | 币安 | CoinW |
|------|------|-------|
| 方向 | BUY/SELL | long/short |
| Symbol | ETHUSDT | ETH |
| 止损止盈 | STOP_MARKET | TPSL接口 |
| 市价单 | MARKET | execute |
| 限价单 | LIMIT | plan |
| 幂等键 | newClientOrderId | thirdOrderId |
| WebSocket | wss://fstream.binance.com | wss://ws.futurescw.com/perpum |

---

## License

MIT
