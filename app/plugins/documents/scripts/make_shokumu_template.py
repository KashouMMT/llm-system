"""
Build the 職務経歴書 .docx template from the client-approved sample.

The sample supplies everything a human chose — page size, margins, footers,
MS 明朝 at 10pt, the table ruling and its grey header shading. This script
keeps all of that and replaces the sample's text with docxtpl tags.

Run it from the project root and open the result in Word before committing:

    python -m app.plugins.documents.scripts.make_shokumu_template \
        "documentation/other/T【職務経歴書】.docx" \
        app/plugins/documents/templates/shokumu_keirekisho.docx

Almost all branching lives in the renderer, not here: it flattens each
section into a list of lines and the template just loops over them. A
template full of {%p if %} tags would be three paragraphs per optional
field, unreadable in Word and untestable outside it.
"""

import sys

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, Twips

# The sample's body font. Taken from its own runs rather than assumed:
# docDefaults name Century/ＭＳ 明朝, but every body run overrides ascii to
# ＭＳ 明朝 so that Latin text in a Japanese document matches the kana.
_FONT = "ＭＳ 明朝"
_BODY_SIZE = Pt(10)
_TITLE_SIZE = Pt(14)

# Full text width inside the sample's margins.
_BODY_WIDTH = 9781
_HEADER_SHADE = "F2F2F2"


def _clear_body(document) -> None:
    """Remove every block in the body, keeping the section properties."""
    body = document.element.body

    for element in list(body):
        if element.tag != qn("w:sectPr"):
            body.remove(element)


def _style_run(run, size=_BODY_SIZE) -> None:
    run.font.name = _FONT
    run.font.size = size
    # East Asian glyphs are selected by w:eastAsia, which python-docx does
    # not expose; without it Word falls back to the theme font for kana
    # while using ＭＳ 明朝 for Latin, and the two do not match.
    run._element.rPr.rFonts.set(qn("w:eastAsia"), _FONT)


def _paragraph(document, text="", align=None, size=_BODY_SIZE, style=None):
    paragraph = document.add_paragraph(style=style)

    if align is not None:
        paragraph.alignment = align

    if text:
        _style_run(paragraph.add_run(text), size)

    return paragraph


def _cell_paragraph(cell, text="", first=False):
    """Write into a cell, reusing the empty paragraph a new cell starts with."""
    paragraph = cell.paragraphs[0] if first else cell.add_paragraph()

    if text:
        _style_run(paragraph.add_run(text))

    return paragraph


def _bordered_table(document, columns: int, widths: list[int]):
    """
    A table ruled like the sample's: single lines, fixed layout.

    python-docx has no border API, so the properties are written as XML.
    They are copied from the sample rather than invented, which is why the
    result is indistinguishable from a table a person drew in Word.
    """
    table = document.add_table(rows=0, cols=columns)
    properties = table._element.tblPr

    borders = properties.makeelement(qn("w:tblBorders"), {})

    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        element = borders.makeelement(
            qn(f"w:{edge}"),
            {
                qn("w:val"): "single",
                qn("w:sz"): "4",
                qn("w:space"): "0",
                qn("w:color"): "auto",
            },
        )
        borders.append(element)

    properties.append(borders)

    layout = properties.makeelement(qn("w:tblLayout"), {qn("w:type"): "fixed"})
    properties.append(layout)

    table.autofit = False

    for index, width in enumerate(widths):
        table.columns[index].width = Twips(width)

    return table


def _shade(cell, fill: str = _HEADER_SHADE) -> None:
    properties = cell._element.get_or_add_tcPr()
    shading = properties.makeelement(
        qn("w:shd"),
        {qn("w:val"): "clear", qn("w:color"): "auto", qn("w:fill"): fill},
    )
    properties.append(shading)


def _add_row(table, texts: list[str], widths: list[int]):
    row = table.add_row()

    for cell, text, width in zip(row.cells, texts, widths):
        cell.width = Twips(width)
        _cell_paragraph(cell, text, first=True)

    return row


def _two_column_section(document, heading: str, tag: str, fields: tuple[str, str]):
    """
    ■PCスキル and ■資格 are the same shape: a heading over a 2-column table.

    docxtpl repeats the rows between a {%tr for %} row and a {%tr endfor %}
    row, so the template needs three rows to produce one.
    """
    widths = [1985, 7796]

    _paragraph(document, f"{{%p if {tag} %}}")
    _paragraph(document, heading)

    table = _bordered_table(document, 2, widths)
    _add_row(table, [f"{{%tr for item in {tag} %}}", ""], widths)
    _add_row(
        table,
        [f"{{{{ item.{fields[0]} }}}}", f"{{{{ item.{fields[1]} }}}}"],
        widths,
    )
    _add_row(table, ["{%tr endfor %}", ""], widths)

    _paragraph(document)
    _paragraph(document, "{%p endif %}")


def main(source: str, destination: str) -> None:
    document = Document(source)
    _clear_body(document)

    # --- 表題 ---
    _paragraph(document, "職 務 経 歴 書", WD_ALIGN_PARAGRAPH.CENTER, _TITLE_SIZE)
    _paragraph(document, "{{ generated_year }}年現在", WD_ALIGN_PARAGRAPH.RIGHT)
    _paragraph(document, "氏名　{{ name_line }}", WD_ALIGN_PARAGRAPH.RIGHT)
    _paragraph(document)

    # --- 職務要約 ---
    _paragraph(document, "{%p if summary_lines %}")
    _paragraph(document, "■職務要約")
    _paragraph(document, "{%p for line in summary_lines %}")
    _paragraph(document, "{{ line }}")
    _paragraph(document, "{%p endfor %}")
    _paragraph(document)
    _paragraph(document, "{%p endif %}")

    # --- 職務経歴 ---
    #
    # One table per job: a shaded header row carrying the dates and the
    # employer, then a single body cell holding every line the renderer
    # produced for that job. The sample's first job puts 使用技術 and 規模
    # in narrow side columns; those are folded into the body here so that
    # one table shape fits every job, including the ones with no technical
    # stack to list.
    _paragraph(document, "{%p for job in jobs %}")
    _paragraph(document, "■職務経歴{{ job.number }}")

    table = _bordered_table(document, 1, [_BODY_WIDTH])

    header = _add_row(table, ["{{ job.header }}"], [_BODY_WIDTH])
    _shade(header.cells[0])

    # The body row is guarded so that a job the user has named but not yet
    # described renders as a header alone, rather than as an empty ruled
    # box that looks like a rendering failure.
    _add_row(table, ["{%tr if job.lines %}"], [_BODY_WIDTH])

    body = _add_row(table, [""], [_BODY_WIDTH])
    _cell_paragraph(body.cells[0], "{%p for line in job.lines %}", first=True)
    _cell_paragraph(body.cells[0], "{{ line }}")
    _cell_paragraph(body.cells[0], "{%p endfor %}")

    _add_row(table, ["{%tr endif %}"], [_BODY_WIDTH])

    _paragraph(document)
    _paragraph(document, "{%p endfor %}")

    # --- PCスキル / 資格 ---
    _two_column_section(document, "■PCスキル", "pc_skills", ("tool", "level"))
    _two_column_section(document, "■資格", "licenses", ("period", "name"))

    # --- 活かせる経験・知識・技術 ---
    _paragraph(document, "{%p if applicable_skills %}")
    _paragraph(document, "■活かせる経験・知識・技術")
    _paragraph(document, "{%p for item in applicable_skills %}")
    _paragraph(document, "・{{ item }}")
    _paragraph(document, "{%p endfor %}")
    _paragraph(document)
    _paragraph(document, "{%p endif %}")

    # --- 自己PR ---
    _paragraph(document, "{%p if self_pr_lines %}")
    _paragraph(document, "■自己PR")
    _paragraph(document, "{%p for line in self_pr_lines %}")
    _paragraph(document, "{{ line }}")
    _paragraph(document, "{%p endfor %}")
    _paragraph(document)
    _paragraph(document, "{%p endif %}")

    # --- 結び ---
    _paragraph(document, "以上", style="Closing")

    document.save(destination)

    print(f"wrote {destination}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(
            "usage: python -m app.plugins.documents.scripts.make_shokumu_template "
            "<source.docx> "
            "<destination.docx>"
        )

    main(sys.argv[1], sys.argv[2])
