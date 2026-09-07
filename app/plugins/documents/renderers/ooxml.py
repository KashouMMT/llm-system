"""
Repairs the parts openpyxl drops when it rewrites a workbook.

openpyxl models cells, styles, merges, and page setup, and reproduces all
of them exactly. It does not model DrawingML shapes, so saving a workbook
silently discards them. On the 履歴書 form that shape is the 写真を貼る位置
box — the photo frame with its size instructions — which is one of the
first things a reader looks at.

Copying the drawing part back into the saved package restores it. This is
the only OOXML surgery in the project, and it exists because the
alternative was rewriting the whole workbook writer to keep one shape.
"""

import posixpath
import zipfile
from io import BytesIO

_RELATIONSHIPS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_DRAWING_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.drawing+xml"

# openpyxl always writes the first worksheet to this path, and this project
# only ever renders single-sheet forms.
_SHEET_PART = "xl/worksheets/sheet1.xml"
_SHEET_RELS_PART = "xl/worksheets/_rels/sheet1.xml.rels"
_CONTENT_TYPES_PART = "[Content_Types].xml"

# Chosen not to collide with any relationship id openpyxl generates, which
# are all of the form rId<n>.
_DRAWING_RELATIONSHIP_ID = "rIdRestoredDrawing"


def restore_drawings(saved: bytes, template_path: str) -> bytes:
    """
    Copy the template's worksheet drawing into a workbook openpyxl saved.

    Returns `saved` unchanged if the template has no drawing, so a template
    without a photo box needs no special case at the call site.

    Four coordinated edits are needed, and all four must land or the file
    will not open: the drawing part itself, a relationship pointing at it,
    a `<drawing>` element on the worksheet referencing that relationship,
    and a content-type override so the package declares what the part is.
    """
    with zipfile.ZipFile(template_path) as template:
        drawings = [
            name
            for name in template.namelist()
            if name.startswith("xl/drawings/") and name.endswith(".xml")
        ]

        if not drawings:
            return saved

        if len(drawings) > 1:
            raise ValueError(
                f"{template_path} has {len(drawings)} drawing parts; this "
                "repair only handles the single-drawing forms in use."
            )

        drawing_part = drawings[0]
        drawing_xml = template.read(drawing_part)

    source = zipfile.ZipFile(BytesIO(saved))

    if _SHEET_RELS_PART in source.namelist():
        raise ValueError(
            "The saved workbook already has worksheet relationships. This "
            "repair assumes openpyxl wrote none, and merging them is not "
            "implemented — check whether the openpyxl version changed."
        )

    sheet_xml = source.read(_SHEET_PART).decode("utf-8")

    # openpyxl does not declare the relationship namespace on the worksheet
    # root, because nothing it writes needs it.
    if "xmlns:r=" not in sheet_xml[:500]:
        sheet_xml = sheet_xml.replace(
            "<worksheet ", f'<worksheet xmlns:r="{_RELATIONSHIPS}" ', 1
        )

    # `drawing` is the last child of a worksheet in the schema, so appending
    # it immediately before the closing tag is also putting it in the right
    # place.
    sheet_xml = sheet_xml.replace(
        "</worksheet>", f'<drawing r:id="{_DRAWING_RELATIONSHIP_ID}"/></worksheet>'
    )

    relative_target = posixpath.relpath(drawing_part, "xl/worksheets")
    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="{_DRAWING_RELATIONSHIP_ID}" '
        f'Type="{_RELATIONSHIPS}/drawing" Target="{relative_target}"/>'
        "</Relationships>"
    )

    content_types = source.read(_CONTENT_TYPES_PART).decode("utf-8")
    content_types = content_types.replace(
        "</Types>",
        f'<Override PartName="/{drawing_part}" '
        f'ContentType="{_DRAWING_CONTENT_TYPE}"/></Types>',
    )

    output = BytesIO()

    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as repaired:
        for name in source.namelist():
            if name == _SHEET_PART:
                repaired.writestr(name, sheet_xml)
            elif name == _CONTENT_TYPES_PART:
                repaired.writestr(name, content_types)
            else:
                repaired.writestr(name, source.read(name))

        repaired.writestr(_SHEET_RELS_PART, rels_xml)
        repaired.writestr(drawing_part, drawing_xml)

    source.close()

    return output.getvalue()