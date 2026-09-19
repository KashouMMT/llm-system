"""Loads and saves the catalog as rows of recycling_catalog_items.

Speaks in the pipeline's own types — `Catalog` in, `Catalog` out — so
nothing above this file knows there is a database. The mapping between the
nested `ItemMetadata` and the flat columns lives here and nowhere else.

Every database failure is logged here, once, with the table and tenant,
before it leaves as CatalogStorageError.
"""

from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool
from pydantic import ValidationError

from app.plugins.recycling.database.schema import CATALOG_TABLE, DEFAULT_TENANT
from app.plugins.recycling.pipeline.catalog import (
    Catalog,
    CatalogItem,
    Dimensions,
    ItemMetadata,
)
from app.utils.logger import logger

_COLUMNS = (
    "id",
    "position",
    "canonical_label",
    "aliases",
    "visual_class",
    "excluded",
    "exclusion_reason",
    "observations",
    "weight_kg",
    "weight_kg_min",
    "weight_kg_max",
    "length_cm",
    "width_cm",
    "height_cm",
    "volume_m3",
    "material",
    "nestable",
    "stackable",
    "unit_price",
    "currency",
    "extra",
    "source",
)

# Everything a single-row update rewrites: all but the key and the order.
_DATA_COLUMNS = _COLUMNS[2:]


def _to_row(item: CatalogItem, position: int) -> tuple:
    metadata = item.metadata
    return (
        item.id,
        position,
        item.canonical_label,
        item.aliases,
        item.visual_class,
        item.excluded,
        item.exclusion_reason,
        item.observations,
        metadata.weight_kg,
        metadata.weight_kg_min,
        metadata.weight_kg_max,
        metadata.dimensions.length_cm,
        metadata.dimensions.width_cm,
        metadata.dimensions.height_cm,
        metadata.volume_m3,
        metadata.material,
        metadata.nestable,
        metadata.stackable,
        metadata.unit_price,
        metadata.currency,
        Jsonb(metadata.extra),
        metadata.source,
    )


def _from_row(row: dict) -> CatalogItem:
    # Through the Pydantic models, not around them, so a row edited by hand
    # into something invalid (source='guess') fails loudly on load.
    return CatalogItem(
        id=row["id"],
        canonical_label=row["canonical_label"],
        aliases=row["aliases"],
        visual_class=row["visual_class"],
        excluded=row["excluded"],
        exclusion_reason=row["exclusion_reason"],
        observations=row["observations"],
        metadata=ItemMetadata(
            weight_kg=row["weight_kg"],
            weight_kg_min=row["weight_kg_min"],
            weight_kg_max=row["weight_kg_max"],
            dimensions=Dimensions(
                length_cm=row["length_cm"],
                width_cm=row["width_cm"],
                height_cm=row["height_cm"],
            ),
            volume_m3=row["volume_m3"],
            material=row["material"],
            nestable=row["nestable"],
            stackable=row["stackable"],
            unit_price=row["unit_price"],
            currency=row["currency"],
            extra=row["extra"],
            source=row["source"],
        ),
    )


@dataclass(frozen=True)
class CatalogPage:
    """One page of the catalog browser: flat rows as stored (plus
    updated_at), the total matching the filters, and every visual_class
    present, for the filter dropdown."""

    total: int
    rows: list[dict[str, Any]]
    visual_classes: list[str]


def _like_pattern(text: str) -> str:
    """Substring match for ILIKE, with the user's own % and _ taken
    literally rather than as wildcards."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class CatalogStorageError(RuntimeError):
    """The catalog could not be read from or written to the database.

    Already logged, with the traceback, by the time it is raised — the
    caller only turns it into a message for the user. One type rather than
    psycopg's own, so the commands never import the database driver.
    """


class CatalogRepository:
    def __init__(self, pool: AsyncConnectionPool, *, tenant: str = DEFAULT_TENANT) -> None:
        self._pool = pool
        self._tenant = tenant

    async def load(self) -> Catalog:
        """The whole catalog. Empty table → empty Catalog, not an error:
        scan then reports everything as unmatched and build_catalog
        bootstraps one.

        Raises CatalogError on an alias conflict, from Catalog itself, and
        CatalogStorageError when the query fails or a row is invalid.
        """
        try:
            async with (
                self._pool.connection() as conn,
                conn.cursor(row_factory=dict_row) as cur,
            ):
                await cur.execute(
                    f"SELECT {', '.join(_COLUMNS)} FROM {CATALOG_TABLE} "
                    "WHERE tenant = %s ORDER BY position",
                    (self._tenant,),
                )
                rows = await cur.fetchall()

            items = [_from_row(row) for row in rows]
        except (psycopg.Error, ValidationError) as exc:
            # ValidationError too: a row edited by hand into something the
            # model rejects is as much a storage fault as a failed query.
            logger.exception(
                "Catalog load failed | table=%s tenant=%s", CATALOG_TABLE, self._tenant
            )
            raise CatalogStorageError(str(exc)) from exc

        return Catalog(items)

    async def save(self, catalog: Catalog) -> None:
        """Make the tenant's stored catalog equal `catalog`, in one
        transaction.

        The build produces the complete merged catalog
        (merge_into_catalog), so this takes a whole Catalog — but writes it
        as upsert-then-delete-missing, not delete-everything-and-reinsert.
        A row that survives keeps its identity, so what references it
        (evidence, by foreign key with ON DELETE CASCADE) survives too, and
        updated_at moves only for rows whose data actually changed. The old
        delete-and-reinsert wiped all evidence and reset updated_at on
        every build.

        One transaction, so a failure mid-write leaves the old catalog
        intact rather than a half-written one. Raises CatalogStorageError.
        """
        placeholders = ", ".join(["%s"] * (len(_COLUMNS) + 1))
        # Everything but the key. position is rewritten too (build order),
        # but a reorder alone is not a change to the row's data.
        assignments = ", ".join(f"{column} = EXCLUDED.{column}" for column in _COLUMNS[1:])
        stored = ", ".join(f"{CATALOG_TABLE}.{column}" for column in _DATA_COLUMNS)
        incoming = ", ".join(f"EXCLUDED.{column}" for column in _DATA_COLUMNS)

        try:
            async with self._pool.connection() as conn, conn.transaction():
                async with conn.cursor() as cur:
                    await cur.executemany(
                        f"INSERT INTO {CATALOG_TABLE} (tenant, {', '.join(_COLUMNS)}) "
                        f"VALUES ({placeholders}) "
                        "ON CONFLICT (tenant, id) DO UPDATE SET "
                        f"{assignments}, "
                        f"updated_at = CASE WHEN ({stored}) IS DISTINCT FROM ({incoming}) "
                        f"THEN NOW() ELSE {CATALOG_TABLE}.updated_at END",
                        [
                            (self._tenant, *_to_row(item, position))
                            for position, item in enumerate(catalog.items)
                        ],
                    )
                await conn.execute(
                    f"DELETE FROM {CATALOG_TABLE} WHERE tenant = %s AND NOT (id = ANY(%s))",
                    (self._tenant, [item.id for item in catalog.items]),
                )
        except psycopg.Error as exc:
            logger.exception(
                "Catalog save failed, previous catalog kept | table=%s tenant=%s items=%s",
                CATALOG_TABLE,
                self._tenant,
                len(catalog),
            )
            raise CatalogStorageError(str(exc)) from exc

        logger.info(
            "Catalog saved | table=%s tenant=%s items=%s",
            CATALOG_TABLE,
            self._tenant,
            len(catalog),
        )

    async def counts(self) -> tuple[int, int]:
        """(total rows, excluded rows) — one aggregate, no rows loaded."""
        try:
            async with self._pool.connection() as conn:
                cur = await conn.execute(
                    f"SELECT COUNT(*), COUNT(*) FILTER (WHERE excluded) "
                    f"FROM {CATALOG_TABLE} WHERE tenant = %s",
                    (self._tenant,),
                )
                total, excluded = await cur.fetchone()
        except psycopg.Error as exc:
            logger.exception(
                "Catalog count failed | table=%s tenant=%s", CATALOG_TABLE, self._tenant
            )
            raise CatalogStorageError(str(exc)) from exc

        return total, excluded

    async def page(
        self,
        *,
        search: str = "",
        visual_class: str | None = None,
        excluded: bool | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> CatalogPage:
        """A filtered page for the catalog browser, in catalog order.

        Paged in the database rather than load() and sliced: the browser
        exists for catalogs too big to render at once, and load() also
        validates every row through Pydantic, which a read-only table view
        does not need. `search` matches id, label or any alias.
        """
        conditions = ["tenant = %s"]
        params: list[Any] = [self._tenant]

        if search.strip():
            pattern = _like_pattern(search.strip())
            conditions.append(
                "(id ILIKE %s OR canonical_label ILIKE %s "
                "OR EXISTS (SELECT 1 FROM unnest(aliases) AS alias WHERE alias ILIKE %s))"
            )
            params += [pattern, pattern, pattern]

        if visual_class:
            conditions.append("visual_class = %s")
            params.append(visual_class)

        if excluded is not None:
            conditions.append("excluded = %s")
            params.append(excluded)

        where = " AND ".join(conditions)

        try:
            async with (
                self._pool.connection() as conn,
                conn.cursor(row_factory=dict_row) as cur,
            ):
                await cur.execute(
                    f"SELECT COUNT(*) AS total FROM {CATALOG_TABLE} WHERE {where}", params
                )
                total = (await cur.fetchone())["total"]

                await cur.execute(
                    f"SELECT {', '.join(_COLUMNS)}, updated_at FROM {CATALOG_TABLE} "
                    f"WHERE {where} ORDER BY position LIMIT %s OFFSET %s",
                    [*params, limit, offset],
                )
                rows = await cur.fetchall()

                await cur.execute(
                    f"SELECT DISTINCT visual_class FROM {CATALOG_TABLE} "
                    "WHERE tenant = %s AND visual_class IS NOT NULL ORDER BY 1",
                    (self._tenant,),
                )
                visual_classes = [row["visual_class"] for row in await cur.fetchall()]
        except psycopg.Error as exc:
            logger.exception(
                "Catalog page failed | table=%s tenant=%s", CATALOG_TABLE, self._tenant
            )
            raise CatalogStorageError(str(exc)) from exc

        return CatalogPage(total=total, rows=rows, visual_classes=visual_classes)

    # ---- single rows ---------------------------------------------------
    #
    # For the catalog-editing tools: one row per call, never a whole-catalog
    # rewrite, so an edit cannot disturb rows it did not name. Each write
    # logs what it touched at INFO — the audit trail for model-made edits.

    async def get(self, item_id: str) -> CatalogItem | None:
        try:
            async with (
                self._pool.connection() as conn,
                conn.cursor(row_factory=dict_row) as cur,
            ):
                await cur.execute(
                    f"SELECT {', '.join(_COLUMNS)} FROM {CATALOG_TABLE} "
                    "WHERE tenant = %s AND id = %s",
                    (self._tenant, item_id),
                )
                row = await cur.fetchone()

            return None if row is None else _from_row(row)
        except (psycopg.Error, ValidationError) as exc:
            logger.exception(
                "Catalog get failed | table=%s tenant=%s id=%s",
                CATALOG_TABLE,
                self._tenant,
                item_id,
            )
            raise CatalogStorageError(str(exc)) from exc

    async def insert(self, item: CatalogItem) -> None:
        """Append one row after the current last position."""
        placeholders = ", ".join(["%s"] * (len(_COLUMNS) + 1))

        try:
            async with self._pool.connection() as conn, conn.transaction():
                cur = await conn.execute(
                    f"SELECT COALESCE(MAX(position) + 1, 0) FROM {CATALOG_TABLE} "
                    "WHERE tenant = %s",
                    (self._tenant,),
                )
                (position,) = await cur.fetchone()
                await conn.execute(
                    f"INSERT INTO {CATALOG_TABLE} (tenant, {', '.join(_COLUMNS)}) "
                    f"VALUES ({placeholders})",
                    (self._tenant, *_to_row(item, position)),
                )
        except psycopg.Error as exc:
            self._log_write_failure("insert", item.id)
            raise CatalogStorageError(str(exc)) from exc

        logger.info(
            "Catalog row inserted | table=%s tenant=%s id=%s", CATALOG_TABLE, self._tenant, item.id
        )

    async def update(self, item: CatalogItem) -> bool:
        """Rewrite one row's data columns. False when no row has that id."""
        assignments = ", ".join(f"{column} = %s" for column in _DATA_COLUMNS)

        try:
            async with self._pool.connection() as conn:
                cur = await conn.execute(
                    f"UPDATE {CATALOG_TABLE} SET {assignments}, updated_at = NOW() "
                    "WHERE tenant = %s AND id = %s",
                    (*_to_row(item, 0)[2:], self._tenant, item.id),
                )
                updated = cur.rowcount == 1
        except psycopg.Error as exc:
            self._log_write_failure("update", item.id)
            raise CatalogStorageError(str(exc)) from exc

        logger.info(
            "Catalog row updated | table=%s tenant=%s id=%s found=%s",
            CATALOG_TABLE,
            self._tenant,
            item.id,
            updated,
        )
        return updated

    async def delete(self, item_id: str) -> bool:
        """Remove one row. False when no row has that id."""
        try:
            async with self._pool.connection() as conn:
                cur = await conn.execute(
                    f"DELETE FROM {CATALOG_TABLE} WHERE tenant = %s AND id = %s",
                    (self._tenant, item_id),
                )
                deleted = cur.rowcount == 1
        except psycopg.Error as exc:
            self._log_write_failure("delete", item_id)
            raise CatalogStorageError(str(exc)) from exc

        logger.info(
            "Catalog row deleted | table=%s tenant=%s id=%s found=%s",
            CATALOG_TABLE,
            self._tenant,
            item_id,
            deleted,
        )
        return deleted

    def _log_write_failure(self, operation: str, item_id: str) -> None:
        logger.exception(
            "Catalog %s failed | table=%s tenant=%s id=%s",
            operation,
            CATALOG_TABLE,
            self._tenant,
            item_id,
        )
