"""The recycling plugin's own table.

Created here, from the plugin's initialize hook, rather than in core
app/database/init_db.py: the plugin owns its whole vertical, storage
included. The database is disposable (no migrations), so a schema change
is an edit to CREATE TABLE plus dropping the table, then rebuilding the
catalog with /recycle build_catalog. There is no seed file.

A failure here is logged by the plugin loader, which then leaves the whole
plugin out rather than loading commands against a missing table.
"""

from psycopg_pool import AsyncConnectionPool

CATALOG_TABLE = "recycling_catalog_items"

# Every row belongs to a tenant from day one, though only one exists. The
# catalog is meant to become per-client (TODO §4); adding the column later
# means a primary-key change on a table with data and a WHERE clause in
# every query, each one missed being a cross-client leak.
DEFAULT_TENANT = "default"

# One typed column per ItemMetadata field rather than a JSONB blob: the
# catalog-analysis tools and a review UI both filter on weight, material
# and the rest, and a blob hides them. Only `extra` — free-form by design —
# is JSONB.
#
# `aliases` has no uniqueness constraint on purpose. A contested alias
# must reach a reviewer as a reported conflict (Catalog raises on load),
# not be rejected by the database where nobody sees it.
#
# `position` keeps the order the catalog was built in, which is the order
# show_catalog has always listed it.
_CREATE_CATALOG_TABLE = f"""
CREATE TABLE IF NOT EXISTS {CATALOG_TABLE} (
    tenant              TEXT NOT NULL DEFAULT '{DEFAULT_TENANT}',
    id                  TEXT NOT NULL,
    position            INTEGER NOT NULL,
    canonical_label     TEXT NOT NULL,
    aliases             TEXT[] NOT NULL DEFAULT '{{}}',
    visual_class        TEXT NOT NULL DEFAULT '',
    excluded            BOOLEAN NOT NULL DEFAULT FALSE,
    exclusion_reason    TEXT,
    observations        INTEGER NOT NULL DEFAULT 0,
    weight_kg           DOUBLE PRECISION,
    weight_kg_min       DOUBLE PRECISION,
    weight_kg_max       DOUBLE PRECISION,
    length_cm           DOUBLE PRECISION,
    width_cm            DOUBLE PRECISION,
    height_cm           DOUBLE PRECISION,
    volume_m3           DOUBLE PRECISION,
    material            TEXT,
    nestable            BOOLEAN,
    stackable           BOOLEAN,
    unit_price          DOUBLE PRECISION,
    currency            TEXT,
    extra               JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    source              TEXT NOT NULL DEFAULT 'unknown',
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant, id)
)
"""


async def ensure_schema(pool: AsyncConnectionPool) -> None:
    async with pool.connection() as conn:
        await conn.execute(_CREATE_CATALOG_TABLE)
