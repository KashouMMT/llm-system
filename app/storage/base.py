from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from pathlib import Path
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

    async def write_stream(
        self,
        chunks: AsyncIterator[bytes],
        *,
        extension: str,
    ) -> tuple[str, int]:
        """
        Store a stream of bytes; return the key and how many were written.

        Separate from write() rather than replacing it, because the two
        have genuinely different contracts: write() holds every byte and
        can be retried, while a stream is consumed exactly once and its
        length is not known until it ends. A caller that already has the
        bytes keeps using write().

        Exists for uploads too large to hold in memory — a 150 MB video
        buffered into a bytearray and then copied peaks near 300 MB, per
        concurrent upload.

        If `chunks` raises, nothing is left behind. That is load-bearing
        rather than defensive: it is how the upload handler enforces its
        size cap, so the abort path is the common one.
        """
        ...

    def temporary_path(self, key: str) -> AbstractAsyncContextManager[Path]:
        """
        A local filesystem path for `key`, valid only inside the context.

        For the consumers that cannot work from bytes: ffmpeg needs a
        seekable file, and the alternative is reading a whole video into
        memory only to write it straight back out to a temporary file.

        The contract is "a temporary local copy", never "where this file
        lives". The local backend yields the real path and copies nothing;
        an S3 backend would download here and delete on exit. A caller
        must not retain the Path beyond the block, and must not write
        through it.
        """
        ...

    async def read(self, key: str) -> bytes:
        """Raise FileNotFoundError if the key does not exist."""
        ...

    async def delete(self, key: str) -> None:
        """Idempotent: deleting a missing key is not an error."""
        ...
