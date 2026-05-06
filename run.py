"""MT5 Test Bot — single-entry launcher.

Usage:
    python run.py setup           # venv + dependencies
    python run.py install-ea      # copy bridge_ea.mq5 to MT5 MQL5/Experts
    python run.py preflight       # validate config + env
    python run.py test            # full pytest suite
    python run.py e2e             # end-to-end smoke (fake EA ↔ brain)
    python run.py paper           # start brain in paper mode
    python run.py shadow          # start brain in shadow mode (real, tiny lots)
    python run.py live            # start brain in LIVE mode (real money)

Examples:
    python run.py paper --symbol EURUSD --lots 0.01
    python run.py live --symbol EURUSD --lots 0.01

Дотроос нь scripts/* модулиудыг дуудна. Энэ файл дангаараа Windows-д ч,
WSL-д ч ажилладаг (.bat / .sh wrapper нь зөвхөн convenience).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


# ─── helpers ──────────────────────────────────────────────────────────


def _venv_python() -> str:
    """Return the python executable path: venv-ийн дотрох эсвэл одоогийнх."""
    if sys.platform == "win32":
        cand = ROOT / ".venv" / "Scripts" / "python.exe"
    else:
        cand = ROOT / ".venv" / "bin" / "python"
    return str(cand) if cand.exists() else sys.executable


def _run(cmd: list[str], **kw) -> int:
    print(">", " ".join(cmd))
    return subprocess.call(cmd, **kw)


# ─── subcommands ──────────────────────────────────────────────────────


def cmd_setup(_: argparse.Namespace) -> int:
    """Create .venv (хэрэв байхгүй бол) + pip install -r requirements.txt."""
    venv_dir = ROOT / ".venv"
    if not venv_dir.exists():
        print(f"creating venv at {venv_dir} ...")
        rc = _run([sys.executable, "-m", "venv", str(venv_dir)])
        if rc != 0:
            return rc
    py = _venv_python()
    rc = _run([py, "-m", "pip", "install", "--upgrade", "pip"])
    if rc != 0:
        return rc
    rc = _run([py, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")])
    if rc != 0:
        return rc
    print("\nsetup OK. дараа нь:  python run.py preflight")
    return 0


def cmd_install_ea(args: argparse.Namespace) -> int:
    """bridge_ea.mq5-ыг MT5-ийн MQL5/Experts хавтсанд хуулна.

    --mt5-data-path PATH   — гар тохируулга, дараах env-аас уншина:
                              MT5_DATA_PATH    (e.g. C:\\Users\\X\\AppData\\Roaming\\MetaQuotes\\Terminal\\<id>\\MQL5)
    Хэрэв байхгүй бол default Windows зам дээр хайна.
    """
    src = ROOT / "ea" / "bridge_ea.mq5"
    if not src.exists():
        print(f"ERROR: source not found: {src}", file=sys.stderr)
        return 1

    dest_root: Path | None = None
    if args.mt5_data_path:
        dest_root = Path(args.mt5_data_path)
    elif os.environ.get("MT5_DATA_PATH"):
        dest_root = Path(os.environ["MT5_DATA_PATH"])
    else:
        # Windows default: AppData\Roaming\MetaQuotes\Terminal\<terminal_id>\MQL5
        if sys.platform == "win32":
            roaming = os.environ.get("APPDATA")
            if roaming:
                meta_root = Path(roaming) / "MetaQuotes" / "Terminal"
                if meta_root.exists():
                    # Choose the most-recently-modified terminal directory
                    candidates = [d for d in meta_root.iterdir() if d.is_dir() and (d / "MQL5").exists()]
                    if candidates:
                        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                        dest_root = candidates[0] / "MQL5"

    if dest_root is None:
        print(
            "ERROR: MT5 data folder not found.\n"
            "  Хэрвээ Windows дээр бол MT5-ийн File → Open Data Folder-аас замыг хуулж\n"
            "  --mt5-data-path \"C:\\Users\\X\\AppData\\Roaming\\MetaQuotes\\Terminal\\<id>\\MQL5\"\n"
            "  гэж дамжуулна.",
            file=sys.stderr,
        )
        return 2

    experts = dest_root / "Experts"
    experts.mkdir(parents=True, exist_ok=True)
    dest = experts / src.name
    shutil.copy2(src, dest)
    print(f"copied: {src}\n     →  {dest}")
    print("\nДараа нь MT5-д:")
    print("  1. F4 → MetaEditor → File → Compile  (эсвэл Navigator-аас зөв click → Refresh)")
    print("  2. Symbol chart-руу EA drag-drop")
    print("  3. Inputs: AllowExecution=false (paper test үед), HelloToken=<env-той ижил>")
    print("  4. Tools → Options → Expert Advisors → Allow algorithmic trading")
    return 0


def cmd_preflight(args: argparse.Namespace) -> int:
    from scripts.preflight import main as preflight_main
    sys.argv = ["preflight", "--mode", args.mode]
    if args.strict:
        sys.argv.append("--strict")
    return preflight_main()


def cmd_test(_: argparse.Namespace) -> int:
    py = _venv_python()
    return _run([py, "-m", "pytest", "tests/", "-v", "--tb=short"])


def cmd_e2e(_: argparse.Namespace) -> int:
    py = _venv_python()
    return _run([py, "-m", "pytest", "tests/test_e2e_smoke.py", "-v", "--tb=short"])


def _trade(mode: str, args: argparse.Namespace) -> int:
    from scripts.run_trading import main as trading_main
    argv = ["run_trading", "--mode", mode, "--symbol", args.symbol,
            "--lots", str(args.lots), "--port", str(args.port),
            "--metrics-port", str(args.metrics_port)]
    if args.fast:
        argv += ["--fast", str(args.fast)]
    if args.slow:
        argv += ["--slow", str(args.slow)]
    if args.news_csv:
        argv += ["--news-csv", args.news_csv]
    if args.max_lots is not None:
        argv += ["--max-lots", str(args.max_lots)]
    if args.skip_preflight:
        argv += ["--skip-preflight"]
    sys.argv = argv
    return trading_main()


def cmd_paper(args: argparse.Namespace) -> int:
    return _trade("paper", args)


def cmd_shadow(args: argparse.Namespace) -> int:
    return _trade("shadow", args)


def cmd_live(args: argparse.Namespace) -> int:
    return _trade("live", args)


# ─── argparse wiring ──────────────────────────────────────────────────


def _add_trade_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--symbol", default="EURUSD")
    p.add_argument("--lots", type=float, default=0.01)
    p.add_argument("--fast", type=int, default=12)
    p.add_argument("--slow", type=int, default=26)
    p.add_argument("--port", type=int, default=5555)
    p.add_argument("--metrics-port", type=int, default=9090)
    p.add_argument("--news-csv", default="")
    p.add_argument("--max-lots", type=float, default=None)
    p.add_argument("--skip-preflight", action="store_true")


def main() -> int:
    p = argparse.ArgumentParser(description="MT5 Test Bot launcher")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("setup", help="venv + pip install -r requirements.txt").set_defaults(func=cmd_setup)

    p_ea = sub.add_parser("install-ea", help="copy bridge_ea.mq5 → MT5 MQL5/Experts")
    p_ea.add_argument("--mt5-data-path", default="")
    p_ea.set_defaults(func=cmd_install_ea)

    p_pf = sub.add_parser("preflight", help="validate config + env")
    p_pf.add_argument("--mode", choices=["paper", "shadow", "live"], default="paper")
    p_pf.add_argument("--strict", action="store_true")
    p_pf.set_defaults(func=cmd_preflight)

    sub.add_parser("test", help="full pytest suite").set_defaults(func=cmd_test)
    sub.add_parser("e2e", help="end-to-end fake-EA smoke test").set_defaults(func=cmd_e2e)

    for name, fn in (("paper", cmd_paper), ("shadow", cmd_shadow), ("live", cmd_live)):
        sp = sub.add_parser(name, help=f"start brain in {name} mode")
        _add_trade_args(sp)
        sp.set_defaults(func=fn)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
