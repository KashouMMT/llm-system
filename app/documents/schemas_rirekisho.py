import re
from datetime import date
from itertools import pairwise

from pydantic import BaseModel, Field, field_validator, model_validator

from app.documents.dates import today_in_japan

# Kana only: hiragana, katakana, the long-vowel mark, and spaces. Furigana
# containing kanji is the most common malformed input, and it is invisible
# in a rendered document unless it is rejected here.
#
# Public because \u8077\u52D9\u7D4C\u6B74\u66F8 carries the same reading of the same name and
# must not validate it by a different rule \u2014 imported by schemas_shokumu,
# as YearMonth already is.
KANA_PATTERN = re.compile(r"^[\u3040-\u309F\u30A0-\u30FF\u30FC\s\u3000]+$")

# Address furigana is kana plus the block numbers, which are carried across
# as digits rather than transcribed phonetically: "shinjuku 3-12-8" written
# in kana still ends in digits, and that is the normal form rather than
# malformed input. Both ASCII and fullwidth digits and hyphens appear in
# practice; rejecting them forces the user to drop real information from
# the address to satisfy the validator. Kanji stays rejected, which is the
# part of the kana rule that actually matters.
#
# Digits and hyphens lead the class so no \uXXXX escape is followed by a
# hex digit that could read as part of it.
_ADDRESS_KANA_PATTERN = re.compile(
    r"^[0-9\uFF10-\uFF19\-\u2010\u2212\uFF0D"
    r"\u3040-\u309F\u30A0-\u30FF\u30FC\s\u3000]+$"
)

_POSTAL_PATTERN = re.compile(r"^\d{3}-\d{4}$")


class YearMonth(BaseModel):
    """
    A 年月 pair.

    Not a `date`: 履歴書 history rows carry a year and a month only, and
    inventing a day would mean fabricating a value the user never gave.
    """

    year: int = Field(ge=1900, le=2100, description="西暦 (Gregorian year), e.g. 2019")
    month: int = Field(ge=1, le=12, description="Month, 1-12")

    def as_tuple(self) -> tuple[int, int]:
        return (self.year, self.month)

    def __str__(self) -> str:
        return f"{self.year}年{self.month}月"


class HistoryEntry(BaseModel):
    """One 学歴 or 職歴 row."""

    period: YearMonth | None = Field(
        default=None,
        description=(
            "The row's 年月. Omit only for a final, still-ongoing row — "
            "conventionally described as '現在に至る' — which by "
            "definition has no end date. Every other row must have one."
        ),
    )
    description: str = Field(
        min_length=1,
        max_length=100,
        description=(
            "The row text exactly as it should appear, e.g. "
            "'東京大学 工学部 情報工学科 入学' or '株式会社ABC 入社'. A "
            "final, still-ongoing row is conventionally '現在に至る', with "
            "period left empty. Write it as the user stated it; do not "
            "translate or abbreviate."
        ),
    )


class LicenseEntry(BaseModel):
    """One 免許・資格 row."""

    period: YearMonth
    name: str = Field(
        min_length=1,
        max_length=100,
        description=(
            "Official name of the licence or certification, copied exactly, "
            "and ALWAYS ending in 合格 or 取得 — a 免許・資格 row without "
            "one reads as unfinished to a Japanese reader. Which of the two "
            "is decided by what the qualification is, not by preference: an "
            "examination that was passed takes 合格 ('基本情報技術者試験 "
            "合格', '日本語能力試験N2 合格'), and a licence or credential "
            "that is held takes 取得 ('普通自動車第一種運転免許 取得'). A "
            "name ending in 試験 is an examination. English-named "
            "certifications follow the same rule: "
            "'AWS Certified Developer – Associate 取得'."
        ),
    )


def _require_chronological(
    entries: list[HistoryEntry] | list[LicenseEntry], label: str
):
    """
    Reject out-of-order rows, and reject a dateless row anywhere but last.

    Sorting dated rows would hide the usual cause, which is a wrong year
    rather than a wrong order — and this error text is fed back to the
    model, so it is more useful as a question than as an invisible
    correction. A dateless row can only represent something still ongoing,
    which by definition cannot come before a row with an end date.
    """
    dated = [entry for entry in entries if entry.period is not None]

    for previous, current in pairwise(dated):
        if current.period.as_tuple() < previous.period.as_tuple():
            raise ValueError(
                f"{label} must be in chronological order: "
                f"{current.period} appears after {previous.period}."
            )

    undated_positions = [
        index for index, entry in enumerate(entries) if entry.period is None
    ]

    if len(undated_positions) > 1 or (
        undated_positions and undated_positions[0] != len(entries) - 1
    ):
        raise ValueError(
            f"{label}: a row with no year and month can only be the final "
            "row, representing something still ongoing (e.g. '現在に至る')."
        )

    return entries


class Rirekisho(BaseModel):
    """
    A 履歴書, complete or partial.

    Every field description here is sent to the model as part of the tool
    schema, so they are prompt text, not documentation. Write them as
    instructions.

    Almost every field is optional, and that is deliberate. These
    validators check that a value is well *formed*, never that it is
    present: a user who wants a printable draft with the address left
    blank to fill in by hand is asking for something completely normal,
    and a tool that refuses is arguing with the person it serves.
    Completeness is the assistant's job to pursue in conversation, and
    the field descriptions below are where that is instructed.
    """

    # --- 基本情報 ---

    name: str = Field(
        min_length=1,
        max_length=50,
        description="Full name in kanji, family name first, e.g. '山田 太郎'.",
    )
    name_kana: str = Field(
        default="",
        max_length=50,
        description=(
            "Furigana for the name, kana only — no kanji, no romaji, "
            "e.g. 'やまだ たろう'. Always ask for it. Leave empty only if "
            "the user does not know it or asks to write it in by hand."
        ),
    )
    birth_date: date | None = Field(
        default=None,
        description=(
            "Date of birth as an ISO date, e.g. '1995-04-12'. Always ask "
            "for it. Leave empty only if the user declines to give it."
        ),
    )
    gender: str | None = Field(
        default=None,
        max_length=10,
        description=(
            "Optional, and only if the user volunteered it. The 2020 JIS "
            "revision made this field optional — never ask for it. Printed "
            "exactly as given; this template's 男・女 checkbox is not "
            "filled in automatically for a value outside those two words."
        ),
    )

    # --- 連絡先 ---

    postal_code: str = Field(
        default="",
        description=(
            "Postal code in the form '123-4567'. Always ask for it. Leave "
            "empty if the user does not know it — never guess one from a "
            "city or prefecture name."
        ),
    )
    address: str = Field(
        default="",
        max_length=200,
        description=(
            "Full address in Japanese, copied exactly as given. Always ask "
            "for it. Leave empty if the user says they will write it in by "
            "hand — the document then prints with a blank address line, "
            "which is a normal way to use a 履歴書. Never invent a "
            "placeholder such as ［住所を記入］."
        ),
    )
    address_kana: str = Field(
        default="",
        max_length=200,
        description=(
            "Furigana for the address: kana, plus the block numbers written "
            "as digits and hyphens, e.g. 'とうきょうと しんじゅくく "
            "しんじゅく3-12-8'. Keep the numbers — they are read as numbers, "
            "not transcribed into kana. No kanji. Leave empty whenever the "
            "address itself is empty."
        ),
    )
    phone: str = Field(
        default="",
        max_length=20,
        description=(
            "Contact telephone number, digits and hyphens. Always ask for "
            "it. Leave empty only if the user declines."
        ),
    )
    email: str | None = Field(
        default=None,
        max_length=254,
        description="Email address, if the user gave one.",
    )

    # --- 通勤・家族 ---

    commute_time_minutes: int | None = Field(
        default=None,
        ge=0,
        le=999,
        description=(
            "通勤時間: approximate one-way commute time in minutes to the "
            "workplace being applied to. Optional — leave empty if unknown "
            "or not applicable."
        ),
    )
    dependents_excluding_spouse: int | None = Field(
        default=None,
        ge=0,
        le=99,
        description=(
            "扶養家族数（配偶者を除く）: number of dependents, not counting "
            "a spouse. Optional — leave empty if the user does not want to "
            "state it."
        ),
    )
    has_spouse: bool | None = Field(
        default=None,
        description="配偶者の有無. Optional — leave empty if not stated.",
    )
    spouse_support_obligation: bool | None = Field(
        default=None,
        description=(
            "配偶者の扶養義務: whether the user is legally obligated to "
            "support their spouse. Only meaningful when has_spouse is "
            "true. Optional — leave empty if not stated."
        ),
    )

    # --- 経歴 ---

    education: list[HistoryEntry] = Field(
        default_factory=list,
        description=(
            "学歴, oldest first. Conventionally each school appears twice, "
            "as 入学 and 卒業. You MUST ask the user about their education "
            "history before generating — a 履歴書 is not normally "
            "submittable without it. Leave empty only if the user "
            "explicitly asks you to."
        ),
    )
    work: list[HistoryEntry] = Field(
        default_factory=list,
        description=(
            "職歴, oldest first, following 学歴. Each employer appears as "
            "入社 and, if the user has left, 退社. If the user is still "
            "employed there, the final row is '現在に至る' with no period "
            "— never invent an end date for a job the user is still in. "
            "You MUST ask the user about their work history before "
            "generating. If they have never been employed, leave this "
            "empty — the renderer writes なし."
        ),
    )
    licenses: list[LicenseEntry] = Field(
        default_factory=list,
        description=(
            "免許・資格, oldest first. You MUST ask the user whether they "
            "hold any before generating. Leave empty if they hold none."
        ),
    )

    # --- 自由記述 ---

    motivation: str | None = Field(
        default=None,
        max_length=1000,
        description=(
            "志望の動機、特技、好きな学科、アピールポイントなど — one "
            "combined box covering motivation for applying, special "
            "skills, favourite subjects, and personal appeal points. Only "
            "include text the user has seen and approved — never write "
            "this on their behalf without showing it first."
        ),
    )
    requests: str | None = Field(
        default=None,
        max_length=500,
        description=(
            "本人希望記入欄. If the user has no particular request, the "
            "conventional text is '貴社の規定に従います'."
        ),
    )

    # Every validator below returns early on an empty value. Blank means
    # the user chose not to supply it, which is not an error — only a
    # value that is present and malformed is.

    @field_validator("name_kana")
    @classmethod
    def _name_kana_only(cls, value: str) -> str:
        if not value:
            return value

        if not KANA_PATTERN.match(value):
            raise ValueError(f"must be kana only (hiragana or katakana); got {value!r}")

        return value

    @field_validator("address_kana")
    @classmethod
    def _address_kana_only(cls, value: str) -> str:
        if not value:
            return value

        if not _ADDRESS_KANA_PATTERN.match(value):
            raise ValueError(
                f"must be kana, digits, or hyphens — no kanji; got {value!r}"
            )

        return value

    @field_validator("postal_code")
    @classmethod
    def _postal_format(cls, value: str) -> str:
        if not value:
            return value

        if not _POSTAL_PATTERN.match(value):
            raise ValueError(f"must be in the form '123-4567'; got {value!r}")

        return value

    @field_validator("birth_date")
    @classmethod
    def _plausible_birth_date(cls, value: date | None) -> date | None:
        if value is None:
            return value

        today = today_in_japan()

        if value >= today:
            raise ValueError("must be in the past")

        if value.year < today.year - 120:
            raise ValueError("is implausibly far in the past")

        return value

    @model_validator(mode="after")
    def _validate_order(self) -> "Rirekisho":
        _require_chronological(self.education, "学歴")
        _require_chronological(self.work, "職歴")
        _require_chronological(self.licenses, "免許・資格")

        if self.birth_date is None:
            return self

        # A history row dated before the applicant was born is a
        # transcription error, and one the reader would not notice.
        birth = (self.birth_date.year, self.birth_date.month)

        for entry in [*self.education, *self.work]:
            if entry.period is not None and entry.period.as_tuple() < birth:
                raise ValueError(
                    f"'{entry.description}' is dated {entry.period}, "
                    "which is before the date of birth."
                )

        return self