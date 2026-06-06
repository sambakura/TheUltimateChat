"""Ed25519 keypair generation and event signature verification via PyNaCl."""

import binascii
import nacl.signing
import nacl.exceptions


def generate_keypair() -> tuple[str, str]:
    """Return (privkey_hex, pubkey_hex)."""
    sk = nacl.signing.SigningKey.generate()
    privkey_hex = sk.encode().hex()
    pubkey_hex = sk.verify_key.encode().hex()
    return privkey_hex, pubkey_hex


def sign_event_id(event_id_hex: str, privkey_hex: str) -> str:
    """Sign the event id (32-byte hash) and return the signature as hex."""
    sk = nacl.signing.SigningKey(bytes.fromhex(privkey_hex))
    signed = sk.sign(bytes.fromhex(event_id_hex))
    return signed.signature.hex()


def verify_event(event: dict) -> tuple[bool, str]:
    """Verify that event["sig"] is a valid Ed25519 signature of event["id"] by event["pubkey"]."""
    try:
        vk = nacl.signing.VerifyKey(bytes.fromhex(event["pubkey"]))
        vk.verify(
            bytes.fromhex(event["id"]),
            bytes.fromhex(event["sig"]),
        )
        return True, ""
    except nacl.exceptions.BadSignatureError:
        return False, "invalid signature"
    except (ValueError, binascii.Error) as exc:
        return False, f"hex decode error: {exc}"
