"""ZMQ transport — gateway ↔ brain.

Two sockets:
  PUB/SUB  — gateway publishes ticks/bars/account, brain subscribes
  REQ/REP  — brain sends orders, gateway replies with fill/reject

Wire format: msgpack(payload) + HMAC-SHA256 signature (prepended 32 bytes).
Loopback only, but HMAC catches accidental cross-talk and bit flips.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from dataclasses import dataclass
from typing import Any

import msgpack

# zmq is imported lazily inside Publisher/Subscriber so unit tests for
# encode/decode don't require the native pyzmq build.


def _hmac_secret() -> bytes:
    secret = os.environ.get("MT5BOT_HMAC", "")
    if not secret:
        # Dev default — replace in prod via env var.
        secret = "dev-only-change-me"
    return secret.encode("utf-8")


def encode(payload: dict) -> bytes:
    body = msgpack.packb(payload, use_bin_type=True)
    sig = hmac.new(_hmac_secret(), body, hashlib.sha256).digest()
    return sig + body


def decode(frame: bytes) -> dict:
    if len(frame) < 32:
        raise ValueError("frame too short")
    sig, body = frame[:32], frame[32:]
    expected = hmac.new(_hmac_secret(), body, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        raise ValueError("hmac mismatch")
    return msgpack.unpackb(body, raw=False)


@dataclass
class TickMessage:
    """Single quote update from MT5."""
    symbol: str
    bid: float
    ask: float
    ts_ms: int           # broker timestamp, milliseconds since epoch
    volume: int = 0

    def to_dict(self) -> dict:
        return {
            "type": "tick", "symbol": self.symbol,
            "bid": self.bid, "ask": self.ask,
            "ts_ms": self.ts_ms, "volume": self.volume,
        }


@dataclass
class HeartbeatMessage:
    ts_ms: int
    source: str          # "gateway" | "brain"

    def to_dict(self) -> dict:
        return {"type": "heartbeat", "ts_ms": self.ts_ms, "source": self.source}


class Publisher:
    """PUB socket — gateway side."""

    def __init__(self, url: str):
        import zmq  # noqa: PLC0415  (lazy — see top-of-file note)
        self._ctx = zmq.Context.instance()
        self._sock = self._ctx.socket(zmq.PUB)
        self._sock.bind(url)
        # Drop messages if subscriber slow rather than queueing forever.
        self._sock.setsockopt(zmq.SNDHWM, 10_000)

    def send(self, payload: dict) -> None:
        self._sock.send(encode(payload))

    def close(self) -> None:
        self._sock.close(linger=0)


class Subscriber:
    """SUB socket — brain side."""

    def __init__(self, url: str, topics: tuple[str, ...] = ("",)):
        import zmq  # noqa: PLC0415
        self._ctx = zmq.Context.instance()
        self._sock = self._ctx.socket(zmq.SUB)
        self._sock.connect(url)
        for t in topics:
            self._sock.setsockopt_string(zmq.SUBSCRIBE, t)
        self._sock.setsockopt(zmq.RCVHWM, 10_000)

    def recv(self, timeout_ms: int = 1000) -> dict | None:
        if self._sock.poll(timeout_ms) == 0:
            return None
        return decode(self._sock.recv())

    def close(self) -> None:
        self._sock.close(linger=0)


def now_ms() -> int:
    return int(time.time() * 1000)
