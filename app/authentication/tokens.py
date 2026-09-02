import hashlib
import secrets

# 32 bytes = 256 bits of entropy, url-safe base64 encoded to ~43 chars.
_TOKEN_BYTES = 32

def generate_session_token() -> str:
    return secrets.token_urlsafe(_TOKEN_BYTES)

def hash_session_token(token: str) -> bytes:
    """
    SHA-256, not argon2: the token is already a high-entropy random value,
    not a low-entropy password, and this runs on every authenticated request
    including every SSE reconnect.
    """
    return hashlib.sha256(token.encode("utf-8")).digest()