from typing import Protocol


class FileStorage(Protocol):
    """
    Where generated file bytes live.

    Async on purpose, even though the local implementation is disk I/O.
    Every call site therefore awaits, so swapping in an S3 backend later
    changes no caller — and the blocking work is confined behind this
    interface, where it can be offloaded once instead of being remembered
    at each use.

    The storage layer generates its own keys. A caller cannot supply one,
    so a filename can never reach a filesystem path and path traversal is
    impossible by construction rather than by validation.
    """

    async def write(self, data: bytes, *, extension: str) -> str:
        """Store bytes and return the key that addresses them."""
        ...

    async def read(self, key: str) -> bytes:
        """Raise FileNotFoundError if the key does not exist."""
        ...

    async def delete(self, key: str) -> None:
        """Idempotent: deleting a missing key is not an error."""
        ...
