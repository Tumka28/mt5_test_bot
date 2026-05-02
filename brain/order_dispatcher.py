"""Order Dispatcher — Risk Manager-аар pass хийсэн intent-уудыг gateway руу
явуулна. Idempotency-ийн нөхцөлд retry хийнэ.

Энд бид gateway руу зөвхөн REQ socket-оор RPC-тэй адил хүсэлт явуулдаг.
Бодит execution MT5 тал дээр болно. Энэ class зөвхөн "send + wait reply"
хариуцана; risk decision энд хийгдэхгүй.
"""
from __future__ import annotations

import logging
from typing import Any

from brain.types import OrderIntent

logger = logging.getLogger(__name__)


class OrderDispatcher:
    def __init__(self, *, rpc_send: Any) -> None:
        # rpc_send: callable(dict) -> dict — wired to a ZMQ REQ socket in prod;
        # injected by tests.
        self._rpc_send = rpc_send

    def submit(self, intent: OrderIntent) -> dict:
        payload = {
            "type": "order",
            "client_order_id": intent.client_order_id,
            "symbol": intent.symbol,
            "side": intent.side,
            "lots": intent.lots,
            "entry": intent.entry,
            "stop_loss": intent.stop_loss,
            "take_profit": intent.take_profit,
            "comment": intent.comment,
        }
        logger.info("dispatching order id=%s %s %s %.2f@%.5f",
                    intent.client_order_id, intent.side, intent.symbol,
                    intent.lots, intent.entry)
        return self._rpc_send(payload)
