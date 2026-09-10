"""Label normalisation, shared by everything that has to compare two labels.

There are two different jobs here and conflating them causes bugs.

`normalize` cleans a label for *display and storage*: lowercase, trimmed,
single-spaced. What the user sees.

`collapse_key` produces a key for *matching only*: it additionally strips every
non-alphanumeric character, so "mouse pad", "mousepad" and "Mouse-Pad" all
collapse to "mousepad". Never show a collapse key to a human — it is a lookup
key, not a name.

What this deliberately does NOT do is merge synonyms. "table" and "desk",
"package" and "packet" are different keys here, and no amount of string
manipulation will fix that. Those need a catalog with an alias list, which is
the next thing to build.
"""

from __future__ import annotations

import re

_WHITESPACE = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize(label: str) -> str:
    """Lowercase, strip, and collapse internal whitespace. Safe to display."""
    return _WHITESPACE.sub(" ", label.strip().lower())


def collapse_key(label: str) -> str:
    """A matching key: normalised, then stripped of spaces and punctuation.

    Used to decide whether two labels refer to the same thing. Intentionally
    crude — it catches spacing and punctuation drift, nothing more.
    """
    return _NON_ALNUM.sub("", normalize(label))
