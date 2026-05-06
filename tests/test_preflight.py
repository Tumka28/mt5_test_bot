"""Preflight check скриптийн тест."""
from __future__ import annotations

import os

import pytest

from scripts.preflight import check


def test_paper_mode_no_env_vars_passes(monkeypatch):
    for k in ("MT5BOT_HMAC", "MT5BOT_STRICT", "MT5BOT_HELLO_TOKEN",
              "MT5BOT_ALLOWED_LOGINS", "MT5BOT_I_KNOW_THIS_IS_REAL_MONEY"):
        monkeypatch.delenv(k, raising=False)
    errors, _ = check("paper")
    assert errors == [], f"unexpected: {errors}"


def test_live_mode_without_confirm_errors(monkeypatch):
    for k in ("MT5BOT_HMAC", "MT5BOT_STRICT", "MT5BOT_HELLO_TOKEN",
              "MT5BOT_ALLOWED_LOGINS", "MT5BOT_I_KNOW_THIS_IS_REAL_MONEY"):
        monkeypatch.delenv(k, raising=False)
    errors, _ = check("live")
    msgs = " ".join(errors)
    assert "MT5BOT_HMAC" in msgs
    assert "MT5BOT_I_KNOW_THIS_IS_REAL_MONEY" in msgs
    assert "MT5BOT_HELLO_TOKEN" in msgs
    assert "MT5BOT_ALLOWED_LOGINS" in msgs


def test_live_mode_full_env_passes(monkeypatch):
    monkeypatch.setenv("MT5BOT_HMAC", "this-is-a-real-secret-1234")
    monkeypatch.setenv("MT5BOT_STRICT", "1")
    monkeypatch.setenv("MT5BOT_HELLO_TOKEN", "abcdef0123456789abcdef")
    monkeypatch.setenv("MT5BOT_ALLOWED_LOGINS", "12345,67890")
    monkeypatch.setenv("MT5BOT_I_KNOW_THIS_IS_REAL_MONEY", "yes")
    errors, _ = check("live")
    assert errors == [], f"unexpected: {errors}"


def test_shadow_mode_without_hmac_errors(monkeypatch):
    monkeypatch.delenv("MT5BOT_HMAC", raising=False)
    errors, _ = check("shadow")
    assert any("MT5BOT_HMAC" in e for e in errors)


def test_short_token_errors_in_live(monkeypatch):
    monkeypatch.setenv("MT5BOT_HMAC", "this-is-a-real-secret-1234")
    monkeypatch.setenv("MT5BOT_HELLO_TOKEN", "tooShort")  # < 16 chars
    monkeypatch.setenv("MT5BOT_ALLOWED_LOGINS", "12345")
    monkeypatch.setenv("MT5BOT_I_KNOW_THIS_IS_REAL_MONEY", "yes")
    errors, _ = check("live")
    assert any("MT5BOT_HELLO_TOKEN" in e for e in errors)
