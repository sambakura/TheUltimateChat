"""Persistent Ed25519 identity keypair stored in ~/.shellchat/identity.json."""

import json
import os
from pathlib import Path

from relay.crypto import generate_keypair

IDENTITY_PATH = Path.home() / ".shellchat" / "identity.json"


def load_or_create_keypair() -> tuple[str, str]:
    """Return (privkey_hex, pubkey_hex), creating and saving on first run."""
    IDENTITY_PATH.parent.mkdir(parents=True, exist_ok=True)
    if IDENTITY_PATH.exists():
        data = json.loads(IDENTITY_PATH.read_text())
        return data["privkey"], data["pubkey"]
    privkey, pubkey = generate_keypair()
    IDENTITY_PATH.write_text(json.dumps({"privkey": privkey, "pubkey": pubkey}, indent=2))
    os.chmod(IDENTITY_PATH, 0o600)
    return privkey, pubkey
