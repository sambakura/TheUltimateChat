"""
Integration tests — Phase 1 + Phase 2 (DM routing, groups, encryption).
Run with relay server active.
"""

import asyncio
import json
import sys
import time
import websockets

sys.path.insert(0, "/root/TheUltimateChat")
from relay.crypto import generate_keypair, sign_event_id, box_encrypt, box_decrypt
from relay.protocol import compute_id, inbox_key, Kind

URL = "ws://127.0.0.1:8765"
NOW = int(time.time())


def make_event(privkey, pubkey, kind, content, channel=None, recipient_pubkey=None):
    tags = []
    if channel:
        tags.append(["channel", channel])
    if recipient_pubkey:
        tags.append(["p", recipient_pubkey])
    event = {
        "pubkey": pubkey,
        "created_at": int(time.time()),
        "kind": kind,
        "tags": tags,
        "content": content,
    }
    event["id"] = compute_id(event)
    event["sig"] = sign_event_id(event["id"], privkey)
    return event


async def drain_eose(ws, timeout=3.0):
    """Consume messages until EOSE (relay sent all buffered events)."""
    buffered = []
    try:
        async with asyncio.timeout(timeout):
            async for raw in ws:
                msg = json.loads(raw)
                if msg[0] == "EOSE":
                    break
                buffered.append(msg)
    except TimeoutError:
        pass
    return buffered


async def collect(ws, count, timeout=3.0):
    """Collect up to `count` messages within timeout."""
    collected = []
    try:
        async with asyncio.timeout(timeout):
            async for raw in ws:
                collected.append(json.loads(raw))
                if len(collected) >= count:
                    break
    except TimeoutError:
        pass
    return collected


async def run():
    alice_priv, alice_pub = generate_keypair()
    bob_priv,   bob_pub   = generate_keypair()
    carol_priv, carol_pub = generate_keypair()
    print(f"Alice: {alice_pub[:12]}…")
    print(f"Bob:   {bob_pub[:12]}…")
    print(f"Carol: {carol_pub[:12]}…")

    # ── Phase 1: basic routing + replay ─────────────────────────────────────
    print("\n[1] Alice publishes to #general, Bob receives live…")
    async with (
        websockets.connect(URL) as alice,
        websockets.connect(URL) as bob,
    ):
        # Subscribe with since=NOW so only live messages arrive, drain to EOSE
        await bob.send(json.dumps(["REQ", "sub-bob", {"channel": "#general", "since": NOW}]))
        await drain_eose(bob)

        ev = make_event(alice_priv, alice_pub, Kind.MESSAGE, "hello phase-1", "#general")
        await alice.send(json.dumps(["EVENT", ev]))
        alice_msgs = await collect(alice, 2, timeout=2.0)
        ok = next((m for m in alice_msgs if m[0] == "OK"), None)
        assert ok and ok[2] is True, f"Expected OK=True, got {ok}"

        bob_msgs = await collect(bob, 1, timeout=2.0)
        ev_msg = next((m for m in bob_msgs if m[0] == "EVENT"), None)
        assert ev_msg and ev_msg[2]["content"] == "hello phase-1", f"Bob got: {bob_msgs}"
        print("  ✓ live routing works")

    print("\n[2] Bob reconnects, gets buffered replay…")
    async with websockets.connect(URL) as bob2:
        since = int(time.time()) - 60
        await bob2.send(json.dumps(["REQ", "sub-bob2", {"channel": "#general", "since": since}]))
        buffered = await drain_eose(bob2)
        events = [m for m in buffered if m[0] == "EVENT"]
        assert events
        assert any(e[2]["content"] == "hello phase-1" for e in events)
        print(f"  ✓ {len(events)} event(s) replayed, EOSE received")

    print("\n[3] Tampered signature rejected…")
    async with websockets.connect(URL) as client:
        bad_priv, _ = generate_keypair()
        ev = make_event(alice_priv, alice_pub, Kind.MESSAGE, "tampered", "#general")
        ev["sig"] = sign_event_id(ev["id"], bad_priv)
        await client.send(json.dumps(["EVENT", ev]))
        msgs = await collect(client, 2, timeout=2.0)
        ok = next((m for m in msgs if m[0] == "OK"), None)
        assert ok and ok[2] is False
        print("  ✓ tampered event rejected")

    # ── Phase 2: DM routing via inbox ────────────────────────────────────────
    print("\n[4] Alice DMs Bob — Bob gets it, Carol doesn't…")
    async with (
        websockets.connect(URL) as alice,
        websockets.connect(URL) as bob,
        websockets.connect(URL) as carol,
    ):
        await bob.send(json.dumps(["REQ", "inbox-bob", {"channel": inbox_key(bob_pub), "since": NOW}]))
        await drain_eose(bob)

        await carol.send(json.dumps(["REQ", "carol-gen", {"channel": "#general", "since": NOW}]))
        await drain_eose(carol)

        ciphertext = box_encrypt("secret from alice", alice_priv, bob_pub)
        ev = make_event(alice_priv, alice_pub, Kind.WHISPER, ciphertext, recipient_pubkey=bob_pub)
        await alice.send(json.dumps(["EVENT", ev]))

        alice_msgs = await collect(alice, 2, timeout=2.0)
        ok = next((m for m in alice_msgs if m[0] == "OK"), None)
        assert ok and ok[2] is True, f"Expected OK, got {ok}"

        bob_msgs = await collect(bob, 1, timeout=2.0)
        ev_msg = next((m for m in bob_msgs if m[0] == "EVENT"), None)
        assert ev_msg, f"Bob didn't receive DM, got: {bob_msgs}"
        decrypted = box_decrypt(ev_msg[2]["content"], bob_priv, alice_pub)
        assert decrypted == "secret from alice"
        print("  ✓ Bob received and decrypted DM")

        carol_msgs = await collect(carol, 1, timeout=1.0)
        carol_events = [m for m in carol_msgs if m[0] == "EVENT"]
        assert not carol_events, f"Carol should not see DMs, got {carol_events}"
        print("  ✓ Carol sees nothing")

    print("\n[5] DM offline replay…")
    async with websockets.connect(URL) as bob3:
        since = int(time.time()) - 60
        await bob3.send(json.dumps(["REQ", "inbox-bob2", {"channel": inbox_key(bob_pub), "since": since}]))
        buffered = await drain_eose(bob3)
        events = [m for m in buffered if m[0] == "EVENT"]
        assert events, f"No buffered DMs, got: {buffered}"
        decrypted = box_decrypt(events[0][2]["content"], bob_priv, alice_pub)
        assert decrypted == "secret from alice"
        print(f"  ✓ {len(events)} DM(s) replayed, decryption ok")

    # ── Phase 2: Groups ───────────────────────────────────────────────────────
    print("\n[6] Group #dev — three members, late-joiner gets replay…")
    async with (
        websockets.connect(URL) as alice,
        websockets.connect(URL) as bob,
    ):
        await alice.send(json.dumps(["REQ", "grp-alice", {"channel": "#dev", "since": NOW}]))
        await bob.send(json.dumps(["REQ", "grp-bob", {"channel": "#dev", "since": NOW}]))
        await drain_eose(alice)
        await drain_eose(bob)

        ev = make_event(alice_priv, alice_pub, Kind.MESSAGE, "group message", "#dev")
        await alice.send(json.dumps(["EVENT", ev]))
        await collect(alice, 2, timeout=2.0)

        bob_msgs = await collect(bob, 1, timeout=2.0)
        grp_ev = next((m for m in bob_msgs if m[0] == "EVENT"), None)
        assert grp_ev and grp_ev[2]["content"] == "group message"
        print("  ✓ Bob got group message live")

    async with websockets.connect(URL) as carol:
        since = int(time.time()) - 60
        await carol.send(json.dumps(["REQ", "grp-carol", {"channel": "#dev", "since": since}]))
        buffered = await drain_eose(carol)
        events = [m for m in buffered if m[0] == "EVENT"]
        assert events and any(e[2]["content"] == "group message" for e in events)
        print(f"  ✓ Carol (late joiner) got {len(events)} replayed group message(s)")

    print("\n✓ All Phase-1 + Phase-2 relay tests passed.")


asyncio.run(run())
