"""Catalog knowledge: the model reads the catalog with SQL and edits it one
row at a time.

Reads and writes take deliberately different paths:

- **Reads are free-form SQL** (recycle_query_catalog), because analysis
  questions are open-ended — "which labels look like duplicates", "what is
  heavier than its own maximum". The SQL runs as the agent database role
  through AgentRole.query, which can read the catalog view and nothing
  else. The rows go to the model, not the user: here the model is meant to
  reason over them, not relay them.
- **Writes are typed, one row per call** (create / update / delete), never
  model-written SQL. A raw UPDATE missing its WHERE clause rewrites every
  row, and no database permission can tell that from a correct one. A
  typed call names one row, every value passes the pipeline's own Pydantic
  models, and an alias clash is caught by the same Catalog index scans use.
  The exact change is shown to the user as a reply block — nothing written
  to the catalog is invisible to a human.

Every tool is admin-only, checked here against the run config. Whether a
write should need the user's click first is the permission-mode work
(Manual / Accept edits / Auto) planned after this; the tools are shaped so
that can sit in front of them without changing them.
"""

import json
import time
from typing import Any, Literal

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field, ValidationError

from app.database.agent_role import AgentQueryError, AgentRole
from app.plugins.recycling import prompts
from app.plugins.recycling.database import CatalogRepository, CatalogStorageError
from app.plugins.recycling.pipeline.catalog import (
    Catalog,
    CatalogError,
    CatalogItem,
    make_id,
)
from app.plugins.run_context import RunIdentity, run_identity
from app.services.reply_blocks import ReplyBlocks
from app.utils.logger import logger

# Enough to list a catalog page or read a grouped summary; a whole
# 10k-row catalog is meant to be counted and grouped in SQL, never read
# row by row, and the cut message says so.
MAX_QUERY_ROWS = 200
MAX_QUERY_CHARS = 20_000

MetadataSourceArg = Literal["llm_estimate", "measured", "client_supplied", "unknown"]


# --------------------------------------------------------------------------
# Argument schemas
# --------------------------------------------------------------------------


class _ValueFields(BaseModel):
    """Every field a person may set on a catalog row, except its label. Not
    id (the stable key scan results reference), observations (a harvest
    count) or updated_at — the system owns those.

    Always passed NESTED (`changes` / `values`), never as top-level tool
    arguments: LangChain fills every omitted top-level argument with its
    default, so "not sent" and "sent as null" arrive identical. A nested
    model keeps Pydantic's model_fields_set, which is what lets an edit
    touch only the fields the model named — and still clear one with null.
    """

    aliases: list[str] | None = Field(
        None, description="Other names that should match this row. Replaces the list."
    )
    visual_class: str | None = Field(None, description="What a detector looks for.")
    excluded: bool | None = Field(None, description="True: detected but never collected.")
    exclusion_reason: str | None = None
    weight_kg: float | None = Field(None, description="Typical weight of one unit, kg.")
    weight_kg_min: float | None = None
    weight_kg_max: float | None = None
    length_cm: float | None = Field(None, description="Bounding box, largest side first.")
    width_cm: float | None = None
    height_cm: float | None = None
    volume_m3: float | None = Field(None, description="Only when not the bounding box.")
    material: str | None = Field(None, description="English, lowercase, e.g. 'wood'.")
    nestable: bool | None = None
    stackable: bool | None = None
    unit_price: float | None = None
    currency: str | None = None
    extra: dict[str, str] | None = Field(
        None, description="Client-specific string fields. Replaces the map."
    )
    source: MetadataSourceArg | None = Field(
        None, description="Where the metadata came from; 'client_supplied' for figures the user gives."
    )


class _ItemFields(_ValueFields):
    canonical_label: str | None = Field(None, description="Display name, in English.")


class _CreateArgs(BaseModel):
    canonical_label: str = Field(description="Display name, in English. The id is derived from it.")
    copy_from_id: str | None = Field(
        None, description="Start from this existing row's values."
    )
    values: _ValueFields | None = Field(
        None, description="Values for the new row; omit what is unknown."
    )


class _UpdateArgs(BaseModel):
    item_id: str = Field(description="id of the row to change.")
    changes: _ItemFields = Field(
        description="Only the fields to change. null clears a field."
    )


class _DeleteArgs(BaseModel):
    item_id: str = Field(description="id of the row to delete.")


class _QueryArgs(BaseModel):
    sql: str = Field(description="One read-only SELECT over recycling_catalog.")


_ITEM_KEYS = {"canonical_label", "aliases", "visual_class", "excluded", "exclusion_reason"}
_DIMENSION_KEYS = {"length_cm", "width_cm", "height_cm"}
_EDITABLE = set(_ItemFields.model_fields)

# Display order for the tables the user sees.
_FIELD_ORDER = [
    "canonical_label",
    "aliases",
    "visual_class",
    "excluded",
    "exclusion_reason",
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
    "observations",
]


# --------------------------------------------------------------------------
# Row helpers
# --------------------------------------------------------------------------


class _Rejected(Exception):
    """An edit that must not be written, with a reason the model can relay."""


def _provided(fields: BaseModel | dict | None) -> dict[str, Any]:
    """Only the fields the model actually sent, explicit nulls included."""
    if fields is None:
        return {}
    if isinstance(fields, dict):
        return dict(fields)
    return {key: getattr(fields, key) for key in fields.model_fields_set}


def _apply(item: CatalogItem, changes: dict[str, Any]) -> CatalogItem:
    """A new CatalogItem with `changes` applied, validated by the model the
    pipeline itself uses. Only keys present in `changes` are touched; an
    explicit None clears a field (aliases and extra clear to empty)."""
    data = item.model_dump()

    for key, value in changes.items():
        if key not in _EDITABLE:
            continue
        if key in _ITEM_KEYS:
            data[key] = [] if key == "aliases" and value is None else value
        elif key in _DIMENSION_KEYS:
            data["metadata"]["dimensions"][key] = value
        else:
            data["metadata"][key] = {} if key == "extra" and value is None else value

    try:
        updated = CatalogItem.model_validate(data)
    except ValidationError as exc:
        errors = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        raise _Rejected(f"invalid value — {errors}.") from exc

    # Format, not completeness — but a row with no name cannot be shown,
    # matched or edited again.
    if not updated.canonical_label.strip():
        raise _Rejected("canonical_label must not be empty.")

    return updated


def _check_aliases(catalog: Catalog, candidate: CatalogItem) -> None:
    """Build the catalog as it would be after the edit. Catalog's own index
    raises when a name is claimed by two rows — the same check every scan
    relies on, so an edit can never leave the catalog unloadable."""
    others = [item for item in catalog.items if item.id != candidate.id]
    try:
        Catalog([*others, candidate])
    except CatalogError as exc:
        raise _Rejected(str(exc)) from exc


def _flatten(item: CatalogItem) -> dict[str, Any]:
    metadata = item.metadata
    return {
        "canonical_label": item.canonical_label,
        "aliases": item.aliases,
        "visual_class": item.visual_class,
        "excluded": item.excluded,
        "exclusion_reason": item.exclusion_reason,
        "weight_kg": metadata.weight_kg,
        "weight_kg_min": metadata.weight_kg_min,
        "weight_kg_max": metadata.weight_kg_max,
        "length_cm": metadata.dimensions.length_cm,
        "width_cm": metadata.dimensions.width_cm,
        "height_cm": metadata.dimensions.height_cm,
        "volume_m3": metadata.volume_m3,
        "material": metadata.material,
        "nestable": metadata.nestable,
        "stackable": metadata.stackable,
        "unit_price": metadata.unit_price,
        "currency": metadata.currency,
        "extra": metadata.extra,
        "source": metadata.source,
        "observations": item.observations,
    }


def _display(value: Any) -> str:
    if value is None or value == [] or value == {} or value == "":
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, list):
        text = ", ".join(str(part) for part in value)
    elif isinstance(value, dict):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value)
    # A pipe or newline would break the Markdown table row.
    return text.replace("|", "/").replace("\n", " ")


def _row_table(item: CatalogItem) -> list[str]:
    flat = _flatten(item)
    lines = ["| Field | Value |", "|---|---|", f"| id | {item.id} |"]
    lines += [f"| {key} | {_display(flat[key])} |" for key in _FIELD_ORDER]
    return lines


def _diff(before: CatalogItem, after: CatalogItem) -> list[tuple[str, str, str]]:
    old, new = _flatten(before), _flatten(after)
    return [
        (key, _display(old[key]), _display(new[key]))
        for key in _FIELD_ORDER
        if old[key] != new[key]
    ]


def _short(changes: list[tuple[str, str, str]]) -> str:
    return "; ".join(f"{key}: {old} → {new}" for key, old, new in changes)


# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------


def make_catalog_tools(
    *,
    catalog_repository: CatalogRepository,
    agent_role: AgentRole,
    reply_blocks: ReplyBlocks,
) -> list[BaseTool]:
    def guard(config: RunnableConfig, tool_name: str) -> tuple[RunIdentity, str | None]:
        """(identity, refusal). Refusal is None when the caller may proceed."""
        who = run_identity(config)
        logger.info("Tool started | tool=%s conversation=%s", tool_name, who.conversation_id)

        if not who.is_admin:
            logger.warning(
                "Tool refused, admin only | tool=%s user=%s conversation=%s",
                tool_name,
                who.user.id,
                who.conversation_id,
            )
            return who, prompts.ADMIN_ONLY

        return who, None

    def finish(tool_name: str, start: float, outcome: str) -> None:
        logger.info(
            "Tool completed | tool=%s outcome=%s elapsed=%.2fs",
            tool_name,
            outcome,
            time.perf_counter() - start,
        )

    def publish(who: RunIdentity, markdown: str, summary: str, detail: str) -> str:
        """Show the change to the user; the model gets the summary. If it
        cannot be shown, the write has still happened — the model must say
        so rather than imply nothing changed."""
        if reply_blocks.publish(who.assistant_message_id, markdown):
            return summary
        return prompts.EDIT_NOT_DISPLAYED.format(detail=detail)

    # ---- read ----------------------------------------------------------

    async def query_catalog(config: RunnableConfig, sql: str) -> str:
        name, start = "recycle_query_catalog", time.perf_counter()
        _who, refusal = guard(config, name)
        if refusal:
            return refusal

        if not agent_role.ready:
            finish(name, start, "disabled")
            return prompts.QUERY_DISABLED

        # Whitespace collapsed to one line, but long enough to keep a whole
        # analysis query: at 500 characters a multi-condition filter was
        # cut mid-WHERE, and its shape could not be read from the app log.
        logger.info("Agent query | sql=%s", " ".join(sql.split())[:4000])

        try:
            result = await agent_role.query(sql, max_rows=MAX_QUERY_ROWS)
        except AgentQueryError as exc:
            finish(name, start, "error")
            return prompts.QUERY_FAILED.format(error=exc)

        finish(name, start, f"rows={len(result.rows)} truncated={result.truncated}")
        return result.as_text(MAX_QUERY_CHARS)

    # ---- create --------------------------------------------------------

    async def create_item(
        config: RunnableConfig,
        canonical_label: str,
        copy_from_id: str | None = None,
        values: _ValueFields | None = None,
    ) -> str:
        name, start = "recycle_create_catalog_item", time.perf_counter()
        who, refusal = guard(config, name)
        if refusal:
            return refusal

        fields = {**_provided(values), "canonical_label": canonical_label}

        try:
            label = (canonical_label or "").strip()
            if not label:
                raise _Rejected("canonical_label must not be empty.")

            item_id = make_id(label)
            catalog = await catalog_repository.load()

            if catalog.by_id(item_id) is not None:
                raise _Rejected(
                    f"a row with id `{item_id}` already exists. Update it instead, "
                    "or choose a different label."
                )

            if copy_from_id:
                source_row = catalog.by_id(copy_from_id)
                if source_row is None:
                    raise _Rejected(f"no row with id `{copy_from_id}` to copy from.")
                # Aliases are not copied: the same name on two rows is an
                # alias clash, and would stop the catalog loading.
                base = source_row.model_copy(
                    update={"id": item_id, "aliases": [], "observations": 0}, deep=True
                )
            else:
                base = CatalogItem(id=item_id, canonical_label=label)

            new_item = _apply(base, fields)
            _check_aliases(catalog, new_item)
            await catalog_repository.insert(new_item)
        except _Rejected as exc:
            finish(name, start, "rejected")
            return prompts.EDIT_REJECTED.format(reason=str(exc))
        except (CatalogError, CatalogStorageError) as exc:
            finish(name, start, "error")
            return prompts.EDIT_REJECTED.format(reason=f"the catalog could not be read or written ({exc}).")

        origin = f" (copied from `{copy_from_id}`)" if copy_from_id else ""
        markdown = "\n".join(
            [f"**Catalog row added — `{new_item.id}`**{origin}", "", *_row_table(new_item)]
        )
        detail = f"label {new_item.canonical_label!r}{origin}"
        finish(name, start, "created")
        return publish(
            who,
            markdown,
            prompts.edit_summary(action="Added", item_id=new_item.id, detail=detail),
            f"added `{new_item.id}`, {detail}",
        )

    # ---- update --------------------------------------------------------

    async def update_item(config: RunnableConfig, item_id: str, changes: _ItemFields) -> str:
        name, start = "recycle_update_catalog_item", time.perf_counter()
        who, refusal = guard(config, name)
        if refusal:
            return refusal

        fields = _provided(changes)

        try:
            catalog = await catalog_repository.load()
            before = catalog.by_id(item_id)
            if before is None:
                raise _Rejected(f"no row with id `{item_id}`.")

            after = _apply(before, fields)
            changes = _diff(before, after)
            if not changes:
                finish(name, start, "no_change")
                return prompts.EDIT_REJECTED.format(
                    reason=f"`{item_id}` already has those values."
                )

            _check_aliases(catalog, after)
            if not await catalog_repository.update(after):
                raise _Rejected(f"`{item_id}` was removed before the change could be saved.")
        except _Rejected as exc:
            finish(name, start, "rejected")
            return prompts.EDIT_REJECTED.format(reason=str(exc))
        except (CatalogError, CatalogStorageError) as exc:
            finish(name, start, "error")
            return prompts.EDIT_REJECTED.format(reason=f"the catalog could not be read or written ({exc}).")

        markdown = "\n".join(
            [
                f"**Catalog row updated — `{item_id}`**",
                "",
                "| Field | Before | After |",
                "|---|---|---|",
                *(f"| {key} | {old} | {new} |" for key, old, new in changes),
            ]
        )
        detail = _short(changes)
        finish(name, start, f"updated fields={len(changes)}")
        return publish(
            who,
            markdown,
            prompts.edit_summary(action="Updated", item_id=item_id, detail=detail),
            f"updated `{item_id}`: {detail}",
        )

    # ---- delete --------------------------------------------------------

    async def delete_item(config: RunnableConfig, item_id: str) -> str:
        name, start = "recycle_delete_catalog_item", time.perf_counter()
        who, refusal = guard(config, name)
        if refusal:
            return refusal

        try:
            removed = await catalog_repository.get(item_id)
            if removed is None or not await catalog_repository.delete(item_id):
                raise _Rejected(f"no row with id `{item_id}`.")
        except _Rejected as exc:
            finish(name, start, "rejected")
            return prompts.EDIT_REJECTED.format(reason=str(exc))
        except CatalogStorageError as exc:
            finish(name, start, "error")
            return prompts.EDIT_REJECTED.format(reason=f"the catalog could not be read or written ({exc}).")

        # The whole removed row, not just its id: a deleted row is exactly
        # what a reviewer must be able to see and put back.
        markdown = "\n".join(
            [f"**Catalog row deleted — `{item_id}`**", "", *_row_table(removed)]
        )
        detail = f"label {removed.canonical_label!r}"
        finish(name, start, "deleted")
        return publish(
            who,
            markdown,
            prompts.edit_summary(action="Deleted", item_id=item_id, detail=detail),
            f"deleted `{item_id}`, {detail}",
        )

    return [
        StructuredTool.from_function(
            coroutine=query_catalog,
            name="recycle_query_catalog",
            description=prompts.QUERY_CATALOG_DESCRIPTION,
            args_schema=_QueryArgs,
        ),
        StructuredTool.from_function(
            coroutine=create_item,
            name="recycle_create_catalog_item",
            description=prompts.CREATE_ITEM_DESCRIPTION,
            args_schema=_CreateArgs,
        ),
        StructuredTool.from_function(
            coroutine=update_item,
            name="recycle_update_catalog_item",
            description=prompts.UPDATE_ITEM_DESCRIPTION,
            args_schema=_UpdateArgs,
        ),
        StructuredTool.from_function(
            coroutine=delete_item,
            name="recycle_delete_catalog_item",
            description=prompts.DELETE_ITEM_DESCRIPTION,
            args_schema=_DeleteArgs,
        ),
    ]
