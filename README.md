# MT5 Test Bot

Local algo trading stack — MT5 (Windows) + Python brain (WSL/Linux), 100% local.

> **Энэ нь test/research stack.** Real money-д ашиглахын өмнө 5-tier deployment funnel-ыг
> бүрэн дуусгасан байх ёстой (DEV → BACKTEST → PAPER → SHADOW → PROD).

## Архитектур (товч)

```
MT5 Terminal (Win) ─[ZMQ]─► Python Brain (WSL)
   bridge_ea.mq5             ├─ Strategy
   thin EA, exec only        ├─ Risk Manager (hard gate)
                             ├─ Order Dispatcher
                             └─ Persistence (parquet + sqlite + jsonl)

Offline lane:
   Tick Replay Simulator  ──►  Walk-Forward Validator  ──►  Model Registry
                                                            (champion / challenger)
```

Дэлгэрэнгүй: `docs/architecture.md` (хожим нэмэгдэнэ).

## Quick start

```bash
# 1. virtualenv
python -m venv .venv && .venv\Scripts\activate

# 2. dependencies (pinned)
pip install -r requirements.txt

# 3. smoke tests (no MT5 required)
pytest tests/ -v

# 4. preflight check
python scripts/preflight.py --mode paper

# 5. paper mode (демо MT5 акаунт + bridge_ea.mq5 chart-д attached)
python scripts/run_trading.py --symbol EURUSD --mode paper

# 6. live (зөвхөн 4 долоо хоног paper test амжилттай дууссаны дараа!)
export MT5BOT_HMAC=$(openssl rand -hex 32)
export MT5BOT_HELLO_TOKEN=$(openssl rand -hex 16)
export MT5BOT_ALLOWED_LOGINS=12345,67890
export MT5BOT_I_KNOW_THIS_IS_REAL_MONEY=yes
export MT5BOT_STRICT=1
python scripts/run_trading.py --symbol EURUSD --mode live --lots 0.01
```

## Deployment funnel (хатуу мөрдөнө)

| Stage | Account | Code path | Pass criteria |
|-------|---------|-----------|----------------|
| DEV       | none      | unit tests | `pytest` 100% pass |
| BACKTEST  | tick replay | `scripts/run_walk_forward.py` | OOS sharpe > 0.5, max DD < 5% |
| PAPER     | MT5 demo  | `--mode paper` + EA `AllowExecution=true` | 4 долоо хоног, ≥100 trade, journal sane |
| SHADOW    | MT5 live, tiny | `--mode shadow --lots 0.01` (max 0.05) | 1 долоо хоног, fill quality OK, no manual interventions |
| PROD      | MT5 live, real | `--mode live` | гар л switch on |

## Production env vars

```
MT5BOT_HMAC=<≥32 char hex>          # ZMQ leg-д ашиглана; live/shadow-д заавал
MT5BOT_HELLO_TOKEN=<≥16 char hex>   # EA HelloToken-той ижил
MT5BOT_ALLOWED_LOGINS=12345,67890   # MT5 account login allow-list
MT5BOT_STRICT=1                     # secret default-уудаас татгалзана
MT5BOT_I_KNOW_THIS_IS_REAL_MONEY=yes # live mode confirm
```

## Observability

- Prometheus scrape: `http://127.0.0.1:9090/metrics`
- SQLite journal: `data/journal.sqlite` — orders, fills, rejects
- Structured log (JSON-аар тохируулна): `--log-json` (default text)

## Дүрэм

- Strategy Risk Manager-аар **заавал** дамжина. Stop-loss-гүй order reject.
- Live, paper, backtest **нэг л** Risk Manager class ашиглана.
- Champion model-ыг манай гараар л promote хийнэ. Auto-promotion байхгүй.
- VPS-д л prod гүйнэ. Гэрийн машин = dev/research only.

## Layout

```
config/         — yaml configs
bridge/         — MT5 ↔ Python ZMQ transport
brain/          — strategy / risk / dispatcher / service main loop
persistence/    — tick recorder, trade journal
replay/         — tick replay simulator (offline)
observability/  — logger, metrics
tests/          — pytest unit tests
scripts/        — entrypoints
ea/             — MQL5 Expert Advisor source
data/           — runtime data (parquet, sqlite, logs) — git-ignored
```

## License

Private.
