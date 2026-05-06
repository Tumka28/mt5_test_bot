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

## Quick start (1 script)

**Windows:**
```bat
:: First run does setup + paper mode automatically
start.bat

:: Subcommands
start.bat install-ea         REM bridge_ea.mq5-ыг MT5 MQL5\Experts хавтсанд хуулна
start.bat preflight          REM config + env шалгана
start.bat test               REM бүх pytest
start.bat e2e                REM end-to-end smoke (fake EA ↔ brain)
start.bat live --lots 0.01   REM real money (env var-ууд тохируулсан байх ёстой)
```

**Linux/WSL:**
```bash
./start.sh                   # paper mode
./start.sh install-ea --mt5-data-path "/mnt/c/.../MQL5"
./start.sh test
./start.sh live --lots 0.01
```

**Гар ажиллуулах (хэрвээ wrapper-уудыг алгасах бол):**
```bash
python run.py setup          # venv + deps
python run.py install-ea     # EA-г MT5 руу хуулна
python run.py preflight --mode paper
python run.py test
python run.py paper --symbol EURUSD --lots 0.01
python run.py live --symbol EURUSD --lots 0.01     # env var заавал
```

**Live горимд env var-ууд (`MT5BOT_*`) заавал:**
```
MT5BOT_HMAC=<≥32 char hex>            # bridge layer secret
MT5BOT_HELLO_TOKEN=<≥16 char hex>     # EA-ийн HelloToken-той ижил
MT5BOT_ALLOWED_LOGINS=12345,67890     # MT5 account login allow-list
MT5BOT_STRICT=1                       # secret default-уудыг таслана
MT5BOT_I_KNOW_THIS_IS_REAL_MONEY=yes  # confirm
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
