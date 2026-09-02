from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# argon2id with the library defaults (time_cost=3, memory_cost=64 MiB,
# parallelism=4). Adequate for a local single-tenant tool; raise memory_cost
# if this ever faces the internet.
_hasher = PasswordHasher()

# Verified against on the user-not-found path so login response time does not
# reveal whether a username exists.
_DUMMY_HASH = _hasher.hash("timing-parity-placeholder")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        _hasher.verify(password_hash, password)
        return True
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def verify_dummy(password: str) -> None:
    """Burn the same work verify_password would, and discard the result."""
    try:
        _hasher.verify(_DUMMY_HASH, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        pass
