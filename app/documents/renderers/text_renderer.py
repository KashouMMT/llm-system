from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import BaseModel

from app.documents.dates import (
    age_on,
    to_japanese_era,
    to_japanese_era_year,
    today_in_japan,
)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

# StrictUndefined on purpose: a typo in a template would otherwise render as
# an empty string, producing a document that is silently missing a field.
# For a document a human will submit to an employer, failing loudly is the
# only acceptable behaviour.
_environment = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
    # No autoescape: this renders plain text, and HTML escaping would
    # corrupt characters that are legitimate here.
    autoescape=False,
)

# 和暦/age formatting lives in app.documents.dates, not here or in the
# template — this just exposes it, the same way "%4d"|format already
# reaches into the template for column alignment.
_environment.globals["to_japanese_era"] = to_japanese_era
_environment.globals["to_japanese_era_year"] = to_japanese_era_year
_environment.globals["age_on"] = age_on


class TextRenderer:
    """
    Renders a document to plain UTF-8 text.

    The simplest possible implementation of the Renderer protocol, and the
    one to develop the schema against — it has no binary format to debug,
    so a wrong result is always the data or the template.
    """

    extension = "txt"
    content_type = "text/plain; charset=utf-8"

    def __init__(self, template_name: str) -> None:
        self._template_name = template_name

    def render(self, data: BaseModel) -> bytes:
        template = _environment.get_template(self._template_name)

        # Render metadata is supplied here rather than carried on the model:
        # the generation date is a fact about this file, not about the
        # applicant, and putting it in the schema would invite the model to
        # invent a value for it.
        text = template.render(
            **data.model_dump(),
            generated_on=today_in_japan(),
        )

        return text.encode("utf-8")