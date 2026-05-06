"""Pre-flight check — live эхлэхийн өмнө config + env-ийг шалгана.

Зорилго: алдаатай тохиргоотой live горим яаралтай эхлэхээс сэргийлэх. Ангилал:
  ERROR — заавал зассан үгүй бол run_trading.py зогсоно
  WARN  — олдвор тэмдэглэнэ, стартыг саатуулахгүй

Usage:
    python scripts/preflight.py --mode paper
    python scripts/preflight.py --mode live --strict   # exit 1 on any WARN
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # type: ignore

from bridge.transport import is_dev_secret
from observability.logger import configure


_REQUIRED_RISK_KEYS = (
    "max_risk_per_trade", "max_daily_loss", "max_weekly_loss",
    "max_open_positions", "require_stop_loss",
)


def check(mode: str) -> tuple[list[str], list[str]]:
    """Returns (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []

    # 1. config.yaml байгаа эсэх
    cfg_path = ROOT / "config" / "config.yaml"
    if not cfg_path.exists():
        errors.append(f"config missing: {cfg_path}")
        return errors, warnings
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))

    # 2. risk keys
    risk = cfg.get("risk", {})
    for k in _REQUIRED_RISK_KEYS:
        if k not in risk:
            errors.append(f"config.risk.{k} missing")
    if risk.get("require_stop_loss") is not True:
        errors.append("config.risk.require_stop_loss must be true (хэзээ ч өөрчилж болохгүй)")
    if float(risk.get("max_risk_per_trade", 0)) > 0.01:
        warnings.append(
            f"max_risk_per_trade={risk.get('max_risk_per_trade')} > 1% — risky for live"
        )
    if float(risk.get("max_daily_loss", 0)) > 0.05:
        warnings.append(
            f"max_daily_loss={risk.get('max_daily_loss')} > 5% — high"
        )

    # 3. journal path writable
    journal_dir = (ROOT / cfg.get("journal", {}).get("sqlite_path", "data/journal.sqlite")).parent
    if not journal_dir.exists():
        try:
            journal_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            errors.append(f"journal dir not writable: {journal_dir} ({e})")

    # 4. HMAC env var (live/shadow-д)
    if mode in ("shadow", "live"):
        if is_dev_secret():
            errors.append("MT5BOT_HMAC env var заавал шинэ secret-аар тохируулах шаардлагатай")
        if os.environ.get("MT5BOT_STRICT", "") not in ("1", "true", "yes"):
            warnings.append("MT5BOT_STRICT=1 тохируулах нь HMAC default-ыг таслана")

    # 5. Live mode-д explicit confirm
    if mode == "live":
        if os.environ.get("MT5BOT_I_KNOW_THIS_IS_REAL_MONEY", "") != "yes":
            errors.append(
                "MT5BOT_I_KNOW_THIS_IS_REAL_MONEY=yes env var required to start live mode"
            )
        token = os.environ.get("MT5BOT_HELLO_TOKEN", "")
        if not token or len(token) < 16:
            errors.append("MT5BOT_HELLO_TOKEN ≥16 char заавал live mode-д")
        if not os.environ.get("MT5BOT_ALLOWED_LOGINS", ""):
            errors.append("MT5BOT_ALLOWED_LOGINS=12345,67890 заавал live mode-д")

    # 6. Symbols.yaml
    syms_path = ROOT / "config" / "symbols.yaml"
    if not syms_path.exists():
        errors.append(f"symbols config missing: {syms_path}")

    return errors, warnings


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["paper", "shadow", "live"], default="paper")
    p.add_argument("--strict", action="store_true",
                   help="warning байвал exit 1")
    args = p.parse_args()

    configure(level="INFO", json=False)
    log = logging.getLogger("preflight")

    errors, warnings = check(args.mode)

    for w in warnings:
        log.warning("WARN: %s", w)
    for e in errors:
        log.error("ERROR: %s", e)

    if errors:
        log.error("PREFLIGHT FAILED — %d error(s)", len(errors))
        return 1
    if warnings and args.strict:
        log.error("PREFLIGHT WARN (strict mode) — %d warning(s)", len(warnings))
        return 1
    log.info("PREFLIGHT OK — mode=%s (warnings=%d)", args.mode, len(warnings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
