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

# 2. dependencies
pip install -r requirements.txt

# 3. smoke tests (no MT5 required)
pytest tests/ -v

# 4. (Windows-д MT5 терминал ажиллаж байх үед)
python scripts/run_gateway.py     # MT5 → ZMQ publisher
python scripts/run_brain.py       # Strategy + Risk + Dispatcher
```

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
