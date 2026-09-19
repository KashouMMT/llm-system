"""Evidence rows: which image each catalog row was detected in.

Written by /recycle build_catalog after the catalog itself is saved; read
by show_catalog (and, later, the catalog browser page) to link each row to
the photo or video frame a reviewer should look at.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import psycopg
from psycopg.rows import class_row
from psycopg_pool import AsyncConnectionPool

from app.plugins.recycling.database.catalog_repository import CatalogStorageError
from app.plugins.recycling.database.schema import DEFAULT_TENANT, EVIDENCE_TABLE
from app.utils.logger import logger

# Newest kept per catalog row. A row seen in every build of a busy site
# would otherwise collect evidence without bound; a reviewer needs a few
# recent examples, not the full history.
MAX_EVIDENCE_PER_ITEM = 5


@dataclass(frozen=True)
class EvidenceEntry:
    item_id: str
    file_id: UUID
    # The frame's index in the source video; None for a photo.
    frame_index: int | None
    # The label the model actually said, before clustering mapped it to
    # the row — "desk" evidence on the "table" row explains itself.
    raw_label: str


@dataclass(frozen=True)
class EvidenceRecord:
    item_id: str
    file_id: UUID
    frame_index: int | None
    raw_label: str
    created_at: datetime


class EvidenceRepository:
    def __init__(self, pool: AsyncConnectionPool, *, tenant: str = DEFAULT_TENANT) -> None:
        self._pool = pool
        self._tenant = tenant

    async def add(self, entries: Sequence[EvidenceEntry], *, build_run_id: UUID) -> None:
        """Record one build's evidence, then trim each touched row back to
        its newest MAX_EVIDENCE_PER_ITEM. The same image twice for one row
        adds nothing (unique constraint, DO NOTHING)."""
        if not entries:
            return

        item_ids = sorted({entry.item_id for entry in entries})

        try:
            async with self._pool.connection() as conn, conn.transaction():
                async with conn.cursor() as cur:
                    await cur.executemany(
                        f"INSERT INTO {EVIDENCE_TABLE} "
                        "(tenant, item_id, file_id, frame_index, raw_label, build_run_id) "
                        "VALUES (%s, %s, %s, %s, %s, %s) "
                        "ON CONFLICT (tenant, item_id, file_id) DO NOTHING",
                        [
                            (
                                self._tenant,
                                entry.item_id,
                                entry.file_id,
                                entry.frame_index,
                                entry.raw_label,
                                build_run_id,
                            )
                            for entry in entries
                        ],
                    )
                await conn.execute(
                    f"DELETE FROM {EVIDENCE_TABLE} WHERE id IN ("
                    "  SELECT id FROM ("
                    "    SELECT id, row_number() OVER ("
                    "      PARTITION BY item_id ORDER BY id DESC"
                    "    ) AS rank"
                    f"   FROM {EVIDENCE_TABLE}"
                    "    WHERE tenant = %s AND item_id = ANY(%s)"
                    "  ) ranked WHERE rank > %s"
                    ")",
                    (self._tenant, item_ids, MAX_EVIDENCE_PER_ITEM),
                )
        except psycopg.Error as exc:
            logger.exception(
                "Catalog evidence save failed | table=%s tenant=%s entries=%s",
                EVIDENCE_TABLE,
                self._tenant,
                len(entries),
            )
            raise CatalogStorageError(str(exc)) from exc

        logger.info(
            "Catalog evidence saved | table=%s tenant=%s entries=%s items=%s build=%s",
            EVIDENCE_TABLE,
            self._tenant,
            len(entries),
            len(item_ids),
            build_run_id,
        )

    async def by_item(
        self,
        item_ids: Sequence[str] | None = None,
    ) -> dict[str, list[EvidenceRecord]]:
        """Evidence per row, newest first: every row's, or only those of
        `item_ids` (one page of the catalog browser)."""
        condition = "tenant = %s"
        params: list[object] = [self._tenant]

        if item_ids is not None:
            condition += " AND item_id = ANY(%s)"
            params.append(list(item_ids))

        try:
            async with (
                self._pool.connection() as conn,
                conn.cursor(row_factory=class_row(EvidenceRecord)) as cur,
            ):
                await cur.execute(
                    "SELECT item_id, file_id, frame_index, raw_label, created_at "
                    f"FROM {EVIDENCE_TABLE} WHERE {condition} "
                    "ORDER BY item_id, id DESC",
                    params,
                )
                rows = await cur.fetchall()
        except psycopg.Error as exc:
            logger.exception(
                "Catalog evidence load failed | table=%s tenant=%s", EVIDENCE_TABLE, self._tenant
            )
            raise CatalogStorageError(str(exc)) from exc

        evidence: dict[str, list[EvidenceRecord]] = {}
        for row in rows:
            evidence.setdefault(row.item_id, []).append(row)
        return evidence
