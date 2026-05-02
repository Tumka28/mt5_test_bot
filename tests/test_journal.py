"""Journal smoke test — schema applied, insert/update works."""
from __future__ import annotations

import tempfile
from pathlib import Path

from persistence.journal import Journal


def test_journal_roundtrip(tmp_path: Path):
    j = Journal(tmp_path / "j.sqlite")
    j.record_submission(
        client_order_id="oid1", symbol="EURUSD", side="buy", lots=0.1,
        entry=1.1, stop_loss=1.09, take_profit=None,
        submitted_ts=1, mode="paper",
    )
    assert j.count_orders() == 1
    j.record_fill("oid1", fill_price=1.10010, fill_ts=2)
    j.record_reject("oid1", "test")  # second update — should be idempotent on schema
