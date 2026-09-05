"""
Renders a 履歴書 into the JIS-style .xlsx form.

The form is filled, never built. Its ruling, borders, column widths, print
setup, and photo box come from a template workbook that a human made in
Excel; this module only writes text into cells that already exist. That is
the whole reason the output is indistinguishable from the samples the
client approved.
"""

from copy import copy
from datetime import date
from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.cell.cell import Cell, MergedCell
from openpyxl.worksheet.worksheet import Worksheet

from app.documents.dates import age_on, today_in_japan
from app.documents.layouts import rirekisho_jis as layout
from app.documents.layouts.rirekisho_jis import LayoutOverflow, Region
from app.documents.renderers.ooxml import restore_drawings
from app.documents.schemas_rirekisho import HistoryEntry, LicenseEntry, Rirekisho

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


class XlsxRenderer:
    """
    Renders a 履歴書 to .xlsx by filling the JIS form template.

    Implements the Renderer protocol, so swapping it in for TextRenderer is
    a one-line change in document_tool.py. The .txt renderer stays useful:
    it has no binary format to debug, so a wrong result there is always the
    data or the template.
    """

    extension = "xlsx"
    content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    def __init__(self, template_name: str = "rirekisho.xlsx") -> None:
        self._template_path = TEMPLATES_DIR / template_name

    def render(self, data: Rirekisho) -> bytes:
        workbook = load_workbook(self._template_path)
        sheet = workbook.active

        generated_on = today_in_japan()

        _write(sheet, layout.GENERATED_ON_CELL, f"{generated_on.year}年　現在")

        _write_basic_information(sheet, data, generated_on)
        _write_history(sheet, data)
        _write_licenses(sheet, data.licenses)
        _write_free_text(sheet, data)

        buffer = BytesIO()
        workbook.save(buffer)

        return restore_drawings(buffer.getvalue(), str(self._template_path))


# --- 基本情報 -------------------------------------------------------------


def _write_basic_information(
    sheet: Worksheet, data: Rirekisho, generated_on: date
) -> None:
    _fit_into(sheet, layout.NAME, data.name)
    _fit_into(sheet, layout.NAME_KANA, data.name_kana)

    if data.birth_date is not None:
        birth = data.birth_date
        _fit_into(
            sheet,
            layout.BIRTH_LINE,
            f"{birth.year}年{birth.month}月{birth.day}日生"
            f"　（満{age_on(birth, generated_on)}歳）　",
        )

    if data.gender:
        _fit_into(sheet, layout.GENDER, data.gender)

    # The postal code shares the label's ruled line; there is no cell of its
    # own to write it into.
    if data.postal_code:
        _write(
            sheet,
            layout.ADDRESS_LABEL_CELL,
            f"{layout.ADDRESS_LABEL_TEXT}{data.postal_code}",
        )

    _fit_into(sheet, layout.ADDRESS, data.address)
    _fit_into(sheet, layout.ADDRESS_KANA, data.address_kana)

    # 電話 and E-mail carry their labels inside the value cell, so the value
    # is appended to the label rather than replacing it.
    if data.phone:
        _fit_into(sheet, layout.PHONE, f"{layout.PHONE_LABEL}　{data.phone}")

    if data.email:
        _fit_into(sheet, layout.EMAIL, f"{layout.EMAIL_LABEL}\n{data.email}")


# --- 学歴・職歴 -----------------------------------------------------------


def _write_history(sheet: Worksheet, data: Rirekisho) -> None:
    """
    Lay 学歴 and 職歴 into the form's fixed rows.

    The form has as many rows as it has, exactly like the printed sheet it
    reproduces — there is no inserting one. Overflowing raises rather than
    truncating, and the message becomes the assistant's question to the
    user.
    """
    rows: list[tuple[HistoryEntry | None, str]] = []

    if data.education:
        rows.append((None, layout.EDUCATION_HEADING))
        rows.extend((entry, entry.description) for entry in data.education)

    if data.work:
        rows.append((None, layout.WORK_HEADING))
        rows.extend((entry, entry.description) for entry in data.work)

    if rows:
        rows.append((None, layout.CLOSING))

    available = len(layout.HISTORY_ANCHORS)

    if len(rows) > available:
        raise LayoutOverflow(
            f"学歴・職歴が{len(rows)}行あり、履歴書の{available}行に収まりません。"
            "同じ会社の入社・退職を1行にまとめるなど、行数を減らせないか"
            "利用者に確認してから、もう一度作成してください。"
        )

    for anchor, (entry, text) in zip(layout.HISTORY_ANCHORS, rows):
        column, row = anchor[0], anchor[1:]

        if entry is not None and entry.period is not None:
            _write(
                sheet,
                f"{layout.HISTORY_YEAR_COLUMN[column]}{row}",
                entry.period.year,
            )
            _write(
                sheet,
                f"{layout.HISTORY_MONTH_COLUMN[column]}{row}",
                entry.period.month,
            )

        _fit_into(
            sheet,
            layout.single_row(
                anchor, layout.HISTORY_ROW, f"学歴・職歴の「{text}」の行"
            ),
            text,
        )


def _write_licenses(sheet: Worksheet, licenses: list[LicenseEntry]) -> None:
    available = len(layout.LICENSE_ANCHORS)

    if len(licenses) > available:
        raise LayoutOverflow(
            f"免許・資格が{len(licenses)}件あり、履歴書の{available}行に"
            "収まりません。応募先に関係の深いものだけに絞れないか利用者に"
            "確認してから、もう一度作成してください。"
        )

    for anchor, entry in zip(layout.LICENSE_ANCHORS, licenses):
        row = anchor[1:]

        _write(sheet, f"{layout.LICENSE_YEAR_COLUMN}{row}", entry.period.year)
        _write(sheet, f"{layout.LICENSE_MONTH_COLUMN}{row}", entry.period.month)
        _fit_into(
            sheet,
            layout.single_row(
                anchor, layout.LICENSE_ROW, f"免許・資格の「{entry.name}」の行"
            ),
            entry.name,
        )


# --- 自由記述 -------------------------------------------------------------


def _write_free_text(sheet: Worksheet, data: Rirekisho) -> None:
    if data.motivation:
        _fit_into(sheet, layout.MOTIVATION, data.motivation)

    if data.requests:
        _fit_into(sheet, layout.REQUESTS, data.requests)


# --- cell writing ---------------------------------------------------------


def _write(sheet: Worksheet, reference: str, value: object) -> Cell:
    """
    Write a value to a cell, rejecting any cell hidden inside a merge.

    Writing to a merged range's non-anchor cell is silently ignored by
    Excel, which is exactly the kind of failure that looks like a data
    problem for an afternoon.
    """
    cell = sheet[reference]

    if isinstance(cell, MergedCell):
        raise ValueError(  # noqa: TRY004
            f"{reference} is inside a merged range but is not its anchor; "
            "the layout must name the top-left cell."
        )

    cell.value = value

    return cell


def _fit_into(sheet: Worksheet, region: Region, text: str) -> None:
    """
    Write `text` into `region`, shrinking the font until it fits.

    Raises LayoutOverflow if it does not fit even at the smallest size —
    see rirekisho_jis.fit for why shrinking is silent but truncating never
    is.
    """
    if not text:
        return

    lines, font_size = layout.fit(text, region)

    if region.wraps:
        # Excel does the wrapping; ours only measured. Baking our line
        # breaks in would fight it — the cell would wrap the already-broken
        # lines again at slightly different points, leaving a ragged column
        # and splitting the user's own words.
        cell = _write(sheet, region.anchors[0], text)
        _apply_font_size(cell, font_size)
        _enable_wrap(cell)
        return

    # An unwrapped region spreads its lines across its anchor cells: the
    # 本人希望記入欄 is four separate ruled rows, not one box.
    for anchor, line in zip(region.anchors, lines):
        cell = _write(sheet, anchor, line)
        _apply_font_size(cell, font_size)


def _apply_font_size(cell: Cell, font_size: float) -> None:
    """
    Resize a cell's font, keeping every other attribute the template set.

    Copied rather than mutated: openpyxl shares one Font object across
    every cell using the same style, so assigning to cell.font.size would
    resize a few hundred unrelated cells.
    """
    if cell.font.size == font_size:
        return

    font = copy(cell.font)
    font.size = font_size
    cell.font = font


def _enable_wrap(cell: Cell) -> None:
    if cell.alignment.wrapText:
        return

    alignment = copy(cell.alignment)
    alignment.wrapText = True
    cell.alignment = alignment
