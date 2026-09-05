"""
Where every 履歴書 field goes on the JIS-style form, and how much text each
slot holds.

Transcribed from documentation/other/【履歴書】K.xlsx, which is identical in
layout to 【履歴書】I.xlsx. Nothing here is computed from a formula: the
ruling is irregular — D28:I29 spans two rows, D34:I34 spans one — so an
anchor list is the only description that is actually true of the file.
Re-derive it from the template if the template changes; never edit it to
match a guess.

Capacity is expressed in half-width units, the same unit Excel uses for
column width: one unit is the width of one digit in the default font at
11pt, and a full-width character is two units. A region's capacity at font
size S is therefore `width_units * 11 / S` per line.
"""

import unicodedata
from dataclasses import dataclass
from math import ceil, floor

# A merged range is never auto-fitted: Excel leaves it at whatever height
# its rows already have, so the number of visible lines is fixed by the
# template rather than by the text. 1.32 is the ratio of line box to font
# size for the MS 明朝 the form uses. It is deliberately generous, because
# guessing high costs one font step and guessing low overflows the box
# invisibly.
_LINE_HEIGHT_RATIO = 1.32

# Excel's column width unit is defined against the default font size.
_BASE_FONT_SIZE = 11.0


class LayoutOverflow(Exception):
    """
    Raised when content cannot be made to fit the form.

    The message is read by the model, not by a developer: it reaches the
    assistant through ToolNode's error handler and becomes the question it
    asks the user. So it names the section, says how much room there is,
    and gives the concrete way out.
    """


def display_width(text: str) -> int:
    """
    Width of `text` in half-width units.

    East Asian "ambiguous" characters (※ ○ ― and most punctuation) count as
    full width, because that is how they render in MS 明朝. Counting them
    narrow would let text overflow a cell the capacity check just declared
    safe.
    """
    return sum(
        2 if unicodedata.east_asian_width(character) in "WFA" else 1
        for character in text
    )


@dataclass(frozen=True)
class Region:
    """
    One writable area of the form.

    `anchors` is every cell the region may write into, in order. Most
    fields have one; 本人希望記入欄 has four, because the template rules it
    as four separate merged rows rather than as one box.

    Width and height are the summed column widths and row heights of the
    merged range in the template. They are recorded here rather than read
    back at render time so that a template edit which changes the ruling
    shows up as a mismatch to investigate, instead of as silently different
    wrapping.
    """

    anchors: tuple[str, ...]
    width_units: float
    height_points: float
    label: str
    wraps: bool = False
    font_sizes: tuple[float, ...] = (12.0, 11.0, 10.0, 9.0, 8.0)

    def units_per_line(self, font_size: float) -> float:
        return self.width_units * _BASE_FONT_SIZE / font_size

    def line_capacity(self, font_size: float) -> int:
        """How many lines of text are visible at this font size."""
        if not self.wraps:
            # An unwrapped region shows exactly one line per anchor cell,
            # however tall the cell happens to be.
            return len(self.anchors)

        return max(1, floor(self.height_points / (font_size * _LINE_HEIGHT_RATIO)))


def wrap(text: str, units_per_line: float) -> list[str]:
    """
    Break `text` into the lines Excel's word wrap will produce.

    Japanese has no spaces, so this breaks on width rather than on word
    boundaries — which is what Excel does for CJK text too. Explicit
    newlines are honoured and always start a new line.
    """
    lines: list[str] = []

    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue

        current = ""

        for character in paragraph:
            candidate = current + character

            if current and display_width(candidate) > units_per_line:
                lines.append(current)
                current = character
            else:
                current = candidate

        lines.append(current)

    return lines


def fit(text: str, region: Region) -> tuple[list[str], float]:
    """
    Choose the largest font size at which `text` fits, and wrap it there.

    Two caps: overflowing at the current size steps the font down, and
    overflowing at the smallest size raises. Shrinking silently is fine —
    the reader just sees smaller text. Truncating silently is not, because
    this document goes to an employer and a half-printed company name is
    worse than a generation that failed and asked a question.
    """
    if not text:
        return [], region.font_sizes[0]

    for font_size in region.font_sizes:
        lines = wrap(text, region.units_per_line(font_size))

        if len(lines) <= region.line_capacity(font_size):
            return lines, font_size

    smallest = region.font_sizes[-1]
    room = int(region.units_per_line(smallest) * region.line_capacity(smallest) / 2)

    raise LayoutOverflow(
        f"{region.label}に入りきりません。最小の文字サイズでも全角約{room}文字"
        f"までのところ、約{ceil(display_width(text) / 2)}文字あります。"
        "短くまとめてから、もう一度作成してください。"
    )


def single_row(anchor: str, template: Region, label: str) -> Region:
    """A one-cell region borrowing another region's box size."""
    return Region((anchor,), template.width_units, template.height_points, label)


# --- 基本情報 -------------------------------------------------------------

NAME = Region(("B7",), 63.3, 72.0, "氏名", font_sizes=(28.0, 24.0, 20.0, 16.0))
NAME_KANA = Region(
    ("D5",), 43.7, 17.2, "氏名のふりがな", font_sizes=(11.0, 10.0, 9.0, 8.0)
)
BIRTH_LINE = Region(("B10",), 63.3, 28.5, "生年月日", font_sizes=(11.0, 10.0, 9.0))
GENDER = Region(("H11",), 29.1, 17.2, "性別", font_sizes=(11.0, 10.0, 9.0))

ADDRESS = Region(("B15",), 74.3, 37.5, "現住所")
ADDRESS_KANA = Region(
    ("C12",), 63.2, 13.0, "現住所のふりがな", font_sizes=(10.0, 9.0, 8.0)
)

# The postal code has no box of its own — the 〒 mark and the digits share
# the pre-printed label's ruled line, so the value is appended to the
# label rather than written to a separate cell. Same for 電話 and E-mail,
# whose labels live inside the value cell.
ADDRESS_LABEL_CELL = "B13"
ADDRESS_LABEL_TEXT = " 現住所　〒"

PHONE = Region(("I12",), 18.1, 17.2, "電話番号", font_sizes=(11.0, 10.0, 9.0, 8.0))
PHONE_LABEL = "電話"
EMAIL = Region(("I13",), 18.1, 54.0, "E-mail", wraps=True, font_sizes=(11.0, 9.0, 8.0))
EMAIL_LABEL = "E-mail"

# --- 学歴・職歴 -----------------------------------------------------------
#
# Two columns of one sheet: the left half of the A3 spread runs rows 26-49,
# and the right half continues at rows 4-14, above the 免許・資格 block.
# Reading order is the whole left column, then the right.

HISTORY_ANCHORS = (
    "D26",
    "D28",
    "D30",
    "D32",
    "D34",
    "D35",
    "D37",
    "D39",
    "D40",
    "D42",
    "D44",
    "D46",
    "D47",
    "D48",
    "D49",
    "N4",
    "N6",
    "N8",
    "N9",
    "N10",
    "N12",
    "N14",
)

# Which columns carry the 年 and 月 for a row anchored in D or in N.
HISTORY_YEAR_COLUMN = {"D": "B", "N": "L"}
HISTORY_MONTH_COLUMN = {"D": "C", "N": "M"}

HISTORY_ROW = Region((), 72.8, 28.5, "学歴・職歴の行")

EDUCATION_HEADING = "学歴"
WORK_HEADING = "職歴"
CLOSING = "以上"

# --- 免許・資格 -----------------------------------------------------------
#
# The 免許・資格 heading stays at row 16, as in 【履歴書】K. It could in
# principle move up to claim unused 学歴・職歴 continuation rows —
# 【履歴書】I puts it at row 12 — but that row carries its own ruling and
# font, so moving it means restyling cells rather than writing them. Not
# worth the complexity for the two extra slots it buys.

LICENSE_ANCHORS = ("N18", "N21", "N22", "N25", "N27", "N29")
LICENSE_YEAR_COLUMN = "L"
LICENSE_MONTH_COLUMN = "M"

LICENSE_ROW = Region((), 73.5, 28.5, "免許・資格の行")

# --- 自由記述 -------------------------------------------------------------

MOTIVATION = Region(("L33",), 93.2, 169.5, "志望の動機・自己PR欄", wraps=True)

REQUESTS = Region(
    ("L46", "L47", "L48", "L49"),
    93.2,
    28.5,
    "本人希望記入欄",
    font_sizes=(12.0, 11.0, 10.0),
)

# --- 表題 -----------------------------------------------------------------

GENERATED_ON_CELL = "E3"
