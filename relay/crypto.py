"""Ed25519 keypair generation, event signature verification, and NaCl box encryption."""

import binascii
import nacl.public
import nacl.signing
import nacl.exceptions
import nacl.utils


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


# ── Box encryption (DMs) ────────────────────────────────────────────────────
# Ed25519 identity keys are converted to Curve25519 for NaCl box.
# Both sides derive the same shared secret from their identity keypairs.

def box_encrypt(message: str, sender_privkey_hex: str, recipient_pubkey_hex: str) -> str:
    """Encrypt a DM for recipient. Returns hex-encoded (nonce + ciphertext)."""
    sender_curve = nacl.signing.SigningKey(bytes.fromhex(sender_privkey_hex)).to_curve25519_private_key()
    recip_curve  = nacl.signing.VerifyKey(bytes.fromhex(recipient_pubkey_hex)).to_curve25519_public_key()
    box = nacl.public.Box(sender_curve, recip_curve)
    return box.encrypt(message.encode()).hex()


def box_decrypt(ciphertext_hex: str, recipient_privkey_hex: str, sender_pubkey_hex: str) -> str:
    """Decrypt a DM. Returns plaintext string. Raises on failure."""
    recip_curve  = nacl.signing.SigningKey(bytes.fromhex(recipient_privkey_hex)).to_curve25519_private_key()
    sender_curve = nacl.signing.VerifyKey(bytes.fromhex(sender_pubkey_hex)).to_curve25519_public_key()
    box = nacl.public.Box(recip_curve, sender_curve)
    return box.decrypt(bytes.fromhex(ciphertext_hex)).decode()
