"""Loads and saves the catalog as rows of recycling_catalog_items.

Speaks in the pipeline's own types — `Catalog` in, `Catalog` out — so
nothing above this file knows there is a database. The mapping between the
nested `ItemMetadata` and the flat columns lives here and nowhere else.

Every database failure is logged here, once, with the table and tenant,
before it leaves as CatalogStorageError.
"""

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
        """Replace the tenant's whole catalog in one transaction.

        Whole-replace rather than per-row upsert because that is what the
        build produces: merge_into_catalog returns the complete merged
        catalog. One transaction, so a failure mid-write leaves the old
        catalog intact rather than a half-written one.

        Raises CatalogStorageError when the write fails.
        """
        placeholders = ", ".join(["%s"] * (len(_COLUMNS) + 1))

        try:
            async with self._pool.connection() as conn, conn.transaction():
                await conn.execute(
                    f"DELETE FROM {CATALOG_TABLE} WHERE tenant = %s",
                    (self._tenant,),
                )
                async with conn.cursor() as cur:
                    await cur.executemany(
                        f"INSERT INTO {CATALOG_TABLE} (tenant, {', '.join(_COLUMNS)}) "
                        f"VALUES ({placeholders})",
                        [
                            (self._tenant, *_to_row(item, position))
                            for position, item in enumerate(catalog.items)
                        ],
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
