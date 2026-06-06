"""
Event protocol — Nostr-style signed events.

Event shape:
  {
    "id":         sha256(canonical_serialize(event)),
    "pubkey":     hex(ed25519_public_key),
    "created_at": unix timestamp (int),
    "kind":       int (see Kind),
    "tags":       [["channel", "#general"], ...],
    "content":    str,
    "sig":        hex(ed25519_signature_of_id)
  }

Client → Relay messages:
  ["EVENT", event]                    publish
  ["REQ",   sub_id, {"channel": …}]  subscribe
  ["CLOSE", sub_id]                  unsubscribe

Relay → Client messages:
  ["EVENT",  sub_id, event]           incoming event
  ["OK",     event_id, ok, reason]    publish result
  ["EOSE",   sub_id]                  end of stored events
  ["NOTICE", message]                 server info
"""

import hashlib
import json


class Kind:
    MESSAGE  = 1   # chat message
    WHISPER  = 2   # private message (encrypted content)
    JOIN     = 3   # join channel
    LEAVE    = 4   # leave channel
    DELETE   = 5   # delete a previous event
    EDIT     = 6   # edit a previous event


def canonical_serialize(event: dict) -> bytes:
    """Canonical byte string that is signed/hashed — order matters."""
    payload = [
        event["pubkey"],
        event["created_at"],
        event["kind"],
        event["tags"],
        event["content"],
    ]
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()


def compute_id(event: dict) -> str:
    return hashlib.sha256(canonical_serialize(event)).hexdigest()


def validate_event(event: dict) -> tuple[bool, str]:
    """Return (ok, reason). Does NOT verify the signature — caller does that."""
    for field in ("id", "pubkey", "created_at", "kind", "tags", "content", "sig"):
        if field not in event:
            return False, f"missing field: {field}"

    if not isinstance(event["created_at"], int):
        return False, "created_at must be int"
    if not isinstance(event["kind"], int):
        return False, "kind must be int"
    if not isinstance(event["tags"], list):
        return False, "tags must be list"

    expected_id = compute_id(event)
    if event["id"] != expected_id:
        return False, f"id mismatch: expected {expected_id}"

    return True, ""


def channel_from_tags(tags: list) -> str | None:
    for tag in tags:
        if isinstance(tag, list) and len(tag) >= 2 and tag[0] == "channel":
            return tag[1]
    return None


def get_channel(event: dict) -> str | None:
    return channel_from_tags(event.get("tags", []))
