"""
TheUltimateChat — Phase 1 Relay Server

Binds to localhost:8765 (WebSocket). Routes signed events between clients
by channel. Buffers messages for offline clients (7-day TTL in SQLite).

Wire protocol (JSON arrays):
  Client → Relay:  ["EVENT", event]  |  ["REQ", sub_id, filter]  |  ["CLOSE", sub_id]
  Relay → Client:  ["EVENT", sub_id, event]  |  ["OK", id, bool, reason]
                   ["EOSE", sub_id]  |  ["NOTICE", msg]
"""

import asyncio
import json
import logging
import os
import time
import websockets

from .buffer import init_db, store_event, get_events_since, purge_expired
from .crypto import verify_event
from .protocol import validate_event, get_channel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

HOST = "127.0.0.1"
PORT = 8765

# channel → set of (websocket, sub_id) tuples
_channel_subs: dict[str, set] = {}
# websocket → set of sub_ids active on it
_client_subs: dict = {}


def _subscribe(ws, sub_id: str, channel: str) -> None:
    _channel_subs.setdefault(channel, set()).add((ws, sub_id))
    _client_subs.setdefault(id(ws), set()).add((sub_id, channel))


def _unsubscribe(ws, sub_id: str) -> None:
    subs = _client_subs.pop(id(ws), set())
    for sid, channel in list(subs):
        if sid == sub_id and channel in _channel_subs:
            _channel_subs[channel].discard((ws, sub_id))
            if not _channel_subs[channel]:
                del _channel_subs[channel]
    remaining = {(s, c) for s, c in subs if s != sub_id}
    if remaining:
        _client_subs[id(ws)] = remaining


def _unsubscribe_all(ws) -> None:
    for sub_id, channel in _client_subs.pop(id(ws), set()):
        if channel in _channel_subs:
            _channel_subs[channel].discard((ws, sub_id))
            if not _channel_subs[channel]:
                del _channel_subs[channel]


async def _send(ws, msg: list) -> None:
    try:
        await ws.send(json.dumps(msg))
    except Exception:
        pass


async def _handle_event(ws, event: dict) -> None:
    ok, reason = validate_event(event)
    if not ok:
        await _send(ws, ["OK", event.get("id", ""), False, reason])
        return

    ok, reason = verify_event(event)
    if not ok:
        await _send(ws, ["OK", event["id"], False, reason])
        return

    channel = get_channel(event)
    await store_event(event, channel)

    await _send(ws, ["OK", event["id"], True, ""])

    if channel and channel in _channel_subs:
        for sub_ws, sub_id in list(_channel_subs[channel]):
            if sub_ws is not ws:
                await _send(sub_ws, ["EVENT", sub_id, event])

    log.info("EVENT kind=%d channel=%s from=%s...", event["kind"], channel, event["pubkey"][:8])


async def _handle_req(ws, sub_id: str, fil: dict) -> None:
    channel = fil.get("channel")
    if not channel:
        await _send(ws, ["NOTICE", "filter must include 'channel'"])
        return

    since = fil.get("since", int(time.time()) - 7 * 24 * 3600)
    _subscribe(ws, sub_id, channel)

    stored = await get_events_since(channel, since)
    for ev in stored:
        await _send(ws, ["EVENT", sub_id, ev])
    await _send(ws, ["EOSE", sub_id])
    log.info("REQ sub=%s channel=%s replayed=%d", sub_id, channel, len(stored))


async def _handle_client(ws) -> None:
    remote = ws.remote_address
    log.info("connect %s", remote)
    await _send(ws, ["NOTICE", "TheUltimateChat relay v0.1 — Phase 1"])
    try:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _send(ws, ["NOTICE", "invalid JSON"])
                continue

            if not isinstance(msg, list) or len(msg) < 2:
                await _send(ws, ["NOTICE", "expected JSON array"])
                continue

            verb = msg[0]
            if verb == "EVENT" and len(msg) == 2:
                await _handle_event(ws, msg[1])
            elif verb == "REQ" and len(msg) == 3:
                await _handle_req(ws, str(msg[1]), msg[2])
            elif verb == "CLOSE" and len(msg) == 2:
                _unsubscribe(ws, str(msg[1]))
            else:
                await _send(ws, ["NOTICE", f"unknown verb: {verb}"])
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        _unsubscribe_all(ws)
        log.info("disconnect %s", remote)


async def _purge_loop() -> None:
    while True:
        await asyncio.sleep(3600)
        n = await purge_expired()
        if n:
            log.info("purged %d expired events", n)


async def main() -> None:
    os.makedirs(os.path.dirname("/root/.shellchat/"), exist_ok=True)
    await init_db()
    log.info("relay starting on ws://%s:%d", HOST, PORT)
    async with websockets.serve(_handle_client, HOST, PORT):
        await asyncio.gather(
            asyncio.Future(),
            _purge_loop(),
        )


if __name__ == "__main__":
    asyncio.run(main())
