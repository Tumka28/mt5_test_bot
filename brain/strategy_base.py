"""Strategy interface — энгийн callback-base.

Шинэ стратеги бичихдээ `Strategy`-аас удамшуулан `on_tick` / `on_bar` дотроос
`OrderIntent` буцаана. Risk Manager бүгдийг шалгана.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from brain.types import OrderIntent, Tick


class Strategy(ABC):
    name: str = "base"

    @abstractmethod
    def on_tick(self, tick: Tick) -> list[OrderIntent]:
        ...

    def on_bar(self, symbol: str, ohlc: dict) -> list[OrderIntent]:  # noqa: D401
        return []


class NoopStrategy(Strategy):
    """Огт trade хийдэггүй стратеги — pipeline-ыг wiring-аар тестлэхэд."""
    name = "noop"

    def on_tick(self, tick: Tick) -> list[OrderIntent]:
        return []
