"""The /recycle command namespace: scan (aliases scan_image, scan_video),
build_catalog, build_catalog_force, show_catalog. scan and both
build_catalog variants take one room video or one or more photos.

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
from dataclasses import dataclass, field

from openai import OpenAI

from app.plugins.command_help import render_subcommand_lines
from app.plugins.contracts import (
    CommandContext,
    CommandHandler,
    PluginCommand,
    SubcommandSpec,
)
from app.plugins.recycling.database import CatalogRepository, CatalogStorageError
from app.plugins.recycling.pipeline.build import (
    EnrichedItem,
    assemble,
    cluster,
    enrich,
    merge_into_catalog,
    reconcile,
)
from app.plugins.recycling.pipeline.catalog import (
    CatalogError,
    CatalogFile,
    ItemMetadata,
)
from app.plugins.recycling.pipeline.labels import normalize
from app.plugins.recycling.pipeline.resolve import (
    Resolution,
    ResolvedItem,
    UnmatchedItem,
)
from app.plugins.recycling.pipeline.vision import DetectionError
from app.plugins.recycling.runner import (
    DEFAULT_MIN_RUNS_SEEN,
    harvest,
    scan,
    scan_video,
    video_frames,
)
from app.repositories.file_repository import FileRecord, FileRepository
from app.storage.base import FileStorage
from app.utils.detect import IMAGE_CONTENT_TYPES, TEXT_PLAIN, VIDEO_CONTENT_TYPES
from app.utils.logger import logger
from app.utils.video_frames import (
    DEFAULT_FRAME_COUNT,
    MAX_FRAME_COUNT,
    MIN_FRAME_COUNT,
    FrameExtractionError,
    FrameSample,
)

# What the user sees when the catalog table cannot be read or written.
# Deliberately no database detail: the repository has already logged the
# full error, and the chat is not where a stack trace belongs.
_STORAGE_FAILED = "Could not reach the item catalog (database error — details are in the server log)."

# Detection passes per photo for build_catalog's harvest stage. Matches
# the original playground/build_catalog.py CLI's default.
BUILD_CATALOG_RUNS = 2

_CAPTURE = "one room video alone (video button), or one or more photos"

# The one description of /recycle. ChatService, the system prompt and
# GET /commands all read this; see app/plugins/command_help.py.
SUBCOMMANDS = (
    SubcommandSpec(
        name="scan",
        usage="[frames]",
        summary=(
            "Estimate the collectable items in a room — counts, approximate "
            "weight, dimensions, volume and material — as a table for staff "
            "review, with the full result attached as JSON. `frames` (4–40, "
            f"default {DEFAULT_FRAME_COUNT}) applies to a video only."
        ),
        attachments=_CAPTURE,
        aliases=("scan_image", "scan_video"),
    ),
    # Every catalog command is admin only. The build commands write the
    # catalog, which every scan depends on and a reviewer corrects by
    # hand; show_catalog exposes it — unreviewed rows, exclusion decisions
    # and, once prices are filled in, pricing — which is staff data, not
    # something a customer needs to get a scan.
    SubcommandSpec(
        name="build_catalog",
        usage="[frames]",
        summary=(
            "Detect items in a capture and ADD the ones not already in the "
            "catalog. Existing rows are never changed."
        ),
        attachments=_CAPTURE,
        admin_only=True,
    ),
    SubcommandSpec(
        name="build_catalog_force",
        usage="[frames]",
        summary=(
            "Like build_catalog, but also OVERWRITES matching existing rows "
            "with the new detection, replacing hand-reviewed data."
        ),
        attachments=_CAPTURE,
        admin_only=True,
    ),
    SubcommandSpec(
        name="show_catalog",
        summary="Show the item catalog as a table: label, excluded, weight, dimensions, material.",
        admin_only=True,
    ),
)


# --------------------------------------------------------------------------
# Attachments
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Media:
    """
    What the command's own message carries: one video, or photos — never
    both. `error` is set instead when the message cannot be scanned at all.
    """

    video: FileRecord | None = None
    images: list[tuple[str, bytes]] = field(default_factory=list)
    # Non-image attachments ignored beside photos — reported, never
    # silently dropped, per the project's one rule.
    skipped: list[str] = field(default_factory=list)
    error: str | None = None
    frame_count: int = DEFAULT_FRAME_COUNT


async def _attached_media(
    context: CommandContext,
    *,
    file_repository: FileRepository,
    file_storage: FileStorage,
) -> _Media:
    """
    Resolve the attachments and the `[frames]` argument together, because
    whether the argument is valid depends on what is attached.

    The one-video-alone rule is enforced by create_turn before any command
    runs; the check here is for a caller that did not come through it. So
    one command can take either kind of capture without the mixed case
    ever reaching the pipeline.
    """
    command = f"/recycle {context.subcommand}"
    files = await file_repository.get_by_message_ids([context.user_message_id])
    videos = [file for file in files if file.content_type in VIDEO_CONTENT_TYPES]
    argument = context.argument.strip()

    if videos:
        if len(files) > 1:
            return _Media(error="A video must be sent on its own: one video, no other attachments.")

        frame_count = _frame_count_argument(argument)

        if frame_count is None:
            return _Media(
                error=(
                    f"Frame count must be a number from {MIN_FRAME_COUNT} to "
                    f"{MAX_FRAME_COUNT}, e.g. `{command} 20`. Leave it out for "
                    f"the default of {DEFAULT_FRAME_COUNT}."
                )
            )

        return _Media(video=videos[0], frame_count=frame_count)

    # An error rather than ignored: the user typed a number expecting it to
    # change something, and for photos it cannot.
    if argument:
        return _Media(
            error=(
                f"A frame count only applies to a video. Photos are used as "
                f"attached — send `{command}` without `{argument}`."
            )
        )

    images: list[tuple[str, bytes]] = []
    skipped: list[str] = []

    for file in files:
        if file.content_type in IMAGE_CONTENT_TYPES:
            data = await file_storage.read(file.storage_key)
            images.append((file.filename, data))
        else:
            skipped.append(file.filename)

    if not images:
        message = (
            "Nothing to scan. Attach one room video with the video button, or "
            f"one or more photos, and send `{command}` with them."
        )
        if skipped:
            message += f"\n\nIgnored non-image attachment(s): {', '.join(skipped)}"
        return _Media(error=message)

    return _Media(images=images, skipped=skipped)


def _frame_count_argument(argument: str) -> int | None:
    """
    `[frames]` for a video. None means the argument is invalid.

    A tuning knob, not the quality presets the TODO describes: those trade
    frame count for time, and the accuracy curve they would be named after
    has not been measured yet.
    """
    if not argument:
        return DEFAULT_FRAME_COUNT

    if not argument.isdigit() or not MIN_FRAME_COUNT <= int(argument) <= MAX_FRAME_COUNT:
        return None

    return int(argument)


def _frame_check_header(filename: str, sample: FrameSample) -> list[str]:
    # Capture problems go above the table, not below it: a reviewer has to
    # read "half the video was too dark" before trusting the counts.
    return [f"Scanned `{filename}` — {sample.summary()}."] + [
        f"- ⚠ {warning}" for warning in sample.warnings
    ]


def _frame_check_payload(sample: FrameSample) -> dict:
    return {
        "candidates": sample.candidates,
        "used": len(sample.frames),
        "skipped": sample.skipped,
        "warnings": sample.warnings,
    }


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


def _render_excluded_line(items: list[ResolvedItem]) -> str:
    """
    Catalog-excluded items as one line, not a table.

    Mostly room structure — walls, floor, doors — which has no weight or
    volume, so a table of it was rows of "?" that buried the real result.
    Still listed rather than hidden: a reviewer has to be able to spot a
    detached door that the catalog excluded as "door". The full rows stay in
    the attached JSON.
    """
    names = ", ".join(
        f"{item.label} ×{item.count}" if item.count > 1 else item.label
        for item in items
    )
    return f"**Excluded by catalog ({len(items)}):** {names}"


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
        sections += ["", _render_excluded_line(confident.excluded)]
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


def _make_scan(
    *,
    client: OpenAI,
    model: str,
    file_repository: FileRepository,
    file_storage: FileStorage,
    catalog_repository: CatalogRepository,
) -> CommandHandler:
    """
    `/recycle scan [frames]` — one room video, or one or more photos.

    One command rather than scan_image + scan_video: both captures end in
    the same runner.scan over a list of images (a video is frames first),
    so the split only ever existed in this layer. scan_image and scan_video
    remain as aliases in the dispatch table.
    """

    async def scan_command(context: CommandContext) -> str:
        media = await _attached_media(
            context, file_repository=file_repository, file_storage=file_storage
        )

        if media.error:
            return media.error

        try:
            catalog = await catalog_repository.load()
        except CatalogError as exc:
            return f"Could not load the catalog: {exc}"
        except CatalogStorageError:
            return _STORAGE_FAILED

        sample: FrameSample | None = None

        try:
            if media.video is not None:
                outcome = await scan_video(
                    media.video,
                    file_storage=file_storage,
                    client=client,
                    model=model,
                    catalog=catalog,
                    frame_count=media.frame_count,
                )
                confident, low, sample = outcome.confident, outcome.low, outcome.sample
            else:
                confident, low = await scan(
                    [data for _, data in media.images],
                    client=client,
                    model=model,
                    catalog=catalog,
                )
        except FrameExtractionError as exc:
            return f"Could not scan `{media.video.filename}`: {exc}"
        except DetectionError as exc:
            return f"Scan failed: {exc}"

        if media.video is not None:
            header = _frame_check_header(media.video.filename, sample)
            source = {"kind": "video", "file": media.video.filename}
        else:
            header = [f"Scanned {len(media.images)} image(s)."]
            if media.skipped:
                header[0] += f" Ignored non-image attachment(s): {', '.join(media.skipped)}."
            source = {"kind": "images", "files": [name for name, _ in media.images]}

        payload = {
            # Which capture this came from, so a later read of the file can
            # say "the video" or "the 3 photos" without guessing.
            "source": source,
            **_resolution_payload(confident),
            "low_agreement": _resolution_payload(low),
            "totals": {
                "weight_kg": confident.total_weight_kg,
                "volume_m3": confident.total_volume_m3,
                "price": confident.total_price,
            },
        }
        if sample is not None:
            payload["frame_check"] = _frame_check_payload(sample)

        await _attach_json(
            context,
            file_repository=file_repository,
            file_storage=file_storage,
            filename="recycle_scan_result.json",
            payload=payload,
        )

        body = render_scan_result(confident, low, DEFAULT_MIN_RUNS_SEEN)

        return "\n".join(header) + f"\n\n{body}"

    return scan_command


def _make_build_catalog(
    *,
    client: OpenAI,
    model: str,
    file_repository: FileRepository,
    file_storage: FileStorage,
    catalog_repository: CatalogRepository,
    force: bool,
) -> CommandHandler:
    async def build_catalog(context: CommandContext) -> str:
        media = await _attached_media(
            context, file_repository=file_repository, file_storage=file_storage
        )

        if media.error:
            return media.error

        sample: FrameSample | None = None

        # A video is ONE source of many frames; each photo is its own
        # source. See runner.harvest for why frequencies count per source.
        if media.video is not None:
            try:
                sample = await video_frames(
                    media.video, file_storage=file_storage, frame_count=media.frame_count
                )
            except FrameExtractionError as exc:
                return f"Could not read `{media.video.filename}`: {exc}"

            sources = [[frame.jpeg for frame in sample.frames]]
        else:
            sources = [[data] for _, data in media.images]

        try:
            harvested = await harvest(
                sources,
                client=client,
                model=model,
                runs=BUILD_CATALOG_RUNS,
            )
        except DetectionError as exc:
            return f"Harvest failed: {exc}"

        frequencies = harvested.frequencies

        if not frequencies:
            return "No labels were detected in the attached capture."

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
            existing_catalog = await catalog_repository.load()
            result = merge_into_catalog(existing_catalog, scanned_catalog, force=force)
            await catalog_repository.save(result.catalog)
        except CatalogError as exc:
            return f"Could not merge into the catalog: {exc}"
        except CatalogStorageError:
            # The paid build ran and its result is lost; say so, rather
            # than the generic line, so nobody assumes it was saved.
            return (
                f"{_STORAGE_FAILED} The build finished but was **not saved** — "
                "the catalog is unchanged. Run the build again once the "
                "database is reachable."
            )

        included = [item for item in result.catalog if not item.excluded]
        incomplete = result.catalog.incomplete()

        notes: list[str] = []
        if harvested.failed_images:
            unit = "frame(s)" if media.video is not None else "photo(s)"
            notes.append(
                f"detection failed on {harvested.failed_images} {unit}; any item "
                "visible only there is missing from this build"
            )
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

        header = f"{len(result.added)} new item(s) added"
        if force:
            header += f", {len(result.replaced)} replaced with the newer scan"
        header += (
            f". Catalog now has {len(result.catalog)} item(s) total "
            f"({len(included)} collectable, {len(result.catalog) - len(included)} excluded)."
        )

        if sample is not None:
            lines = _frame_check_header(media.video.filename, sample) + ["", header]
        else:
            summary = f"Scanned {len(media.images)} image(s): {header}"
            if media.skipped:
                summary += f" Ignored non-image attachment(s): {', '.join(media.skipped)}."
            lines = [summary]
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
            # A snapshot for read_attachment after summarization, not a
            # file anything loads — the table is the catalog.
            filename="recycle_catalog_snapshot.json",
            payload=CatalogFile(
                version=result.catalog.version, items=result.catalog.items
            ).model_dump(mode="json"),
        )

        return "\n".join(lines)

    return build_catalog


def _make_show_catalog(*, catalog_repository: CatalogRepository) -> CommandHandler:
    async def show_catalog(context: CommandContext) -> str:
        try:
            catalog = await catalog_repository.load()
        except CatalogError as exc:
            return f"Could not load the catalog: {exc}"
        except CatalogStorageError:
            return _STORAGE_FAILED

        if len(catalog) == 0:
            return (
                "The catalog is empty. Run `/recycle build_catalog` with a room "
                "video or some photos first."
            )

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

    return show_catalog


# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------


def make_recycle_commands(
    *,
    client: OpenAI,
    model: str,
    file_repository: FileRepository,
    file_storage: FileStorage,
    catalog_repository: CatalogRepository,
) -> tuple[PluginCommand, ...]:
    """Build the /recycle command with its dependencies bound in — same
    closure-factory shape as make_document_tools and make_attachment_tools.
    """
    scan_handler = _make_scan(
        client=client,
        model=model,
        file_repository=file_repository,
        file_storage=file_storage,
        catalog_repository=catalog_repository,
    )

    # Canonical names only: ChatService resolves the scan_image / scan_video
    # aliases from SUBCOMMANDS before the handler runs. They are pure
    # aliases — `scan_video` with photos attached scans the photos.
    subcommands: dict[str, CommandHandler] = {
        "scan": scan_handler,
        "build_catalog": _make_build_catalog(
            client=client,
            model=model,
            file_repository=file_repository,
            file_storage=file_storage,
            catalog_repository=catalog_repository,
            force=False,
        ),
        "build_catalog_force": _make_build_catalog(
            client=client,
            model=model,
            file_repository=file_repository,
            file_storage=file_storage,
            catalog_repository=catalog_repository,
            force=True,
        ),
        "show_catalog": _make_show_catalog(catalog_repository=catalog_repository),
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
            # Unreachable through ChatService, which answers unknown
            # subcommands itself; kept for a caller that bypasses it.
            result = (
                f"Unknown `/recycle` subcommand: `{context.subcommand}`.\n\n"
                + render_subcommand_lines("recycle", SUBCOMMANDS)
            )
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
            subcommands=SUBCOMMANDS,
        ),
    )
