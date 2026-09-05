"""
Build the blank 履歴書 template from the client-approved sample.

Everything the applicant wrote is cleared; everything pre-printed on the
form — labels, ruling, the photo box, print setup — is kept. Run it from
the project root and check the result in Excel before committing it:

    python scripts/make_rirekisho_template.py \
        "documentation/other/【履歴書】K.xlsx" \
        app/documents/templates/rirekisho.xlsx
"""

import sys
from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook

from app.documents.layouts import rirekisho_jis as layout
from app.documents.renderers.ooxml import restore_drawings

# Cells the applicant filled in on the sample. Everything else on the sheet
# is pre-printed and must survive.
_APPLICANT_CELLS = [
    layout.GENERATED_ON_CELL,
    "B7", "D5", "B10", "H11",
    "C12", "B15", "D17",
    *layout.HISTORY_ANCHORS,
    *[f"{layout.HISTORY_YEAR_COLUMN[a[0]]}{a[1:]}" for a in layout.HISTORY_ANCHORS],
    *[f"{layout.HISTORY_MONTH_COLUMN[a[0]]}{a[1:]}" for a in layout.HISTORY_ANCHORS],
    *layout.LICENSE_ANCHORS,
    *[f"{layout.LICENSE_YEAR_COLUMN}{a[1:]}" for a in layout.LICENSE_ANCHORS],
    *[f"{layout.LICENSE_MONTH_COLUMN}{a[1:]}" for a in layout.LICENSE_ANCHORS],
    *layout.MOTIVATION.anchors,
    *layout.REQUESTS.anchors,
]

# Labels that carry a value on the sample and must be reset to the bare
# label rather than emptied.
_LABELS_TO_RESET = {
    layout.ADDRESS_LABEL_CELL: layout.ADDRESS_LABEL_TEXT,
    layout.PHONE.anchors[0]: layout.PHONE_LABEL,
    layout.EMAIL.anchors[0]: f"{layout.EMAIL_LABEL}\n",
}


def main(source: str, destination: str) -> None:
    workbook = load_workbook(source)
    sheet = workbook.active

    cleared = sum(1 for ref in _APPLICANT_CELLS if sheet[ref].value is not None)

    for reference in _APPLICANT_CELLS:
        sheet[reference] = None

    for reference, label in _LABELS_TO_RESET.items():
        sheet[reference] = label

    buffer = BytesIO()
    workbook.save(buffer)

    Path(destination).write_bytes(restore_drawings(buffer.getvalue(), source))

    print(f"cleared {cleared} filled cells -> {destination}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])