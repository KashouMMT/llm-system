"""The /recycle command namespace: scan_image, scan_video, build_catalog,
show_catalog.

One namespace, one handler (handle_recycle) that dispatches on
context.subcommand — same shape as clock's /clock. Every subcommand is
deterministic: it runs the pipeline directly and writes Markdown as the
assistant message, never through the LLM, so a 40-row table can never be
dropped or paraphrased by a model relaying it. The full structured result
is also attached as a text file on the same message (read back later via
the existing read_attachment tool), so a follow-up question about the scan
still has the complete data available even after the conversation has been
summarized past the point the Markdown table itself would survive.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from openai import OpenAI

from app.plugins.contracts import CommandContext, CommandHandler, PluginCommand
from app.plugins.recycling.pipeline.build import (
    EnrichedItem,
    assemble,
    cluster,
    enrich,
    merge_into_catalog,
    reconcile,
)
from app.plugins.recycling.pipeline.catalog import Catalog, CatalogError, ItemMetadata
from app.plugins.recycling.pipeline.labels import normalize
from app.plugins.recycling.pipeline.resolve import (
    Resolution,
    ResolvedItem,
    UnmatchedItem,
)
from app.plugins.recycling.pipeline.vision import DetectionError
from app.plugins.recycling.runner import DEFAULT_MIN_RUNS_SEEN, harvest, scan
from app.repositories.file_repository import FileRepository
from app.storage.base import FileStorage
from app.utils.detect import IMAGE_CONTENT_TYPES, TEXT_PLAIN
from app.utils.logger import logger

CATALOG_PATH = Path(__file__).resolve().parent / "catalog.json"


def _load_catalog_or_empty() -> Catalog:
    """Catalog.load(), except a missing file means "no catalog built yet"
    rather than an error. Every command that reads the catalog must
    survive it being deleted or not yet built — scan_image then reports
    everything as unmatched (correct: nothing is known yet), and
    build_catalog bootstraps a fresh one instead of failing.
    """
    if not CATALOG_PATH.is_file():
        return Catalog([])
    return Catalog.load(CATALOG_PATH)


# Detection passes per photo for build_catalog's harvest stage. Matches
# the original playground/build_catalog.py CLI's default.
BUILD_CATALOG_RUNS = 2

_HELP = (
    "Available: `scan_image`, `scan_video`, `build_catalog`, "
    "`build_catalog_force`, `show_catalog`"
)


# --------------------------------------------------------------------------
# Attachments
# --------------------------------------------------------------------------


async def _attached_images(
    context: CommandContext,
    *,
    file_repository: FileRepository,
    file_storage: FileStorage,
) -> tuple[list[tuple[str, bytes]], list[str]]:
    """Images attached to the command's own message, and the filenames of
    any non-image attachments it ignored — never silently, per the
    project's one rule: nothing is dropped without being reported.
    """
    files = await file_repository.get_by_message_ids([context.user_message_id])

    images: list[tuple[str, bytes]] = []
    skipped: list[str] = []

    for file in files:
        if file.content_type in IMAGE_CONTENT_TYPES:
            data = await file_storage.read(file.storage_key)
            images.append((file.filename, data))
        else:
            skipped.append(file.filename)

    return images, skipped


async def _attach_json(
    context: CommandContext,
    *,
    file_repository: FileRepository,
    file_storage: FileStorage,
    filename: str,
    payload: object,
) -> None:
    """Attach a JSON payload to the command's own assistant message, as a
    text/plain file — read_attachment already reads text, so this needs no
    new tool. document_type='recycle_scan' names the migration that added
    it to the files table's document_type check constraint.
    """
    data = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
    storage_key = await file_storage.write(data, extension="txt")

    await file_repository.create(
        conversation_id=context.conversation_id,
        user_id=context.user.id,
        origin="generated",
        document_type="recycle_scan",
        filename=filename,
        storage_key=storage_key,
        content_type=TEXT_PLAIN,
        size_bytes=len(data),
        message_id=context.assistant_message_id,
    )


# --------------------------------------------------------------------------
# Markdown rendering
# --------------------------------------------------------------------------


def _fmt_number(value: float | None, unit: str, places: int = 1) -> str:
    return "?" if value is None else f"{value:.{places}f}{unit}"


def _fmt_count(item: ResolvedItem) -> str:
    if item.count_min == item.count_max:
        return str(item.count)
    return f"{item.count} ({item.count_min}-{item.count_max})"


def _render_matched_table(items: list[ResolvedItem], title: str) -> str:
    if not items:
        return f"**{title}:** none"

    lines = [
        f"**{title} ({len(items)}):**",
        "",
        "| Item | Count | Weight | Volume | Agreement |",
        "|---|---|---|---|---|",
    ]
    for item in items:
        flag = " ⚠" if item.count_is_unstable else ""
        lines.append(
            f"| {item.label}{flag} | {_fmt_count(item)} | "
            f"{_fmt_number(item.total_weight_kg, ' kg')} | "
            f"{_fmt_number(item.total_volume_m3, ' m3', 2)} | "
            f"{item.runs_seen}/{item.total_runs} |"
        )
    return "\n".join(lines)


def _render_unmatched_table(items: list[UnmatchedItem], title: str) -> str:
    if not items:
        return f"**{title}:** none"

    lines = [f"**{title} ({len(items)}):**", "", "| Item | Count | Agreement |", "|---|---|---|"]
    for item in items:
        lines.append(f"| {item.label} | {item.count} | {item.runs_seen}/{item.total_runs} |")
    return "\n".join(lines)


def _render_totals(resolution: Resolution) -> str:
    lines = [
        "**Totals:**",
        f"- Kinds: {len(resolution.matched)}",
        f"- Units: {sum(item.count for item in resolution.matched)}",
        f"- Weight: {_fmt_number(resolution.total_weight_kg, ' kg')}",
        f"- Volume: {_fmt_number(resolution.total_volume_m3, ' m3', 2)}",
    ]
    incomplete = resolution.items_missing_metadata
    if incomplete:
        names = ", ".join(item.label for item in incomplete[:6])
        suffix = ", ..." if len(incomplete) > 6 else ""
        lines.append(
            f"- ⚠ totals exclude {len(incomplete)} item(s) with missing metadata: "
            f"{names}{suffix}"
        )
    return "\n".join(lines)


def _render_low_agreement(low: Resolution, min_runs_seen: int) -> str:
    title = f"Low agreement — seen in fewer than {min_runs_seen} runs, not counted"
    lines = [f"**{title}:**", ""]
    for item in low.matched:
        lines.append(f"- {item.label} x{item.count} ({item.runs_seen}/{item.total_runs} runs)")
    for item in low.unmatched:
        lines.append(
            f"- {item.label} x{item.count} ({item.runs_seen}/{item.total_runs} runs) "
            "[not in catalog]"
        )
    if low.excluded:
        lines.append(f"- (+{len(low.excluded)} excluded by catalog)")
    return "\n".join(lines)


def render_scan_result(confident: Resolution, low: Resolution, min_runs_seen: int) -> str:
    """Every section estimate.py's CLI prints, in Markdown: Collectable,
    Totals, Excluded by catalog, Not in catalog, Low agreement. Nothing
    detected is ever dropped without appearing in one of these.
    """
    sections = [
        _render_matched_table(confident.matched, "Collectable"),
        "",
        _render_totals(confident),
    ]
    if confident.excluded:
        sections += ["", _render_matched_table(confident.excluded, "Excluded by catalog")]
    if confident.unmatched:
        sections += [
            "",
            _render_unmatched_table(confident.unmatched, "Not in catalog — needs a human"),
        ]
    if low.matched or low.unmatched or low.excluded:
        sections += ["", _render_low_agreement(low, min_runs_seen)]
    return "\n".join(sections)


def _resolved_item_payload(item: ResolvedItem) -> dict:
    return {
        "id": item.catalog_item.id,
        "label": item.label,
        "observed_labels": item.observed_labels,
        "count": item.count,
        "count_min": item.count_min,
        "count_max": item.count_max,
        "count_is_unstable": item.count_is_unstable,
        "runs_seen": item.runs_seen,
        "total_runs": item.total_runs,
        "total_weight_kg": item.total_weight_kg,
        "total_volume_m3": item.total_volume_m3,
        "metadata": item.metadata.model_dump(),
    }


def _resolution_payload(resolution: Resolution) -> dict:
    return {
        "matched": [_resolved_item_payload(item) for item in resolution.matched],
        "excluded": [_resolved_item_payload(item) for item in resolution.excluded],
        "unmatched": [item.model_dump() for item in resolution.unmatched],
    }


# --------------------------------------------------------------------------
# Subcommands
# --------------------------------------------------------------------------


def _make_scan_image(
    *, client: OpenAI, model: str, file_repository: FileRepository, file_storage: FileStorage
) -> CommandHandler:
    async def scan_image(context: CommandContext) -> str:
        images, skipped = await _attached_images(
            context, file_repository=file_repository, file_storage=file_storage
        )

        if not images:
            message = (
                "No images attached. Attach one or more photos and run "
                "`/recycle scan_image` again."
            )
            if skipped:
                message += f"\n\nIgnored non-image attachment(s): {', '.join(skipped)}"
            return message

        try:
            catalog = _load_catalog_or_empty()
        except CatalogError as exc:
            return f"Could not load the catalog: {exc}"

        try:
            confident, low = await scan(
                [data for _, data in images],
                client=client,
                model=model,
                catalog=catalog,
            )
        except DetectionError as exc:
            return f"Scan failed: {exc}"

        header = f"Scanned {len(images)} image(s)."
        if skipped:
            header += f" Ignored non-image attachment(s): {', '.join(skipped)}."

        await _attach_json(
            context,
            file_repository=file_repository,
            file_storage=file_storage,
            filename="recycle_scan_result.json",
            payload={
                **_resolution_payload(confident),
                "low_agreement": _resolution_payload(low),
                "totals": {
                    "weight_kg": confident.total_weight_kg,
                    "volume_m3": confident.total_volume_m3,
                    "price": confident.total_price,
                },
            },
        )

        body = render_scan_result(confident, low, DEFAULT_MIN_RUNS_SEEN)
        return f"{header}\n\n{body}"

    return scan_image


async def scan_video(context: CommandContext) -> str: 
    return (
        "`/recycle scan_video` is not implemented yet — video needs OpenCV "
        "keyframe sampling, which has not been built (TODO §11a / phase 7). "
        "For now, attach one or more still photos and use `/recycle scan_image` "
        "instead; several photos of the same room already get deduplicated "
        "across views."
    )


def _make_build_catalog(
    *,
    client: OpenAI,
    model: str,
    file_repository: FileRepository,
    file_storage: FileStorage,
    force: bool,
) -> CommandHandler:
    command_name = "build_catalog_force" if force else "build_catalog"

    async def build_catalog(context: CommandContext) -> str:
        images, skipped = await _attached_images(
            context, file_repository=file_repository, file_storage=file_storage
        )

        if not images:
            message = (
                "No images attached. Attach one or more photos and run "
                f"`/recycle {command_name}` again."
            )
            if skipped:
                message += f"\n\nIgnored non-image attachment(s): {', '.join(skipped)}"
            return message

        try:
            frequencies = await harvest(
                [data for _, data in images],
                client=client,
                model=model,
                runs=BUILD_CATALOG_RUNS,
            )
        except DetectionError as exc:
            return f"Harvest failed: {exc}"

        if not frequencies:
            return "No labels were detected across the attached images."

        try:
            clusters = cluster(frequencies, client=client, model=model)
        except DetectionError as exc:
            return f"Clustering failed: {exc}"

        clusters, missing = reconcile(clusters, list(frequencies))

        wanted = [
            normalize(item.canonical_label) for item in clusters if not item.excluded
        ]
        try:
            enriched: dict[str, EnrichedItem] = enrich(wanted, client=client, model=model)
        except DetectionError as exc:
            return f"Enrichment failed: {exc}"

        try:
            scanned_catalog, conflicts = assemble(clusters, enriched, frequencies)
        except CatalogError as exc:
            return f"Could not assemble the catalog: {exc}"

        try:
            existing_catalog = _load_catalog_or_empty()
            result = merge_into_catalog(existing_catalog, scanned_catalog, force=force)
        except CatalogError as exc:
            return f"Could not merge into the catalog: {exc}"

        result.catalog.save(CATALOG_PATH)

        included = [item for item in result.catalog if not item.excluded]
        incomplete = result.catalog.incomplete()

        notes: list[str] = []
        if missing:
            notes.append(
                f"clustering skipped {len(missing)} label(s), restored as unmerged "
                f"rows: {', '.join(missing[:8])}"
            )
        notes.extend(conflicts)
        if result.kept_existing:
            verb = "kept unchanged" if not force else "kept (no match found to replace)"
            notes.append(
                f"{len(result.kept_existing)} item(s) already existed and were "
                f"{verb}: {', '.join(result.kept_existing[:8])}"
                + (
                    " — use `/recycle build_catalog_force` to overwrite them with this scan"
                    if not force
                    else ""
                )
            )
        if incomplete:
            notes.append(
                f"{len(incomplete)} collectable item(s) missing weight or volume: "
                + ", ".join(item.canonical_label for item in incomplete[:8])
            )

        header = (
            f"Scanned {len(images)} image(s): {len(result.added)} new item(s) added"
        )
        if force:
            header += f", {len(result.replaced)} replaced with the newer scan"
        header += (
            f". Catalog now has {len(result.catalog)} item(s) total "
            f"({len(included)} collectable, {len(result.catalog) - len(included)} excluded)."
        )
        if skipped:
            header += f" Ignored non-image attachment(s): {', '.join(skipped)}."

        lines = [header]
        if notes:
            lines += ["", "**Check these during review:**"]
            lines += [f"- {note}" for note in notes]
        lines += [
            "",
            (
                "**This catalog has not been fully reviewed.** The model gets "
                "granularity and exclusions wrong often enough that a human pass "
                "is not optional — run `/recycle show_catalog` to check it before "
                "relying on it."
            ),
        ]

        await _attach_json(
            context,
            file_repository=file_repository,
            file_storage=file_storage,
            filename="catalog.json",
            payload=json.loads(CATALOG_PATH.read_text(encoding="utf-8")),
        )

        return "\n".join(lines)

    return build_catalog


async def show_catalog(context: CommandContext) -> str:  
    try:
        catalog = Catalog.load(CATALOG_PATH)
    except CatalogError as exc:
        return f"Could not load the catalog: {exc}"

    if len(catalog) == 0:
        return "The catalog is empty. Run `/recycle build_catalog` with some photos first."

    lines = [
        f"**Catalog ({len(catalog)} items):**",
        "",
        "| ID | Label | Excluded | Weight | Dimensions | Material |",
        "|---|---|---|---|---|---|",
    ]
    for item in catalog:
        metadata: ItemMetadata = item.metadata
        lines.append(
            f"| {item.id} | {item.canonical_label} | "
            f"{'yes' if item.excluded else ''} | "
            f"{_fmt_number(metadata.weight_kg, ' kg')} | "
            f"{metadata.dimensions} | "
            f"{metadata.material or '?'} |"
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------


def make_recycle_commands(
    *,
    client: OpenAI,
    model: str,
    file_repository: FileRepository,
    file_storage: FileStorage,
) -> tuple[PluginCommand, ...]:
    """Build the /recycle command with its dependencies bound in — same
    closure-factory shape as make_document_tools and make_attachment_tools.
    """
    subcommands: dict[str, CommandHandler] = {
        "scan_image": _make_scan_image(
            client=client, model=model, file_repository=file_repository, file_storage=file_storage
        ),
        "scan_video": scan_video,
        "build_catalog": _make_build_catalog(
            client=client,
            model=model,
            file_repository=file_repository,
            file_storage=file_storage,
            force=False,
        ),
        "build_catalog_force": _make_build_catalog(
            client=client,
            model=model,
            file_repository=file_repository,
            file_storage=file_storage,
            force=True,
        ),
        "show_catalog": show_catalog,
    }

    async def handle_recycle(context: CommandContext) -> str:
        start = time.perf_counter()
        handler = subcommands.get(context.subcommand)

        logger.info(
            "Command started | command=/recycle %s conversation=%s",
            context.subcommand,
            context.conversation_id,
        )

        if handler is None:
            result = f"Unknown `/recycle` subcommand: `{context.subcommand}`.\n\n{_HELP}"
        else:
            result = await handler(context)

        logger.info(
            "Command completed | command=/recycle %s elapsed=%.2fs",
            context.subcommand,
            time.perf_counter() - start,
        )

        return result

    return (
        PluginCommand(
            namespace="recycle",
            handler=handle_recycle,
            help_text=(
                "/recycle scan_image <images>, scan_video <video> (not yet "
                "implemented), build_catalog <images> (adds new items, never "
                "touches existing ones), build_catalog_force <images> (also "
                "overwrites matching existing items with the new scan), "
                "show_catalog"
            ),
        ),
    )
