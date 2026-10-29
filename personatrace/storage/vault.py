"""Encrypted local key vault (PersonaTrace v2.0).

Algorithm: ChaCha20 stream cipher (RFC 8439, pure Python, no extra
dependency) with a key derived by PBKDF2-HMAC-SHA256 from a passphrase
the investigator supplies (environment PERSONATRACE_VAULT_PASSPHRASE or
a CLI flag). Each stored key gets its own salt and nonce, and an
HMAC-SHA256 tag so a tampered entry is detected, never silently used.

Rules:
- No passphrase = vault is not_configured and nothing is stored.
- The vault file stores names and ciphertext only, never a passphrase
  and never a plaintext key.
- A stored key is used only for the run that asks for it; it is never
  printed in an export, a log, or a GUI response.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import struct

_VAULT_ENV = "PERSONATRACE_VAULT_PATH"
_PASSPHRASE_ENV = "PERSONATRACE_VAULT_PASSPHRASE"


def _rotl(v: int, n: int) -> int:
    return ((v << n) & 0xFFFFFFFF) | (v >> (32 - n))


def _quarter_round(state, a, b, c, d):
    state[a] = (state[a] + state[b]) & 0xFFFFFFFF; state[d] ^= state[a]; state[d] = _rotl(state[d], 16)
    state[c] = (state[c] + state[d]) & 0xFFFFFFFF; state[b] ^= state[c]; state[b] = _rotl(state[b], 12)
    state[a] = (state[a] + state[b]) & 0xFFFFFFFF; state[d] ^= state[a]; state[d] = _rotl(state[d], 8)
    state[c] = (state[c] + state[d]) & 0xFFFFFFFF; state[b] ^= state[c]; state[b] = _rotl(state[b], 7)


def _chacha20_block(key: bytes, counter: int, nonce: bytes) -> bytes:
    constants = b"expand 32-byte k"
    state = list(struct.unpack("<4I", constants)) + list(struct.unpack("<8I", key))
    state.append(counter)
    state += list(struct.unpack("<3I", nonce))
    working = state[:]
    for _ in range(10):
        _quarter_round(working, 0, 4, 8, 12); _quarter_round(working, 1, 5, 9, 13)
        _quarter_round(working, 2, 6, 10, 14); _quarter_round(working, 3, 7, 11, 15)
        _quarter_round(working, 0, 5, 10, 15); _quarter_round(working, 1, 6, 11, 12)
        _quarter_round(working, 2, 7, 8, 13); _quarter_round(working, 3, 4, 9, 14)
    out = [(working[i] + state[i]) & 0xFFFFFFFF for i in range(16)]
    return struct.pack("<16I", *out)


def _chacha20_crypt(key: bytes, nonce: bytes, data: bytes) -> bytes:
    out = bytearray()
    counter = 1
    for i in range(0, len(data), 64):
        block = _chacha20_block(key, counter, nonce)
        counter += 1
        chunk = data[i:i + 64]
        out += bytes(c ^ b for c, b in zip(chunk, block))
    return bytes(out)


def vault_path() -> str:
    return os.environ.get(_VAULT_ENV) or os.path.join(os.getcwd(), ".personatrace_vault.json")


def _passphrase() -> str:
    return os.environ.get(_PASSPHRASE_ENV) or ""


def _load() -> dict:
    try:
        with open(vault_path(), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {"keys": {}}


def _save(data: dict):
    with open(vault_path(), "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def store_key(name: str, value: str, passphrase: str | None = None) -> dict:
    """Encrypt and store one key by name. Returns names only, never values."""
    pw = passphrase or _passphrase()
    if not pw:
        return {"status": "not_configured", "reason": "No vault passphrase set (PERSONATRACE_VAULT_PASSPHRASE). Nothing stored."}
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000, dklen=32)
    ciphertext = _chacha20_crypt(key, nonce, value.encode())
    tag = hmac.new(key, salt + nonce + ciphertext, hashlib.sha256).hexdigest()
    data = _load()
    data["keys"][name] = {"salt": salt.hex(), "nonce": nonce.hex(),
                          "ciphertext": ciphertext.hex(), "tag": tag,
                          "algorithm": "ChaCha20 + PBKDF2-HMAC-SHA256 + HMAC-SHA256"}
    _save(data)
    return {"status": "stored", "name": name}


def load_key(name: str, passphrase: str | None = None) -> dict:
    """Decrypt one stored key, or report why it cannot be used."""
    pw = passphrase or _passphrase()
    if not pw:
        return {"status": "not_configured", "reason": "No vault passphrase set"}
    entry = _load().get("keys", {}).get(name)
    if not entry:
        return {"status": "not_found", "name": name}
    try:
        salt = bytes.fromhex(entry["salt"]); nonce = bytes.fromhex(entry["nonce"])
        ciphertext = bytes.fromhex(entry["ciphertext"])
        key = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000, dklen=32)
        expected = hmac.new(key, salt + nonce + ciphertext, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, entry["tag"]):
            return {"status": "tampered_or_wrong_passphrase", "name": name}
        return {"status": "ok", "name": name, "value": _chacha20_crypt(key, nonce, ciphertext).decode()}
    except Exception as exc:
        return {"status": "error", "name": name, "reason": str(exc)}


def list_key_names() -> list:
    """Names only, never values."""
    return sorted(_load().get("keys", {}).keys())


# ---------------------------------------------------------------- roles
ROLES = {
    "viewer": {"can_search": False, "can_export": False, "can_manage_keys": False, "description": "Read-only: view saved cases only"},
    "analyst": {"can_search": True, "can_export": True, "can_manage_keys": False, "description": "Run searches and export cases"},
    "admin": {"can_search": True, "can_export": True, "can_manage_keys": True, "description": "Full access, including key management"},
}


def role_for(user: str | None) -> str:
    """Role from PERSONATRACE_ROLE, default analyst for a local single user.

    This is a local single-machine control, not a multi-user server
    authentication system: it does not replace a real login system if
    the GUI is ever exposed on a network.
    """
    role = (os.environ.get("PERSONATRACE_ROLE") or "analyst").lower()
    return role if role in ROLES else "analyst"


def can(role: str, action: str) -> bool:
    return bool(ROLES.get(role, ROLES["analyst"]).get(action, False))
