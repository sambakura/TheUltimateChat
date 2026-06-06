"""
Phase-1 integration test:
  1. Generate two keypairs (Alice, Bob)
  2. Alice sends a message to #general
  3. Bob subscribes and receives it (live)
  4. Bob reconnects and gets the buffered event (EOSE replay)
"""

import asyncio
import json
import time
import sys
import websockets

sys.path.insert(0, "/root/TheUltimateChat")
from relay.crypto import generate_keypair, sign_event_id
from relay.protocol import compute_id, Kind

URL = "ws://127.0.0.1:8765"


def make_event(privkey: str, pubkey: str, kind: int, content: str, channel: str) -> dict:
    event = {
        "pubkey": pubkey,
        "created_at": int(time.time()),
        "kind": kind,
        "tags": [["channel", channel]],
        "content": content,
    }
    event["id"] = compute_id(event)
    event["sig"] = sign_event_id(event["id"], privkey)
    return event


async def collect(ws, count: int, timeout: float = 3.0) -> list:
    collected = []
    try:
        async with asyncio.timeout(timeout):
            async for raw in ws:
                msg = json.loads(raw)
                collected.append(msg)
                if len(collected) >= count:
                    break
    except TimeoutError:
        pass
    return collected


async def run():
    alice_priv, alice_pub = generate_keypair()
    bob_priv,   bob_pub   = generate_keypair()
    print(f"Alice pubkey: {alice_pub[:16]}…")
    print(f"Bob   pubkey: {bob_pub[:16]}…")

    # ── Test 1: Alice publishes, Bob receives live ──────────────────────────
    print("\n[1] Alice publishes, Bob receives live…")
    async with (
        websockets.connect(URL) as alice,
        websockets.connect(URL) as bob,
    ):
        # Bob subscribes first
        await bob.send(json.dumps(["REQ", "sub-bob", {"channel": "#general"}]))
        # consume NOTICE + EOSE
        await collect(bob, 2, timeout=2.0)

        # Alice sends
        ev = make_event(alice_priv, alice_pub, Kind.MESSAGE, "hello from alice", "#general")
        await alice.send(json.dumps(["EVENT", ev]))

        # Alice gets OK
        alice_msgs = await collect(alice, 2, timeout=2.0)
        ok = next((m for m in alice_msgs if m[0] == "OK"), None)
        assert ok and ok[2] is True, f"Expected OK=True, got {ok}"
        print("  ✓ relay accepted event")

        # Bob gets EVENT
        bob_msgs = await collect(bob, 1, timeout=2.0)
        ev_msg = next((m for m in bob_msgs if m[0] == "EVENT"), None)
        assert ev_msg, f"Bob didn't receive event. Got: {bob_msgs}"
        assert ev_msg[2]["content"] == "hello from alice"
        print("  ✓ Bob received live event")

    # ── Test 2: Bob reconnects and gets buffered event (EOSE replay) ────────
    print("\n[2] Bob reconnects — buffered event should replay…")
    async with websockets.connect(URL) as bob2:
        since = int(time.time()) - 60
        await bob2.send(json.dumps(["REQ", "sub-bob2", {"channel": "#general", "since": since}]))
        msgs = await collect(bob2, 10, timeout=3.0)
        events = [m for m in msgs if m[0] == "EVENT"]
        eose   = [m for m in msgs if m[0] == "EOSE"]
        assert events, f"No buffered events on reconnect. Got: {msgs}"
        assert eose,   "No EOSE received"
        assert any(e[2]["content"] == "hello from alice" for e in events)
        print(f"  ✓ {len(events)} event(s) replayed from buffer")
        print("  ✓ EOSE received")

    # ── Test 3: Invalid signature is rejected ───────────────────────────────
    print("\n[3] Tampered event should be rejected…")
    async with websockets.connect(URL) as client:
        bad_priv, bad_pub = generate_keypair()
        ev = make_event(alice_priv, alice_pub, Kind.MESSAGE, "tampered", "#general")
        ev["sig"] = sign_event_id(ev["id"], bad_priv)  # wrong key
        await client.send(json.dumps(["EVENT", ev]))
        msgs = await collect(client, 2, timeout=2.0)
        ok = next((m for m in msgs if m[0] == "OK"), None)
        assert ok and ok[2] is False, f"Expected rejection, got {ok}"
        print("  ✓ tampered event rejected")

    print("\n✓ All Phase-1 tests passed.")


asyncio.run(run())
