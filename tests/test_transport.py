"""HMAC + msgpack roundtrip тест."""
from __future__ import annotations

import os

import pytest

from bridge.transport import decode, encode


def test_roundtrip():
    os.environ["MT5BOT_HMAC"] = "test-secret"
    payload = {"type": "tick", "symbol": "EURUSD", "bid": 1.1, "ask": 1.10001, "ts_ms": 1}
    frame = encode(payload)
    out = decode(frame)
    assert out == payload


def test_tampered_frame_rejected():
    os.environ["MT5BOT_HMAC"] = "test-secret"
    frame = bytearray(encode({"x": 1}))
    frame[-1] ^= 0xFF  # flip a bit in the body
    with pytest.raises(ValueError, match="hmac mismatch"):
        decode(bytes(frame))


def test_short_frame_rejected():
    with pytest.raises(ValueError):
        decode(b"\x00" * 10)


def test_secret_mismatch_rejected():
    os.environ["MT5BOT_HMAC"] = "secret-A"
    frame = encode({"x": 1})
    os.environ["MT5BOT_HMAC"] = "secret-B"
    with pytest.raises(ValueError):
        decode(frame)
