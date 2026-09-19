"""The recycling plugin's own table.

Created here, from the plugin's initialize hook, rather than in core
app/database/init_db.py: the plugin owns its whole vertical, storage
included. The database is disposable (no migrations), so a schema change
is an edit to CREATE TABLE plus dropping the table, then rebuilding the
catalog with /recycle build_catalog. There is no seed file.

A failure here is logged by the plugin loader, which then leaves the whole
plugin out rather than loading commands against a missing table.
"""

import psycopg
from psycopg_pool import AsyncConnectionPool

from app.database.agent_role import AgentRole
from app.utils.logger import logger

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


# What the model's SQL sees, instead of the table. Three jobs:
# - Tenant isolation. The agent role is granted this view only, never the
#   table, so model-written SQL cannot read another tenant's rows. The
#   tenant is a literal because there is one today; per-tenant access for
#   agent SQL (a view per tenant, or row-level security) is unsolved and
#   must be decided before a second tenant exists.
# - Internals hidden: `tenant` and `position` mean nothing to an analyst.
# - security_barrier, so a function in the model's WHERE clause is never
#   evaluated against rows the tenant filter would have removed.
#
# Dropped and recreated on every start: CREATE OR REPLACE VIEW refuses a
# changed column list, and the database is disposable anyway.
CATALOG_VIEW = "recycling_catalog"

_CREATE_CATALOG_VIEW = f"""
CREATE VIEW {CATALOG_VIEW} WITH (security_barrier) AS
SELECT id, canonical_label, aliases, visual_class, excluded, exclusion_reason,
       observations, weight_kg, weight_kg_min, weight_kg_max,
       length_cm, width_cm, height_cm, volume_m3, material, nestable, stackable,
       unit_price, currency, extra, source, updated_at
FROM {CATALOG_TABLE}
WHERE tenant = '{DEFAULT_TENANT}'
"""


async def ensure_schema(pool: AsyncConnectionPool) -> None:
    async with pool.connection() as conn:
        await conn.execute(_CREATE_CATALOG_TABLE)
        await conn.execute(f"DROP VIEW IF EXISTS {CATALOG_VIEW}")
        await conn.execute(_CREATE_CATALOG_VIEW)

    await _try_enable_trigram(pool)


async def _try_enable_trigram(pool: AsyncConnectionPool) -> None:
    """
    pg_trgm gives the model similarity(a, b) for near-duplicate labels —
    "office chair" / "office-chair" / "officechair" — which exact GROUP BY
    cannot find, and which matters more the larger the catalog grows.

    Best effort: CREATE EXTENSION needs privileges a managed database may
    not grant. Without it the query tool still works; the model just gets
    an "unknown function" error if it tries similarity(), and falls back.
    """
    try:
        async with pool.connection() as conn:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    except psycopg.Error as exc:
        logger.warning(
            "pg_trgm not available; near-duplicate search disabled | error=%s",
            str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__,
        )


async def grant_agent_read(agent_role: AgentRole) -> bool:
    """Let model-written SQL read the catalog view — the view, never the
    table, so the tenant filter cannot be bypassed."""
    return await agent_role.grant_select(CATALOG_VIEW)
